"""Non-blocking quality reports: reach evaluation, flagged trials, nose/tail swap
suspicion, and trial-numbering / naming warnings.

None of this blocks the run -- the final say is the user's -- but a high or
systematic miss rate is surfaced loudly as a likely alignment problem, since a
misaligned arena makes nearly all reward trials miss.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import metrics
from .config_io import is_no_reward_trial
from .validate import warn


@dataclass
class TrialReach:
    filename: str
    mouse: str
    trial: str
    entrance: str
    reward_expecting: bool
    reached: bool
    closest_cm: float
    suspected_swap: bool


def evaluate(result) -> list:
    """Closest nose-to-target approach + reach status for every trial."""
    patterns = result.cfg.no_reward_trials
    out = []
    for rec in result.records:
        no_reward = is_no_reward_trial(rec.trial, patterns)
        closest = min(metrics.closest_approach(rec.r_nose, t) for t in rec.target)
        # suspected nose/tail swap: tail reaches the window but the nose did not
        swap = False
        if not rec.reward_reached:
            _, tail_reached = metrics.k_reward(rec.r_tail, rec.target)
            swap = bool(tail_reached)
        out.append(TrialReach(
            rec.filename, rec.mouse_number, rec.trial, rec.entrance,
            reward_expecting=not no_reward, reached=bool(rec.reward_reached),
            closest_cm=closest, suspected_swap=swap,
        ))
    return out


def write_flagged_csv(reaches: list, path: Path) -> Path:
    """Write every reward-expecting trial that did not reach, with its closest approach."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flagged = [r for r in reaches if r.reward_expecting and not r.reached]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["filename", "mouse", "trial", "entrance", "closest_cm", "suspected_nose_tail_swap"])
        for r in sorted(flagged, key=lambda r: -r.closest_cm):
            w.writerow([r.filename, r.mouse, r.trial, r.entrance, f"{r.closest_cm:.2f}", r.suspected_swap])
    return path


def print_report(reaches: list, result) -> None:
    """Print the reach summary, the misalignment pre-screen, and the flagged list."""
    expecting = [r for r in reaches if r.reward_expecting]
    missed = [r for r in expecting if not r.reached]
    no_reward = [r for r in reaches if not r.reward_expecting]

    print(f"\n--- Reach report for {result.experiment} ---")
    print(f"  reward-expecting trials: {len(expecting)}  |  reached: {len(expecting) - len(missed)}  |  missed: {len(missed)}")
    print(f"  no-reward trials (exempt, e.g. {', '.join(result.cfg.no_reward_trials)}): {len(no_reward)}")

    # Misalignment pre-screen: a misaligned arena makes nearly all reward trials miss.
    if expecting and len(missed) / len(expecting) > 0.5:
        warn(f"{len(missed)}/{len(expecting)} reward trials missed their target -- "
             f"this is a LIKELY ALIGNMENT PROBLEM (wrong corner / reward-reverse swap / rotation). "
             f"Check the target-alignment image before trusting the output.")
    by_entrance = {}
    for r in expecting:
        by_entrance.setdefault(r.entrance, []).append(r)
    for ent, rs in by_entrance.items():
        ent_missed = [r for r in rs if not r.reached]
        if rs and len(ent_missed) == len(rs):
            warn(f"ALL {len(rs)} reward trials from entrance {ent} missed -- likely a "
                 f"target/entrance misassignment for {ent}.")

    if missed:
        print("  Flagged (missed) trials, worst first:")
        for r in sorted(missed, key=lambda r: -r.closest_cm)[:25]:
            tag = "  <-- suspected nose/tail swap (re-export in Ethovision)" if r.suspected_swap else ""
            print(f"     M{r.mouse} {r.trial} (entrance {r.entrance}): closest {r.closest_cm:.1f} cm{tag}")


def trial_numbering_warnings(result) -> None:
    """Warn on gaps in the per-mouse numeric trial sequence (likely mis-numbered/missing)."""
    by_mouse = {}
    for rec in result.records:
        if rec.trial.isdigit():
            by_mouse.setdefault(rec.mouse_number, []).append(int(rec.trial))
    for mouse, nums in by_mouse.items():
        nums = sorted(set(nums))
        if not nums:
            continue
        gaps = [n for n in range(nums[0], nums[-1] + 1) if n not in nums]
        if gaps:
            warn(f"Mouse {mouse}: numeric trials have gap(s) at {gaps} "
                 f"(a skipped number usually means a mis-numbered or missing trial). "
                 f"Proceeding -- fix if unintended.")


# Letters immediately followed by digits, with no whitespace separator.
# Used to flag e.g. "Probe2"/"Habituation1" -- CHECKLIST recommends "Probe 2"/"Habituation 1".
_LETTERS_THEN_DIGITS = re.compile(r"^[A-Za-z]+\d+$")


def trial_naming_warnings(result) -> None:
    """Warn once per distinct trial name that deviates from CHECKLIST conventions.

    Recommendations (CHECKLIST.md, Trial naming and numbering):
      * Capitalize named trials -- ``Probe``, not ``probe``.
      * Number repeats with a space -- ``Habituation 1``, not ``Habituation1``.

    Both are recommendations, never blocking. The legacy ``R<angle>`` rotation
    prefix (``R90``, ``R180``) is treated as a known convention and not flagged.
    """
    seen = set()
    for rec in result.records:
        t = rec.trial
        if not t or t.isdigit() or t in seen:
            continue
        seen.add(t)
        if t[0].islower():
            warn(f"trial '{t}' starts lowercase -- convention is capitalized "
                 f"(e.g. 'Probe', not 'probe'). Ignore if intentional; proceeding.")
        elif _LETTERS_THEN_DIGITS.match(t) and not (t.startswith("R") and t[1:].isdigit()):
            warn(f"trial '{t}' joins letters and digits with no space -- convention "
                 f"is 'Probe 2' / 'Habituation 1'. Ignore if intentional; proceeding.")
