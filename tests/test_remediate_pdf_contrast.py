"""PDF text-contrast fixer (1.4.3/1.4.6) — deterministic content-stream darkening.

The oracle is the detector itself: office_structure.pdf_contrast_checks flags text
whose fill luma exceeds the AA (0.62) / AAA (0.45) floors, so the round-trip proof is
"detector flags the original → fix → detector finds nothing". Text-scoped by
construction: a shape/background fill must never be darkened (that would invert the
contrast problem), which the shape-safety test pins.
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


def test_capability_table_promoted():
    import remediation_capability as cap
    assert cap.CAPABILITY["pdf"]["1.4.3"] == cap.AUTO
    assert cap.CAPABILITY["pdf"]["1.4.6"] == cap.AUTO
