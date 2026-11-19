"""Convert validated weather records into the canonical ranked CSV dataset."""

import logging

import pandas as pd

from .models import SortCriteria, WeatherRecord

logger = logging.getLogger(__name__)

OUTPUT_COLUMNS: list[str] = [
    "City",
    "Temperature (C)",
    "Temperature (F)",
    "Humidity (%)",
    "Wind Speed (m/s)",
    "Wind Speed (mph)",
]
MS_TO_MPH_FACTOR: float = 2.23694


class WeatherTransformer:
    """Transform weather records and independently rank canonical DataFrames."""

    def transform(self, records: list[WeatherRecord]) -> pd.DataFrame:
        """Normalize records, calculate units, and deduplicate city names.

        Args:
            records: Validated weather observations.

        Returns:
            A DataFrame with the required CSV columns in canonical order.
        """
        if not records:
            logger.warning("No weather records received for transformation.")
            return pd.DataFrame(columns=OUTPUT_COLUMNS)

        rows = [
            {
                "City": record.city,
                "Temperature (C)": record.temperature_c,
                "Humidity (%)": record.humidity_pct,
                "Wind Speed (m/s)": record.wind_speed_ms,
                "_extracted_at": record.extracted_at,
            }
            for record in records
        ]
        frame = pd.DataFrame(rows)
        frame["_city_key"] = frame["City"].str.strip().str.casefold()
        frame = (
            frame.sort_values("_extracted_at", ascending=False)
            .drop_duplicates(subset=["_city_key"], keep="first")
            .drop(columns=["_city_key", "_extracted_at"])
        )
        frame["Temperature (F)"] = (
            frame["Temperature (C)"] * 9.0 / 5.0 + 32.0
        ).round(2)
        frame["Wind Speed (mph)"] = (
            frame["Wind Speed (m/s)"] * MS_TO_MPH_FACTOR
        ).round(2)
        frame["Temperature (C)"] = frame["Temperature (C)"].round(2)
        frame["Humidity (%)"] = frame["Humidity (%)"].round(1)
        frame["Wind Speed (m/s)"] = frame["Wind Speed (m/s)"].round(2)
        return frame[OUTPUT_COLUMNS].reset_index(drop=True)

    @staticmethod
    def rank(
        frame: pd.DataFrame,
        sort_by: SortCriteria = "temperature_desc",
        top_n: int | None = None,
    ) -> pd.DataFrame:
        """Sort an already-transformed DataFrame without recalculating metrics.

        Args:
            frame: DataFrame containing all canonical output columns.
            sort_by: Supported ranking criterion.
            top_n: Optional positive maximum number of rows.

        Returns:
            A sorted copy of the input frame.

        Raises:
            ValueError: If columns, sort criteria, or ``top_n`` are invalid.
        """
        if top_n is not None and (
            not isinstance(top_n, int) or isinstance(top_n, bool) or top_n <= 0
        ):
            raise ValueError("top_n must be a positive integer.")
        missing_columns = set(OUTPUT_COLUMNS).difference(frame.columns)
        if missing_columns:
            raise ValueError(
                f"DataFrame is missing required columns for ranking: {sorted(missing_columns)}"
            )

        sort_map: dict[SortCriteria, tuple[str, bool]] = {
            "temperature_desc": ("Temperature (C)", False),
            "temperature_asc": ("Temperature (C)", True),
            "humidity_asc": ("Humidity (%)", True),
            "humidity_desc": ("Humidity (%)", False),
            "wind_desc": ("Wind Speed (m/s)", False),
            "wind_asc": ("Wind Speed (m/s)", True),
            "city_asc": ("City", True),
        }
        if sort_by not in sort_map:
            raise ValueError(f"Unsupported sort criteria: {sort_by!r}")

        column, ascending = sort_map[sort_by]
        ranked = frame.sort_values(
            by=[column, "City"], ascending=[ascending, True]
        ).reset_index(drop=True)
        return ranked.head(top_n) if top_n is not None else ranked
