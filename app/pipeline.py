"""Orchestrate the extraction, transformation, ranking, and optional export steps."""

import logging

import pandas as pd

from .exporter import DataSink
from .extractor import WeatherExtractor
from .models import CityInput, SortCriteria
from .transformer import WeatherTransformer

logger = logging.getLogger(__name__)


def run_weather_pipeline(
    cities: list[CityInput],
    extractor: WeatherExtractor,
    transformer: WeatherTransformer,
    *,
    sink: DataSink | None = None,
    sort_by: SortCriteria = "temperature_desc",
    top_n: int | None = None,
) -> pd.DataFrame:
    """Run the ETL flow and optionally persist its ranked output.

    Args:
        cities: Validated city requests.
        extractor: Component that retrieves upstream observations.
        transformer: Component that converts and ranks observations.
        sink: Optional destination for non-empty results.
        sort_by: Ranking criterion.
        top_n: Optional positive limit for ranked rows.

    Returns:
        A DataFrame with the canonical output schema.
    """
    records = extractor.extract_batch(cities)
    if not records:
        logger.warning("No weather records extracted.")
    frame = transformer.transform(records)
    frame = transformer.rank(frame, sort_by=sort_by, top_n=top_n)

    if sink is not None and not frame.empty:
        sink.export(frame)
    return frame
