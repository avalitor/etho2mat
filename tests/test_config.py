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
