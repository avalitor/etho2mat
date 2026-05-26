"""The frozen output contract -- the single source of truth for the ``.mat`` schema.

Downstream ephys code parses these files by exact field **name, dtype-kind, shape,
and array orientation**, so this module defines the contract once and serialises
to it explicitly (never as a side effect of ``savemat(self.__dict__)``).

Orientation rules (preserved from the legacy files, see RECON section 6):
  * coordinate arrays ``r_nose/r_center/r_tail`` are ``(N, 2)``
  * ``time / velocity / head_direction / heading`` are ``(1, N)`` row vectors
  * ``target`` is ``(K, 2)`` (K>=1, one row per assigned reward target)
  * scalar strings are stored as char arrays; ``mouse_number/day/trial`` stay strings
  * ``eth_file`` is a **string** (the original Ethovision filename)

Adding a field is a deliberate ``SCHEMA_VERSION`` bump. Optional fields are safe
because the consumer guards them with ``if key in m``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .validate import SchemaError

# Bump when the set/encoding of written fields changes deliberately.
SCHEMA_VERSION = "etho2mat-1"

# Fields the legacy pipeline never wrote; consumers must guard them.
# (informational -- used by the golden harness to classify "new" vs "parity" fields)
NEW_FIELDS = ("schema_version", "mouse_strain", "reward_reached")

# Explicitly NOT written here -- the ephys side injects it via its sync pipeline.
NOT_WRITTEN = ("time_ttl",)


@dataclass
class TrialRecord:
    """Everything that goes into one trial's ``.mat`` file.

    Required fields have no default; fields that are absent on older vintages or
    only present on some trials default to ``None`` and are omitted from the
    output dict when unset.
    """

    # --- metadata (strings) ---
    exp: str
    eth_file: str                 # original Ethovision filename (was an int)
    protocol_name: str
    protocol_description: str
    experimenter: str
    bkgd_img: str
    mouse_number: str
    mouse_sex: str
    day: str
    trial: str
    entrance: str
    filename: str

    # --- geometry / config (float) ---
    img_extent: np.ndarray        # (4,) -> stored (1,4)
    target: np.ndarray            # (K,2)

    # --- trajectory data (float) ---
    time: np.ndarray              # (N,) -> stored (1,N)
    r_nose: np.ndarray            # (N,2)
    r_center: np.ndarray          # (N,2)
    r_tail: np.ndarray            # (N,2)

    # --- optional / version-tagged ---
    mouse_strain: str = ""
    target_reverse: Optional[np.ndarray] = None   # (1,2), reverse trials only
    velocity: Optional[np.ndarray] = None         # (N,) -> (1,N)
    head_direction: Optional[np.ndarray] = None   # (N,) -> (1,N)
    heading: Optional[np.ndarray] = None          # (N,) -> (1,N)
    arena_circle: Optional[np.ndarray] = None     # (3,) -> (1,3)
    r_arena_holes: Optional[np.ndarray] = None    # (M,2)
    k_reward: Optional[int] = None                # (1,1)
    reward_reached: Optional[bool] = None         # (1,1) logical
    k_hole_checks: Optional[np.ndarray] = None    # (K,2) int

    schema_version: str = SCHEMA_VERSION


def _f64(a) -> np.ndarray:
    return np.asarray(a, dtype=np.float64)


def to_matdict(rec: TrialRecord) -> dict:
    """Build the exact dict handed to ``scipy.io.savemat``.

    Strings are passed through (scipy encodes them as char arrays). 1-D vectors
    that must read back as ``(1, N)`` are stored as 1-D; scipy promotes them.
    Optional fields that are ``None`` are omitted entirely.
    """
    d: dict = {
        "exp": str(rec.exp),
        "protocol_name": str(rec.protocol_name),
        "protocol_description": str(rec.protocol_description),
        "eth_file": str(rec.eth_file),
        "bkgd_img": str(rec.bkgd_img),
        "img_extent": _f64(rec.img_extent).reshape(-1),         # (4,) -> (1,4)
        "experimenter": str(rec.experimenter),
        "mouse_number": str(rec.mouse_number),
        "mouse_sex": str(rec.mouse_sex),
        "mouse_strain": str(rec.mouse_strain),
        "day": str(rec.day),
        "trial": str(rec.trial),
        "entrance": str(rec.entrance),
        "target": _f64(rec.target).reshape(-1, 2),              # (K,2)
        "time": _f64(rec.time).reshape(-1),                     # (N,) -> (1,N)
        "r_nose": _f64(rec.r_nose).reshape(-1, 2),
        "r_center": _f64(rec.r_center).reshape(-1, 2),
        "r_tail": _f64(rec.r_tail).reshape(-1, 2),
        "filename": str(rec.filename),
        "schema_version": str(rec.schema_version),
    }

    if rec.target_reverse is not None:
        d["target_reverse"] = _f64(rec.target_reverse).reshape(1, 2)
    if rec.velocity is not None:
        d["velocity"] = _f64(rec.velocity).reshape(-1)
    if rec.head_direction is not None:
        d["head_direction"] = _f64(rec.head_direction).reshape(-1)
    if rec.heading is not None:
        d["heading"] = _f64(rec.heading).reshape(-1)
    if rec.arena_circle is not None:
        d["arena_circle"] = _f64(rec.arena_circle).reshape(-1)  # (3,) -> (1,3)
    if rec.r_arena_holes is not None:
        d["r_arena_holes"] = _f64(rec.r_arena_holes).reshape(-1, 2)
    if rec.k_reward is not None:
        d["k_reward"] = int(rec.k_reward)
    if rec.reward_reached is not None:
        d["reward_reached"] = bool(rec.reward_reached)
    if rec.k_hole_checks is not None:
        khc = np.asarray(rec.k_hole_checks)
        # Match the legacy empty encoding: no hole checks -> np.array([]) -> (0,0).
        d["k_hole_checks"] = np.array([]) if khc.size == 0 else khc.reshape(-1, 2).astype(np.int64)

    return d


def validate_record(rec: TrialRecord) -> None:
    """Light structural check before writing -- fail loud on a contract violation."""
    target = _f64(rec.target).reshape(-1, 2)
    if target.shape[0] < 1:
        raise SchemaError(f"{rec.filename}: target must have at least one row, got {target.shape}.")
    n = _f64(rec.time).reshape(-1).shape[0]
    for name in ("r_nose", "r_center", "r_tail"):
        arr = _f64(getattr(rec, name)).reshape(-1, 2)
        if arr.shape[0] != n:
            raise SchemaError(
                f"{rec.filename}: {name} has {arr.shape[0]} rows but time has {n} samples."
            )
