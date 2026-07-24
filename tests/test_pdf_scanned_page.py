"""1.4.5 Images of Text (Review) for PDF — pdf_scanned_page_checks.

A cheap, deterministic pre-OCR heuristic (ADR 0025 style): near-zero extractable text on a
page, plus one image covering most of the page, reads as a scanned photocopy. Distinct from
ocr.py's images_of_text (which needs the OCR stack), this needs neither — reportlab draws a
full-page image with no text (flags) and plain extractable text (doesn't).
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


def _png(tmp: Path, name: str = "page.png") -> Path:
    """Minimal 4x4 grey PNG (no PIL dependency)."""
    p = tmp / name
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


def _pdf_full_page_scan(tmp: Path) -> Path:
    """One page, no extractable text, a single image covering the whole page — the classic
    scanned-photocopy shape."""
    from reportlab.pdfgen import canvas
    img = _png(tmp)
    p = tmp / "scan.pdf"
    c = canvas.Canvas(str(p), pagesize=(300, 300))
    c.drawImage(str(img), 0, 0, width=300, height=300)   # covers the entire page, no text at all
    c.save()
    return p


def _pdf_plain_text(tmp: Path) -> Path:
    from reportlab.pdfgen import canvas
    p = tmp / "plain.pdf"
    c = canvas.Canvas(str(p), pagesize=(300, 300))
    c.setFont("Helvetica", 18)
    c.drawString(40, 200, "This page has a real extractable text layer, not a scanned image.")
    c.save()
    return p


def _pdf_small_image_with_text(tmp: Path) -> Path:
    """A page with plenty of real text AND a small incidental image (e.g. a logo) — the image
    doesn't dominate the page, so this must not fire."""
    from reportlab.pdfgen import canvas
    img = _png(tmp, "logo.png")
    p = tmp / "logo.pdf"
    c = canvas.Canvas(str(p), pagesize=(300, 300))
    c.setFont("Helvetica", 14)
    c.drawString(20, 260, "A perfectly normal born-digital page of real text.")
    c.drawImage(str(img), 10, 10, width=20, height=20)   # small logo, ~0.4% of the page
    c.save()
    return p


def test_full_page_scan_flags(tmp_path):
    f = os_.pdf_scanned_page_checks(_pdf_full_page_scan(tmp_path))
    assert {x["wcag"] for x in f} == {"1.4.5 Images of Text"}
    assert f[0]["severity"] == "REVIEW" and f[0]["advisory"] is True
    assert f[0]["ruleId"] == "PDF_LIKELY_SCANNED"
    # rides the pdf dispatcher
    assert any(x["ruleId"] == "PDF_LIKELY_SCANNED"
               for x in os_.checks_for(_pdf_full_page_scan(tmp_path), ".pdf"))


def test_plain_text_not_flagged(tmp_path):
    assert os_.pdf_scanned_page_checks(_pdf_plain_text(tmp_path)) == []


def test_small_incidental_image_with_text_not_flagged(tmp_path):
    assert os_.pdf_scanned_page_checks(_pdf_small_image_with_text(tmp_path)) == []


def test_corrupt_pdf_never_raises(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    assert os_.pdf_scanned_page_checks(bad) == []
