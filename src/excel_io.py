"""Read an Ethovision Excel export robustly.

The export layout is NOT assumed fixed (it may change after the author leaves):
the data-column header is located by scanning for the ``Recording time`` row, and
the metadata is found by its row labels (``Mouse Number`` etc.) rather than by
hardcoded row counts. Required columns are validated by name and a missing one
fails loudly. ``Velocity`` / ``Direction`` are optional-but-expected (absent in
older exports).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .validate import ExcelError

# Column header that marks the start of the per-sample data block.
_DATA_HEADER_MARKERS = ("Recording time", "Trial time")

# Metadata rows we need, by their label in column A.
_META = {
    "mouse_number": "Mouse Number",
    "day": "Day",
    "trial": "Trial",
    "entrance": "Start Location",
}

# Required data columns (fail loud if any is missing/renamed).
_REQUIRED = {
    "time": "Recording time",
    "x_nose": "X nose", "y_nose": "Y nose",
    "x_center": "X center", "y_center": "Y center",
    "x_tail": "X tail", "y_tail": "Y tail",
}
# Optional-but-expected columns (recorded in the schema version when absent).
_OPTIONAL = {"velocity": "Velocity", "head_direction": "Direction"}


@dataclass
class TrialExcel:
    """One trial's contents, straight from the Excel file (no derived metrics)."""

    source_filename: str          # basename -> becomes eth_file
    mouse_number: str
    day: str
    trial: str
    entrance: str
    time: np.ndarray              # (N,)
    r_nose: np.ndarray            # (N,2)
    r_center: np.ndarray          # (N,2)
    r_tail: np.ndarray            # (N,2)
    velocity: Optional[np.ndarray]        # (N,) or None
    head_direction: Optional[np.ndarray]  # (N,) or None


def _as_str(value) -> str:
    """Coerce a header cell to a clean string ('69', not 69.0; 'Probe' as-is)."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _find_data_header_row(probe: pd.DataFrame, path: Path) -> int:
    """Row index (0-based) of the data-column header, found by its marker cell."""
    for r in range(len(probe)):
        cells = {str(x) for x in probe.iloc[r].tolist()}
        if cells & set(_DATA_HEADER_MARKERS):
            return r
    raise ExcelError(
        f"{path.name}: could not find the data header row (no "
        f"'Recording time' cell in the first {len(probe)} rows). "
        f"Is this an Ethovision trial export?"
    )


def _read_metadata(probe: pd.DataFrame, header_row: int, path: Path) -> dict:
    """Build {field: value} from the labelled metadata rows above the data block."""
    labels = {}
    for r in range(header_row):
        key = probe.iloc[r, 0]
        if isinstance(key, str):
            labels[key.strip()] = probe.iloc[r, 1]
    out = {}
    for field, label in _META.items():
        if label not in labels:
            raise ExcelError(
                f"{path.name}: metadata row '{label}' not found in the header. "
                f"Expected a row labelled '{label}' in column A."
            )
        out[field] = _as_str(labels[label])
    return out


def _drop_units_row(df: pd.DataFrame) -> pd.DataFrame:
    """Drop the units row ('s','cm',...) that sits directly under the header."""
    if len(df) == 0:
        return df
    first = df[_REQUIRED["time"]].iloc[0]
    try:
        float(first)
        return df            # first row is already numeric -> no units row
    except (TypeError, ValueError):
        return df.iloc[1:]   # non-numeric (e.g. 's') -> it's the units row


def read_trial_excel(path) -> TrialExcel:
    """Parse one Ethovision ``.xlsx`` trial export into a :class:`TrialExcel`."""
    path = Path(path)
    probe = pd.read_excel(path, header=None, nrows=100)
    header_row = _find_data_header_row(probe, path)
    meta = _read_metadata(probe, header_row, path)

    df = pd.read_excel(path, header=0, skiprows=header_row, na_values=["-"])
    df = _drop_units_row(df)

    missing = [name for name in _REQUIRED.values() if name not in df.columns]
    if missing:
        raise ExcelError(
            f"{path.name}: missing required data column(s): {missing}. "
            f"Found columns: {list(df.columns)}"
        )

    def col(name: str) -> np.ndarray:
        return df[name].to_numpy().astype(float)

    time = col(_REQUIRED["time"])
    r_nose = np.column_stack([col(_REQUIRED["x_nose"]), col(_REQUIRED["y_nose"])])
    r_center = np.column_stack([col(_REQUIRED["x_center"]), col(_REQUIRED["y_center"])])
    r_tail = np.column_stack([col(_REQUIRED["x_tail"]), col(_REQUIRED["y_tail"])])

    velocity = col(_OPTIONAL["velocity"]) if _OPTIONAL["velocity"] in df.columns else None
    head_direction = col(_OPTIONAL["head_direction"]) if _OPTIONAL["head_direction"] in df.columns else None

    return TrialExcel(
        source_filename=path.name,
        mouse_number=meta["mouse_number"],
        day=meta["day"],
        trial=meta["trial"],
        entrance=meta["entrance"],
        time=time,
        r_nose=r_nose,
        r_center=r_center,
        r_tail=r_tail,
        velocity=velocity,
        head_direction=head_direction,
    )
