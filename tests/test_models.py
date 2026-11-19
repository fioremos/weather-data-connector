"""Verify defensive validation of city names and coordinate pairs."""

import pytest
from pydantic import ValidationError

from app.models import CityInput


@pytest.mark.parametrize("city", [" London\n", "http://example.com", "A" * 101])
def test_city_input_rejects_unsafe_or_oversized_names(city: str) -> None:
    """Control characters, URL punctuation, and overlong names are rejected."""
    with pytest.raises(ValidationError):
        CityInput(city=city)


def test_city_input_requires_complete_coordinate_pair() -> None:
    """A latitude without longitude is not accepted."""
    with pytest.raises(ValidationError, match="Both latitude and longitude"):
        CityInput(city="London", latitude=51.5)
