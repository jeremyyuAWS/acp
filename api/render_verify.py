"""ADR 0024 Tier B — render-verified measurement kernel.

Tier A flags "text over a non-solid fill — contrast unknowable from the file". Tier B renders
the page (ADR 0018 seam) and MEASURES the contrast from the actual pixels. This module is the
pure measurement kernel: given a rendered page PNG and a normalized region, it samples the text
ink against the dominant background and returns a real WCAG contrast ratio — or ABSTAINS.

Honesty first (ADR 0016): a guessed contrast over a busy photo is worse than none. So this
returns a ratio ONLY when the pixels support one unambiguously:

  * the region has a genuinely DOMINANT background field (one luminance clusters most of the
    area) — a busy/multicolour background has no single "background" to contrast against → None;
  * a distinct INK cluster exists — a minority of pixels sitting a clear luminance gap away from
    the background (the glyphs) — with mass in a plausible text band → else None;
  * a solid single-colour region (no ink) has nothing to measure → None.

Contrast is the WCAG 2.x ratio `(L1+0.05)/(L2+0.05)` on sRGB relative luminance. Pure Pillow +
stdlib (no numpy, no new dep — rule 8): PNG bytes in, dict|None out, NEVER raises. Unit-tests
against synthetic PNGs, exactly like render.py / geometry.py.
"""
from __future__ import annotations

import io

# The background must own at least this fraction of the region's pixels to count as a single
# field we can contrast against. Below it the background is ambiguous (photo/gradient/multicolour)
# and we abstain rather than pick a "background" colour.
_MIN_BG_FRACTION = 0.55
# The ink cluster must hold at least this fraction (real glyphs cover a small but non-trivial
# slice of a text box) and no more than this fraction (past it, it isn't foreground-on-background).
_MIN_INK_FRACTION = 0.008
_MAX_INK_FRACTION = 0.45
# Ink must sit at least this far in relative luminance from the background to be a distinct
# cluster and not anti-aliasing / JPEG-ish noise around the field colour.
_MIN_INK_GAP = 0.10
# Luminance histogram resolution.
_BINS = 32
# Downsample cap: a page region can be large; contrast statistics are stable well below full res
# and this bounds the work (the render itself is the expensive step, not this).
_MAX_SAMPLE_EDGE = 400


def _srgb_channel_to_linear(c: float) -> float:
    """One sRGB channel in [0,1] → linear light (WCAG relative-luminance definition)."""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


# Precompute the 0..255 → linear map once (256 floats), so per-pixel luminance is table lookups.
_LIN = [_srgb_channel_to_linear(i / 255.0) for i in range(256)]


def _rel_luminance(rgb: tuple[int, int, int]) -> float:
    """sRGB 8-bit triple → WCAG relative luminance in [0,1]."""
    r, g, b = rgb
    return 0.2126 * _LIN[r] + 0.7152 * _LIN[g] + 0.0722 * _LIN[b]


def _contrast(l1: float, l2: float) -> float:
    hi, lo = (l1, l2) if l1 >= l2 else (l2, l1)
    return (hi + 0.05) / (lo + 0.05)


def region_contrast(png_bytes: bytes, bbox: dict | None = None) -> dict | None:
    """Measure the text/background contrast inside `bbox` of a rendered page PNG.

    `bbox` is normalized page fractions `{x,y,w,h}` in [0,1] (the geometry.shape_bbox shape); None
    measures the whole image. Returns a dict on a confident measurement, or None when the pixels
    are too ambiguous to measure honestly (busy background, no ink, degenerate region):

        {"ratio": 2.13, "text_l": 0.12, "bg_l": 0.74,
         "ink_fraction": 0.06, "bg_fraction": 0.71,
         "passes_aa": False, "passes_aa_large": False}

    Never raises — any decode/geometry error degrades to None (the finding stays at its Tier-A 🟡)."""
    try:
        return _region_contrast(png_bytes, bbox)
    except Exception:
        return None


