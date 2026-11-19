"""Generate in-memory or saved Matplotlib charts from transformed weather data."""

from io import BytesIO
from pathlib import Path
import threading
from typing import Literal

import matplotlib
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
from matplotlib.figure import Figure

# Backend selection must precede pyplot, so its import grouping is intentionally overridden.
matplotlib.use("Agg")
# pylint: disable=wrong-import-position,wrong-import-order,ungrouped-imports
import matplotlib.pyplot as plt
# pylint: enable=wrong-import-position,wrong-import-order,ungrouped-imports

ChartType = Literal["bar", "scatter", "dashboard", "heatmap"]
CHART_COLUMNS: tuple[str, ...] = (
    "Temperature (C)",
    "Humidity (%)",
    "Wind Speed (m/s)",
)
_CHART_LOCK = threading.Lock()


def _plot_bar(frame: pd.DataFrame, axis: Axes) -> None:
    """Draw a horizontal temperature comparison."""
    temperature = frame["Temperature (C)"]
    color_map = plt.get_cmap("coolwarm")
    normalization = Normalize(vmin=temperature.min(), vmax=temperature.max())
    axis.barh(
        frame["City"],
        temperature,
        color=color_map(normalization(temperature)),
    )
    axis.figure.colorbar(
        ScalarMappable(norm=normalization, cmap=color_map),
        ax=axis,
        label="Temperature (C)",
    )
    axis.set_xlabel("Temperature (C)")
    axis.set_title("Temperature by City")


def _plot_scatter(frame: pd.DataFrame, axis: Axes) -> None:
    """Draw temperature/humidity points sized by wind speed."""
    wind = frame["Wind Speed (m/s)"]
    maximum_wind = float(wind.max())
    sizes = wind * (400.0 / maximum_wind) if maximum_wind > 0 else 30.0
    axis.scatter(
        frame["Temperature (C)"],
        frame["Humidity (%)"],
        s=sizes,
        alpha=0.7,
        c=frame["Temperature (C)"],
        cmap="coolwarm",
    )
    axis.figure.colorbar(
        axis.collections[0], ax=axis, label="Temperature (C)"
    )
    for city, temperature, humidity in zip(
        frame["City"], frame["Temperature (C)"], frame["Humidity (%)"]
    ):
        axis.annotate(
            str(city),
            (temperature, humidity),
            xytext=(5, 5),
            textcoords="offset points",
        )
    axis.set_xlabel("Temperature (C)")
    axis.set_ylabel("Humidity (%)")
    axis.set_title("Temperature, Humidity, and Wind")


def _plot_dashboard(frame: pd.DataFrame, figure: Figure) -> None:
    """Draw three horizontal metric charts with a shared city axis."""
    axes = figure.subplots(1, 3, sharey=True)
    titles = (
        ("Temperature (C)", "Temperature (C)"),
        ("Humidity (%)", "Humidity (%)"),
        ("Wind Speed (m/s)", "Wind Speed (m/s)"),
    )
    color_maps = {
        "Temperature (C)": "coolwarm",
        "Humidity (%)": "Blues",
        "Wind Speed (m/s)": "YlGnBu",
    }
    for axis, (column, title) in zip(axes, titles):
        values = pd.to_numeric(frame[column])
        color_map = plt.get_cmap(color_maps[column])
        normalization = Normalize(vmin=values.min(), vmax=values.max())
        axis.barh(frame["City"], values, color=color_map(normalization(values)))
        axis.axvline(
            values.mean(), color="#37474F", linestyle="--", label="Mean"
        )
        axis.legend()
        axis.set_title(title)
        axis.set_xlabel(column)


def _plot_heatmap(frame: pd.DataFrame, axis: Axes) -> None:
    """Draw a min-max normalized city/metric matrix with raw-value labels."""
    values = frame[list(CHART_COLUMNS)].apply(pd.to_numeric)
    ranges = values.max() - values.min()
    normalized = (values - values.min()) / ranges.where(ranges != 0, 1)
    image = axis.imshow(normalized.to_numpy(), aspect="auto", cmap="coolwarm")
    axis.set_xticks(range(len(CHART_COLUMNS)), CHART_COLUMNS, rotation=25, ha="right")
    axis.set_yticks(range(len(frame)), frame["City"])
    for row_index in range(len(frame)):
        for column_index, column in enumerate(CHART_COLUMNS):
            axis.text(
                column_index,
                row_index,
                f"{values.iloc[row_index][column]:g}",
                ha="center",
                va="center",
                color="black",
            )
    axis.figure.colorbar(image, ax=axis, label="Normalized value")
    axis.set_title("Weather Metrics by City")


def generate_weather_chart(
    frame: pd.DataFrame,
    chart_type: ChartType = "bar",
    output_path: Path | None = None,
) -> bytes:
    """Render a chart to PNG bytes and optionally save those bytes to disk.

    Args:
        frame: Non-empty transformed data with city and weather metric columns.
        chart_type: Chart layout to render.
        output_path: Optional destination for the generated PNG.

    Returns:
        PNG-encoded image bytes.

    Raises:
        ValueError: If the chart type, input data, or required columns are invalid.

    Side Effects:
        May create the output directory and write the PNG; always closes the figure.
    """
    if chart_type not in ("bar", "scatter", "dashboard", "heatmap"):
        raise ValueError(f"Unsupported chart type: {chart_type!r}")
    required_columns = {"City", *CHART_COLUMNS}
    missing_columns = required_columns.difference(frame.columns)
    if missing_columns:
        raise ValueError(f"DataFrame is missing chart columns: {sorted(missing_columns)}")
    if frame.empty:
        raise ValueError("Cannot create a chart from an empty DataFrame.")
    if frame["City"].isna().any():
        raise ValueError("City values must not be empty.")
    metrics = frame[list(CHART_COLUMNS)].apply(pd.to_numeric, errors="raise")
    if metrics.isna().any().any():
        raise ValueError("Weather metric values must not be empty.")
    chart_frame = frame.copy()
    chart_frame[list(CHART_COLUMNS)] = metrics

    figure_width = 15 if chart_type == "dashboard" else 10
    with _CHART_LOCK:
        figure = plt.figure(figsize=(figure_width, max(4, len(chart_frame) * 0.5)))
        try:
            if chart_type == "dashboard":
                _plot_dashboard(chart_frame, figure)
            else:
                axis = figure.subplots()
                if chart_type == "bar":
                    _plot_bar(chart_frame, axis)
                elif chart_type == "scatter":
                    _plot_scatter(chart_frame, axis)
                else:
                    _plot_heatmap(chart_frame, axis)
            figure.tight_layout()
            with BytesIO() as image_buffer:
                figure.savefig(image_buffer, format="png", bbox_inches="tight")
                image_bytes = image_buffer.getvalue()
            if output_path is not None:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(image_bytes)
            return image_bytes
        finally:
            plt.close(figure)
