"""Safely persist transformed records as atomic, formula-neutralized CSV files."""

from abc import ABC, abstractmethod
import logging
import os
from pathlib import Path
import tempfile
import threading

import pandas as pd

logger = logging.getLogger(__name__)

DANGEROUS_CSV_PREFIXES: tuple[str, ...] = ("=", "+", "-", "@", "\t", "\r")
_EXPORT_LOCK = threading.Lock()


def resolve_output_path(output_dir: Path, filename: str) -> tuple[Path, Path]:
    """Create an output directory and resolve a file strictly inside it.

    Args:
        output_dir: Configured directory for generated artifacts.
        filename: Relative file name to place in that directory.

    Returns:
        The resolved output directory and target file paths.

    Raises:
        ValueError: If the target resolves outside the output directory.
    """
    resolved_dir = output_dir.resolve()
    resolved_dir.mkdir(parents=True, exist_ok=True)
    target_path = (resolved_dir / filename).resolve()
    if target_path == resolved_dir or resolved_dir not in target_path.parents:
        raise ValueError(f"Unsafe target path detected: {target_path}")
    return resolved_dir, target_path


class DataSink(ABC):
    """Define the destination contract for transformed tabular data."""

    @abstractmethod
    def export(self, frame: pd.DataFrame) -> Path:
        """Persist a frame and return the resulting artifact path."""


class AtomicCSVExporter(DataSink):
    """Write sanitized CSV data inside a configured directory atomically.

    Args:
        output_dir: Directory that contains the resulting CSV.
        filename: Relative CSV filename constrained to the output directory.
    """

    def __init__(
        self, output_dir: Path, filename: str = "weather_data.csv"
    ) -> None:
        """Resolve and validate the output file and create its parent directory."""
        self.output_dir, self.target_path = resolve_output_path(output_dir, filename)

    def export(self, frame: pd.DataFrame) -> Path:
        """Sanitize text and atomically replace the configured CSV.

        Args:
            frame: Transformed rows to persist.

        Returns:
            The resolved output file path.

        Side Effects:
            Writes a temporary file and replaces the target under a process lock.
        """
        safe_frame = self._sanitize_for_csv(frame)
        file_descriptor, temp_path_string = tempfile.mkstemp(
            dir=str(self.output_dir), prefix=".tmp_weather_", suffix=".csv"
        )
        temp_path = Path(temp_path_string)
        try:
            with os.fdopen(file_descriptor, mode="w", encoding="utf-8", newline="") as handle:
                safe_frame.to_csv(handle, index=False)
            with _EXPORT_LOCK:
                # The temporary file shares the destination filesystem, so replacement is atomic.
                os.replace(temp_path, self.target_path)
            logger.info(
                "Exported %d rows atomically to '%s'",
                len(safe_frame),
                self.target_path,
            )
            return self.target_path
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

    @staticmethod
    def _sanitize_for_csv(frame: pd.DataFrame) -> pd.DataFrame:
        """Copy the frame and neutralize dangerous spreadsheet text.

        Args:
            frame: DataFrame containing strings that will be written to CSV.

        Returns:
            A sanitized copy; the input DataFrame is unchanged.
        """
        sanitized = frame.copy()
        for column in sanitized.select_dtypes(include=["object", "string"]).columns:
            sanitized[column] = sanitized[column].map(
                lambda value: f"'{value}"
                if isinstance(value, str) and value.startswith(DANGEROUS_CSV_PREFIXES)
                else value
            )
        return sanitized
