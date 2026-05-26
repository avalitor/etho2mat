"""Guided entry point: validate -> detect arena -> confirm -> confirm alignment -> write.

This is what the double-clickable launcher runs. Nothing is written to disk until
BOTH the arena geometry and the target alignment are confirmed. On either 'n',
the run aborts and writes nothing.

If a step raises a known error (missing file, malformed CSV, etc.) the tool prints
the error and offers a per-step retry: fix the file outside, press Enter, and that
step alone re-runs -- the user doesn't lose progress from earlier steps.

    python -m src.convert <experiment> [--force] [--yes]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import scipy.io as sio

from . import alignment, arena as arena_module, config_io, paths, process, report
from .arena import save_verification_image
from .process import ProcessResult
from .schema import to_matdict
from .validate import ArenaError, Etho2matError, InputError


_QUIT = object()                       # sentinel returned by _step_with_retry on user quit


def _safe_stem(filename: str) -> str:
    """Strip the extension and any path separators -- safe for a verification PNG name."""
    return Path(filename).stem.replace("/", "_").replace("\\", "_")


def _confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        print(f"{prompt} [auto-yes]")
        return True
    return input(f"{prompt} [y/n] ").strip().lower().startswith("y")


def _step_with_retry(name: str, fn, assume_yes: bool):
    """Run ``fn``; on a known error, let the user fix the underlying issue and retry.

    Returns whatever ``fn`` returns, or ``_QUIT`` if the user typed 'q'.
    With ``assume_yes`` (non-interactive), errors propagate.
    """
    while True:
        try:
            return fn()
        except Etho2matError as exc:
            print(f"\nERROR during {name}: {exc}", file=sys.stderr)
            if assume_yes:
                raise
            ans = input("\nFix the issue, then press Enter to retry, or 'q' + Enter to quit: ").strip().lower()
            if ans == "q":
                return _QUIT


def _step1_with_retry(fn, current_experiment: list, assume_yes: bool):
    """Like ``_step_with_retry`` but also lets the user re-enter the experiment id.

    The most common step-1 failure is a typo in the experiment id (no matching
    folder or no row in experiment_list.csv). Plain retry with the same id would
    loop forever, so this prompt also accepts a fresh experiment id which is
    written back into ``current_experiment`` for the next attempt.
    """
    while True:
        try:
            return fn()
        except Etho2matError as exc:
            print(f"\nERROR during loading config and detecting arena: {exc}", file=sys.stderr)
            if assume_yes:
                raise
            print(
                f"\nFix the issue and press Enter to retry,"
                f"\nOR type a different experiment id (current: '{current_experiment[0]}'),"
                f"\nOR type 'q' to quit."
            )
            ans = input("> ").strip()
            if ans.lower() == "q":
                return _QUIT
            if ans:
                current_experiment[0] = ans


def _write_records(records, force: bool) -> Path:
    out_dir = paths.OUTPUT_DIR / records[0].exp
    out_dir.mkdir(parents=True, exist_ok=True)        # makedirs, not mkdir
    for rec in records:
        path = out_dir / rec.filename
        if path.exists() and not force:
            raise InputError(
                f"{rec.filename} already exists in {out_dir}. Re-run with --force to overwrite."
            )
        sio.savemat(str(path), to_matdict(rec), long_field_names=True)
    return out_dir


def run(experiment: str, force: bool = False, assume_yes: bool = False) -> int:
    # Step 1 may be retried after the user re-enters the experiment id (typo recovery),
    # so the closure reads from this mutable container instead of the outer parameter.
    current_experiment = [experiment]

    # --- Step 1: load config + detect arena(s) + save verification image(s) (retryable). ---
    # The verification image is written for every background BEFORE any raise, so
    # a failed detection still leaves a diagnostic figure on disk for the user to
    # inspect (and to send along when asking for help).
    def step1():
        exp = current_experiment[0]
        cfg = config_io.load_experiment(exp)
        rules = config_io.load_targets(exp)
        mouse_map = config_io.load_mouse_map()
        raw_dir = paths.raw_experiment_dir(exp)
        specs = process.distinct_arena_specs(cfg, mouse_map)
        single = len(specs) == 1
        arenas: dict = {}
        background_paths: dict = {}
        first_error: Optional[ArenaError] = None
        for bg, extent in specs.items():
            path = paths.BACKGROUND_DIR / bg
            if not path.exists():
                raise InputError(
                    f"{cfg.experiment}: background image '{bg}' not found in {paths.BACKGROUND_DIR}."
                )
            print(f"Analyzing arena geometry for {exp} from {bg} ...")
            result = arena_module.analyze(path, extent, cfg.expected_hole_count)
            arenas[bg] = result
            background_paths[bg] = path
            out_name = f"{exp}_arena.png" if single else f"{exp}_arena_{_safe_stem(bg)}.png"
            img_path = save_verification_image(
                path, result, extent, paths.VERIFICATION_DIR / out_name,
            )
            print(f"  Saved arena verification image: {img_path}")
            if result.error_message and first_error is None:
                first_error = ArenaError(
                    f"{result.error_message} See {img_path} for what the detector saw."
                )
        if first_error is not None:
            raise first_error
        return cfg, rules, mouse_map, raw_dir, arenas, background_paths

    out = _step1_with_retry(step1, current_experiment, assume_yes)
    if out is _QUIT:
        return 1
    cfg, rules, mouse_map, raw_dir, arenas, background_paths = out
    experiment = current_experiment[0]   # sync outer name with whatever step1 accepted

    # --- Arena y/n confirmation (one per distinct arena). ---
    arena_items = list(arenas.items())
    for i, (bg, arena) in enumerate(arena_items, 1):
        prefix = f"arena {i} of {len(arena_items)} ({bg}): " if len(arena_items) > 1 else ""
        label = f"{prefix}1 arena and {arena.n_holes} holes -- looks right?"
        if not _confirm(label, assume_yes):
            print("Aborted at arena check. Nothing written.")
            return 2

    # --- Step 2: read every Excel + build records + collision check (retryable). ---
    def step2():
        excel_paths = process.iter_excel_paths(raw_dir)
        print(f"\nReading {len(excel_paths)} trials ...")
        recs = []
        for i, p in enumerate(excel_paths, 1):
            print(f"  [{i}/{len(excel_paths)}] {p.name}")
            recs.append(process.build_record(cfg, rules, mouse_map, p, arenas))
        process._check_filename_collisions(recs)
        return recs

    out = _step_with_retry("reading Excel files", step2, assume_yes)
    if out is _QUIT:
        return 1
    records = out
    result = ProcessResult(experiment, cfg, rules, arenas, records, background_paths)

    # --- Reach report + warnings (non-fatal; print and continue). ---
    reaches = report.evaluate(result)
    report.trial_numbering_warnings(result)
    report.trial_naming_warnings(result)
    report.arena_target_consistency_warnings(result)
    report.print_report(reaches, result)
    report.write_flagged_csv(reaches, paths.FLAGGED_TRIALS_CSV)

    # --- Step 3: build alignment figure (retryable). ---
    def step3():
        print("\nBuilding alignment figure ...")
        return alignment.build_alignment_figure(
            result, paths.VERIFICATION_DIR / f"{experiment}_alignment.png"
        )

    fig_path = _step_with_retry("building alignment figure", step3, assume_yes)
    if fig_path is _QUIT:
        return 1
    print(f"  Saved target-alignment image: {fig_path}")

    # --- Alignment y/n confirmation. ---
    if not _confirm("paths reach the marked targets and start from the labelled entrances?", assume_yes):
        print("Aborted at alignment check. Nothing written.")
        return 2

    # --- Step 4: write .mat files (retryable; existing files without --force trigger here). ---
    def step4():
        return _write_records(records, force)

    out_dir = _step_with_retry("writing .mat files", step4, assume_yes)
    if out_dir is _QUIT:
        return 1
    print(f"\nWrote {len(records)} .mat files to {out_dir}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Convert one experiment's Ethovision exports to .mat.")
    parser.add_argument("experiment", help="experiment id = start date, e.g. 2025-01-21")
    parser.add_argument("--force", action="store_true", help="overwrite existing .mat output")
    parser.add_argument("--yes", action="store_true", help="skip the y/n confirmations (non-interactive)")
    args = parser.parse_args(argv)
    try:
        return run(args.experiment, force=args.force, assume_yes=args.yes)
    except Etho2matError as exc:
        # Reached only with --yes (the per-step retry doesn't engage in non-interactive runs).
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
