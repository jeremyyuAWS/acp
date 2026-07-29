"""PDF text-contrast fixer (1.4.3/1.4.6) — deterministic content-stream recolouring.

The oracle is the detector itself: office_structure.pdf_contrast_checks measures each
glyph's colour against the background structurally resolved behind it, so the round-trip
proof is "detector flags the original → fix → detector finds nothing". Text-scoped by
construction: a shape/background fill must never be recoloured (that would invert the
contrast problem), which the shape-safety test pins.

This fixer runs UNATTENDED, so the tests that matter most are the ones proving what it
leaves alone. It used to inherit the detector's white-page assumption and darken any text
above a luma floor, which turned compliant dark-theme documents non-compliant with no
human in the loop — white-on-black went from 21:1 to #666666 at 3.66:1, an AA failure.
`test_white_text_on_*` pin that; `test_dark_page_text_is_lightened_not_darkened` pins the
positive half (on a dark page the fix is to move AWAY from the background, not toward it).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import office_structure as os_  # noqa: E402
import remediate_pdf as rp  # noqa: E402

reportlab = pytest.importorskip("reportlab")
pikepdf = pytest.importorskip("pikepdf")


def _pdf_with(tmp: Path, draw) -> Path:
    from reportlab.pdfgen import canvas
    p = tmp / "doc.pdf"
    c = canvas.Canvas(str(p))
    draw(c)
    c.save()
    return p


def _fix(src: Path) -> Path:
    out = src.with_name("fixed.pdf")
    with pikepdf.open(str(src)) as pdf:
        n = rp._fix_pdf_text_contrast(pdf)
        assert n > 0
        pdf.save(str(out))
    return out


def test_light_text_darkened_until_detector_clears(tmp_path):
    from reportlab.lib.colors import Color
    def draw(c):
        c.setFillColor(Color(0.8, 0.8, 0.8))
        c.drawString(72, 650, "Light grey text is low contrast")
    src = _pdf_with(tmp_path, draw)
    assert {f["ruleId"] for f in os_.pdf_contrast_checks(src)} == {
        "PDF_LOW_CONTRAST_AA", "PDF_LOW_CONTRAST_AAA"}
    fixed = _fix(src)
    assert os_.pdf_contrast_checks(fixed) == []          # the round-trip proof


def test_light_gray_operator_and_rgb_hue_preserved(tmp_path):
    from reportlab.lib.colors import Color
    def draw(c):
        c.setFillGray(0.75)                              # DeviceGray `g` operator
        c.drawString(72, 700, "gray-op text that is too light to read comfortably")
        c.setFillColor(Color(0.9, 0.6, 0.6))             # light red — hue must survive
        c.drawString(72, 650, "light red text that also fails the contrast floor")
    fixed = _fix(_pdf_with(tmp_path, draw))
    assert os_.pdf_contrast_checks(fixed) == []
    import pdfplumber
    with pdfplumber.open(str(fixed)) as pdf:
        reds = [ch["non_stroking_color"] for ch in pdf.pages[0].chars
                if isinstance(ch.get("non_stroking_color"), (tuple, list))
                and len(ch["non_stroking_color"]) == 3]
    r, g, b = reds[-1]
    assert r > g and abs(g - b) < 1e-6                   # scaled together — still red-ish


def test_shape_fills_never_touched(tmp_path):
    from reportlab.lib.colors import Color
    LIGHT = (0.9, 0.9, 0.5)
    def draw(c):
        c.setFillColor(Color(*LIGHT))                    # light yellow BACKGROUND rect
        c.rect(50, 500, 300, 200, stroke=0, fill=1)
        c.setFillColor(Color(0, 0, 0))
        c.drawString(72, 600, "black text on the yellow panel is fine")
    src = _pdf_with(tmp_path, draw)
    out = src.with_name("fixed.pdf")
    with pikepdf.open(str(src)) as pdf:
        assert rp._fix_pdf_text_contrast(pdf) == 0       # nothing text-coloured is light
        pdf.save(str(out))
    import pdfplumber
    with pdfplumber.open(str(out)) as pdf:
        rects = pdf.pages[0].rects
    assert rects and tuple(round(v, 2) for v in rects[0]["non_stroking_color"]) == LIGHT


def test_dark_text_untouched(tmp_path):
    from reportlab.lib.colors import Color
    def draw(c):
        c.setFillColor(Color(0.1, 0.1, 0.1))
        c.drawString(72, 700, "Dark text is already readable")
    src = _pdf_with(tmp_path, draw)
    with pikepdf.open(str(src)) as pdf:
        assert rp._fix_pdf_text_contrast(pdf) == 0


# ── what the fixer must NOT touch: text that already passes on its real background ──

def _rgb(*channels):
    from reportlab.lib.colors import Color
    return Color(*(v / 255 for v in channels))


def _text_colours(path: Path) -> list[str]:
    import office_structure as _os
    import pdfplumber
    with pdfplumber.open(str(path)) as pdf:
        return [_os._pdf_color_hex(ch["non_stroking_color"]) for ch in pdf.pages[0].chars]


def _fix_count(src: Path) -> tuple[int, Path]:
    out = src.with_name("fixed.pdf")
    with pikepdf.open(str(src)) as pdf:
        n = rp._fix_pdf_text_contrast(pdf)
        pdf.save(str(out))
    return n, out


def test_white_text_on_dark_panel_left_alone(tmp_path):
    """21:1 — passes AA and AAA. The white-page model rewrote it to a 3.66:1 AA FAILURE."""
    def draw(c):
        c.setFillColor(_rgb(0, 0, 0))
        c.rect(50, 50, 500, 700, stroke=0, fill=1)
        c.setFillColor(_rgb(255, 255, 255))
        c.drawString(72, 400, "White text on a black panel")
    src = _pdf_with(tmp_path, draw)
    n, out = _fix_count(src)
    assert n == 0
    assert "FFFFFF" in _text_colours(out)
    assert os_.pdf_contrast_checks(out) == []


def test_white_text_on_full_page_dark_fill_left_alone(tmp_path):
    """The dark-cover variant of the same defect."""
    def draw(c):
        c.setFillColor(_rgb(0x10, 0x1C, 0x3A))
        c.rect(0, 0, 612, 792, stroke=0, fill=1)
        c.setFillColor(_rgb(255, 255, 255))
        c.drawString(72, 400, "White text on a navy cover")
    n, out = _fix_count(_pdf_with(tmp_path, draw))
    assert n == 0 and "FFFFFF" in _text_colours(out)


def test_dark_page_text_is_lightened_not_darkened(tmp_path):
    """#4C4C4C on #262626 is 1.76:1 — a real failure whose only fix is a LIGHTER text
    colour. Darkening toward black is the one move that makes it worse."""
    def draw(c):
        c.setFillColor(_rgb(0x26, 0x26, 0x26))
        c.rect(0, 0, 612, 792, stroke=0, fill=1)
        c.setFillColor(_rgb(0x4C, 0x4C, 0x4C))
        c.drawString(72, 400, "Dark grey on a dark grey page")
    src = _pdf_with(tmp_path, draw)
    assert "PDF_LOW_CONTRAST_AA" in {f["ruleId"] for f in os_.pdf_contrast_checks(src)}
    n, out = _fix_count(src)
    assert n == 1
    new = [h for h in _text_colours(out) if h != "262626"][0]
    assert os_._contrast_ratio(new, "262626") > os_._contrast_ratio("4C4C4C", "262626")
    assert os_.pdf_contrast_checks(out) == []


def test_same_colour_on_light_and_dark_backgrounds_abstains(tmp_path):
    """One body-text colour shared between a white page and a dark-grey callout box: no
    colour clears 4.5:1 on both #FFFFFF and #333333, so no fix is claimed and the finding
    routes to a human rather than being "fixed" into a failure on one of the two."""
    def draw(c):
        c.setFillColor(_rgb(0x33, 0x33, 0x33))
        c.rect(50, 500, 500, 200, stroke=0, fill=1)
        c.setFillColor(_rgb(0x80, 0x80, 0x80))
        c.drawString(72, 560, "mid grey inside the dark callout")
        c.drawString(72, 300, "the same mid grey on the white page")
    src = _pdf_with(tmp_path, draw)
    n, out = _fix_count(src)
    assert n == 0
    assert set(_text_colours(out)) <= {"808080", "333333"}
    assert os_.pdf_contrast_checks(out)          # still reported, not silently "fixed"


def test_capability_table_promoted():
    import remediation_capability as cap
    assert cap.mode_for("pdf", "1.4.3") == cap.AUTO
    assert cap.mode_for("pdf", "1.4.6") == cap.AUTO
