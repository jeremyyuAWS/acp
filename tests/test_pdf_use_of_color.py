"""ADR 0025 Tier A — pdf_use_of_color_checks (1.4.1 Use of Color for PDF).

A hyperlink distinguished only by a chromatic text colour, with no underline, relies on colour
alone. Builds real PDFs with reportlab: a coloured no-underline link flags; an underlined coloured
link and a black link don't. Conservative — abstains on anything it can't read.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

reportlab = pytest.importorskip("reportlab")
pytest.importorskip("pdfplumber")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import office_structure as os_  # noqa: E402


def _pdf_link(tmp: Path, *, coloured: bool, underline: bool) -> Path:
    from reportlab.pdfgen import canvas
    p = tmp / f"link_{coloured}_{underline}.pdf"
    c = canvas.Canvas(str(p), pagesize=(400, 200))
    c.setFont("Helvetica", 12)
    c.setFillColorRGB(0, 0, 0)
    c.drawString(50, 150, "Some body text before the link:")
    x, y, txt = 50, 120, "click here"
    if coloured:
        c.setFillColorRGB(0.0, 0.0, 0.8)
    c.drawString(x, y, txt)
    w = c.stringWidth(txt, "Helvetica", 12)
    if underline:
        c.setStrokeColorRGB(0.0, 0.0, 0.8)
        c.line(x, y - 2, x + w, y - 2)
    c.linkURL("https://example.com", (x, y - 3, x + w, y + 10), relative=0)
    c.save()
    return p


def test_coloured_link_without_underline_flags(tmp_path):
    f = os_.pdf_use_of_color_checks(_pdf_link(tmp_path, coloured=True, underline=False))
    assert {x["wcag"] for x in f} == {"1.4.1 Use of Color"}
    assert f[0]["severity"] == "REVIEW" and f[0]["advisory"] is True
    # dispatcher routes it
    assert any(x["wcag"].startswith("1.4.1")
               for x in os_.checks_for(_pdf_link(tmp_path, coloured=True, underline=False), ".pdf"))


def test_underlined_coloured_link_not_flagged(tmp_path):
    assert os_.pdf_use_of_color_checks(_pdf_link(tmp_path, coloured=True, underline=True)) == []


def test_black_link_not_flagged(tmp_path):
    assert os_.pdf_use_of_color_checks(_pdf_link(tmp_path, coloured=False, underline=False)) == []


def test_corrupt_pdf_never_raises(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    assert os_.pdf_use_of_color_checks(bad) == []


def test_chromatic_helper():
    assert os_._pdf_is_chromatic((0, 0, 0.8)) is True
    assert os_._pdf_is_chromatic((0.2, 0.2, 0.2)) is False   # gray
    assert os_._pdf_is_chromatic(0.0) is False               # grayscale float
    assert os_._pdf_is_chromatic(None) is False
    assert os_._pdf_is_chromatic((0, 0.8, 0, 0)) is True      # CMYK with magenta... (C/M/Y present)
