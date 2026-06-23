"""Shared text-region style probe (skill code, not third-party OCR).

PaddleOCR returns text + box + confidence. It does NOT return color, font, or
size. The skill recovers those from the original image. The old
helpers assumed "text is always dark ink on a light background" (they filtered
`sum(rgb) < 600` or `luminance < 150` as ink), so light text on a dark
background (e.g. white chalk on a green board) was filtered out and the sampled
"text color" became the dark background -> invisible after rebuild.

This module replaces that with a polarity-agnostic foreground separation:
estimate the background luminance from the box border ring, then treat pixels
whose luminance is FAR from the background as ink, regardless of whether the
ink is lighter or darker than the background. Color and glyph height are both
derived from that same foreground mask so the two failure domains stay in one
place. Used by both `ocr_paddle_worker.py` and `pdf_to_ppt_simple.py`.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image

_LUMA = np.array([0.299, 0.587, 0.114], dtype=np.float32)
_DEFAULT = "#111111"


def _foreground_mask(arr: np.ndarray) -> tuple[np.ndarray, float]:
    """Return (ink_mask, bg_luminance) without assuming ink polarity."""
    h, w = arr.shape[:2]
    lum = arr @ _LUMA
    if h >= 3 and w >= 3:
        border = np.concatenate([lum[0, :], lum[-1, :], lum[:, 0], lum[:, -1]])
    else:
        border = lum.reshape(-1)
    bg_lum = float(np.median(border))
    dist = np.abs(lum - bg_lum)
    mx = float(dist.max()) if dist.size else 0.0
    if mx < 8.0:  # near-uniform crop: no reliable ink signal
        return np.zeros((h, w), dtype=bool), bg_lum
    thr = max(mx * 0.5, float(np.percentile(dist, 80)))
    return dist >= thr, bg_lum


def analyze_text_region(
    image: Image.Image, box: tuple[int, int, int, int]
) -> dict[str, Any]:
    """Recover ink color, polarity, glyph height and ink density for a text box."""
    x1, y1, x2, y2 = box
    crop = image.crop((x1, y1, x2, y2)).convert("RGB")
    if crop.width <= 0 or crop.height <= 0:
        return {
            "color": _DEFAULT,
            "is_light_on_dark": False,
            "glyph_height": 0.0,
            "ink_density": 0.0,
        }
    arr = np.asarray(crop, dtype=np.float32)
    mask, bg_lum = _foreground_mask(arr)
    fg = arr[mask]
    if fg.shape[0] < 4:
        # too little ink detected: fall back to the most-distant pixels so we
        # still return a real foreground color rather than the background.
        lum = (arr @ _LUMA).reshape(-1)
        dist = np.abs(lum - bg_lum)
        if dist.size == 0:
            return {
                "color": _DEFAULT,
                "is_light_on_dark": False,
                "glyph_height": 0.0,
                "ink_density": 0.0,
            }
        k = max(4, int(dist.size * 0.12))
        idx = np.argsort(dist)[-k:]
        fg = arr.reshape(-1, 3)[idx]
    avg = fg.mean(axis=0)
    r, g, b = (max(0, min(255, int(round(float(c))))) for c in avg)
    fg_lum = float(avg @ _LUMA)
    ys, xs = np.where(mask)
    glyph_height = float(ys.max() - ys.min() + 1) if ys.size else 0.0
    glyph_width = float(xs.max() - xs.min() + 1) if xs.size else 0.0
    # density measured inside the tight ink bounding box, polarity-agnostic.
    if ys.size:
        tight = mask[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
        tight_density = float(tight.mean())
    else:
        tight_density = 0.0
    return {
        "color": f"#{r:02X}{g:02X}{b:02X}",
        "is_light_on_dark": fg_lum > bg_lum,
        "glyph_height": glyph_height,
        "glyph_width": glyph_width,
        "ink_density": float(mask.mean()),
        "tight_ink_density": tight_density,
    }


def text_color_from_region(
    image: Image.Image, box: tuple[int, int, int, int]
) -> str:
    """Polarity-agnostic text color. Drop-in replacement for the old helper."""
    return analyze_text_region(image, box)["color"]
