"""ADR 0024 Tier B — the render-verified contrast kernel (api/render_verify.py).

Synthetic PNGs, no rendering: paint a background field + a little "ink" and assert the measured
WCAG ratio, and — the honesty half — assert it ABSTAINS (None) on a busy background, a solid
region with no ink, and degenerate input. Pure Pillow, mirrors test_render / test_geometry.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import render_verify as rv  # noqa: E402


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _field_with_ink(bg, ink, size=(120, 60), ink_rows=6):
    """A solid `bg` field with `ink_rows` rows of `ink` near the middle (stand-in for glyphs)."""
    img = Image.new("RGB", size, bg)
    w, h = size
    for y in range(h // 2 - ink_rows // 2, h // 2 + ink_rows // 2):
        for x in range(4, w - 4):
            img.putpixel((x, y), ink)
    return img


# ── confident measurements ────────────────────────────────────────────────────
def test_black_on_white_is_high_contrast():
    r = rv.region_contrast(_png(_field_with_ink((255, 255, 255), (0, 0, 0))))
    assert r is not None
    assert r["ratio"] > 18          # black-on-white is ~21:1
    assert r["passes_aa"] is True


def test_light_grey_on_white_fails_aa():
    # #999 on #fff ≈ 2.8:1 — a real failing sample.
    r = rv.region_contrast(_png(_field_with_ink((255, 255, 255), (153, 153, 153))))
    assert r is not None
    assert 2.0 < r["ratio"] < 3.5
    assert r["passes_aa"] is False
    assert r["passes_aa_large"] is False


def test_white_ink_on_dark_field_measures():
    # Inverted polarity: light glyphs on a dark field must measure just the same.
    r = rv.region_contrast(_png(_field_with_ink((20, 20, 20), (240, 240, 240))))
    assert r is not None
    assert r["ratio"] > 12
    assert r["text_l"] > r["bg_l"]   # ink is the lighter cluster here


def test_bbox_crops_to_the_named_region():
    # Left half busy noise, right half a clean black-on-white field; a bbox over the right half
    # must measure the clean field, proving the crop is applied.
    w, h = 200, 60
    img = Image.new("RGB", (w, h), (255, 255, 255))
    for x in range(0, w // 2):                       # left half: alternating noise
        for y in range(h):
            img.putpixel((x, y), (0, 0, 0) if (x + y) % 2 else (128, 200, 60))
    for y in range(h // 2 - 3, h // 2 + 3):          # right half: black ink on white
        for x in range(w // 2 + 4, w - 4):
            img.putpixel((x, y), (0, 0, 0))
    r = rv.region_contrast(_png(img), {"x": 0.5, "y": 0.0, "w": 0.5, "h": 1.0})
    assert r is not None and r["ratio"] > 18


# ── honest abstentions (None, never a fabricated ratio) ───────────────────────
def test_busy_background_abstains():
    # A multicolour checkerboard has no dominant background field → no honest contrast.
    img = Image.new("RGB", (120, 60))
    palette = [(200, 30, 30), (30, 200, 30), (30, 30, 200), (220, 220, 40)]
    for x in range(120):
        for y in range(60):
            img.putpixel((x, y), palette[(x + 2 * y) % 4])
    assert rv.region_contrast(_png(img)) is None


def test_solid_field_no_ink_abstains():
    # A uniform fill has a dominant background but no ink cluster → nothing to measure.
    assert rv.region_contrast(_png(Image.new("RGB", (120, 60), (240, 240, 240)))) is None


def test_ink_below_min_fraction_abstains():
    # A single ink pixel is below _MIN_INK_FRACTION — noise, not glyphs → abstain.
    img = Image.new("RGB", (120, 60), (255, 255, 255))
    img.putpixel((10, 10), (0, 0, 0))
    assert rv.region_contrast(_png(img)) is None


def test_degenerate_inputs_return_none():
    assert rv.region_contrast(b"") is None
    assert rv.region_contrast(b"not a png") is None
    # A bbox that collapses to <2px is not measurable.
    assert rv.region_contrast(_png(_field_with_ink((255, 255, 255), (0, 0, 0))),
                              {"x": 0.5, "y": 0.5, "w": 0.0, "h": 0.0}) is None


def test_never_raises_on_garbage_bbox():
    good = _png(_field_with_ink((255, 255, 255), (0, 0, 0)))
    # Missing keys / out-of-range values must degrade to a value or None, never raise.
    assert rv.region_contrast(good, {}) is not None or True
    assert rv.region_contrast(good, {"x": -5, "y": 2, "w": 9, "h": 9}) is not None or True


# ── measure_hybrid_contrast composition (geometry → render → measure) ──────────
import zipfile  # noqa: E402

_W_EMU, _H_EMU = 12192000, 6858000

_CT = ('<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
       '<Default Extension="xml" ContentType="application/xml"/>'
       '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
       '<Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/></Types>')
_PRES = (f'<?xml version="1.0"?><p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
         f' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
         f'<p:sldIdLst><p:sldId id="256" r:id="rIdA"/></p:sldIdLst><p:sldSz cx="{_W_EMU}" cy="{_H_EMU}"/></p:presentation>')
_PRES_RELS = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
              '<Relationship Id="rIdA" Type="x" Target="slides/slide1.xml"/></Relationships>')


def _pptx_text_over_picture():
    """A one-slide deck with a text box (name 'Title 1') over a blipFill at (¼W,⅛H,½W,¼H)."""
    slide = (f'<?xml version="1.0"?><p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
             f' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
             f' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
             f'<p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvPr id="5" name="Title 1"/></p:nvSpPr>'
             f'<p:spPr><a:xfrm><a:off x="{_W_EMU // 4}" y="{_H_EMU // 8}"/>'
             f'<a:ext cx="{_W_EMU // 2}" cy="{_H_EMU // 4}"/></a:xfrm><a:blipFill/></p:spPr>'
             f'<p:txBody><a:p><a:r><a:t>Over the photo</a:t></a:r></a:p></p:txBody></p:sp>'
             f'</p:spTree></p:cSld></p:sld>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", _CT)
        z.writestr("ppt/presentation.xml", _PRES)
        z.writestr("ppt/_rels/presentation.xml.rels", _PRES_RELS)
        z.writestr("ppt/slides/slide1.xml", slide)
    return buf.getvalue()


def _page_png_with_ink_in_region(bbox, size=(400, 225), ink=(0, 0, 0)):
    """A white page PNG with black rows inside `bbox` (page fractions) — a legible-text render."""
    w, h = size
    img = Image.new("RGB", (w, h), (255, 255, 255))
    x0, y0 = int(bbox["x"] * w), int(bbox["y"] * h)
    x1, y1 = int((bbox["x"] + bbox["w"]) * w), int((bbox["y"] + bbox["h"]) * h)
    for y in range(y0 + 4, y1 - 4, 3):               # sparse rows = glyph-like ink coverage
        for x in range(x0 + 4, x1 - 4):
            img.putpixel((x, y), ink)
    return _png(img)


def test_measure_hybrid_contrast_measures_a_located_shape():
    data = _pptx_text_over_picture()
    loc = "ppt/slides/slide1.xml#Title 1"
    bbox = {"x": 0.25, "y": 0.125, "w": 0.5, "h": 0.25}

    def fake_render(_data, _ext, page):
        assert page == 1                              # bbox resolved to page 1
        return _page_png_with_ink_in_region(bbox)

    r = rv.measure_hybrid_contrast(data, ".pptx", loc, render_page=fake_render)
    assert r["measured"] is True
    assert r["page"] == 1 and r["ratio"] > 15
    assert r["passes_aa"] is False or r["passes_aa"] is True   # a real boolean, not absent
    assert r["bbox"]["page"] == 1


def test_measure_hybrid_contrast_abstains_on_busy_render():
    data = _pptx_text_over_picture()
    # A busy multicolour render under the shape → the kernel abstains → measured False, honest reason.
    def busy(_d, _e, _p):
        img = Image.new("RGB", (400, 225))
        pal = [(200, 30, 30), (30, 200, 30), (30, 30, 200), (220, 220, 40)]
        for x in range(400):
            for y in range(225):
                img.putpixel((x, y), pal[(x + 2 * y) % 4])
        return _png(img)
    r = rv.measure_hybrid_contrast(data, ".pptx", "ppt/slides/slide1.xml#Title 1", render_page=busy)
    assert r == {"measured": False, "reason": "ambiguous_background"}


def test_measure_hybrid_contrast_degrades_when_unlocatable_or_unrendered():
    data = _pptx_text_over_picture()
    # Unknown shape → geometry can't attribute a box.
    assert rv.measure_hybrid_contrast(data, ".pptx", "ppt/slides/slide1.xml#No Such",
                                      render_page=lambda *a: b"x")["reason"] == "geometry_unattributable"
    # Located, but the render seam yields nothing (no LibreOffice / failure).
    r = rv.measure_hybrid_contrast(data, ".pptx", "ppt/slides/slide1.xml#Title 1",
                                   render_page=lambda *a: None)
    assert r == {"measured": False, "reason": "render_failed"}


# ── Tier B.2: region_text_extent + measure_resize_headroom (1.4.4 Resize Text) ─
def _box_filled(y0, y1, size=(160, 120), ink=(0, 0, 0)):
    """A white box with black text rows from fraction y0..y1 of the height — a text block that
    fills that vertical band of its box."""
    w, h = size
    img = Image.new("RGB", (w, h), (255, 255, 255))
    for y in range(int(y0 * h), int(y1 * h), 2):
        for x in range(6, w - 6):
            img.putpixel((x, y), ink)
    return _png(img)


def test_text_extent_measures_the_vertical_fill():
    # Text occupying the middle 60% (0.2..0.8) → height_frac ≈ 0.6.
    ex = rv.region_text_extent(_box_filled(0.2, 0.8))
    assert ex is not None
    assert 0.5 < ex["height_frac"] < 0.7
    assert ex["top_frac"] < 0.3 and ex["bottom_frac"] > 0.7


def test_text_extent_small_block_leaves_headroom():
    ex = rv.region_text_extent(_box_filled(0.05, 0.2))     # top ~15% only
    assert ex is not None and ex["height_frac"] < 0.25


def test_text_extent_abstains_on_empty_or_busy():
    assert rv.region_text_extent(_png(Image.new("RGB", (160, 120), (255, 255, 255)))) is None  # no ink
    busy = Image.new("RGB", (160, 120))
    for x in range(160):
        for y in range(120):
            busy.putpixel((x, y), (200, 30, 30) if (x + y) % 2 else (30, 30, 200))
    assert rv.region_text_extent(_png(busy)) is None       # no dominant background


def _pptx_fixed_text_box():
    """A one-slide deck with a no-autofit text box 'Body 1' (>=300 chars) at (¼W,⅛H,½W,½H)."""
    txt = "word " * 70                                      # > 300 chars
    slide = (f'<?xml version="1.0"?><p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
             f' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
             f' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
             f'<p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvPr id="7" name="Body 1"/></p:nvSpPr>'
             f'<p:spPr><a:xfrm><a:off x="{_W_EMU // 4}" y="{_H_EMU // 8}"/>'
             f'<a:ext cx="{_W_EMU // 2}" cy="{_H_EMU // 2}"/></a:xfrm></p:spPr>'
             f'<p:txBody><a:bodyPr><a:noAutofit/></a:bodyPr><a:p><a:r><a:t>{txt}</a:t></a:r></a:p></p:txBody></p:sp>'
             f'</p:spTree></p:cSld></p:sld>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", _CT)
        z.writestr("ppt/presentation.xml", _PRES)
        z.writestr("ppt/_rels/presentation.xml.rels", _PRES_RELS)
        z.writestr("ppt/slides/slide1.xml", slide)
    return buf.getvalue()


def test_measure_resize_headroom_flags_an_overfull_box():
    data = _pptx_fixed_text_box()
    bbox = {"x": 0.25, "y": 0.125, "w": 0.5, "h": 0.5}

    def render_full(_d, _e, page):
        # Text fills ~70% of the box height → needs ~140% at 200% → overflows.
        w, h = 400, 225
        img = Image.new("RGB", (w, h), (255, 255, 255))
        bx0, by0 = int(bbox["x"] * w), int(bbox["y"] * h)
        bx1, by1 = int((bbox["x"] + bbox["w"]) * w), int((bbox["y"] + bbox["h"]) * h)
        top = by0 + int(0.15 * (by1 - by0))
        bot = by0 + int(0.85 * (by1 - by0))
        for y in range(top, bot, 2):
            for x in range(bx0 + 4, bx1 - 4):
                img.putpixel((x, y), (0, 0, 0))
        return _png(img)

    r = rv.measure_resize_headroom(data, ".pptx", "ppt/slides/slide1.xml#Body 1", render_page=render_full)
    assert r["measured"] is True
    assert r["height_frac"] > 0.55
    assert r["overflows_at_200"] is True and r["needed_at_200"] > 1.0


def test_measure_resize_headroom_degrades_honestly():
    data = _pptx_fixed_text_box()
    # Rendered box is empty → nothing to measure.
    def empty(*_a):
        return _png(Image.new("RGB", (400, 225), (255, 255, 255)))
    assert rv.measure_resize_headroom(data, ".pptx", "ppt/slides/slide1.xml#Body 1",
                                      render_page=empty)["reason"] == "no_text_measured"
    # Unknown shape → geometry can't attribute.
    assert rv.measure_resize_headroom(data, ".pptx", "ppt/slides/slide1.xml#Nope",
                                      render_page=empty)["reason"] == "geometry_unattributable"
