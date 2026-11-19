"""Provide command-line arguments and execute the weather ETL pipeline."""

import argparse
import logging
from pathlib import Path
from typing import get_args

from .client import create_http_session
from .exporter import AtomicCSVExporter
from .extractor import WeatherExtractor
from .models import MAX_CITIES_PER_BATCH, CityInput, SortCriteria
from .pipeline import run_weather_pipeline
from .transformer import WeatherTransformer

DEFAULT_CITIES: list[CityInput] = [
    CityInput(city="New York", latitude=40.7128, longitude=-74.0060),
    CityInput(city="Tokyo", latitude=35.6895, longitude=139.6917),
    CityInput(city="London", latitude=51.5074, longitude=-0.1278),
    CityInput(city="Paris", latitude=48.8566, longitude=2.3522),
    CityInput(city="Berlin", latitude=52.5200, longitude=13.4050),
    CityInput(city="Sydney", latitude=-33.8688, longitude=151.2093),
    CityInput(city="Mumbai", latitude=19.0760, longitude=72.8777),
    CityInput(city="Cape Town", latitude=-33.9249, longitude=18.4241),
    CityInput(city="Moscow", latitude=55.7558, longitude=37.6173),
    CityInput(city="Rio de Janeiro", latitude=-22.9068, longitude=-43.1729),
]


def main() -> None:
    """Parse CLI options, run the pipeline, and print non-empty results."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    parser = argparse.ArgumentParser(description="Weather Data Connector CLI")
    parser.add_argument(
        "--cities",
        nargs="+",
        help=f"City names (at most {MAX_CITIES_PER_BATCH}; defaults to 10 preset cities)",
    )
    parser.add_argument(
        "--sort-by",
        choices=get_args(SortCriteria),
        default="temperature_desc",
        help="Ranking criterion",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("output"), help="CSV output folder"
    )
    args = parser.parse_args()
    if args.cities and len(args.cities) > MAX_CITIES_PER_BATCH:
        parser.error(f"--cities accepts at most {MAX_CITIES_PER_BATCH} city names.")
    try:
        cities = (
            [CityInput(city=name) for name in args.cities]
            if args.cities
            else DEFAULT_CITIES
        )
    except ValueError as exc:
        parser.error(str(exc))

    frame = run_weather_pipeline(
        cities=cities,
        extractor=WeatherExtractor(session_factory=create_http_session),
        transformer=WeatherTransformer(),
        sink=AtomicCSVExporter(output_dir=args.output_dir),
        sort_by=args.sort_by,
    )
    if not frame.empty:
        print(frame.to_string(index=False))


if __name__ == "__main__":
    main()
