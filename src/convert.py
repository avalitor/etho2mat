"""Guided entry point: validate -> detect arena -> confirm -> confirm alignment -> write.

This is what the double-clickable launcher runs. Nothing is written to disk until
BOTH the arena geometry and the target alignment are confirmed. On either 'n',
the run aborts and writes nothing.

    python -m src.convert <experiment> [--force] [--yes]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import scipy.io as sio

from . import alignment, config_io, paths, process, report
from .arena import compute_arena, save_verification_image
from .process import ProcessResult
from .schema import to_matdict
from .validate import Etho2matError, InputError


def _confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        print(f"{prompt} [auto-yes]")
        return True
    return input(f"{prompt} [y/n] ").strip().lower().startswith("y")


def _resolve_background(cfg) -> Path:
    if not cfg.background_image:
        raise InputError(f"{cfg.experiment}: background_image is blank in experiment_list.csv.")
    bg = paths.BACKGROUND_DIR / cfg.background_image
    if not bg.exists():
        raise InputError(
            f"{cfg.experiment}: background image '{cfg.background_image}' not found in "
            f"{paths.BACKGROUND_DIR}."
        )
    return bg


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
    cfg = config_io.load_experiment(experiment)
    rules = config_io.load_targets(experiment)
    mouse_map = config_io.load_mouse_map()
    background = _resolve_background(cfg)
    raw_dir = paths.raw_experiment_dir(experiment)

    # 1) Arena geometry -> verification image -> confirm
    print(f"Detecting arena geometry for {experiment} from {cfg.background_image} ...")
    arena = compute_arena(cfg, background)
    img_path = save_verification_image(
        background, arena, cfg.img_extent, paths.VERIFICATION_DIR / f"{experiment}_arena.png"
    )
    print(f"  Saved arena verification image: {img_path}")
    if not _confirm(f"1 arena and {arena.n_holes} holes -- looks right?", assume_yes):
        print("Aborted at arena check. Nothing written.")
        return 2

    # 2) Assemble records (needs arena), run reach pre-screen + alignment figure -> confirm
    excel_paths = process.iter_excel_paths(raw_dir)
    records = [process.build_record(cfg, rules, mouse_map, p, arena) for p in excel_paths]
    process._check_filename_collisions(records)
    result = ProcessResult(experiment, cfg, rules, arena, records, background)

    reaches = report.evaluate(result)
    report.trial_numbering_warnings(result)
    report.trial_naming_warnings(result)
    report.print_report(reaches, result)
    report.write_flagged_csv(reaches, paths.FLAGGED_TRIALS_CSV)

    fig_path = alignment.build_alignment_figure(
        result, paths.VERIFICATION_DIR / f"{experiment}_alignment.png"
    )
    print(f"\n  Saved target-alignment image: {fig_path}")
    if not _confirm("paths reach the marked targets and start from the labelled entrances?", assume_yes):
        print("Aborted at alignment check. Nothing written.")
        return 2

    # 3) Write
    out_dir = _write_records(records, force)
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
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
