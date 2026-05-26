"""Target/entrance alignment verification figure.

Entrance codes are room directions; the camera may be rotated, so a target entered
for the wrong corner, a reward/reverse swap, or a mis-assigned A/B target all make
valid numbers land in the wrong place. We catch it visually using the mice's actual
paths: one panel per config rule (each targets row, split by mouse group), overlaying
the arena, the assigned target, and a few sampled LATE trajectories (late trials are
direct, so a path to the wrong corner is obvious). Panel count scales with config
complexity, not trial count.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from . import config_io


def _rule_matches_record(rules, rule, rec) -> bool:
    """True if this specific rule is the one that fires for the record (handles 'remaining')."""
    fired = config_io._matching_rules(rules, rule.role, rec.entrance, rec.trial, rec.mouse_number)
    return any(r is rule for r in fired)


def _trial_sort_key(rec):
    return (0, int(rec.trial)) if rec.trial.isdigit() else (1, rec.trial)


def build_alignment_figure(result, out_path, sample: int = 5) -> Path:
    """Render one panel per targets rule and save it. Returns the output path."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rules = result.rules
    arena = result.arena
    ext = result.cfg.img_extent

    n = len(rules)
    ncols = min(4, n) or 1
    nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(4.2 * ncols, 4.2 * nrows), squeeze=False)

    for idx, rule in enumerate(rules):
        ax = axes[idx // ncols][idx % ncols]
        # arena + holes (faint)
        cx, cy, r = arena.arena_circle
        ax.add_artist(plt.Circle((cx, cy), r, fill=False, color="0.6", lw=1))
        ax.scatter(arena.r_arena_holes[:, 0], arena.r_arena_holes[:, 1],
                   s=4, color="0.8", zorder=0)
        # sampled late trajectories for this rule
        matched = sorted([rec for rec in result.records if _rule_matches_record(rules, rule, rec)],
                         key=_trial_sort_key, reverse=True)
        drawn = matched[:sample]
        for rec in drawn:
            ax.plot(rec.r_nose[:, 0], rec.r_nose[:, 1], lw=0.8, alpha=0.7)
        # assigned target for this rule
        color = "blue" if rule.role == "reward" else "red"
        ax.add_artist(plt.Circle((rule.x, rule.y), 3.0, color=color, alpha=0.9))

        mice = ",".join(rule.mice) if rule.mice else "all"
        trials_drawn = ", ".join(rec.trial for rec in drawn) or "(none matched)"
        ax.set_title(f"{rule.entrance} {rule.role} ({rule.x:.1f},{rule.y:.1f})\n"
                     f"sel='{rule.trials}' mice={mice}\ndrawn: {trials_drawn}", fontsize=7)
        ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3])
        ax.set_aspect("equal", "box"); ax.axis("off")

    for j in range(n, nrows * ncols):
        axes[j // ncols][j % ncols].axis("off")

    fig.suptitle(f"{result.experiment} -- target/entrance alignment "
                 f"(blue=reward, red=reverse; paths reach the marked targets?)", fontsize=10)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(out_path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out_path
