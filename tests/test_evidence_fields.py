"""ADR 0026 Epic 2 — structured `evidence` on measured review findings.

The compact evidence header renders ONLY from detector-attached structure (never parsed from
prose), so these pin: the measured detectors carry {method, metric, value, required?, unit}
mirroring the number already worded in `detail`; non-measured review findings carry none."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import office_structure as os_  # noqa: E402


def test_review_finding_helper_attaches_evidence_only_when_given():
    plain = os_._review_finding("R1", "1.4.1 Use of Color", "detail")
    assert "evidence" not in plain
    ev = {"method": "structural", "metric": "Contrast", "value": 2.4, "required": 3.0, "unit": ":1"}
    rich = os_._review_finding("R2", "1.4.11 Non-text Contrast", "detail", evidence=ev)
    assert rich["evidence"] == ev


def test_pdf_nontext_contrast_carries_structured_evidence(tmp_path):
    pytest.importorskip("reportlab")
    pytest.importorskip("pdfplumber")
    from reportlab.pdfgen import canvas
    p = tmp_path / "faint.pdf"
    c = canvas.Canvas(str(p), pagesize=(200, 200))
    c.setStrokeColorRGB(0.9, 0.9, 0.9)   # faint border on white fill
    c.setFillColorRGB(1, 1, 1)
    c.rect(30, 30, 120, 80, stroke=1, fill=1)
    c.save()
    f = os_.pdf_nontext_contrast_checks(p)
    assert f and f[0]["evidence"]["method"] == "structural"
    assert f[0]["evidence"]["metric"] == "Contrast"
    assert f[0]["evidence"]["required"] == 3.0
    assert 0 < f[0]["evidence"]["value"] < 3.0
    # the structured value mirrors the prose (same measurement, two forms)
    assert f"{f[0]['evidence']['value']:.1f}:1" in f[0]["detail"] or str(f[0]["evidence"]["value"]) in f[0]["detail"]


def test_text_over_image_has_no_fabricated_evidence(tmp_path):
    """A count-based flag holds no measured value — no evidence dict is honest (ADR 0016)."""
    pytest.importorskip("reportlab")
    pytest.importorskip("PIL")
    from PIL import Image
    from reportlab.pdfgen import canvas
    img = tmp_path / "bg.png"
    Image.new("RGB", (100, 60), (200, 200, 200)).save(img)
    p = tmp_path / "over.pdf"
    c = canvas.Canvas(str(p), pagesize=(300, 300))
    c.drawImage(str(img), 40, 40, width=220, height=120)
    c.setFont("Helvetica", 18)
    c.drawString(60, 90, "TEXT ON THE PICTURE")
    c.save()
    f = os_.pdf_text_over_image_checks(p)
    assert f and "evidence" not in f[0]
