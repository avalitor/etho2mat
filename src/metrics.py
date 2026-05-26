"""Derived metrics: heading, k_reward, reach evaluation, and k_hole_checks.

These reproduce the legacy numbers **exactly** (the golden test locks this), so the
magic constants and quirks are kept deliberately:
  * reward window radius = 3.0 cm, measured on the **nose** (r_nose)
  * hole-check radius = 2.0 cm, curvature peak ``delta`` = 1.0
  * heading = atan2 of diff(r_center), with a leading NaN
  * k_reward generalises to multi-target as "first entry into ANY target window"
    while staying byte-identical to the old single-target result.
"""

from __future__ import annotations

import numpy as np

REWARD_RADIUS_CM = 3.0
HOLE_RADIUS_CM = 2.0
CURVATURE_DELTA = 1.0


# --------------------------------------------------------------------------- #
# heading
# --------------------------------------------------------------------------- #
def heading(r_center: np.ndarray) -> np.ndarray:
    """Movement heading (deg) from consecutive center points, leading NaN to keep length."""
    v = np.diff(r_center, axis=0)
    h = np.arctan2(v[:, 1], v[:, 0]) * (180.0 / np.pi)
    return np.insert(h, 0, np.nan)


# --------------------------------------------------------------------------- #
# k_reward (reward-arrival index)
# --------------------------------------------------------------------------- #
def _dist(p, q) -> float:
    return float(np.sqrt((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2))


def _last_valid_index(r_nose: np.ndarray) -> int:
    """Last sample whose nose coordinate is not NaN (fallback: last index)."""
    valid = np.where(~np.isnan(r_nose).any(axis=1))[0]
    return int(valid[-1]) if valid.size else len(r_nose) - 1


def k_reward(r_nose: np.ndarray, targets: np.ndarray, radius: float = REWARD_RADIUS_CM):
    """Index of first nose entry into ANY target's reward window.

    Returns ``(index, reached)``. Reproduces the legacy single-target result
    byte-for-byte (including the ``np.where(coords == row)`` index lookup); when
    no target is reached, returns ``(last valid index, False)`` -- the deliberate
    fix that replaces the old ``len-2`` sentinel.
    """
    targets = np.asarray(targets, dtype=np.float64).reshape(-1, 2)
    for row in r_nose:
        if any(_dist(row, t) <= radius for t in targets):
            return int(np.where(r_nose == row)[0][0]), True
    return _last_valid_index(r_nose), False


def closest_approach(r_nose: np.ndarray, target) -> float:
    """Minimum nose-to-target distance over the trial (NaN-safe)."""
    d = np.linalg.norm(r_nose - np.asarray(target, dtype=np.float64), axis=1)
    return float(np.nanmin(d)) if np.isfinite(d).any() else float("nan")


# --------------------------------------------------------------------------- #
# k_hole_checks (curvature-near-hole detection chain)
# --------------------------------------------------------------------------- #
def _hole_intersections(bodypoint: np.ndarray, r_holes: np.ndarray, hole_radius: float):
    """For each hole, the trajectory indices within ``hole_radius`` (or None)."""
    idx_inter = []
    for r0 in r_holes:
        tind = np.nonzero(np.linalg.norm(bodypoint - r0, axis=1) < hole_radius)[0]
        idx_inter.append(tind if len(tind) > 0 else None)
    return idx_inter


def _menger_curvature(A, B, C) -> float:
    matrix = np.column_stack((np.append(A, 1), np.append(B, 1), np.append(C, 1)))
    with np.errstate(invalid="ignore"):   # NaN coords -> NaN det (expected, kept)
        area = 0.5 * np.linalg.det(matrix)
    if np.all(A == B) or np.all(B == C) or np.all(A == C):
        return 0.0
    return 4 * area / (np.linalg.norm(A - B) * np.linalg.norm(B - C) * np.linalg.norm(C - A))


def _traj_curvatures(r_nose: np.ndarray) -> np.ndarray:
    x, y = r_nose[:, 0], r_nose[:, 1]
    out = np.empty(0)
    for i in range(len(x) - 2):
        A = np.array([x[i], y[i]]); B = np.array([x[i + 1], y[i + 1]]); C = np.array([x[i + 2], y[i + 2]])
        out = np.append(out, abs(_menger_curvature(A, B, C)))
    return np.append(out, [0, 0])   # two trailing zeros to match length


def _peakdet(v: np.ndarray, delta: float):
    """endolith's peakdet -- returns (maxtab, mintab) as (pos, value) arrays."""
    maxtab, mintab = [], []
    x = np.arange(len(v))
    v = np.asarray(v)
    mn, mx = np.inf, -np.inf
    mnpos, mxpos = np.nan, np.nan
    lookformax = True
    for i in np.arange(len(v)):
        this = v[i]
        if this > mx:
            mx = this; mxpos = x[i]
        if this < mn:
            mn = this; mnpos = x[i]
        if lookformax:
            if this < mx - delta:
                maxtab.append((mxpos, mx)); mn = this; mnpos = x[i]; lookformax = False
        else:
            if this > mn + delta:
                mintab.append((mnpos, mn)); mx = this; mxpos = x[i]; lookformax = True
    return np.array(maxtab), np.array(mintab)


def _sharp_curve_near_hole(curvatures: np.ndarray, idx_inter, delta: float):
    peaks, _ = _peakdet(curvatures, delta)
    idx_traj_holes_curve = []
    for k in idx_inter:
        if k is not None and len(np.intersect1d(peaks, k)) > 0:
            idx_traj_holes_curve.append(np.intersect1d(peaks, k))
        else:
            idx_traj_holes_curve.append(None)
    return idx_traj_holes_curve


def _get_k_times(idx_inter, idx_traj_holes_curve) -> np.ndarray:
    already_visited = []
    k_times = []
    for i, hole in enumerate(idx_inter):
        if hole is not None and idx_traj_holes_curve[i] is not None:
            for enum_idx, traj_idx in enumerate(hole):
                if enum_idx - traj_idx in already_visited:
                    continue
                if np.intersect1d(idx_traj_holes_curve[i], traj_idx).size != 0:
                    for h in idx_traj_holes_curve[i]:
                        if h == traj_idx:
                            k_times.append([i, int(traj_idx)])
                            already_visited.append(enum_idx - traj_idx)
    return np.array(k_times, dtype=np.int64).reshape(-1, 2)


def k_hole_checks(r_nose: np.ndarray, r_center: np.ndarray, r_holes: np.ndarray,
                  hole_radius: float = HOLE_RADIUS_CM, delta: float = CURVATURE_DELTA) -> np.ndarray:
    """``(K,2)`` array of ``[hole_index, trajectory_index]`` hole checks."""
    bodypoint = r_nose if len(r_nose) > 1 else r_center
    idx_inter = _hole_intersections(bodypoint, r_holes, hole_radius)
    curvatures = _traj_curvatures(r_nose)
    idx_traj_holes_curve = _sharp_curve_near_hole(curvatures, idx_inter, delta)
    return _get_k_times(idx_inter, idx_traj_holes_curve)
