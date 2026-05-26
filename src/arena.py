"""Arena-circle and hole detection, plus geometry verification.

Detected per experiment from that experiment's own screenshot (the arena shifts
between experiments). Validation is hard: exactly one arena circle and exactly
``expected_hole_count`` holes, or the run stops with a named likely cause -- fix
the screenshot per CHECKLIST.md rather than papering over a bad detection.

The detection sequence (downscale to height 500 -> grayscale -> bilateral filter
-> HoughCircles -> Otsu + small-contour centroids -> pixel->cm transform) and its
constants reproduce the legacy geometry byte-for-byte.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from .validate import ArenaError

# Detection constants (reproduce the legacy result).
_SCALING = 500.0
_MASK_SENSITIVITY = 60.0
_HOUGH = dict(dp=1, minDist=20, param1=80, minRadius=50, maxRadius=200)
_HOLE_AREA_MAX = 30          # contour area (downscaled px) below which it's a hole


@dataclass
class ArenaResult:
    arena_circle: np.ndarray     # (3,) [cx, cy, r] in cm
    r_arena_holes: np.ndarray    # (M,2) in cm
    n_circles: int
    n_holes: int
    main_px: list                # [cx, cy, r] in pixels (for the verification image)
    gray_shape: tuple            # (H, W) of the downscaled image


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
    import cv2

    circles = cv2.HoughCircles(gray, method=cv2.HOUGH_GRADIENT, param2=_MASK_SENSITIVITY, **_HOUGH)
    if circles is None:
        raise ArenaError(
            f"No arena circle detected in {image_name}. The edge may be too faint -- "
            f"boost contrast on the screenshot (see CHECKLIST.md) and try again."
        )
    circles = np.uint16(np.around(circles))
    n = len(circles[0])
    if n != 1:
        raise ArenaError(
            f"Detected {n} circles in {image_name}, expected exactly 1. A reflection or "
            f"the arena rim may be doubling up -- crop or clean the image and try again."
        )
    # Replicate the legacy in-place draws (they affect downstream hole contours).
    main = None
    for i in circles[0, :]:
        cv2.circle(gray, (i[0], i[1]), i[2], (0, 255, 0), 2)
        cv2.circle(gray, (i[0], i[1]), 2, (0, 0, 255), 3)
        main = [int(i[0]), int(i[1]), int(i[2])]
    return main, n


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


def _transpose(holes_px, main_px, gray_shape, img_extent):
    """pixel -> cm (center on image centre, scale by height ratio, flip y)."""
    H, W = gray_shape
    center = (W / 2.0, H / 2.0)
    scale = H / (img_extent[3] - img_extent[2])
    holes_cm = (np.asarray(holes_px, dtype=np.float64) - np.asarray(center)) / scale * (1.0, -1.0)
    arena_cm = (np.append(np.asarray(main_px[:2], dtype=np.float64) - np.asarray(center), main_px[2])
                / scale) * (1.0, -1.0, 1.0)
    return holes_cm, arena_cm


def _validate_hole_count(n_holes, expected, image_name):
    if n_holes != expected:
        cause = ("a food-filled or shadowed hole was missed" if n_holes < expected
                 else "a wire, cable, reflection, or speck was counted as an extra hole")
        raise ArenaError(
            f"Detected {n_holes} holes in {image_name}, expected {expected}. Likely cause: "
            f"{cause}. See CHECKLIST.md (arena screenshot): the arena must be clear, evenly "
            f"lit, with all holes empty and visible."
        )


def detect(image_path, img_extent, expected_hole_count) -> ArenaResult:
    """Detect arena + holes from a screenshot. Raises :class:`ArenaError` on a bad count."""
    image_path = Path(image_path)
    gray = _preprocess(image_path)
    main, n_circ = _detect_circle(gray, image_path.name)
    holes_px = _detect_holes(main, gray)
    _validate_hole_count(len(holes_px), expected_hole_count, image_path.name)
    holes_cm, arena_cm = _transpose(holes_px, main, gray.shape, img_extent)
    return ArenaResult(arena_cm, holes_cm, n_circ, len(holes_px), main, gray.shape)


def compute_arena(cfg, image_path) -> ArenaResult:
    """Detect the arena from the screenshot. Kept as a small seam in case a future
    rescue path (e.g. manual override, hole-template) needs to slot in here."""
    return detect(image_path, cfg.img_extent, cfg.expected_hole_count)


def save_verification_image(image_path, arena: ArenaResult, img_extent, out_path) -> Path:
    """Save circle + holes overlaid on the screenshot (counts in the title)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.image as mpimg

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.imshow(mpimg.imread(str(image_path)), extent=list(img_extent))
    cx, cy, r = arena.arena_circle
    ax.add_artist(plt.Circle((cx, cy), r, fill=False, color="lime", lw=2))
    ax.scatter(arena.r_arena_holes[:, 0], arena.r_arena_holes[:, 1],
               s=18, facecolors="none", edgecolors="red", linewidths=1.2)
    ax.set_xlim(img_extent[0], img_extent[1])
    ax.set_ylim(img_extent[2], img_extent[3])
    ax.set_title(f"{Path(image_path).name}\n1 arena and {arena.n_holes} holes")
    ax.axis("off")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path
