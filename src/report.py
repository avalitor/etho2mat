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

from . import config_io, metrics
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


def arena_target_consistency_warnings(result, margin: float = 1.05) -> None:
    """Warn when a target's (x,y) lies outside the arena assigned to its mouse.

    Multi-arena experiments (mouse_map.csv overrides background_image per cohort)
    are easy to mis-configure: assign a mouse to arena B but leave its target rows
    pointing at arena-A coordinates. The arenas are physically shifted, so an
    arena-A target used by an arena-B mouse typically lands well outside arena B's
    circle -- geometrically detectable.

    This warning never blocks the run -- the user has the final say (e.g. for an
    unusual setup where the target is intentionally outside the dish, or arenas
    are still being calibrated). A small ``margin * r`` slack is allowed so that
    hand-measured targets near the rim don't trigger false positives.

    Single-arena experiments are skipped: in that case there is no second arena
    to swap with, and any "target outside arena" condition would already be
    surfaced by the existing reach report (every reward trial would miss).
    """
    # Per-mouse arena: every record for a given mouse carries the same arena
    # (driven by mouse_map.csv), so first-seen wins.
    mouse_arena: dict = {}             # mouse_number -> (arena_circle, bkgd_img)
    mouse_trials: dict = {}            # mouse_number -> list[(entrance, trial)]
    for rec in result.records:
        if rec.mouse_number not in mouse_arena:
            mouse_arena[rec.mouse_number] = (rec.arena_circle, rec.bkgd_img)
        mouse_trials.setdefault(rec.mouse_number, []).append((rec.entrance, rec.trial))

    arena_by_bg: dict = {rec.bkgd_img: rec.arena_circle for rec in result.records}
    if len(arena_by_bg) <= 1:
        return                          # single-arena -> nothing to cross-check here

    rules = result.rules
    seen_pairs = set()                  # (rule_source_row, mouse) -> already warned
    for rule in rules:
        for mouse, trials in mouse_trials.items():
            # Does this rule fire for at least one of this mouse's trials?
            fires = False
            for entrance, trial in trials:
                fired = config_io._matching_rules(rules, rule.role, entrance, trial, mouse)
                if any(f is rule for f in fired):
                    fires = True
                    break
            if not fires:
                continue
            (cx, cy, r), bg = mouse_arena[mouse]
            d = float(np.hypot(rule.x - cx, rule.y - cy))
            if d <= r * margin:
                continue                # inside the mouse's arena -> OK
            key = (rule.source_row, mouse)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            # Outside this mouse's arena. Check whether the coords land inside
            # ANOTHER arena's circle -- that's strong evidence of a copy-paste swap.
            swap_with = None
            for other_bg, (ocx, ocy, orad) in arena_by_bg.items():
                if other_bg == bg:
                    continue
                if float(np.hypot(rule.x - ocx, rule.y - ocy)) <= orad * margin:
                    swap_with = other_bg
                    break
            base = (
                f"targets row {rule.source_row} ({rule.role}, ({rule.x:.2f}, {rule.y:.2f})) "
                f"applies to mouse {mouse} (arena '{bg}', center ({cx:.2f}, {cy:.2f}), r={r:.2f}) "
                f"but the target is {d:.2f} cm from that arena's center"
            )
            if swap_with:
                warn(
                    f"ARENA/TARGET MISMATCH: {base}. Coords land inside arena '{swap_with}' "
                    f"-- likely a copy-paste swap. Confirm the mice column and coords."
                )
            else:
                warn(
                    f"ARENA/TARGET MISMATCH: {base}. Coords are outside every detected "
                    f"arena -- check the target row and the mouse's mouse_map.csv assignment."
                )


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
