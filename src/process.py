"""Assemble trials into :class:`schema.TrialRecord` objects (no file writing here).

This is the seam shared by the guided ``convert`` entry point and the golden test:
it loads config, computes the arena geometry once per distinct background image
referenced by the experiment (default + any per-mouse overrides in mouse_map.csv),
and builds one record per Excel file. Writing and the y/n confirmation gates live
in ``convert``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from . import config_io, excel_io, metrics, paths
from .arena import ArenaResult, detect
from .schema import TrialRecord, validate_record
from .validate import CollisionError, ConfigError, InputError


@dataclass
class ProcessResult:
    experiment: str
    cfg: config_io.ExperimentConfig
    rules: list
    arenas: dict            # {background_image_filename: ArenaResult}
    records: list           # list[TrialRecord], in Excel-file order
    background_paths: dict  # {background_image_filename: Path}


def iter_excel_paths(raw_dir: Path):
    """All ``.xlsx`` trial exports in an experiment's raw folder, name-sorted."""
    files = sorted(p for p in Path(raw_dir).glob("*.xlsx") if not p.name.startswith("~$"))
    if not files:
        raise InputError(f"No .xlsx trial files found in {raw_dir}.")
    return files


def distinct_arena_specs(cfg, mouse_map) -> dict:
    """Collect every (background_image -> img_extent) the experiment will need.

    Starts with the experiment-wide default. Adds every distinct override seen in
    ``mouse_map.csv`` for this experiment. If two rows reference the same
    background image with different extents, that's a config error -- one image
    file can only correspond to one cm calibration.
    """
    specs: dict[str, np.ndarray] = {}
    if cfg.background_image:
        specs[cfg.background_image] = cfg.img_extent
    for (exp, _mouse), entry in mouse_map.items():
        if exp != cfg.experiment:
            continue
        bg = entry.get("background_image") or ""
        if not bg:
            continue
        ext = entry.get("img_extent")
        ext = ext if ext is not None else cfg.img_extent
        if bg in specs and not np.allclose(specs[bg], ext):
            raise ConfigError(
                f"{cfg.experiment}: background image '{bg}' is referenced with two "
                f"different img_extent values ({specs[bg].tolist()} vs {ext.tolist()}). "
                f"One image file must correspond to exactly one cm calibration."
            )
        specs[bg] = ext
    if not specs:
        raise InputError(
            f"{cfg.experiment}: background_image is blank in experiment_list.csv "
            f"and no mouse_map.csv row provides one."
        )
    return specs


def build_arena_map(cfg, mouse_map, background_dir: Path) -> tuple:
    """Detect the arena once per distinct background image.

    Returns ``(arenas, background_paths, extents)`` -- three dicts keyed by the
    background-image filename. ``extents`` is the cm calibration the detection
    used for each image (needed when rendering its verification figure).
    """
    background_dir = Path(background_dir)
    specs = distinct_arena_specs(cfg, mouse_map)
    arenas: dict[str, ArenaResult] = {}
    background_paths: dict[str, Path] = {}
    for bg, extent in specs.items():
        path = background_dir / bg
        if not path.exists():
            raise InputError(
                f"{cfg.experiment}: background image '{bg}' not found in {background_dir}."
            )
        arenas[bg] = detect(path, extent, cfg.expected_hole_count)
        background_paths[bg] = path
    return arenas, background_paths, specs


def build_record(cfg, rules, mouse_map, excel_path, arenas: dict) -> TrialRecord:
    """Build one trial's record from its Excel file + config + arena geometry.

    The arena geometry, ``bkgd_img`` and ``img_extent`` are resolved per-mouse so
    multi-arena experiments (mice 1-4 on arena A, mice 5-8 on arena B) drop the
    right values into each trial's record.
    """
    ex = excel_io.read_trial_excel(excel_path)
    sex, strain = config_io.resolve_mouse_sex_strain(cfg, ex.mouse_number, mouse_map)
    background, img_extent = config_io.resolve_mouse_arena(cfg, ex.mouse_number, mouse_map)
    arena = arenas.get(background)
    if arena is None:
        raise InputError(
            f"{cfg.experiment}: mouse {ex.mouse_number} resolved to background image "
            f"'{background}' which was not detected. Check mouse_map.csv and "
            f"experiment_list.csv for a typo."
        )
    target, target_reverse = config_io.resolve_targets(rules, ex.entrance, ex.trial, ex.mouse_number)

    head = metrics.heading(ex.r_center)
    k_rew, reached = metrics.k_reward(ex.r_nose, target)
    holes = arena.r_arena_holes
    khc = metrics.k_hole_checks(ex.r_nose, ex.r_center, holes)

    rec = TrialRecord(
        exp=cfg.experiment,
        eth_file=ex.source_filename,
        protocol_name=cfg.protocol,
        protocol_description=cfg.protocol_description,
        experimenter=cfg.experimenter,
        bkgd_img=background,
        mouse_number=ex.mouse_number,
        mouse_sex=sex,
        mouse_strain=strain,
        day=ex.day,
        trial=ex.trial,
        entrance=ex.entrance,
        filename=f"hfm_{cfg.experiment}_M{ex.mouse_number}_{ex.trial}.mat",
        img_extent=img_extent,
        target=target,
        target_reverse=target_reverse,
        time=ex.time,
        r_nose=ex.r_nose,
        r_center=ex.r_center,
        r_tail=ex.r_tail,
        velocity=ex.velocity,
        head_direction=ex.head_direction,
        heading=head,
        arena_circle=arena.arena_circle,
        r_arena_holes=holes,
        k_reward=k_rew,
        reward_reached=reached,
        k_hole_checks=khc,
    )
    validate_record(rec)
    return rec


def _check_filename_collisions(records):
    """The only trial-level hard stop: two trials writing to the same file."""
    seen = {}
    for rec in records:
        if rec.filename in seen:
            raise CollisionError(
                f"Two trials map to the same output file '{rec.filename}': "
                f"'{seen[rec.filename]}' and '{rec.eth_file}'. Two trials for one mouse "
                f"share a name -- rename one in Ethovision and re-export."
            )
        seen[rec.filename] = rec.eth_file


def process_experiment(experiment: str, *, raw_dir=None, background_dir=None,
                       experiment_list=None, targets_path=None, mouse_map_path=None) -> ProcessResult:
    """Load config, detect arena(s), and build every trial's record (no writing)."""
    cfg = config_io.load_experiment(experiment, experiment_list)
    rules = config_io.load_targets(experiment, targets_path)
    mouse_map = config_io.load_mouse_map(mouse_map_path)

    bg_dir = Path(background_dir) if background_dir else paths.BACKGROUND_DIR
    arenas, background_paths, _extents = build_arena_map(cfg, mouse_map, bg_dir)

    raw = Path(raw_dir) if raw_dir else paths.raw_experiment_dir(experiment)
    records = [build_record(cfg, rules, mouse_map, p, arenas) for p in iter_excel_paths(raw)]
    _check_filename_collisions(records)

    return ProcessResult(experiment, cfg, rules, arenas, records, background_paths)