def _region_contrast(png_bytes: bytes, bbox: dict | None) -> dict | None:
    from PIL import Image

    if not png_bytes:
        return None
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    w, h = img.size
    if w == 0 or h == 0:
        return None

    if bbox is not None:
        left = int(round(_clip01(bbox.get("x", 0.0)) * w))
        top = int(round(_clip01(bbox.get("y", 0.0)) * h))
        right = int(round(_clip01(bbox.get("x", 0.0) + bbox.get("w", 0.0)) * w))
        bottom = int(round(_clip01(bbox.get("y", 0.0) + bbox.get("h", 0.0)) * h))
        if right - left < 2 or bottom - top < 2:
            return None
        img = img.crop((left, top, right, bottom))

    # Downsample large regions — NEAREST keeps the true colours (no averaged edge pixels that would
    # invent intermediate luminances between ink and field).
    rw, rh = img.size
    longest = max(rw, rh)
    if longest > _MAX_SAMPLE_EDGE:
        ratio = _MAX_SAMPLE_EDGE / longest
        img = img.resize((max(1, round(rw * ratio)), max(1, round(rh * ratio))), Image.NEAREST)

    raw = img.tobytes()          # RGB, 3 bytes/pixel — avoids the getdata() per-pixel tuple churn
    total = len(raw) // 3
    if total < 16:
        return None

    # Luminance histogram: bin index → [pixel count, summed luminance] to recover each bin's mean L.
    counts = [0] * _BINS
    lsum = [0.0] * _BINS
    lin = _LIN
    scale = _BINS - 1
    for i in range(0, total * 3, 3):
        lum = 0.2126 * lin[raw[i]] + 0.7152 * lin[raw[i + 1]] + 0.0722 * lin[raw[i + 2]]
        b = int(lum * scale + 0.5)
        counts[b] += 1
        lsum[b] += lum

    # Background = the single densest bin. It must be genuinely dominant, else the region has no
    # one background field to measure against and we abstain.
    bg_bin = max(range(_BINS), key=lambda i: counts[i])
    bg_fraction = counts[bg_bin] / total
    if bg_fraction < _MIN_BG_FRACTION:
        return None
    bg_l = lsum[bg_bin] / counts[bg_bin]

    # Ink = the pixels a clear luminance gap away from the background, pooled. Take the far side
    # with the most mass (glyphs are typically all darker, or all lighter, than their field).
    dark_c = light_c = 0
    dark_s = light_s = 0.0
    for i in range(_BINS):
        if not counts[i]:
            continue
        mean_l = lsum[i] / counts[i]
        gap = abs(mean_l - bg_l)
        if gap < _MIN_INK_GAP:
            continue
        if mean_l < bg_l:
            dark_c += counts[i]
            dark_s += lsum[i]
        else:
            light_c += counts[i]
            light_s += lsum[i]

    if dark_c >= light_c:
        ink_c, ink_s = dark_c, dark_s
    else:
        ink_c, ink_s = light_c, light_s
    if ink_c == 0:
        return None
    ink_fraction = ink_c / total
    if ink_fraction < _MIN_INK_FRACTION or ink_fraction > _MAX_INK_FRACTION:
        return None
    text_l = ink_s / ink_c

    ratio = _contrast(text_l, bg_l)
    return {
        "ratio": round(ratio, 2),
        "text_l": round(text_l, 4),
        "bg_l": round(bg_l, 4),
        "ink_fraction": round(ink_fraction, 4),
        "bg_fraction": round(bg_fraction, 4),
        "passes_aa": ratio >= 4.5,          # WCAG 1.4.3 normal text
        "passes_aa_large": ratio >= 3.0,    # WCAG 1.4.3 large text / 1.4.6 relaxed
    }


def _clip01(v: float) -> float:
    v = float(v)
    return 0.0 if v < 0 else (1.0 if v > 1 else v)


def region_text_extent(png_bytes: bytes, bbox: dict | None = None) -> dict | None:
    """How much of `bbox` the text ink already fills — the Tier B.2 measurement for 1.4.4 Resize
    Text. A fixed-size box already >50% full (by height) cannot hold text enlarged to 200%, so the
    fill fraction is the honest headroom signal. Returns the ink's extent as fractions of the
    region, or None when there's no dominant background / too little ink to measure (abstain, never
    a fabricated overflow). Never raises.

        {"height_frac": 0.62, "width_frac": 0.88, "top_frac": 0.10, "bottom_frac": 0.72,
         "ink_fraction": 0.14}
    """
    try:
        return _region_text_extent(png_bytes, bbox)
    except Exception:
        return None


