"""ADR 0025 — pdf_nontext_contrast_checks (1.4.11 Non-text Contrast for PDF).

The PDF analogue of the docx/pptx solid outline-on-fill check: the lowest-contrast bordered
rectangle (its stroke colour vs its own fill, < 3:1). reportlab draws a faint-bordered rect
(flags) and a high-contrast one (doesn't).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

reportlab = pytest.importorskip("reportlab")
pytest.importorskip("pdfplumber")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import office_structure as os_  # noqa: E402


def _pdf_rect(tmp: Path, *, stroke, fill) -> Path:
    from reportlab.pdfgen import canvas
    p = tmp / f"rect_{stroke}_{fill}.pdf"
    c = canvas.Canvas(str(p), pagesize=(300, 300))
    c.setStrokeColorRGB(*stroke)
    c.setFillColorRGB(*fill)
    c.rect(50, 50, 200, 150, stroke=1, fill=1)
    c.save()
    return p


def test_faint_border_on_fill_flags(tmp_path):
    # near-white stroke on white fill → ~1:1.
    f = os_.pdf_nontext_contrast_checks(_pdf_rect(tmp_path, stroke=(0.93, 0.93, 0.93), fill=(1, 1, 1)))
    assert {x["wcag"] for x in f} == {"1.4.11 Non-text Contrast"}
    assert f[0]["severity"] == "REVIEW" and f[0]["advisory"] is True
    assert "3:1" in f[0]["detail"]
    assert any(x["wcag"].startswith("1.4.11")
               for x in os_.checks_for(_pdf_rect(tmp_path, stroke=(0.93, 0.93, 0.93), fill=(1, 1, 1)), ".pdf"))


def test_high_contrast_border_not_flagged(tmp_path):
    assert os_.pdf_nontext_contrast_checks(_pdf_rect(tmp_path, stroke=(0, 0, 0), fill=(1, 1, 1))) == []


def test_corrupt_pdf_never_raises(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    assert os_.pdf_nontext_contrast_checks(bad) == []


def test_color_hex_helper():
    assert os_._pdf_color_hex((1, 1, 1)) == "FFFFFF"
    assert os_._pdf_color_hex(0.0) == "000000"
    assert os_._pdf_color_hex((0, 0, 0, 0)) == "FFFFFF"   # CMYK all-zero = white
    assert os_._pdf_color_hex(None) is None
