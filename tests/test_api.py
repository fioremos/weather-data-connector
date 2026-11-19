"""Verify API input validation, authentication, and artifact-not-found responses."""

from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import api
from app.exporter import DataSink
from app.transformer import OUTPUT_COLUMNS


def test_artifact_endpoints_return_404_when_files_are_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CSV and chart requests report missing output and direct users to ingest."""
    monkeypatch.setattr(api, "OUTPUT_DIR", tmp_path)
    client = TestClient(api.app)

    assert client.get("/integrations/weather/export").status_code == 404
    chart_response = client.get("/integrations/weather/chart")
    assert chart_response.status_code == 404
    assert "run the ingestion pipeline first" in chart_response.json()["detail"].lower()


def test_chart_is_generated_from_existing_csv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The chart endpoint renders a selected type from CSV without re-ingestion."""
    monkeypatch.setattr(api, "OUTPUT_DIR", tmp_path)
    frame = pd.DataFrame(
        [["London", 10.0, 50.0, 60.0, 2.0, 4.47]],
        columns=OUTPUT_COLUMNS,
    )
    frame.to_csv(tmp_path / "weather_data.csv", index=False)
    monkeypatch.setattr(
        api,
        "run_weather_pipeline",
        lambda **kwargs: pytest.fail("Chart generation must not rerun ingestion."),
    )
    client = TestClient(api.app)

    response = client.get("/integrations/weather/chart?chart_type=scatter")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_empty_csv_returns_not_found_and_invalid_chart_type_returns_unprocessable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty CSV data returns 404, while unsupported chart types return 422."""
    monkeypatch.setattr(api, "OUTPUT_DIR", tmp_path)
    client = TestClient(api.app)
    empty_csv = tmp_path / "weather_data.csv"
    empty_csv.write_text(",".join(OUTPUT_COLUMNS) + "\n", encoding="utf-8")

    assert client.get("/integrations/weather/chart").status_code == 404
    empty_csv.write_text("invalid\n", encoding="utf-8")
    assert (
        client.get("/integrations/weather/chart?chart_type=pie").status_code == 422
    )


def test_run_validates_sort_and_city_batch_size() -> None:
    """Invalid sort values and oversized request batches fail with HTTP 422."""
    client = TestClient(api.app)
    invalid_sort = client.post(
        "/integrations/weather/run",
        json={"cities": [{"city": "London"}], "sort_by": "unknown"},
    )
    oversized = client.post(
        "/integrations/weather/run",
        json={"cities": [{"city": f"City {index}"} for index in range(51)]},
    )

    assert invalid_sort.status_code == 422
    assert oversized.status_code == 422


def test_run_requires_api_key_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The run endpoint requires the configured X-API-Key header."""
    monkeypatch.setattr(api, "API_KEY", "expected-secret")
    monkeypatch.setattr(
        api,
        "run_weather_pipeline",
        lambda **kwargs: pd.DataFrame(columns=OUTPUT_COLUMNS),
    )
    client = TestClient(api.app)
    payload = {"cities": [{"city": "London"}]}

    assert client.post("/integrations/weather/run", json=payload).status_code == 401
    assert (
        client.post(
            "/integrations/weather/run",
            json=payload,
            headers={"X-API-Key": "expected-secret"},
        ).status_code
        == 502
    )


def test_successful_run_writes_csv_and_chart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful ETL run produces both artifacts served by download routes."""
    monkeypatch.setattr(api, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(api, "API_KEY", "")
    frame = pd.DataFrame(
        [["London", 10.0, 50.0, 60.0, 2.0, 4.47]],
        columns=OUTPUT_COLUMNS,
    )
    def export_frame(**kwargs: object) -> pd.DataFrame:
        """Persist the test frame through the sink as the real pipeline does."""
        sink = kwargs.get("sink")
        if isinstance(sink, DataSink):
            sink.export(frame)
        return frame

    monkeypatch.setattr(api, "run_weather_pipeline", export_frame)
    client = TestClient(api.app)

    response = client.post(
        "/integrations/weather/run",
        json={"cities": [{"city": "London"}]},
    )

    assert response.status_code == 200
    assert client.get("/integrations/weather/export").status_code == 200
    assert client.get("/integrations/weather/chart").status_code == 200
