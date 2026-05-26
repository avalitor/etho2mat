"""Assemble trials into :class:`schema.TrialRecord` objects (no file writing here).

This is the seam shared by the guided ``convert`` entry point and the golden test:
it loads config, computes the arena geometry once per experiment, and builds one
record per Excel file. Writing and the y/n confirmation gates live in ``convert``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import config_io, excel_io, metrics, paths
from .arena import ArenaResult, compute_arena
from .schema import TrialRecord, validate_record
from .validate import CollisionError, InputError


@dataclass
class ProcessResult:
    experiment: str
    cfg: config_io.ExperimentConfig
    rules: list
    arena: ArenaResult
    records: list            # list[TrialRecord], in Excel-file order
    background_path: Path


def iter_excel_paths(raw_dir: Path):
    """All ``.xlsx`` trial exports in an experiment's raw folder, name-sorted."""
    files = sorted(p for p in Path(raw_dir).glob("*.xlsx") if not p.name.startswith("~$"))
    if not files:
        raise InputError(f"No .xlsx trial files found in {raw_dir}.")
    return files


def build_record(cfg, rules, mouse_map, excel_path, arena: ArenaResult) -> TrialRecord:
    """Build one trial's record from its Excel file + config + arena geometry."""
    ex = excel_io.read_trial_excel(excel_path)
    sex, strain = config_io.resolve_mouse_sex_strain(cfg, ex.mouse_number, mouse_map)
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
        bkgd_img=cfg.background_image,
        mouse_number=ex.mouse_number,
        mouse_sex=sex,
        mouse_strain=strain,
        day=ex.day,
        trial=ex.trial,
        entrance=ex.entrance,
        filename=f"hfm_{cfg.experiment}_M{ex.mouse_number}_{ex.trial}.mat",
        img_extent=cfg.img_extent,
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
    """Load config, detect arena once, and build every trial's record (no writing)."""
    cfg = config_io.load_experiment(experiment, experiment_list)
    rules = config_io.load_targets(experiment, targets_path)
    mouse_map = config_io.load_mouse_map(mouse_map_path)

    bg_dir = Path(background_dir) if background_dir else paths.BACKGROUND_DIR
    if not cfg.background_image:
        raise InputError(f"{experiment}: background_image is blank in experiment_list.csv.")
    background_path = bg_dir / cfg.background_image
    if not background_path.exists():
        raise InputError(
            f"{experiment}: background image '{cfg.background_image}' not found in {bg_dir}."
        )

    arena = compute_arena(cfg, background_path)

    raw = Path(raw_dir) if raw_dir else paths.raw_experiment_dir(experiment)
    records = [build_record(cfg, rules, mouse_map, p, arena) for p in iter_excel_paths(raw)]
    _check_filename_collisions(records)

    return ProcessResult(experiment, cfg, rules, arena, records, background_path)
