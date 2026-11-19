"""Verify Matplotlib chart variants, PNG output, and figure cleanup."""

from pathlib import Path

import matplotlib
import pandas as pd
import pytest
from matplotlib._pylab_helpers import Gcf

from app.visualizer import ChartType, generate_weather_chart

CHART_DATA = pd.DataFrame(
    {
        "City": ["London", "Tokyo"],
        "Temperature (C)": [12.0, 20.0],
        "Temperature (F)": [53.6, 68.0],
        "Humidity (%)": [70.0, 55.0],
        "Wind Speed (m/s)": [3.0, 5.0],
        "Wind Speed (mph)": [6.71, 11.18],
    }
)


@pytest.mark.parametrize("chart_type", ["bar", "scatter", "dashboard", "heatmap"])
def test_chart_types_render_png_and_close_figures(chart_type: ChartType) -> None:
    """Every supported chart type produces PNG bytes without leaking figures."""
    assert matplotlib.get_backend().lower() == "agg"
    existing_figures = len(Gcf.get_all_fig_managers())

    image = generate_weather_chart(CHART_DATA, chart_type=chart_type)

    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(Gcf.get_all_fig_managers()) == existing_figures


def test_chart_can_also_be_saved_to_disk(tmp_path: Path) -> None:
    """An optional output path receives the same PNG bytes returned to callers."""
    output_path = tmp_path / "weather.png"

    image = generate_weather_chart(CHART_DATA, output_path=output_path)

    assert output_path.read_bytes() == image
