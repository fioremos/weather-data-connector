"""Expose authenticated ETL execution and safe access to generated artifacts."""

import hmac
import os
from pathlib import Path
import threading
from typing import Annotated, Literal

import pandas as pd
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import FileResponse, Response

from .client import create_http_session
from .exporter import AtomicCSVExporter
from .extractor import WeatherExtractor
from .models import WeatherRunRequest
from .pipeline import run_weather_pipeline
from .transformer import OUTPUT_COLUMNS, WeatherTransformer
from .visualizer import generate_weather_chart

load_dotenv()

app: FastAPI = FastAPI(title="Weather Data Connector", version="1.0.0")
OUTPUT_DIR: Path = Path(os.getenv("OUTPUT_DIR", "output")).resolve()
API_KEY: str = os.getenv("API_KEY", "")
_RUN_LOCK: threading.Lock = threading.Lock()
_NO_WEATHER_DATA_MESSAGE = (
    "Weather data is unavailable. Run the ingestion pipeline first."
)


def _require_api_key(
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    """Validate the optional run-endpoint API key.

    Args:
        x_api_key: Value of the request's ``X-API-Key`` header.

    Raises:
        HTTPException: If a configured key is absent or does not match.
    """
    if API_KEY and (x_api_key is None or not hmac.compare_digest(x_api_key, API_KEY)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
            headers={"WWW-Authenticate": "API key"},
        )


def _artifact_path(
    filename: str, missing_detail: str = "Artifact not found."
) -> Path:
    """Resolve an in-directory artifact and reject missing files or symlink escapes.

    Args:
        filename: Fixed artifact name selected by an API route.
        missing_detail: Message to include when the file is absent or unsafe.

    Returns:
        The resolved path, guaranteed to be inside ``OUTPUT_DIR``.

    Raises:
        HTTPException: If the file is absent or resolves outside the output directory.
    """
    output_dir = OUTPUT_DIR.resolve()
    artifact = (output_dir / filename).resolve()
    if output_dir not in artifact.parents or not artifact.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=missing_detail)
    return artifact


@app.get("/health")
def health() -> dict[str, str]:
    """Return a simple liveness response without exposing configuration secrets."""
    return {"status": "ok"}


@app.post(
    "/integrations/weather/run",
    dependencies=[Depends(_require_api_key)],
)
def run_weather(request: WeatherRunRequest) -> dict[str, int | str]:
    """Run ETL and persist both artifacts for a validated request.

    Args:
        request: Bounded cities, sorting criterion, and optional row limit.

    Returns:
        Counts and filenames for the generated artifacts.

    Raises:
        HTTPException: If upstream retrieval produces no usable weather records.
    """
    with _RUN_LOCK:
        frame = run_weather_pipeline(
            cities=request.cities,
            extractor=WeatherExtractor(session_factory=create_http_session),
            transformer=WeatherTransformer(),
            sink=AtomicCSVExporter(OUTPUT_DIR),
            sort_by=request.sort_by,
            top_n=request.top_n,
        )
        if frame.empty:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="No weather data could be retrieved from the upstream service.",
            )
        chart_path = OUTPUT_DIR / "weather_chart.png"
        generate_weather_chart(frame, output_path=chart_path)
    return {
        "rows": len(frame),
        "csv": Path("weather_data.csv").name,
        "chart": chart_path.name,
    }


@app.get("/integrations/weather/export")
def export_weather() -> FileResponse:
    """Stream the latest CSV file, returning 404 when no export exists."""
    return FileResponse(
        _artifact_path("weather_data.csv"),
        media_type="text/csv",
        filename="weather_data.csv",
    )


@app.get("/integrations/weather/chart")
def weather_chart(
    chart_type: Literal["bar", "scatter", "dashboard", "heatmap"] = "bar",
) -> Response:
    """Render a requested chart from the latest CSV without calling upstream APIs.

    Args:
        chart_type: Supported Matplotlib chart layout.

    Returns:
        The requested chart as a PNG response.

    Raises:
        HTTPException: If weather data is absent, empty, malformed, or incomplete.
    """
    csv_path = _artifact_path("weather_data.csv", _NO_WEATHER_DATA_MESSAGE)
    try:
        frame = pd.read_csv(csv_path)
    except (pd.errors.EmptyDataError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_NO_WEATHER_DATA_MESSAGE,
        ) from exc
    except (pd.errors.ParserError, UnicodeDecodeError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Weather data CSV could not be read.",
        ) from exc

    if frame.empty:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_NO_WEATHER_DATA_MESSAGE,
        )
    missing_columns = set(OUTPUT_COLUMNS).difference(frame.columns)
    if missing_columns:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Weather data CSV is missing required columns.",
        )
    try:
        image_bytes = generate_weather_chart(frame, chart_type=chart_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Weather data CSV contains invalid chart values.",
        ) from exc
    return Response(content=image_bytes, media_type="image/png")
