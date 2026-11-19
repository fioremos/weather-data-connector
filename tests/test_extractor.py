"""Verify upstream contract parameters, worker isolation, and partial failures."""

import threading
from typing import Any

from app.extractor import WeatherExtractor
from app.models import CityInput

FORECAST_PAYLOAD = {
    "latitude": 51.5,
    "longitude": -0.1,
    "generationtime_ms": 0.1,
    "utc_offset_seconds": 0,
    "timezone": "GMT",
    "timezone_abbreviation": "GMT",
    "elevation": 10.0,
    "current_units": {
        "time": "iso8601",
        "interval": "seconds",
        "temperature_2m": "°C",
        "relative_humidity_2m": "%",
        "wind_speed_10m": "m/s",
    },
    "current": {
        "time": "2026-01-01T00:00",
        "interval": 900,
        "temperature_2m": 10.0,
        "relative_humidity_2m": 50,
        "wind_speed_10m": 2.0,
    },
}


class FakeResponse:
    """Provide the minimal response surface used by the extractor."""

    def __init__(self, payload: dict[str, Any]) -> None:
        """Store a JSON payload for the fake HTTP response."""
        self.payload = payload

    def raise_for_status(self) -> None:
        """Represent a successful HTTP response."""

    def json(self) -> dict[str, Any]:
        """Return the configured JSON payload."""
        return self.payload


class FakeSession:
    """Record requests and close state for one extractor worker."""

    def __init__(self, sessions: list["FakeSession"], lock: threading.Lock) -> None:
        """Register this new worker-specific fake session."""
        self.sessions = sessions
        self.lock = lock
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = False
        with lock:
            sessions.append(self)

    def get(
        self, url: str, **kwargs: Any
    ) -> FakeResponse:
        """Record one request and return a valid forecast payload."""
        self.calls.append((url, kwargs))
        return FakeResponse(FORECAST_PAYLOAD)

    def close(self) -> None:
        """Mark this session as closed."""
        self.closed = True


def test_workers_use_distinct_sessions_and_explicit_units() -> None:
    """Concurrent city requests use separate sessions and explicit unit settings."""
    sessions: list[FakeSession] = []
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    class ConcurrentSession(FakeSession):
        """Block each request until both worker sessions have been created."""

        def get(
            self, url: str, **kwargs: Any
        ) -> FakeResponse:
            """Record a request and synchronize both worker threads."""
            self.calls.append((url, kwargs))
            barrier.wait(timeout=5)
            return FakeResponse(FORECAST_PAYLOAD)

    def factory() -> ConcurrentSession:
        """Create and record one isolated worker session."""
        return ConcurrentSession(sessions, lock)

    extractor = WeatherExtractor(session_factory=factory, max_workers=2)
    records = extractor.extract_batch(
        [
            CityInput(city="London", latitude=51.5, longitude=-0.1),
            CityInput(city="Paris", latitude=48.8, longitude=2.3),
        ]
    )

    assert len(records) == 2
    assert len(sessions) == 2
    assert all(session.closed for session in sessions)
    for session in sessions:
        _, request = session.calls[0]
        assert request["allow_redirects"] is False
        assert request["params"]["temperature_unit"] == "celsius"
        assert request["params"]["wind_speed_unit"] == "ms"


def test_malformed_payload_does_not_abort_batch() -> None:
    """A malformed city's response is isolated from other successful records."""
    sessions: list[FakeSession] = []
    lock = threading.Lock()

    class MixedResponseSession(FakeSession):
        """Return malformed JSON for one request to exercise partial failure."""

        def get(
            self, url: str, **kwargs: Any
        ) -> FakeResponse:
            """Fail the first response's JSON parse and return valid data next."""
            self.calls.append((url, kwargs))
            if len(self.calls) == 1:
                class MalformedResponse(FakeResponse):
                    """Simulate a response body that cannot be decoded as JSON."""

                    def json(self) -> dict[str, Any]:
                        """Raise the decoding error produced by a malformed body."""
                        raise ValueError("Malformed JSON")

                return MalformedResponse({})
            return FakeResponse(FORECAST_PAYLOAD)

    def factory() -> MixedResponseSession:
        """Create a worker session whose first response is malformed."""
        return MixedResponseSession(sessions, lock)

    extractor = WeatherExtractor(session_factory=factory, max_workers=1)
    records = extractor.extract_batch(
        [
            CityInput(city="London", latitude=51.5, longitude=-0.1),
            CityInput(city="Paris", latitude=48.8, longitude=2.3),
        ]
    )

    assert len(records) == 1
    assert records[0].city == "Paris"
    assert all(session.closed for session in sessions)


def test_empty_geocoding_results_are_handled() -> None:
    """A valid geocoding response without matches returns no record."""
    sessions: list[FakeSession] = []
    lock = threading.Lock()

    class EmptyGeocodingSession(FakeSession):
        """Return a successful geocoding response with no results."""

        def get(
            self, url: str, **kwargs: Any
        ) -> FakeResponse:
            """Return an empty result list for the geocoding request."""
            self.calls.append((url, kwargs))
            return FakeResponse({"results": []})

    def factory() -> EmptyGeocodingSession:
        """Create a worker session for the empty-result case."""
        return EmptyGeocodingSession(sessions, lock)

    records = WeatherExtractor(session_factory=factory).extract_batch(
        [CityInput(city="Unknown Place")]
    )

    assert not records
    assert sessions[0].closed
