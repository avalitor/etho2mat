"""Arena-circle and hole detection, plus geometry verification.

Detected per experiment from that experiment's own screenshot (the arena shifts
between experiments). Validation is hard: exactly one arena circle and exactly
``expected_hole_count`` holes, or the run stops with a named likely cause -- fix
the screenshot per CHECKLIST.md rather than papering over a bad detection.

The detection sequence (downscale to height 500 -> grayscale -> bilateral filter
-> HoughCircles -> Otsu + small-contour centroids -> pixel->cm transform) and its
constants reproduce the legacy geometry byte-for-byte.

A single verification figure is **always** written per background image, success
or failure. On success it shows the detected overlay (as before); on failure it
shows the preprocessed grayscale, the Canny edge map HoughCircles operates on,
and any circle candidates found at a relaxed accumulator threshold, so the user
can see what the detector saw and decide what to fix on the screenshot.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from .validate import ArenaError

# Detection constants (reproduce the legacy result).
_SCALING = 500.0
_MASK_SENSITIVITY = 60.0
_HOUGH = dict(dp=1, minDist=20, param1=80, minRadius=50, maxRadius=200)
_HOLE_AREA_MAX = 30          # contour area (downscaled px) below which it's a hole

# Diagnostic-only: a relaxed HoughCircles pass shown in the failure figure so
# the user can see what the detector would have locked onto with a lower
# accumulator threshold and a wider radius window. Never feeds the result.
_WEAK_HOUGH = dict(dp=1, minDist=20, param1=80, param2=30, minRadius=30, maxRadius=400)


@dataclass
class ArenaResult:
    # Successful-detection fields. None if detection failed before this stage.
    arena_circle: Optional[np.ndarray] = None     # (3,) [cx, cy, r] in cm
    r_arena_holes: Optional[np.ndarray] = None    # (M,2) in cm
    main_px: Optional[list] = None                # [cx, cy, r] in pixels (for the verification image)
    n_circles: int = 0
    n_holes: int = 0
    gray_shape: tuple = (0, 0)                    # (H, W) of the downscaled image
    # Diagnostic fields (always populated by analyze()).
    gray: Optional[np.ndarray] = None             # preprocessed grayscale, pre-mutation copy
    edges: Optional[np.ndarray] = None            # Canny edge map at param1=80
    holes_px: list = field(default_factory=list)  # hole centroids in downscaled pixels
    weak_candidates: Optional[np.ndarray] = None  # (K,3) candidates at relaxed param2
    error_message: Optional[str] = None           # None = valid; else the human-readable failure cause


def _preprocess(image_path: Path):
    import cv2

    img = cv2.imread(str(image_path))
    if img is None:
        raise ArenaError(f"Could not read background image: {image_path}")
    ratio = img.shape[0] / _SCALING
    img = cv2.resize(img, (int(img.shape[1] / ratio), int(img.shape[0] / ratio)),
                     interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 11, 17, 17)
    return gray


def _detect_circle(gray, image_name: str):
    """Run the production HoughCircles. Returns (main_px, n, error_message).

    Mutates ``gray`` in place via cv2.circle draws when a circle is found; the
    legacy hole pass depends on these side effects for byte-exact reproduction.
    """
    import cv2

    circles = cv2.HoughCircles(gray, method=cv2.HOUGH_GRADIENT, param2=_MASK_SENSITIVITY, **_HOUGH)
    if circles is None:
        return None, 0, (
            f"No arena circle detected in {image_name}. The edge may be too faint -- "
            f"boost contrast on the screenshot (see CHECKLIST.md) and try again."
        )
    circles = np.uint16(np.around(circles))
    n = len(circles[0])
    if n != 1:
        return None, n, (
            f"Detected {n} circles in {image_name}, expected exactly 1. A reflection or "
            f"the arena rim may be doubling up -- crop or clean the image and try again."
        )
    # Replicate the legacy in-place draws (they affect downstream hole contours).
    main = None
    for i in circles[0, :]:
        cv2.circle(gray, (i[0], i[1]), i[2], (0, 255, 0), 2)
        cv2.circle(gray, (i[0], i[1]), 2, (0, 0, 255), 3)
        main = [int(i[0]), int(i[1]), int(i[2])]
    return main, n, None


def _detect_holes(main, gray):
    import cv2

    mask = np.zeros(gray.shape[:2], dtype="uint8")
    cv2.circle(mask, (main[0], main[1]), main[2], 255, -1)
    masked = cv2.bitwise_and(gray, gray, mask=mask)
    _, threshed = cv2.threshold(masked, 100, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    cnts = cv2.findContours(threshed, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[-2]
    holes = []
    for c in cnts:
        if cv2.contourArea(c) < _HOLE_AREA_MAX:
            m = cv2.moments(c)
            holes.append((int(m["m10"] / m["m00"]), int(m["m01"] / m["m00"])))
    return holes


def _weak_candidates(gray_clean):
    """Diagnostic HoughCircles pass with a relaxed accumulator threshold.

    Operates on the pre-mutation grayscale so the production draws don't bias
    the result. Returns ``(K,3) uint16`` array or ``None`` if even this finds
    nothing.
    """
    import cv2

    circles = cv2.HoughCircles(gray_clean, method=cv2.HOUGH_GRADIENT, **_WEAK_HOUGH)
    if circles is None:
        return None
    return np.uint16(np.around(circles))[0]


def _canny_edges(gray):
    import cv2

    return cv2.Canny(gray, _HOUGH["param1"] // 2, _HOUGH["param1"])


def _transpose(holes_px, main_px, gray_shape, img_extent):
    """pixel -> cm (center on image centre, scale by height ratio, flip y)."""
    H, W = gray_shape
    center = (W / 2.0, H / 2.0)
    scale = H / (img_extent[3] - img_extent[2])
    holes_cm = (np.asarray(holes_px, dtype=np.float64) - np.asarray(center)) / scale * (1.0, -1.0)
    arena_cm = (np.append(np.asarray(main_px[:2], dtype=np.float64) - np.asarray(center), main_px[2])
                / scale) * (1.0, -1.0, 1.0)
    return holes_cm, arena_cm


def _hole_count_error(n_holes, expected, image_name):
    if n_holes == expected:
        return None
    cause = ("a food-filled or shadowed hole was missed" if n_holes < expected
             else "a wire, cable, reflection, or speck was counted as an extra hole")
    return (
        f"Detected {n_holes} holes in {image_name}, expected {expected}. Likely cause: "
        f"{cause}. See CHECKLIST.md (arena screenshot): the arena must be clear, evenly "
        f"lit, with all holes empty and visible."
    )


def analyze(image_path, img_extent, expected_hole_count) -> ArenaResult:
    """Run the full arena pipeline; never raises on a detection issue.

    Returns an ``ArenaResult`` with every diagnostic field populated. If the
    result is invalid, ``error_message`` is set; otherwise it is ``None`` and
    the arena/holes fields are filled in. The only exception still raised here
    is :class:`ArenaError` from ``_preprocess`` when the image file can't be
    read -- there is nothing to visualize in that case.
    """
    image_path = Path(image_path)
    gray = _preprocess(image_path)
    gray_clean = gray.copy()                       # pre-mutation snapshot for diagnostics
    edges = _canny_edges(gray_clean)
    weak = _weak_candidates(gray_clean)

    main, n_circles, circle_err = _detect_circle(gray, image_path.name)
    if circle_err is not None:
        return ArenaResult(
            n_circles=n_circles,
            gray_shape=gray.shape,
            gray=gray_clean,
            edges=edges,
            weak_candidates=weak,
            error_message=circle_err,
        )

    holes_px = _detect_holes(main, gray)
    hole_err = _hole_count_error(len(holes_px), expected_hole_count, image_path.name)
    if hole_err is not None:
        # We still have a valid circle to show; arena_circle/holes_cm transposed
        # so the overlay panel can render what we did find.
        try:
            holes_cm, arena_cm = _transpose(holes_px, main, gray.shape, img_extent)
        except Exception:
            holes_cm, arena_cm = None, None
        return ArenaResult(
            arena_circle=arena_cm,
            r_arena_holes=holes_cm,
            main_px=main,
            n_circles=n_circles,
            n_holes=len(holes_px),
            gray_shape=gray.shape,
            gray=gray_clean,
            edges=edges,
            holes_px=holes_px,
            weak_candidates=weak,
            error_message=hole_err,
        )

    holes_cm, arena_cm = _transpose(holes_px, main, gray.shape, img_extent)
    return ArenaResult(
        arena_circle=arena_cm,
        r_arena_holes=holes_cm,
        main_px=main,
        n_circles=n_circles,
        n_holes=len(holes_px),
        gray_shape=gray.shape,
        gray=gray_clean,
        edges=edges,
        holes_px=holes_px,
        weak_candidates=weak,
        error_message=None,
    )


def detect(image_path, img_extent, expected_hole_count) -> ArenaResult:
    """Detect arena + holes. Raises :class:`ArenaError` on a bad result.

    Thin back-compat wrapper over :func:`analyze` so every existing caller
    (including the golden-test path) keeps its raise-on-failure semantics.
    """
    result = analyze(image_path, img_extent, expected_hole_count)
    if result.error_message is not None:
        raise ArenaError(result.error_message)
    return result


def compute_arena(cfg, image_path) -> ArenaResult:
    """Detect the arena from the screenshot. Kept as a small seam in case a future
    rescue path (e.g. manual override, hole-template) needs to slot in here."""
    return detect(image_path, cfg.img_extent, cfg.expected_hole_count)


def _draw_circle_px(ax, main_px, color):
    if main_px is None:
        return
    import matplotlib.pyplot as plt
    cx, cy, r = main_px
    ax.add_artist(plt.Circle((cx, cy), r, fill=False, color=color, lw=1.5))
    ax.plot(cx, cy, marker="+", color=color, markersize=8, mew=1.5)


def save_verification_image(image_path, arena: ArenaResult, img_extent, out_path) -> Path:
    """Always-on 2x2 verification + diagnostic figure.

    Panels:
      - top-left:  original screenshot in cm coords with detected overlay (if any).
      - top-right: preprocessed downscaled grayscale (what HoughCircles sees post-filter).
      - bottom-left: Canny edge map at the production ``param1`` (HoughCircles' edge input).
      - bottom-right: relaxed-threshold candidate circles in orange (diagnostic only).

    Success and failure both write here -- on failure the title reflects the
    error and the user can see what the detector saw.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.image as mpimg

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    (ax_overlay, ax_gray), (ax_edges, ax_weak) = axes

    # --- Top-left: cm-space overlay on the original screenshot ---
    ax_overlay.imshow(mpimg.imread(str(image_path)), extent=list(img_extent))
    if arena.arena_circle is not None:
        cx, cy, r = arena.arena_circle
        ax_overlay.add_artist(plt.Circle((cx, cy), r, fill=False, color="lime", lw=2))
    if arena.r_arena_holes is not None and len(arena.r_arena_holes) > 0:
        ax_overlay.scatter(arena.r_arena_holes[:, 0], arena.r_arena_holes[:, 1],
                           s=18, facecolors="none", edgecolors="red", linewidths=1.2)
    ax_overlay.set_xlim(img_extent[0], img_extent[1])
    ax_overlay.set_ylim(img_extent[2], img_extent[3])
    if arena.error_message is None:
        overlay_title = f"OK -- 1 arena and {arena.n_holes} holes"
    else:
        overlay_title = "FAILED -- " + textwrap.fill(arena.error_message, width=70)
    ax_overlay.set_title(f"{Path(image_path).name}\n{overlay_title}", fontsize=9)
    ax_overlay.axis("off")

    # --- Top-right: preprocessed grayscale (pre-mutation) ---
    if arena.gray is not None:
        ax_gray.imshow(arena.gray, cmap="gray")
        _draw_circle_px(ax_gray, arena.main_px, color="lime")
        for (hx, hy) in arena.holes_px:
            ax_gray.plot(hx, hy, marker="o", markersize=3,
                         markerfacecolor="none", markeredgecolor="red", mew=0.8)
    ax_gray.set_title("preprocessed grayscale (downscaled, bilateral)", fontsize=9)
    ax_gray.axis("off")

    # --- Bottom-left: Canny edges (what HoughCircles operates on) ---
    if arena.edges is not None:
        ax_edges.imshow(arena.edges, cmap="gray")
        _draw_circle_px(ax_edges, arena.main_px, color="lime")
    ax_edges.set_title(f"Canny edges (param1={_HOUGH['param1']}) -- HoughCircles input", fontsize=9)
    ax_edges.axis("off")

    # --- Bottom-right: relaxed-threshold candidates ---
    if arena.gray is not None:
        ax_weak.imshow(arena.gray, cmap="gray")
    if arena.weak_candidates is not None and len(arena.weak_candidates) > 0:
        for (cx, cy, r) in arena.weak_candidates:
            ax_weak.add_artist(plt.Circle((int(cx), int(cy)), int(r),
                                          fill=False, color="orange", lw=1.2))
            ax_weak.text(int(cx), int(cy) - int(r) - 4,
                         f"({int(cx)},{int(cy)},r={int(r)})",
                         color="orange", fontsize=7, ha="center")
        weak_title = (f"relaxed candidates (param2={_WEAK_HOUGH['param2']}, "
                      f"r={_WEAK_HOUGH['minRadius']}..{_WEAK_HOUGH['maxRadius']}) -- "
                      f"diagnostic only, never used")
    else:
        weak_title = (f"no circles even at relaxed threshold "
                      f"(param2={_WEAK_HOUGH['param2']}, "
                      f"r={_WEAK_HOUGH['minRadius']}..{_WEAK_HOUGH['maxRadius']})")
    ax_weak.set_title(weak_title, fontsize=9)
    ax_weak.axis("off")

    fig.suptitle(out_path.name, fontsize=10)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path
