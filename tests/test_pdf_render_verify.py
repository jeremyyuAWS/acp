"""ADR 0025 Tier B — pdf_render_verify (render-verified 1.4.3 text-over-image contrast).

Unit tests inject render_page + locators so the composition is deterministic without pdfium; one
integration test exercises the real pdfium path on a reportlab PDF (text over a solid light image).
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import pdf_render_verify as prv  # noqa: E402
import office_structure as os_   # noqa: E402


def _solid_png(rgb, size=120):
    """A solid-colour PNG (PIL) — a non-busy field region_contrast can measure against."""
    pytest.importorskip("PIL")
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (size, size), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([10, 52, 110, 68], fill=rgb)   # ~13% ink band on white → a measurable field
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


LOC = [{"page": 1, "chars": 6, "bbox": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "page": 1}}]


def test_measured_fail_low_contrast():
    png = _solid_png((150, 150, 150))          # mid-grey ink on white ≈ 2.8:1 < 4.5
    r = prv.measure_pdf_over_image_contrast(b"x", render_page=lambda *a: png, locators=LOC)
    assert r["measured"] is True
    assert r["any_fail_aa"] is True
    assert r["worst_ratio"] < 4.5
    assert r["checked"] == 1 and r["total"] == 1


def test_measured_pass_high_contrast():
    png = _solid_png((0, 0, 0))                 # black on white ≈ 21:1
    r = prv.measure_pdf_over_image_contrast(b"x", render_page=lambda *a: png, locators=LOC)
    assert r["measured"] is True
    assert r["any_fail_aa"] is False
    assert r["worst_ratio"] > 4.5


def test_no_text_over_image():
    r = prv.measure_pdf_over_image_contrast(b"x", render_page=lambda *a: b"", locators=[])
    assert r == {"measured": False, "reason": "no_text_over_image"}


def test_render_failure_reported_honestly():
    r = prv.measure_pdf_over_image_contrast(b"x", render_page=lambda *a: None, locators=LOC)
    assert r["measured"] is False and r["reason"] == "render_failed"
    assert r["checked"] == 1 and r["total"] == 1


def test_ambiguous_when_no_field():
    pytest.importorskip("PIL")
    from PIL import Image
    img = Image.new("RGB", (60, 60))
    img.putdata([(i * 37 % 256, i * 53 % 256, i * 71 % 256) for i in range(60 * 60)])  # busy noise
    buf = io.BytesIO()
    img.save(buf, "PNG")
    r = prv.measure_pdf_over_image_contrast(b"x", render_page=lambda *a: buf.getvalue(), locators=LOC)
    assert r["measured"] is False and r["reason"] == "ambiguous_background"


def test_error_degrades():
    def boom(*a): raise RuntimeError("nope")
    r = prv.measure_pdf_over_image_contrast(b"x", render_page=boom, locators=LOC)
    assert r["measured"] is False and r["reason"] == "error"


# ── integration: real pdfium render on a reportlab PDF ─────────────────────────
def _pdf_text_over_solid_image(tmp: Path) -> bytes:
    pytest.importorskip("reportlab")
    pytest.importorskip("pdfplumber")
    from PIL import Image
    from reportlab.pdfgen import canvas
    img_path = tmp / "bg.png"
    Image.new("RGB", (200, 120), (210, 210, 210)).save(img_path)   # solid light-grey block
    p = tmp / "over.pdf"
    c = canvas.Canvas(str(p), pagesize=(300, 300))
    c.drawImage(str(img_path), 40, 120, width=220, height=120)
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 20)
    c.drawString(60, 170, "OVER THE IMAGE")
    c.save()
    return p.read_bytes()


def test_locators_from_real_pdf(tmp_path):
    data = _pdf_text_over_solid_image(tmp_path)
    runs = os_.pdf_over_image_locators(data)
    assert runs, "expected at least one over-image text run"
    b = runs[0]["bbox"]
    assert 0 <= b["x"] <= 1 and 0 <= b["y"] <= 1 and 0 < b["w"] <= 1 and 0 < b["h"] <= 1
    assert b["page"] == 1


def test_real_pdfium_measure_or_graceful(tmp_path):
    pytest.importorskip("pypdfium2")
    data = _pdf_text_over_solid_image(tmp_path)
    r = prv.measure_pdf_over_image_contrast(data)     # real render_page_png
    assert isinstance(r, dict) and "measured" in r
    if r["measured"]:
        assert isinstance(r["worst_ratio"], (int, float)) and r["worst_ratio"] > 0
    else:
        assert r["reason"] in {"ambiguous_background", "render_failed", "no_text_over_image"}
