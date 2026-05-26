"""One-shot script: copy a curated subset of Excel fixtures from ``_reference/`` into
``tests/fixtures/raw/`` and write ``tests/fixtures/golden_manifest.json`` with the
expected per-field signatures (kind, shape, value-hash) for every fixture trial.

After ``_reference/`` is deleted, the committed test runs entirely against
``tests/fixtures/`` + the manifest, so the safety net stays armed.

Run once from the repo root (in the ``traj`` env):
    python scripts/build_fixtures.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import scipy.io as sio

REPO = Path(__file__).resolve().parent.parent
REF = REPO / "_reference"
DEST_RAW = REPO / "tests" / "fixtures" / "raw"
MANIFEST_PATH = REPO / "tests" / "fixtures" / "golden_manifest.json"

# Curated trials per experiment -- enough to exercise every code path:
#   parity (2022-08-12), multi-target (K,2) + alternating + Habituation quirk
#   (2025-01-21), per-mouse sex-thresholded targets and the mouse_sex bug fix +
#   lowercase no-reward patterns + empty k_hole_checks (2025-07-17).
CURATED = {
    "2022-08-12": [
        ("69", "1"),                                    # parity (single A, no reverse)
        ("69", "19"),                                   # first B (reverse A)
        ("69", "Probe"),                                # code/file divergence (Probe -> B)
        ("69", "Habituation 1"),                        # Habituation -> B, no reverse
        ("70", "1"),                                    # second entrance (SE)
    ],
    "2025-01-21": [
        ("112", "1"),                                   # single A
        ("112", "21"),                                  # first B (reverse A)
        ("112", "30"),                                  # multi-target (K,2), no reverse
        ("112", "35"),                                  # alternating A with reverse B
        ("112", "Probe3"),                              # multi-target probe
        ("112", "Habituation 1"),                       # target = reverse = A quirk
    ],
    "2025-07-17": [
        ("54", "1"),                                    # male, A (sex-bug fixed)
        ("54", "31"),                                   # male first B (threshold 30)
        ("54", "probe2"),                               # male probe -> B
        ("58", "1"),                                    # female, A (sex-bug fixed)
        ("58", "21"),                                   # female first B (threshold 20)
        ("58", "probe1"),                               # probe1 -> A
        ("58", "habit3"),                               # had the 7e-15 arctan2 ULP
    ],
}

# Allowlist (Spec section 12 + new schema): not compared by value.
_GLOBAL_ALLOW = {"eth_file", "mouse_strain", "reward_reached", "schema_version"}
_MULTI_TARGET_TRIALS = {"30", "31", "32", "33", "34", "Probe3"}

_HASH_SEP = chr(124)   # '|' -- safe ASCII separator for join-then-hash


def _is_allowlisted(exp, trial, field, ref):
    if field in _GLOBAL_ALLOW:
        return True
    if exp == "2025-07-17" and field == "mouse_sex":
        return True
    if exp == "2025-01-21" and trial in _MULTI_TARGET_TRIALS and field in {"target", "target_reverse", "k_reward"}:
        return True
    if field == "k_reward" and "k_reward" in ref:
        n = ref["r_nose"].shape[0]
        if int(ref["k_reward"][0][0]) == n - 2:          # legacy "never reached" sentinel
            return True
    return False


def signature(value):
    """Per-field signature: kind + shape + content hash, tolerant of float ULPs."""
    arr = np.asarray(value)
    kind = arr.dtype.kind
    shape = list(arr.shape)
    if arr.size == 0:
        digest = "empty"
    elif kind == "f":
        nan_mask = np.isnan(arr).astype(np.uint8).tobytes()
        non_nan = np.where(np.isnan(arr), 0.0, np.round(arr, 9))
        h = hashlib.sha1()
        h.update(non_nan.astype(np.float64).tobytes())
        h.update(b"NANMASK")
        h.update(nan_mask)
        digest = h.hexdigest()
    elif kind in "iub":
        digest = hashlib.sha1(arr.astype(np.int64).tobytes()).hexdigest()
    elif kind in "US":
        joined = _HASH_SEP.join(str(s) for s in arr.flatten())
        digest = hashlib.sha1(joined.encode("utf-8")).hexdigest()
    else:
        digest = hashlib.sha1(np.array2string(arr).encode("utf-8")).hexdigest()
    return {"kind": kind, "shape": shape, "hash": digest}


def find_excel_for(ref_mat_path, raw_dir):
    """Find the source Excel for a reference .mat (matches by ``eth_file`` index)."""
    m = sio.loadmat(str(ref_mat_path))
    eth = int(m["eth_file"][0][0])
    matches = sorted(p for p in raw_dir.glob("*Trial*.xlsx") if not p.name.startswith("~$"))
    # Trim trailing whitespace and require the stem to end with exactly the index.
    matches = [p for p in matches if p.stem.rstrip().endswith(str(eth))
               and not p.stem.rstrip().endswith(str(eth) + "0")     # avoid 1 matching 10
               and not p.stem.rstrip().endswith(str(eth) + "1")]
    # The above is paranoid -- check exact-match by parsing the trailing integer.
    def trailing_int(name):
        s = name.rstrip()
        i = len(s)
        while i > 0 and s[i-1].isdigit():
            i -= 1
        return s[i:]
    matches = [p for p in matches if trailing_int(p.stem) == str(eth)]
    if not matches:
        raise RuntimeError(f"No Excel for {ref_mat_path.name} (eth_file={eth}) in {raw_dir}")
    return matches[0]


def build_for(experiment, mouse_trial_pairs):
    ref_dir = REF / experiment
    raw_src = REF / f"{experiment}_Raw Trial Data"
    raw_dst = DEST_RAW / f"{experiment}_Raw Trial Data"
    raw_dst.mkdir(parents=True, exist_ok=True)

    entries = {}
    for mouse, trial in mouse_trial_pairs:
        ref_mat = ref_dir / f"hfm_{experiment}_M{mouse}_{trial}.mat"
        if not ref_mat.exists():
            raise RuntimeError(f"Missing reference: {ref_mat}")
        excel = find_excel_for(ref_mat, raw_src)
        shutil.copy2(excel, raw_dst / excel.name)

        ref = sio.loadmat(str(ref_mat))
        fields = {}
        for key in sorted(k for k in ref if not k.startswith("__")):
            sig = signature(ref[key])
            sig["allowlisted"] = _is_allowlisted(experiment, trial, key, ref)
            fields[key] = sig
        entries[ref_mat.name] = {"fields": fields}
        print(f"  + {ref_mat.name}  (excel: {excel.name})")
    return entries


def main():
    if not REF.exists():
        print(f"ERROR: {REF} not present. Run this before deleting _reference/.", file=sys.stderr)
        return 1
    # Wipe any previously-copied Excel files so a shrunk CURATED set doesn't leave orphans.
    if DEST_RAW.exists():
        for child in DEST_RAW.iterdir():
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    DEST_RAW.mkdir(parents=True, exist_ok=True)
    manifest = {
        "_note": ("Expected per-field signatures for the curated golden fixtures. "
                  "Float fields are rounded to 1e-9 before hashing to absorb transcendental "
                  "ULP noise (e.g. arctan2 in `heading`). Allowlisted fields are NOT compared "
                  "by value (Spec section 12 deliberate changes + new-schema fields). The "
                  "matching Excel inputs live in tests/fixtures/raw/."),
        "trials": {},
    }
    for exp, pairs in CURATED.items():
        print(f"\n{exp} ({len(pairs)} trials):")
        manifest["trials"].update(build_for(exp, pairs))

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nManifest written: {MANIFEST_PATH}  ({len(manifest['trials'])} trials)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