def _region_text_extent(png_bytes: bytes, bbox: dict | None) -> dict | None:
    from PIL import Image

    if not png_bytes:
        return None
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    w, h = img.size
    if w == 0 or h == 0:
        return None
    if bbox is not None:
        left = int(round(_clip01(bbox.get("x", 0.0)) * w))
        top = int(round(_clip01(bbox.get("y", 0.0)) * h))
        right = int(round(_clip01(bbox.get("x", 0.0) + bbox.get("w", 0.0)) * w))
        bottom = int(round(_clip01(bbox.get("y", 0.0) + bbox.get("h", 0.0)) * h))
        if right - left < 4 or bottom - top < 4:
            return None
        img = img.crop((left, top, right, bottom))

    rw, rh = img.size
    longest = max(rw, rh)
    if longest > _MAX_SAMPLE_EDGE:
        r = _MAX_SAMPLE_EDGE / longest
        img = img.resize((max(1, round(rw * r)), max(1, round(rh * r))), Image.NEAREST)
    rw, rh = img.size
    raw = img.tobytes()
    total = rw * rh
    if total < 16:
        return None

    lin = _LIN
    scale = _BINS - 1
    # Pass 1 — background = the dominant luminance bin. Bail if it isn't dominant (a busy image
    # region has no clear text/background split, so an "extent" would be meaningless).
    counts = [0] * _BINS
    lsum = [0.0] * _BINS
    for i in range(0, total * 3, 3):
        lum = 0.2126 * lin[raw[i]] + 0.7152 * lin[raw[i + 1]] + 0.0722 * lin[raw[i + 2]]
        b = int(lum * scale + 0.5)
        counts[b] += 1
        lsum[b] += lum
    bg_bin = max(range(_BINS), key=lambda i: counts[i])
    if counts[bg_bin] / total < _MIN_BG_FRACTION:
        return None
    bg_l = lsum[bg_bin] / counts[bg_bin]

    # Pass 2 — per-row / per-column ink counts (ink = a clear luminance gap from the background).
    row_ink = [0] * rh
    col_ink = [0] * rw
    ink_total = 0
    idx = 0
    for y in range(rh):
        for x in range(rw):
            lum = 0.2126 * lin[raw[idx]] + 0.7152 * lin[raw[idx + 1]] + 0.0722 * lin[raw[idx + 2]]
            idx += 3
            if abs(lum - bg_l) > _MIN_INK_GAP:
                row_ink[y] += 1
                col_ink[x] += 1
                ink_total += 1
    if ink_total / total < _MIN_INK_FRACTION:
        return None

    # Ink bounding box, ignoring rows/cols with only a stray pixel or two (anti-alias speckle).
    row_floor = max(1, int(0.01 * rw))
    col_floor = max(1, int(0.01 * rh))
    rows = [y for y in range(rh) if row_ink[y] >= row_floor]
    cols = [x for x in range(rw) if col_ink[x] >= col_floor]
    if not rows or not cols:
        return None
    top_r, bot_r = rows[0], rows[-1]
    left_c, right_c = cols[0], cols[-1]
    return {
        "height_frac": round((bot_r - top_r + 1) / rh, 4),
        "width_frac": round((right_c - left_c + 1) / rw, 4),
        "top_frac": round(top_r / rh, 4),
        "bottom_frac": round((bot_r + 1) / rh, 4),
        "ink_fraction": round(ink_total / total, 4),
    }


def measure_hybrid_contrast(data: bytes, ext: str, locator: str, *, render_page=None) -> dict:
    """ADR 0024 Tier B.1 composition: for the shape a 1.4.3-hybrid finding names, locate it
    (geometry), render its page (ADR 0018 seam), and measure the contrast (region_contrast).

    Returns an always-shaped result the card can render directly — a MEASURED contrast or an
    honest reason it abstained (each keeps the finding at its Tier-A 🟡, never a certified pass):

        {"measured": True,  "ratio": 2.1, "passes_aa": False, ..., "page": 2, "bbox": {...}}
        {"measured": False, "reason": "geometry_unattributable" | "render_failed" |
                                      "ambiguous_background" | "error"}

    `render_page` is injectable (defaults to render.render_page_png) so the composition unit-tests
    without LibreOffice. Never raises — any failure degrades to `{"measured": False, ...}`."""
    try:
        import geometry as _geom

        bbox = _geom.shape_bbox(data, ext, locator)
        if not bbox:
            return {"measured": False, "reason": "geometry_unattributable"}
        if render_page is None:
            import render as _render
            render_page = _render.render_page_png
        png = render_page(data, ext, bbox.get("page", 1))
        if not png:
            return {"measured": False, "reason": "render_failed"}
        m = region_contrast(png, bbox)
        if not m:
            return {"measured": False, "reason": "ambiguous_background"}
        return {"measured": True, "page": bbox.get("page"), "bbox": bbox, **m}
    except Exception:
        return {"measured": False, "reason": "error"}


def measure_resize_headroom(data: bytes, ext: str, locator: str, *, render_page=None) -> dict:
    """ADR 0024 Tier B.2 composition (1.4.4 Resize Text): render the fixed-size text box and MEASURE
    how much of it the text already fills, so the "does it clip at 200%?" question gets a real
    answer instead of a proxy.

    Enlarging text to 200% needs at least twice the current text height (in fact more, because a
    fixed-width box rewraps into more lines) — so `needed_at_200 = 2 × height_frac` is a LOWER bound
    on the space required. `overflows_at_200` (needed > 1.0) is therefore a confident overflow; when
    it fits the box the card still says "verify" (rewrapping may yet clip). Returns a measured
    result or an honest abstain; never raises, never a certified pass (ADR 0016).

        {"measured": True, "height_frac": 0.62, "needed_at_200": 1.24, "overflows_at_200": True, ...}
        {"measured": False, "reason": "geometry_unattributable"|"render_failed"|"no_text_measured"|"error"}
    """
    try:
        import geometry as _geom

        bbox = _geom.shape_bbox(data, ext, locator)
        if not bbox:
            return {"measured": False, "reason": "geometry_unattributable"}
        if render_page is None:
            import render as _render
            render_page = _render.render_page_png
        png = render_page(data, ext, bbox.get("page", 1))
        if not png:
            return {"measured": False, "reason": "render_failed"}
        ex = region_text_extent(png, bbox)
        if not ex:
            return {"measured": False, "reason": "no_text_measured"}
        hf = ex["height_frac"]
        needed = round(2.0 * hf, 4)
        return {"measured": True, "page": bbox.get("page"), "bbox": bbox,
                "height_frac": hf, "width_frac": ex["width_frac"],
                "needed_at_200": needed, "overflows_at_200": needed > 1.0}
    except Exception:
        return {"measured": False, "reason": "error"}
