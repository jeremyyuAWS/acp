"""ADR 0025 — pdf_text_over_image_checks (1.4.3 Contrast, text-over-image case).

`pdf_contrast_checks` resolves a glyph's background from page structure (fill rects, page default)
and abstains where that can't answer — text laid over a raster image, where the background is the
pixels. This owns that case as a review finding. reportlab draws text over an embedded image
(flags) and plain text on a blank page (doesn't).
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

import pytest

pytest.importorskip("reportlab")
pytest.importorskip("pdfplumber")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import office_structure as os_  # noqa: E402


def _png(tmp: Path) -> Path:
    """Minimal 4x4 grey PNG (no PIL dependency)."""
    p = tmp / "bg.png"
    w = h = 4
    raw = b"".join(b"\x00" + b"\x80\x80\x80\xff" * w for _ in range(h))
    def chunk(typ, data):
        c = typ + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw))
           + chunk(b"IEND", b""))
    p.write_bytes(png)
    return p


def _pdf_text_over_image(tmp: Path) -> Path:
    from reportlab.pdfgen import canvas
    img = _png(tmp)
    p = tmp / "over.pdf"
    c = canvas.Canvas(str(p), pagesize=(300, 300))
    c.drawImage(str(img), 40, 40, width=220, height=120)     # big image block
    c.setFont("Helvetica", 18)
    c.drawString(60, 90, "TEXT ON THE PICTURE")               # sits inside the image
    c.save()
    return p


def _pdf_plain_text(tmp: Path) -> Path:
    from reportlab.pdfgen import canvas
    p = tmp / "plain.pdf"
    c = canvas.Canvas(str(p), pagesize=(300, 300))
    c.setFont("Helvetica", 18)
    c.drawString(40, 200, "plain text, no image")
    c.save()
    return p


def test_text_over_image_flags(tmp_path):
    f = os_.pdf_text_over_image_checks(_pdf_text_over_image(tmp_path))
    assert {x["wcag"] for x in f} == {"1.4.3 Contrast (Minimum)"}
    assert f[0]["severity"] == "REVIEW" and f[0]["advisory"] is True
    assert f[0]["ruleId"] == "PDF_TEXT_OVER_IMAGE"
    # rides the pdf dispatcher
    assert any(x["ruleId"] == "PDF_TEXT_OVER_IMAGE"
               for x in os_.checks_for(_pdf_text_over_image(tmp_path), ".pdf"))


def test_plain_text_not_flagged(tmp_path):
    assert os_.pdf_text_over_image_checks(_pdf_plain_text(tmp_path)) == []


def test_corrupt_pdf_never_raises(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    assert os_.pdf_text_over_image_checks(bad) == []


def test_overlap_frac_helper():
    # char fully inside image → 1.0
    assert os_._bbox_overlap_frac(1, 1, 2, 2, 0, 0, 10, 10) == 1.0
    # disjoint → 0.0
    assert os_._bbox_overlap_frac(20, 20, 21, 21, 0, 0, 10, 10) == 0.0
    # half inside → 0.5
    assert os_._bbox_overlap_frac(0, 0, 2, 1, 1, 0, 10, 10) == pytest.approx(0.5)
