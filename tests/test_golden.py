"""Golden regression test: re-run the pipeline on the curated committed fixtures and
assert every produced ``.mat`` field matches the expected signature in
``tests/fixtures/golden_manifest.json``, except the deliberate-change allowlist
(Spec section 12).

Green = the output contract is intact. Red names the exact field and trial that
drifted. The test is self-contained: it needs only the committed fixtures (Excel
inputs + 3 PNGs) and the manifest -- ``_reference/`` is not required and may be
deleted. Re-generate the manifest with ``scripts/build_fixtures.py`` only when
you DELIBERATELY change the contract (and update the allowlist if needed).

Run:  pytest tests/test_golden.py -v
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest
import scipy.io as sio

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from src import process            # noqa: E402
from src.schema import to_matdict  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures"
MANIFEST_PATH = FIXTURES / "golden_manifest.json"
BG_DIR = FIXTURES / "background_images"
RAW_DIR = FIXTURES / "raw"

EXPERIMENTS = ("2022-08-12", "2025-01-21", "2025-07-17")

_HASH_SEP = chr(124)   # '|' -- safe ASCII separator (must match build_fixtures.py)


def _signature(value):
    """Per-field signature: kind + shape + content hash. Mirrors build_fixtures.py."""
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


def _round_trip(rec):
    """Run the record through savemat + loadmat (so we compare what downstream reads)."""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "rec.mat"
        sio.savemat(str(path), to_matdict(rec), long_field_names=True)
        return sio.loadmat(str(path))


def _process(experiment):
    return process.process_experiment(
        experiment,
        raw_dir=RAW_DIR / f"{experiment}_Raw Trial Data",
        background_dir=BG_DIR,
        experiment_list=REPO / "config" / "experiment_list.csv",
        targets_path=REPO / "config" / "targets" / f"{experiment}_targets.csv",
        mouse_map_path=REPO / "config" / "mouse_map.csv",
    )


@pytest.fixture(scope="session")
def manifest():
    if not MANIFEST_PATH.exists():
        pytest.skip(f"manifest not found at {MANIFEST_PATH}")
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def processed():
    """Process each fixture experiment ONCE per test session (Excel reads are slow)."""
    return {exp: _process(exp) for exp in EXPERIMENTS}


@pytest.mark.parametrize("experiment", EXPERIMENTS)
def test_golden(experiment, manifest, processed):
    """Every field in the manifest must match the record's signature (allowlisted = skipped)."""
    expected = {k: v for k, v in manifest["trials"].items()
                if k.startswith(f"hfm_{experiment}_")}
    assert expected, f"manifest has no entries for {experiment}"

    produced = {rec.filename: rec for rec in processed[experiment].records}

    failures = {}
    for filename, entry in expected.items():
        if filename not in produced:
            failures.setdefault(filename, []).append("not produced (missing source Excel?)")
            continue
        loaded = _round_trip(produced[filename])
        for field, exp_sig in entry["fields"].items():
            if exp_sig.get("allowlisted"):
                continue
            if field not in loaded:
                failures.setdefault(filename, []).append(
                    f"{field}: present in manifest but NOT produced"
                )
                continue
            actual = _signature(loaded[field])
            if (actual["kind"], actual["shape"], actual["hash"]) != \
               (exp_sig["kind"], exp_sig["shape"], exp_sig["hash"]):
                reason = []
                if actual["kind"] != exp_sig["kind"]:
                    reason.append(f"kind {actual['kind']}!={exp_sig['kind']}")
                if actual["shape"] != exp_sig["shape"]:
                    reason.append(f"shape {actual['shape']}!={exp_sig['shape']}")
                if actual["hash"] != exp_sig["hash"]:
                    reason.append("value-hash differs")
                failures.setdefault(filename, []).append(f"{field}: {', '.join(reason)}")

    if failures:
        report = "\n".join(
            f"  {fname}:\n" + "\n".join(f"    - {d}" for d in diffs)
            for fname, diffs in failures.items()
        )
        pytest.fail(f"{experiment}: {len(failures)} trials drifted:\n{report}")


def test_multitarget_2025_01_21(processed):
    """The headline bug-fix: 2025-01-21 barrier trials carry BOTH targets as (K,2).

    Only the curated representatives are checked (one numeric barrier trial + Probe3);
    every trial in 30-34 follows the same selector rule, so one sample is enough.
    """
    by_trial = {r.trial: r for r in processed["2025-01-21"].records}
    for trial in ("30", "Probe3"):
        rec = by_trial[trial]
        assert rec.target.shape == (2, 2), f"trial {trial}: expected (2,2) target, got {rec.target.shape}"
        assert rec.target_reverse is None, f"trial {trial}: multi-target trials carry no target_reverse"


def test_2025_07_17_sex_bug_fixed(processed):
    """The mouse_sex bug fix: M54-57 -> male, M58-59 -> female (legacy was 'female' for all)."""
    by_mouse = {}
    for rec in processed["2025-07-17"].records:
        by_mouse.setdefault(rec.mouse_number, set()).add(rec.mouse_sex)
    for m in ("54", "55"):
        if m in by_mouse:
            assert by_mouse[m] == {"male"}, f"M{m} sex {by_mouse[m]} != {{male}}"
    for m in ("58", "59"):
        if m in by_mouse:
            assert by_mouse[m] == {"female"}, f"M{m} sex {by_mouse[m]} != {{female}}"
