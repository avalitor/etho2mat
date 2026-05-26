"""Unit tests for the config layer: selector grammar, target resolution, and the
loud validation errors. These run without any fixtures (fast)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import config_io as c  # noqa: E402
from src.validate import ConfigError  # noqa: E402


# --- selector grammar -------------------------------------------------------
@pytest.mark.parametrize("selector,trial,expected", [
    ("all", "1", True),
    ("all", "Probe", True),
    ("1-20", "20", True),
    ("1-20", "21", False),
    ("1-20", "Probe", False),
    ("1..20", "20", True),               # `..` range (Excel-safe alternative to `-`)
    ("1..20", "21", False),
    ("1,2,5", "5", True),
    ("1,2,5", "3", False),
    ("Probe", "Probe", True),
    ("Probe", "Probe2", False),          # exact name, not prefix
    ("Probe*", "Probe2", True),          # prefix tag
    ("R*", "R90 1", True),
    ("habit*", "habit3", True),
    ("31-99, probe2, habit*", "probe2", True),
    ("remaining", "anything", False),    # 'remaining' is handled by the resolver
    # `!` negation
    ("!1-20, !Probe*", "25", True),      # outside both negatives -> match
    ("!1-20, !Probe*", "5", False),      # inside the !1-20 negative -> no match
    ("!1-20, !Probe*", "Probe3", False), # caught by the !Probe* negative
    ("1-30, !25", "20", True),           # positive matches, negative doesn't
    ("1-30, !25", "25", False),          # positive matches but negative wins
    ("all, !Probe", "Probe", False),     # `all` minus exact `Probe`
    ("all, !Probe", "Probe2", True),     # `Probe` exact doesn't catch Probe2
])
def test_selector_matches(selector, trial, expected):
    assert c._selector_matches(selector, trial) is expected


# --- target resolution ------------------------------------------------------
def _rule(entrance, x, y, trials, role="reward", mice=(), row=1):
    return c.TargetRule(entrance, x, y, trials, mice, role, row)


def test_single_target():
    rules = [_rule("NW", 1.0, 2.0, "1-20")]
    target, reverse = c.resolve_targets(rules, "NW", "5", "111")
    assert target.shape == (1, 2) and reverse is None
    assert np.allclose(target, [[1.0, 2.0]])


def test_multi_target_order_follows_csv():
    rules = [_rule("NW", 1.0, 2.0, "30-34", row=1),
             _rule("NW", 9.0, 8.0, "30-34", row=2)]
    target, reverse = c.resolve_targets(rules, "NW", "31", "111")
    assert target.shape == (2, 2)
    assert np.allclose(target, [[1.0, 2.0], [9.0, 8.0]])   # A then B (row order)
    assert reverse is None


def test_reverse_target():
    rules = [_rule("NW", 1.0, 2.0, "21-29"),
             _rule("NW", 3.0, 4.0, "21-29", role="reverse")]
    target, reverse = c.resolve_targets(rules, "NW", "25", "111")
    assert np.allclose(target, [[1.0, 2.0]])
    assert np.allclose(reverse, [[3.0, 4.0]])


def test_no_reward_match_raises():
    rules = [_rule("NW", 1.0, 2.0, "1-20")]
    with pytest.raises(ConfigError):
        c.resolve_targets(rules, "NW", "99", "111")


def test_ambiguous_reverse_raises():
    rules = [_rule("NW", 1.0, 2.0, "all"),
             _rule("NW", 3.0, 4.0, "all", role="reverse", row=2),
             _rule("NW", 5.0, 6.0, "all", role="reverse", row=3)]
    with pytest.raises(ConfigError):
        c.resolve_targets(rules, "NW", "5", "111")


def test_remaining_selector():
    rules = [_rule("NW", 1.0, 2.0, "1-20", row=1),
             _rule("NW", 9.0, 8.0, "remaining", row=2)]
    t_early, _ = c.resolve_targets(rules, "NW", "5", "111")
    t_late, _ = c.resolve_targets(rules, "NW", "21", "111")
    assert np.allclose(t_early, [[1.0, 2.0]])
    assert np.allclose(t_late, [[9.0, 8.0]])


def test_mice_scoping():
    rules = [_rule("SW", 1.0, 2.0, "1-30", mice=("54",), row=1),
             _rule("SW", 1.0, 2.0, "1-20", mice=("58",), row=2),
             _rule("SW", 9.0, 8.0, "21-99", mice=("58",), row=3),
             _rule("SW", 9.0, 8.0, "31-99", mice=("54",), row=4)]
    assert np.allclose(c.resolve_targets(rules, "SW", "25", "54")[0], [[1.0, 2.0]])  # male still A
    assert np.allclose(c.resolve_targets(rules, "SW", "25", "58")[0], [[9.0, 8.0]])  # female already B


def test_no_reward_patterns():
    assert c.is_no_reward_trial("Probe", ("Habituation*", "Probe*"))
    assert c.is_no_reward_trial("habit3", ("habit*", "probe*"))
    assert not c.is_no_reward_trial("21", ("Habituation*", "Probe*"))


# --- loud validation --------------------------------------------------------
def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def test_placeholder_target_rejected(tmp_path):
    p = _write(tmp_path / "t.csv", "entrance,target_x,target_y,trials,mice,role\nNW,0,0,all,,reward\n")
    with pytest.raises(ConfigError, match="0,0|placeholder"):
        c.load_targets("x", p)


def test_bad_img_extent(tmp_path):
    p = _write(tmp_path / "e.csv",
               "experiment,protocol,protocol_description,img_extent,mouse_sex,mouse_strain,experimenter,background_image,expected_hole_count\n"
               "X,p,d,\"1,2,3\",male,,me,bg.png,100\n")
    with pytest.raises(ConfigError, match="img_extent"):
        c.load_experiment("X", p)


def test_bad_sex(tmp_path):
    p = _write(tmp_path / "e.csv",
               "experiment,protocol,protocol_description,img_extent,mouse_sex,mouse_strain,experimenter,background_image,expected_hole_count\n"
               "X,p,d,\"1,2,3,4\",unicorn,,me,bg.png,100\n")
    with pytest.raises(ConfigError, match="mouse_sex"):
        c.load_experiment("X", p)


def test_missing_experiment(tmp_path):
    p = _write(tmp_path / "e.csv",
               "experiment,protocol,protocol_description,img_extent,mouse_sex,mouse_strain,experimenter,background_image,expected_hole_count\n"
               "X,p,d,\"1,2,3,4\",male,,me,bg.png,100\n")
    with pytest.raises(ConfigError, match="no row"):
        c.load_experiment("Y", p)


# --- mouse_map per-mouse arena override -------------------------------------
def _cfg(experiment="X", img_extent=(-100.0, 100.0, -50.0, 50.0), background_image="default.png"):
    return c.ExperimentConfig(
        experiment=experiment, protocol="p", protocol_description="d",
        img_extent=np.array(img_extent, dtype=np.float64),
        mouse_sex="male", mouse_strain="", experimenter="me",
        background_image=background_image, expected_hole_count=100,
        no_reward_trials=(),
    )


def test_load_mouse_map_arena_columns(tmp_path):
    p = _write(tmp_path / "mm.csv",
               "experiment,mouse_id,sex,strain,background_image,img_extent\n"
               "X,1,male,WT,,\n"
               "X,5,male,WT,arenaB.png,\"-110,110,-55,55\"\n")
    out = c.load_mouse_map(p)
    assert out[("X", "1")]["background_image"] == ""
    assert out[("X", "1")]["img_extent"] is None
    assert out[("X", "5")]["background_image"] == "arenaB.png"
    assert np.allclose(out[("X", "5")]["img_extent"], [-110, 110, -55, 55])


def test_load_mouse_map_rejects_malformed_img_extent(tmp_path):
    p = _write(tmp_path / "mm.csv",
               "experiment,mouse_id,sex,strain,background_image,img_extent\n"
               "X,5,male,,arenaB.png,\"1,2,3\"\n")
    with pytest.raises(ConfigError, match="img_extent"):
        c.load_mouse_map(p)


def test_resolve_mouse_arena_uses_default_when_blank():
    cfg = _cfg()
    mouse_map = {("X", "1"): {"sex": "", "strain": "", "background_image": "", "img_extent": None}}
    bg, ext = c.resolve_mouse_arena(cfg, "1", mouse_map)
    assert bg == "default.png"
    assert np.allclose(ext, cfg.img_extent)


def test_resolve_mouse_arena_uses_override_when_set():
    cfg = _cfg()
    override_extent = np.array([-110, 110, -55, 55], dtype=np.float64)
    mouse_map = {("X", "5"): {"sex": "", "strain": "", "background_image": "arenaB.png", "img_extent": override_extent}}
    bg, ext = c.resolve_mouse_arena(cfg, "5", mouse_map)
    assert bg == "arenaB.png"
    assert np.allclose(ext, override_extent)


def test_resolve_mouse_arena_unmapped_mouse_uses_default():
    cfg = _cfg()
    mouse_map: dict = {}
    bg, ext = c.resolve_mouse_arena(cfg, "99", mouse_map)
    assert bg == "default.png"
    assert np.allclose(ext, cfg.img_extent)


# --- arena/target consistency warning ---------------------------------------
from types import SimpleNamespace                       # noqa: E402
from src import report                                  # noqa: E402


def _make_consistency_result(rules, mouse_records):
    """Minimal ProcessResult-shaped object for the consistency-warning test.

    ``mouse_records`` is a list of dicts with keys
    ``mouse``, ``arena_circle`` (3,), ``bkgd_img``, and ``trials`` (list of
    (entrance, trial)) -- one record per (mouse, trial).
    """
    records = []
    for m in mouse_records:
        for entrance, trial in m["trials"]:
            records.append(SimpleNamespace(
                mouse_number=m["mouse"], arena_circle=np.asarray(m["arena_circle"]),
                bkgd_img=m["bkgd_img"], entrance=entrance, trial=trial,
            ))
    return SimpleNamespace(rules=rules, records=records,
                           cfg=SimpleNamespace(no_reward_trials=()))


def test_arena_target_consistency_silent_when_in_arena(capsys):
    rules = [_rule("NW", 0.0, 0.0, "1-5", mice=("1",), row=1),
             _rule("NW", 50.0, 0.0, "1-5", mice=("5",), row=2)]
    result = _make_consistency_result(
        rules,
        [
            {"mouse": "1", "arena_circle": [0.0, 0.0, 30.0], "bkgd_img": "A.png",
             "trials": [("NW", "1"), ("NW", "2")]},
            {"mouse": "5", "arena_circle": [50.0, 0.0, 30.0], "bkgd_img": "B.png",
             "trials": [("NW", "1"), ("NW", "2")]},
        ],
    )
    report.arena_target_consistency_warnings(result)
    captured = capsys.readouterr()
    assert "MISMATCH" not in captured.err


def test_arena_target_consistency_flags_swap(capsys):
    # Mouse 5 is on arena B (center 50,0) but row 2 targets (0,0) -- arena-A coords.
    rules = [_rule("NW", 0.0, 0.0, "1-5", mice=("1",), row=1),
             _rule("NW", 0.0, 0.0, "1-5", mice=("5",), row=2)]
    result = _make_consistency_result(
        rules,
        [
            {"mouse": "1", "arena_circle": [0.0, 0.0, 30.0], "bkgd_img": "A.png",
             "trials": [("NW", "1")]},
            {"mouse": "5", "arena_circle": [50.0, 0.0, 30.0], "bkgd_img": "B.png",
             "trials": [("NW", "1")]},
        ],
    )
    report.arena_target_consistency_warnings(result)
    captured = capsys.readouterr()
    assert "MISMATCH" in captured.err
    assert "mouse 5" in captured.err
    assert "row 2" in captured.err
    assert "A.png" in captured.err           # swap-with arena identified


def test_arena_target_consistency_flags_outside_any_arena(capsys):
    # Mouse 5 on arena B; target row 2 lands far from any arena.
    rules = [_rule("NW", 0.0, 0.0, "1-5", mice=("1",), row=1),
             _rule("NW", 500.0, 500.0, "1-5", mice=("5",), row=2)]
    result = _make_consistency_result(
        rules,
        [
            {"mouse": "1", "arena_circle": [0.0, 0.0, 30.0], "bkgd_img": "A.png",
             "trials": [("NW", "1")]},
            {"mouse": "5", "arena_circle": [50.0, 0.0, 30.0], "bkgd_img": "B.png",
             "trials": [("NW", "1")]},
        ],
    )
    report.arena_target_consistency_warnings(result)
    captured = capsys.readouterr()
    assert "MISMATCH" in captured.err
    assert "outside every detected arena" in captured.err


def test_arena_target_consistency_skipped_single_arena(capsys):
    # Only one arena -> no cross-arena consistency to check. Target outside
    # the arena is the existing reach report's job, not this one.
    rules = [_rule("NW", 500.0, 500.0, "1-5", row=1)]
    result = _make_consistency_result(
        rules,
        [
            {"mouse": "1", "arena_circle": [0.0, 0.0, 30.0], "bkgd_img": "A.png",
             "trials": [("NW", "1")]},
        ],
    )
    report.arena_target_consistency_warnings(result)
    captured = capsys.readouterr()
    assert "MISMATCH" not in captured.err
