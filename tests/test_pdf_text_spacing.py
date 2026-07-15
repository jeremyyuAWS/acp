"""ADR 0025 Tier A — pdf_text_spacing_checks (1.4.12 Text Spacing for PDF).

Builds real PDFs with reportlab (a declared dep) at chosen line pitches and asserts the detector
flags genuinely-tight line spacing (< 1.15× font) as an advisory REVIEW, and stays silent on
normal spacing / too-few-lines. Mirrors the reportlab pattern in test_remediate_pdf_contrast.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

reportlab = pytest.importorskip("reportlab")
pytest.importorskip("pdfplumber")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import office_structure as os_  # noqa: E402


def _pdf(tmp: Path, *, font: int, pitch: float, lines: int = 8) -> Path:
    from reportlab.pdfgen import canvas
    p = tmp / f"f{font}_{pitch}.pdf"
    c = canvas.Canvas(str(p))
    c.setFont("Helvetica", font)
    y = 780.0
    for i in range(lines):
        c.drawString(72, y, f"Line {i} of body text on the page for spacing measurement.")
        y -= pitch
    c.save()
    return p


def test_tight_line_spacing_flags(tmp_path):
    # 12pt font, 11pt pitch → 0.92× → cramped.
    f = os_.pdf_text_spacing_checks(_pdf(tmp_path, font=12, pitch=11))
    assert {x["wcag"] for x in f} == {"1.4.12 Text Spacing"}
    assert f[0]["severity"] == "REVIEW" and f[0]["advisory"] is True
    assert "×" in f[0]["detail"]
    # routed through the pdf dispatcher too
    assert any(x["wcag"].startswith("1.4.12") for x in os_.checks_for(_pdf(tmp_path, font=12, pitch=11), ".pdf"))


def test_normal_line_spacing_not_flagged(tmp_path):
    # 12pt font, 18pt pitch → 1.5× → comfortable.
    assert os_.pdf_text_spacing_checks(_pdf(tmp_path, font=12, pitch=18)) == []


def test_too_few_lines_abstains(tmp_path):
    # Only 2 lines — not enough to judge pitch honestly.
    assert os_.pdf_text_spacing_checks(_pdf(tmp_path, font=12, pitch=11, lines=2)) == []


def test_corrupt_pdf_never_raises(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    assert os_.pdf_text_spacing_checks(bad) == []
