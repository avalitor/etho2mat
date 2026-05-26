"""Resolves the data folders the pipeline reads and writes.

This is the ONE place to repoint a folder. By default everything lives in
relative folders inside the repo, so a student configures nothing. To send the
`.mat` output straight to the downstream ephys directory, change ``OUTPUT_DIR``
below (or set the ``ETHO2MAT_OUTPUT`` environment variable).

Nothing else in the codebase hardcodes a data path -- import from here.
"""

from __future__ import annotations

import os
from pathlib import Path

# Repo root = the folder that contains src/, config/, raw/, ...
ROOT_DIR = Path(__file__).resolve().parent.parent


def _resolve(env_var: str, default: Path) -> Path:
    """Use an env-var override if set, else the in-repo default."""
    override = os.environ.get(env_var)
    return Path(override).expanduser().resolve() if override else default


# --- The four data folders (override via the matching env var if needed) ---
RAW_DIR = _resolve("ETHO2MAT_RAW", ROOT_DIR / "raw")
BACKGROUND_DIR = _resolve("ETHO2MAT_BACKGROUNDS", ROOT_DIR / "background_images")
OUTPUT_DIR = _resolve("ETHO2MAT_OUTPUT", ROOT_DIR / "output")
CONFIG_DIR = _resolve("ETHO2MAT_CONFIG", ROOT_DIR / "config")

# --- Derived locations ---
TARGETS_DIR = CONFIG_DIR / "targets"
EXPERIMENT_LIST = CONFIG_DIR / "experiment_list.csv"
MOUSE_MAP = CONFIG_DIR / "mouse_map.csv"
VERIFICATION_DIR = OUTPUT_DIR / "verification"
FLAGGED_TRIALS_CSV = OUTPUT_DIR / "flagged_trials.csv"


def raw_experiment_dir(experiment: str) -> Path:
    """The raw-data subfolder for one experiment (``raw/<experiment>...``).

    The folder name must start with the experiment id; the rest is free text
    (e.g. ``2025-01-21_Raw Trial Data``). Returns the first match, or raises.
    """
    matches = sorted(p for p in RAW_DIR.glob(f"{experiment}*") if p.is_dir())
    if not matches:
        from .validate import InputError

        raise InputError(
            f"No raw-data folder for experiment '{experiment}'. "
            f"Expected a folder under {RAW_DIR} whose name starts with "
            f"'{experiment}' (e.g. '{experiment}_Raw Trial Data')."
        )
    return matches[0]
