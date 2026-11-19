"""Verify CSV formula-injection protection and output-path confinement."""

from pathlib import Path

import pandas as pd
import pytest

from app.exporter import AtomicCSVExporter


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
def test_export_neutralizes_formula_prefixes(tmp_path: Path, prefix: str) -> None:
    """CSV text beginning with spreadsheet formula triggers is prefixed safely."""
    exporter = AtomicCSVExporter(tmp_path)
    target = exporter.export(pd.DataFrame({"City": [f"{prefix}SUM(A1:A2)"]}))

    assert pd.read_csv(target, dtype=str).loc[0, "City"] == f"'{prefix}SUM(A1:A2)"


def test_export_rejects_path_traversal(tmp_path: Path) -> None:
    """A filename resolving outside the configured output directory is rejected."""
    with pytest.raises(ValueError, match="Unsafe target path"):
        AtomicCSVExporter(tmp_path, Path("..") / "outside.csv")
