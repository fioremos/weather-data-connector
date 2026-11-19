"""Verify canonical weather transformation, unit conversion, and ranking behavior."""

from datetime import datetime, timezone

import pandas as pd
import pytest

from app.models import WeatherRecord
from app.transformer import OUTPUT_COLUMNS, WeatherTransformer


def _record(city: str, temperature: float, wind_speed: float, day: int) -> WeatherRecord:
    """Build a deterministic test observation."""
    return WeatherRecord(
        city=city,
        latitude=0,
        longitude=0,
        temperature_c=temperature,
        humidity_pct=50,
        wind_speed_ms=wind_speed,
        observation_time="2026-01-01T00:00",
        extracted_at=datetime(2026, 1, day, tzinfo=timezone.utc),
    )


def test_transform_empty_records_keeps_output_schema() -> None:
    """An empty extraction still returns all required CSV columns."""
    frame = WeatherTransformer().transform([])

    assert frame.empty
    assert list(frame.columns) == OUTPUT_COLUMNS


def test_transform_deduplicates_case_insensitively_and_converts_units() -> None:
    """The latest case-insensitive duplicate wins and derived units are accurate."""
    frame = WeatherTransformer().transform(
        [
            _record("Paris", 0, 1, 1),
            _record("parIS", 100, 2, 2),
        ]
    )

    assert len(frame) == 1
    assert frame.loc[0, "City"] == "parIS"
    assert frame.loc[0, "Temperature (F)"] == 212
    assert frame.loc[0, "Wind Speed (mph)"] == 4.47


def test_rank_transformed_csv_frame_without_recalculating_metrics() -> None:
    """Ranking a CSV-loaded frame preserves its precomputed columns."""
    source = pd.DataFrame(
        [
            ["A", 10.0, 50.0, 40.0, 1.0, 2.24],
            ["B", 20.0, 68.0, 60.0, 3.0, 6.71],
        ],
        columns=OUTPUT_COLUMNS,
    )

    ranked = WeatherTransformer.rank(source, sort_by="temperature_desc", top_n=1)

    assert ranked.loc[0, "City"] == "B"
    assert ranked.loc[0, "Temperature (F)"] == 68.0
    assert len(source) == 2


@pytest.mark.parametrize("top_n", [0, -1, 1.5, True])
def test_rank_rejects_invalid_top_n(top_n: object) -> None:
    """Non-positive or non-integer top_n values fail for empty canonical frames."""
    empty = pd.DataFrame(columns=OUTPUT_COLUMNS)

    with pytest.raises(ValueError, match="top_n"):
        WeatherTransformer.rank(empty, top_n=top_n)  # type: ignore[arg-type]


def test_rank_validates_columns_for_empty_frames() -> None:
    """An empty frame with a missing schema is not silently accepted."""
    with pytest.raises(ValueError, match="missing required columns"):
        WeatherTransformer.rank(pd.DataFrame())
