"""Resolve city coordinates and fetch validated weather records concurrently."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import logging
import threading
from typing import Callable

import requests
from pydantic import ValidationError

from .client import create_http_session
from .models import (
    MAX_CITIES_PER_BATCH,
    CityInput,
    OpenMeteoForecastResponse,
    OpenMeteoGeocodingResponse,
    WeatherRecord,
)

logger = logging.getLogger(__name__)

FORECAST_URL: str = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL: str = "https://geocoding-api.open-meteo.com/v1/search"
MAX_WORKERS: int = 10


class WeatherExtractor:
    """Fetch and validate weather data using one HTTP session per worker thread."""

    def __init__(
        self,
        session_factory: Callable[[], requests.Session] = create_http_session,
        max_workers: int = 5,
    ) -> None:
        """Create an extractor with a bounded worker pool and session factory."""
        if not 1 <= max_workers <= MAX_WORKERS:
            raise ValueError(f"max_workers must be between 1 and {MAX_WORKERS}.")
        self._session_factory: Callable[[], requests.Session] = session_factory
        self.max_workers: int = max_workers
        self._thread_local: threading.local = threading.local()
        self._sessions: list[requests.Session] = []
        self._sessions_lock: threading.Lock = threading.Lock()

    def extract_batch(self, cities: list[CityInput]) -> list[WeatherRecord]:
        """Extract a batch, logging individual failures without discarding successes.

        Args:
            cities: Validated city requests, capped at ``MAX_CITIES_PER_BATCH``.

        Returns:
            Successfully extracted records in completion order.
        """
        if len(cities) > MAX_CITIES_PER_BATCH:
            raise ValueError(f"A batch may contain at most {MAX_CITIES_PER_BATCH} cities.")
        if not cities:
            return []

        records: list[WeatherRecord] = []
        try:
            with ThreadPoolExecutor(max_workers=min(self.max_workers, len(cities))) as executor:
                future_to_city = {
                    executor.submit(self._extract_single, city): city.city for city in cities
                }
                for future in as_completed(future_to_city):
                    city_name = future_to_city[future]
                    try:
                        record = future.result()
                        if record is not None:
                            records.append(record)
                    except (requests.RequestException, ValueError, OSError) as exc:
                        logger.error(
                            "City extraction failed for '%s': %s", city_name, exc
                        )
        finally:
            self._close_worker_sessions()
        return records

    def _get_session(self) -> requests.Session:
        """Return the calling worker's private HTTP session.

        Returns:
            The session created by ``session_factory`` for the current thread.

        Side Effects:
            Creates and registers a new session the first time a worker calls it.
        """
        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = self._session_factory()
            self._thread_local.session = session
            with self._sessions_lock:
                self._sessions.append(session)
        return session

    def _close_worker_sessions(self) -> None:
        """Close every worker-owned session after extraction completes.

        Side Effects:
            Closes registered sessions and clears the extractor's session registry.
        """
        with self._sessions_lock:
            sessions, self._sessions = self._sessions, []
        for session in sessions:
            session.close()

    def _extract_single(self, city_input: CityInput) -> WeatherRecord | None:
        """Resolve coordinates and request one validated current forecast.

        Args:
            city_input: Validated city name and optional coordinate pair.

        Returns:
            A normalized weather record, or ``None`` after a logged upstream error.
        """
        coords = self._resolve_coordinates(city_input)
        if coords is None:
            return None

        latitude, longitude = coords
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,relative_humidity_2m,wind_speed_10m",
            "temperature_unit": "celsius",
            "wind_speed_unit": "ms",
        }

        try:
            response = self._get_session().get(
                FORECAST_URL, params=params, allow_redirects=False
            )
            response.raise_for_status()
            payload = OpenMeteoForecastResponse.model_validate(response.json())
        except requests.RequestException as exc:
            logger.error("Weather request failed for '%s': %s", city_input.city, exc)
            return None
        except (ValidationError, ValueError) as exc:
            logger.error("Invalid weather response for '%s': %s", city_input.city, exc)
            return None

        return WeatherRecord(
            city=city_input.city,
            latitude=payload.latitude,
            longitude=payload.longitude,
            temperature_c=payload.current.temperature_2m,
            humidity_pct=payload.current.relative_humidity_2m,
            wind_speed_ms=payload.current.wind_speed_10m,
            observation_time=payload.current.time,
            extracted_at=datetime.now(timezone.utc),
        )

    def _resolve_coordinates(
        self, city_input: CityInput
    ) -> tuple[float, float] | None:
        """Return supplied coordinates or fetch the first geocoding match.

        Args:
            city_input: City to resolve.

        Returns:
            A latitude/longitude pair, or ``None`` if lookup fails or has no result.
        """
        if city_input.latitude is not None and city_input.longitude is not None:
            return city_input.latitude, city_input.longitude

        try:
            response = self._get_session().get(
                GEOCODING_URL,
                params={
                    "name": city_input.city,
                    "count": 1,
                    "language": "en",
                    "format": "json",
                },
                allow_redirects=False,
            )
            response.raise_for_status()
            payload = OpenMeteoGeocodingResponse.model_validate(response.json())
        except requests.RequestException as exc:
            logger.error("Geocoding request failed for '%s': %s", city_input.city, exc)
            return None
        except (ValidationError, ValueError) as exc:
            logger.error("Invalid geocoding response for '%s': %s", city_input.city, exc)
            return None

        if not payload.results:
            logger.warning("Geocoding returned no matches for city '%s'.", city_input.city)
            return None

        best_match = payload.results[0]
        return best_match.latitude, best_match.longitude
