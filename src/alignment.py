"""Target/entrance alignment verification figure.

Entrance codes are room directions; the camera may be rotated, so a target entered
for the wrong corner, a reward/reverse swap, or a mis-assigned A/B target all make
valid numbers land in the wrong place. We catch it visually using the mice's actual
paths: a grid where each ROW is one targets-CSV rule (one panel per sampled trial,
not overlaid -- overlay was a spaghetti bowl and hid bad trajectories). Each subplot
shows the arena + the assigned target + EXACTLY ONE trajectory.

Sampling heuristic: prefer short, reached, non-no-reward trials. A short trial means
a direct, well-trained path; reaching means the mouse found the target; excluding
no-reward (Habituation/Probe) avoids the jumbled exploratory trajectories those
trials produce. When a rule only matches no-reward trials, those are sampled (with
no other option). Trajectories are drawn as a light-to-dark gradient so the
direction of travel is unambiguous, and the entrance is marked at the first valid
r_nose coordinate (always on the arena perimeter).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import numpy as np

from . import config_io


def _rule_matches_record(rules, rule, rec) -> bool:
    """True if this specific rule is the one that fires for the record (handles 'remaining')."""
    fired = config_io._matching_rules(rules, rule.role, rec.entrance, rec.trial, rec.mouse_number)
    return any(r is rule for r in fired)


def _trial_quality_key(rec, no_reward_patterns):
    """Sort key for picking representative trajectories.

    Lower values rank first. The tuple's components are:
      * ``is_no_reward`` -- probe/habituation last (jumbled exploratory paths)
      * ``not reached``  -- reached trials before missed
      * ``length``       -- shorter (more direct) before longer
    """
    is_no_reward = config_io.is_no_reward_trial(rec.trial, no_reward_patterns)
    reached = bool(rec.reward_reached) if rec.reward_reached is not None else False
    if reached and rec.k_reward is not None:
        length = int(rec.k_reward)
    else:
        length = len(rec.time)
    return (is_no_reward, not reached, length)


def _is_multi_target(rec) -> bool:
    return bool(rec.target is not None and getattr(rec.target, "shape", (1,))[0] > 1)


def _pick_representatives(records, rules, rule, no_reward_patterns, sample):
    """Single-target matching records for this rule, ranked by short/reached/non-probe.

    Multi-target trials are excluded entirely -- when both A and B are baited, the
    mouse may head to the OTHER target, so the trajectory cannot meaningfully
    visualise a single-target rule. An empty slot is more honest than a misleading
    one.
    """
    matched = [rec for rec in records if _rule_matches_record(rules, rule, rec)]
    single = [rec for rec in matched if not _is_multi_target(rec)]
    return sorted(single, key=lambda r: _trial_quality_key(r, no_reward_patterns))[:sample]


def _draw_arena(plt, ax, source):
    """Draw the arena circle + holes from any object exposing
    ``arena_circle`` (cx, cy, r) and ``r_arena_holes`` (M, 2).

    Works for both :class:`arena.ArenaResult` and :class:`schema.TrialRecord`,
    which lets every panel render against its own per-trial arena geometry
    (needed when one experiment uses multiple arenas via mouse_map.csv overrides).
    """
    cx, cy, r = source.arena_circle
    ax.add_artist(plt.Circle((cx, cy), r, fill=False, color="0.55", lw=1.2))
    ax.scatter(source.r_arena_holes[:, 0], source.r_arena_holes[:, 1], s=4, color="0.85", zorder=0)
    margin = r * 1.15
    ax.set_xlim(cx - margin, cx + margin); ax.set_ylim(cy - margin, cy + margin)
    ax.set_aspect("equal", "box")
    ax.set_xticks([]); ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def _trajectory_for_display(rec):
    """Crop the trajectory at the reward-reach index so the gradient ends at the target.

    If the trial didn't reach (or k_reward is missing), draw the whole path. The
    crop is inclusive of the reach sample so the line visibly touches the target.
    """
    if rec.reward_reached and rec.k_reward is not None:
        return rec.r_nose[: int(rec.k_reward) + 1]
    return rec.r_nose


# Custom 3-stop colormap: direction is encoded by HUE (purple at the start, blue
# mid-trial, green at the end) so every segment is equally saturated. Avoids the
# single-hue "washed out at the start, opaque at the end" problem.
_TRAJ_CMAP = None  # built lazily on first use (skip import cost at module load)


def _trajectory_cmap():
    global _TRAJ_CMAP
    if _TRAJ_CMAP is None:
        from matplotlib.colors import LinearSegmentedColormap
        _TRAJ_CMAP = LinearSegmentedColormap.from_list(
            "etho2mat_traj", ["#6A3D9A", "#1F77B4", "#2CA02C"],   # purple, blue, green
        )
    return _TRAJ_CMAP


def _gradient_trajectory(ax, xy, alpha=0.85, lw=1.3):
    """Draw the trajectory as a purple -> blue -> green gradient (direction by hue)."""
    from matplotlib.collections import LineCollection

    valid = ~np.isnan(xy).any(axis=1)
    if valid.sum() < 2:
        return
    xy = xy[valid]
    points = xy.reshape(-1, 1, 2)
    segments = np.concatenate([points[:-1], points[1:]], axis=1)
    t = np.linspace(0, 1, len(segments))
    lc = LineCollection(segments, cmap=_trajectory_cmap(), linewidths=lw, alpha=alpha, zorder=2)
    lc.set_array(t); lc.set_clim(0.0, 1.0)
    ax.add_collection(lc)


def _mark_entrance(ax, xy):
    """Mark the trajectory's start (always on the arena perimeter).

    Uses gold rather than green so it can't be confused with the green end of the
    purple-blue-green trajectory gradient.
    """
    valid = np.where(~np.isnan(xy).any(axis=1))[0]
    if not len(valid):
        return
    sx, sy = xy[valid[0]]
    ax.plot(sx, sy, marker="s", markersize=9,
            markerfacecolor="#FFC93C", markeredgecolor="black", markeredgewidth=1.0, zorder=5)


def build_alignment_figure(result, out_path, sample: int = 3) -> Path:
    """Render the alignment grid: one trajectory per subplot. Returns the output path."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rules = result.rules
    no_reward_patterns = result.cfg.no_reward_trials

    rule_drawn = [
        (rule, _pick_representatives(result.records, rules, rule, no_reward_patterns, sample))
        for rule in rules
    ]

    nrows = max(1, len(rules))
    ncols = sample
    fig, axes = plt.subplots(
        nrows, ncols,
        figsize=(3.6 * ncols + 2.4, 3.6 * nrows + 1.4),
        squeeze=False,
        gridspec_kw={"wspace": 0.25, "hspace": 0.55},
    )

    for ri, (rule, drawn) in enumerate(rule_drawn):
        rule_label = f"{rule.entrance}  {rule.role}\n({rule.x:.2f}, {rule.y:.2f})"
        if rule.mice:
            rule_label += f"\nmice: {','.join(rule.mice)}"
        # Wrap long selectors so they fit in the left margin instead of being clipped.
        trials_wrapped = textwrap.fill(rule.trials, width=24)
        rule_label += f"\ntrials:\n{trials_wrapped}"

        for ci in range(ncols):
            ax = axes[ri][ci]
            if ci < len(drawn):
                rec = drawn[ci]
                _draw_arena(plt, ax, rec)
                # On a reverse panel, show the trial's actual reward target(s) dimmed
                # in blue for context -- a reverse trial is also a rewarded trial, and
                # the mouse is heading toward THAT target, not the reverse marker.
                if rule.role == "reverse" and rec.target is not None:
                    for t_row in np.atleast_2d(rec.target):
                        ax.add_artist(plt.Circle((t_row[0], t_row[1]), 3.0,
                                                 color="tab:blue", alpha=0.35, zorder=2))
                target_color = "tab:blue" if rule.role == "reward" else "tab:red"
                ax.add_artist(plt.Circle((rule.x, rule.y), 3.0,
                                         color=target_color, alpha=0.85, zorder=3))
                xy = _trajectory_for_display(rec)
                _gradient_trajectory(ax, xy)
                _mark_entrance(ax, xy)
                ax.set_title(f"M{rec.mouse_number}   trial {rec.trial}", fontsize=12)
            else:
                # No matching trial -- draw a faint placeholder so the row stays aligned,
                # but skip arena/holes so it's visually clearly empty.
                ax.set_xlim(-1, 1); ax.set_ylim(-1, 1)
                ax.set_aspect("equal", "box")
                ax.set_xticks([]); ax.set_yticks([])
                for spine in ax.spines.values():
                    spine.set_visible(False)
                ax.text(0, 0, "(no matching trial)", fontsize=11, color="0.55",
                        ha="center", va="center")

        # Row label in the left margin of the leftmost panel.
        axes[ri][0].text(
            -0.28, 0.5, rule_label, fontsize=11, ha="right", va="center",
            transform=axes[ri][0].transAxes,
        )

    fig.suptitle(f"{result.experiment}   --   target / entrance alignment",
                 fontsize=16, y=0.985)
    fig.text(
        0.5, 0.955,
        "blue circle = reward target    red circle = reverse target    "
        "gold square = entrance    trajectory goes purple -> blue -> green over time\n"
        "reached trials are cropped at reach    "
        "reverse panels also show the trial's actual reward target dimmed in blue",
        ha="center", va="top", fontsize=11, color="0.35",
    )
    # Explicit spacing (tight_layout would collapse the inter-panel gap and
    # crowd the row labels against the leftmost arena).
    fig.subplots_adjust(left=0.18, right=0.98, top=0.92, bottom=0.02,
                        wspace=0.25, hspace=0.55)
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    return out_path
