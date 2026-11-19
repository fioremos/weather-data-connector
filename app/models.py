"""Define validated request, Open-Meteo response, and weather domain models."""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CITY_NAME_PATTERN: re.Pattern[str] = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ0-9 .,'-]+$")
MAX_CITIES_PER_BATCH: int = 50

SortCriteria = Literal[
    "temperature_desc",
    "temperature_asc",
    "humidity_asc",
    "humidity_desc",
    "wind_desc",
    "wind_asc",
    "city_asc",
]


class CityInput(BaseModel):
    """Validate a city name and an optional complete coordinate pair."""

    model_config = ConfigDict(extra="forbid")

    city: str = Field(min_length=1, max_length=100, description="City name")
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)

    @field_validator("city")
    @classmethod
    def sanitize_city_name(cls, value: str) -> str:
        """Validate and trim the city string.

        Args:
            value: Untrusted city name from a CLI or API request.

        Returns:
            A trimmed city name that matches the allowed character set.

        Raises:
            ValueError: If the value contains unsafe characters or is blank.
        """
        if not CITY_NAME_PATTERN.fullmatch(value):
            raise ValueError("City names may contain letters, numbers, spaces, and ,.'- only.")
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("City names may contain letters, numbers, spaces, and ,.'- only.")
        return cleaned

    @model_validator(mode="after")
    def check_coordinates_pair(self) -> "CityInput":
        """Require a complete coordinate pair.

        Returns:
            This validated model instance.

        Raises:
            ValueError: If only one coordinate is present.
        """
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Both latitude and longitude must be provided together, or neither.")
        return self


class OpenMeteoGeocodingItem(BaseModel):
    """Represent one location in an Open-Meteo geocoding response."""

    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    country: str | None = None
    country_code: str | None = None


class OpenMeteoGeocodingResponse(BaseModel):
    """Validate the Open-Meteo geocoding response, including empty results."""

    model_config = ConfigDict(extra="ignore")

    results: list[OpenMeteoGeocodingItem] = Field(default_factory=list)
    generationtime_ms: float | None = None


class OpenMeteoCurrentUnits(BaseModel):
    """Validate unit labels accompanying Open-Meteo current measurements."""

    model_config = ConfigDict(extra="ignore")

    time: str
    interval: str
    temperature_2m: Literal["°C"]
    relative_humidity_2m: Literal["%"]
    wind_speed_10m: Literal["m/s"]


class OpenMeteoCurrentData(BaseModel):
    """Validate the current weather measurements returned by Open-Meteo."""

    model_config = ConfigDict(extra="ignore")

    time: str
    interval: int
    temperature_2m: float
    relative_humidity_2m: float = Field(ge=0.0, le=100.0)
    wind_speed_10m: float = Field(ge=0.0)


class OpenMeteoForecastResponse(BaseModel):
    """Validate the root object of an Open-Meteo forecast response."""

    model_config = ConfigDict(extra="ignore")

    latitude: float
    longitude: float
    generationtime_ms: float
    utc_offset_seconds: int
    timezone: str
    timezone_abbreviation: str
    elevation: float
    current_units: OpenMeteoCurrentUnits
    current: OpenMeteoCurrentData


class WeatherRecord(BaseModel):
    """Store one validated, normalized weather observation."""

    model_config = ConfigDict(frozen=True)

    city: str
    latitude: float
    longitude: float
    temperature_c: float
    humidity_pct: float
    wind_speed_ms: float
    observation_time: str
    extracted_at: datetime


class WeatherRunRequest(BaseModel):
    """Validate a bounded API request to run the weather integration."""

    model_config = ConfigDict(extra="forbid")

    cities: list[CityInput] = Field(min_length=1, max_length=MAX_CITIES_PER_BATCH)
    sort_by: SortCriteria = "temperature_desc"
    top_n: int | None = Field(default=None, gt=0, le=MAX_CITIES_PER_BATCH)
