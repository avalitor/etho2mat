"""Load and validate the config CSVs, and resolve a trial's targets.

All per-experiment variation lives here as data (no experiment-specific code):
  * ``experiment_list.csv`` -- one row per experiment.
  * ``targets/<DATE>_targets.csv`` -- reward/reverse locations with trial selectors.
  * ``mouse_map.csv`` -- per-mouse sex/strain overrides.

The selector grammar for the ``trials`` column:
  ``all`` | ``N-M`` (inclusive numeric range) | ``N,M,...`` (list; items may be
  numbers, exact names, or ``prefix*`` tags) | ``remaining`` (every trial for that
  entrance not claimed by another rule) | ``R*`` / ``Probe*`` (name-prefix tag).
A bare non-numeric token (e.g. ``Probe``) is an EXACT name match, so it will not
catch ``Probe2``.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from . import paths
from .validate import ConfigError, InputError

VALID_SEX = ("male", "female", "mixed")
VALID_ROLES = ("reward", "reverse")
DEFAULT_HOLE_COUNT = 100
DEFAULT_NO_REWARD_PATTERNS = ("Habituation*", "Probe*")


# --------------------------------------------------------------------------- #
# Data classes
# --------------------------------------------------------------------------- #
@dataclass
class TargetRule:
    entrance: str
    x: float
    y: float
    trials: str
    mice: tuple        # () = all mice, else tuple of id strings
    role: str          # 'reward' | 'reverse'
    source_row: int    # 1-based row number in the CSV, for error messages


@dataclass
class ExperimentConfig:
    experiment: str
    protocol: str
    protocol_description: str
    img_extent: np.ndarray          # (4,) floats
    mouse_sex: str
    mouse_strain: str
    experimenter: str
    background_image: str
    expected_hole_count: int
    no_reward_trials: tuple


# --------------------------------------------------------------------------- #
# Selector matching
# --------------------------------------------------------------------------- #
def _token_matches(token: str, trial: str) -> bool:
    token = token.strip()
    if not token:
        return False
    if token.endswith("*"):                      # prefix tag, e.g. R* / Probe*
        return trial.startswith(token[:-1])
    for sep in ("..", "-"):                      # numeric range N-M or N..M (Excel-safe)
        if sep in token:
            lo, hi = token.split(sep, 1)
            lo, hi = lo.strip(), hi.strip()
            if lo.isdigit() and hi.isdigit():
                return trial.isdigit() and int(lo) <= int(trial) <= int(hi)
            break                                 # contains separator but isn't a numeric range
    if token.isdigit():                          # single numeric trial
        return trial.isdigit() and int(trial) == int(token)
    return trial == token                        # exact name match


def _selector_matches(selector: str, trial: str) -> bool:
    """Whether ``trial`` matches ``selector`` (``remaining`` handled by caller).

    Supports ``!`` negation: tokens prefixed with ``!`` exclude trials. The selector
    matches T iff (no negative token matches T) AND (some positive token matches T,
    OR there are no positive tokens at all). Examples:
      ``!1-20, !Probe*``        -- every trial except 1-20 and except Probe*
      ``1-30, !25``             -- digit trials 1-30 except trial 25
      ``all, !Probe``           -- every trial except exactly 'Probe'
    """
    selector = selector.strip()
    if selector == "all":
        return True
    if selector == "remaining":
        return False
    positive, negative = [], []
    for raw in selector.split(","):
        tok = raw.strip()
        if not tok:
            continue
        if tok.startswith("!"):
            negative.append(tok[1:].strip())
        else:
            positive.append(tok)
    if any(_token_matches(n, trial) for n in negative):
        return False
    if not positive:
        return bool(negative)        # `!X, !Y` with no positives = all-minus-negatives
    if "all" in positive:
        return True
    return any(_token_matches(p, trial) for p in positive)


def _mice_scope_includes(rule: TargetRule, mouse: str) -> bool:
    return (not rule.mice) or (str(mouse).strip() in rule.mice)


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #
def _matching_rules(rules, role, entrance, trial, mouse):
    """Reward/reverse rules matching this trial, honouring 'remaining'."""
    scoped = [r for r in rules
              if r.role == role and r.entrance == entrance and _mice_scope_includes(r, mouse)]
    explicit = [r for r in scoped if r.trials.strip() != "remaining"
                and _selector_matches(r.trials, trial)]
    if explicit:
        return explicit
    # 'remaining' fires only when no explicit rule for this entrance claimed the trial
    claimed = any(_selector_matches(r.trials, trial) for r in scoped
                  if r.trials.strip() != "remaining")
    if not claimed:
        return [r for r in scoped if r.trials.strip() == "remaining"]
    return []


def resolve_targets(rules, entrance, trial, mouse):
    """Return ``(target, target_reverse)`` for one trial.

    ``target`` is ``(K, 2)`` in CSV row order (K>=1). ``target_reverse`` is
    ``(1, 2)`` or ``None``. Raises :class:`ConfigError` on no reward match or an
    ambiguous reverse match.
    """
    reward = _matching_rules(rules, "reward", entrance, trial, mouse)
    if not reward:
        raise ConfigError(
            f"No reward target matches trial '{trial}' (entrance {entrance}, "
            f"mouse {mouse}). Add a reward row whose 'trials' selector covers it."
        )
    target = np.array([[r.x, r.y] for r in reward], dtype=np.float64)

    reverse = _matching_rules(rules, "reverse", entrance, trial, mouse)
    if len(reverse) > 1:
        rows = ", ".join(str(r.source_row) for r in reverse)
        raise ConfigError(
            f"Trial '{trial}' (entrance {entrance}, mouse {mouse}) matches "
            f"{len(reverse)} reverse rows (CSV rows {rows}); expected at most one."
        )
    target_reverse = np.array([[reverse[0].x, reverse[0].y]], dtype=np.float64) if reverse else None
    return target, target_reverse


def is_no_reward_trial(trial: str, patterns) -> bool:
    """Whether a trial is exempt from reach alarms (habituation/probe, etc.)."""
    for pat in patterns:
        pat = pat.strip()
        if pat.endswith("*"):
            if trial.startswith(pat[:-1]):
                return True
        elif trial == pat:
            return True
    return False


# --------------------------------------------------------------------------- #
# Loaders
# --------------------------------------------------------------------------- #
def load_experiment(experiment: str, path: Optional[Path] = None) -> ExperimentConfig:
    """Load and validate one experiment's row from ``experiment_list.csv``."""
    path = Path(path or paths.EXPERIMENT_LIST)
    if not path.exists():
        raise ConfigError(f"experiment_list.csv not found at {path}.")
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    match = [r for r in rows if (r.get("experiment") or "").strip() == experiment]
    if not match:
        raise ConfigError(
            f"Experiment '{experiment}' has no row in {path.name}. "
            f"Add a row with its metadata (see the column headers)."
        )
    r = match[0]

    extent = _parse_img_extent((r.get("img_extent") or "").strip(), experiment)

    sex = (r.get("mouse_sex") or "").strip().lower()
    if sex not in VALID_SEX:
        raise ConfigError(f"{experiment}: mouse_sex must be one of {VALID_SEX}; got '{sex}'.")

    hole_raw = (r.get("expected_hole_count") or "").strip()
    if hole_raw == "":
        hole_count = DEFAULT_HOLE_COUNT
    else:
        if not hole_raw.isdigit() or int(hole_raw) <= 0:
            raise ConfigError(f"{experiment}: expected_hole_count must be a positive integer; got '{hole_raw}'.")
        hole_count = int(hole_raw)

    patterns_raw = (r.get("no_reward_trials") or "").strip()
    patterns = tuple(p.strip() for p in patterns_raw.split(",") if p.strip()) if patterns_raw \
        else DEFAULT_NO_REWARD_PATTERNS

    return ExperimentConfig(
        experiment=experiment,
        protocol=(r.get("protocol") or "").strip(),
        protocol_description=(r.get("protocol_description") or "").strip(),
        img_extent=extent,
        mouse_sex=sex,
        mouse_strain=(r.get("mouse_strain") or "").strip(),
        experimenter=(r.get("experimenter") or "").strip(),
        background_image=(r.get("background_image") or "").strip(),
        expected_hole_count=hole_count,
        no_reward_trials=patterns,
    )


def load_targets(experiment: str, path: Optional[Path] = None) -> list:
    """Load and validate ``targets/<experiment>_targets.csv`` into TargetRules."""
    path = Path(path or (paths.TARGETS_DIR / f"{experiment}_targets.csv"))
    if not path.exists():
        raise ConfigError(
            f"Targets file not found: {path}. Copy TEMPLATE_targets.csv to "
            f"'{experiment}_targets.csv' and fill in the reward rows."
        )
    rules = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        required = {"entrance", "target_x", "target_y", "trials", "role"}
        missing = required - set(h.strip() for h in (reader.fieldnames or []))
        if missing:
            raise ConfigError(f"{path.name}: missing column(s) {sorted(missing)}.")
        rows = list(reader)

    for i, row in enumerate(rows, start=1):
        row = {(k.strip() if k else k): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
        entrance = row.get("entrance", "")
        # Comment line: either raw `# ...` or a quoted `"# ..., ..."` that put the comment
        # in column A. Skip uniformly so authors can use either style in Excel.
        if entrance.startswith("#"):
            continue
        if not entrance:
            raise ConfigError(f"{path.name} row {i}: 'entrance' is blank.")
        role = (row.get("role") or "reward").lower()
        if role not in VALID_ROLES:
            raise ConfigError(f"{path.name} row {i}: role must be {VALID_ROLES}; got '{role}'.")
        try:
            x, y = float(row["target_x"]), float(row["target_y"])
        except (ValueError, TypeError, KeyError):
            raise ConfigError(
                f"{path.name} row {i}: target_x/target_y must be numbers; "
                f"got ({row.get('target_x')!r}, {row.get('target_y')!r})."
            )
        if x == 0.0 and y == 0.0:
            raise ConfigError(
                f"{path.name} row {i}: target ({x},{y}) is the placeholder (0,0), "
                f"which is treated as a missing target. Enter the real coordinates."
            )
        if not (row.get("trials") or "").strip():
            raise ConfigError(f"{path.name} row {i}: 'trials' selector is blank.")
        mice_raw = (row.get("mice") or "").strip()
        mice = tuple(m.strip() for m in mice_raw.split(",") if m.strip()) if mice_raw else ()
        rules.append(TargetRule(entrance, x, y, row["trials"].strip(), mice, role, i))

    if not any(r.role == "reward" for r in rules):
        raise ConfigError(f"{path.name}: no reward rows found (need at least one role=reward).")
    return rules


def _parse_img_extent(raw: str, ctx: str) -> np.ndarray:
    """Parse a comma-separated 4-number img_extent string. Loud on malformed input."""
    try:
        arr = np.array([float(x) for x in raw.split(",")], dtype=np.float64)
    except ValueError:
        raise ConfigError(f"{ctx}: img_extent '{raw}' is not 4 comma-separated numbers.")
    if arr.shape != (4,):
        raise ConfigError(
            f"{ctx}: img_extent must have exactly 4 numbers (left,right,bottom,top); "
            f"got {arr.size} from '{raw}'."
        )
    return arr


def load_mouse_map(path: Optional[Path] = None) -> dict:
    """Load mouse_map.csv into {(experiment, mouse_id): {'sex','strain','background_image','img_extent'}}.

    ``background_image`` and ``img_extent`` are optional per-mouse arena overrides
    (used when one experiment runs on physically different arenas, e.g. mice 1-4
    on arena A, mice 5-8 on arena B). Blank means "use the experiment-wide value
    from experiment_list.csv". ``img_extent`` parses the same 4-number CSV format
    as the experiment row.
    """
    path = Path(path or paths.MOUSE_MAP)
    out: dict = {}
    if not path.exists():
        return out
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            exp = (row.get("experiment") or "").strip()
            mouse = (row.get("mouse_id") or "").strip()
            if exp.startswith("#"):          # column-A quoted comment line; skip
                continue
            if not exp or not mouse:
                continue
            extent_raw = (row.get("img_extent") or "").strip()
            extent = _parse_img_extent(extent_raw, f"mouse_map.csv ({exp}/M{mouse})") if extent_raw else None
            out[(exp, mouse)] = {
                "sex": (row.get("sex") or "").strip(),
                "strain": (row.get("strain") or "").strip(),
                "background_image": (row.get("background_image") or "").strip(),
                "img_extent": extent,
            }
    return out


def resolve_mouse_sex_strain(cfg: ExperimentConfig, mouse: str, mouse_map: dict):
    """Per-mouse (sex, strain): mouse_map overrides the experiment-wide defaults."""
    entry = mouse_map.get((cfg.experiment, str(mouse).strip()))
    sex = cfg.mouse_sex
    strain = cfg.mouse_strain
    if entry:
        if entry.get("sex"):
            sex = entry["sex"]
        if entry.get("strain"):
            strain = entry["strain"]
    if sex == "mixed":
        raise ConfigError(
            f"{cfg.experiment}: mouse {mouse} has sex 'mixed' with no mouse_map.csv "
            f"override. Add a row giving its actual sex."
        )
    return sex, strain


def resolve_mouse_arena(cfg: ExperimentConfig, mouse: str, mouse_map: dict):
    """Per-mouse ``(background_image, img_extent)``: mouse_map overrides cfg defaults.

    Blank/missing override -> cfg's experiment-wide values. The two override
    fields are independent (you can override one without the other), but in
    practice they travel together since changing arenas usually changes both
    the screenshot and the camera calibration.
    """
    entry = mouse_map.get((cfg.experiment, str(mouse).strip()))
    background = cfg.background_image
    extent = cfg.img_extent
    if entry:
        if entry.get("background_image"):
            background = entry["background_image"]
        if entry.get("img_extent") is not None:
            extent = entry["img_extent"]
    return background, extent
