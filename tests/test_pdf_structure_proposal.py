"""PDF 1.3.1 structure-map proposal — the untagged-PDF dead end becomes an assisted card.

Tags can't be auto-written safely (re-authoring), but the document's heading hierarchy IS
machine-derivable from its font sizes. The proposal hands a reviewer the structure map to
confirm; the approved map is the tagging instruction + compliance evidence. Deterministic
(font-size rank via infer_heading_levels) and self-gating — a tagged or heading-less PDF
yields nothing, never a fabricated structure (ADR 0016).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import remediate_pdf as rp  # noqa: E402

reportlab = pytest.importorskip("reportlab")
pikepdf = pytest.importorskip("pikepdf")


def _pdf(tmp: Path, *, headings=True) -> Path:
    from reportlab.pdfgen import canvas
    p = tmp / "doc.pdf"
    c = canvas.Canvas(str(p))
    if headings:
        c.setFont("Helvetica-Bold", 24)
        c.drawString(72, 750, "Discharge Instructions")
        c.setFont("Helvetica-Bold", 16)
        c.drawString(72, 700, "Medications")
        c.setFont("Helvetica", 11)
        c.drawString(72, 670, "Take each medication exactly as prescribed by your care team.")
        c.setFont("Helvetica-Bold", 16)
        c.drawString(72, 620, "Follow-up appointments")
    c.setFont("Helvetica", 11)
    c.drawString(72, 560, "Body prose so the page is not empty and body size is modal.")
    c.drawString(72, 540, "More body prose in the same modal size to anchor the ratio.")
    c.save()
    return p


def test_untagged_pdf_gets_a_levelled_structure_map(tmp_path):
    src = _pdf(tmp_path)
    props: list = []
    with pikepdf.open(str(src)) as pdf:
        rp._propose_structure_map(pdf, str(src), proposals=props)
    assert len(props) == 1
    p = props[0]
    assert p["kind"] == "structure-map"
    v = p["proposed_value"]
    # Largest size ranks Heading 1; the two 16pt sections rank Heading 2, in document order.
    assert 'Heading 1 · “Discharge Instructions” (p.1)' in v
    assert 'Heading 2 · “Medications” (p.1)' in v
    assert 'Heading 2 · “Follow-up appointments” (p.1)' in v
    assert v.index("Discharge") < v.index("Medications") < v.index("Follow-up")
    assert "deterministic" in p["source"]                # provenance says font rank, not AI


def test_uniform_font_pdf_proposes_nothing(tmp_path):
    # No visually-distinct headings → no structure to derive → stays plain human review.
    src = _pdf(tmp_path, headings=False)
    props: list = []
    with pikepdf.open(str(src)) as pdf:
        rp._propose_structure_map(pdf, str(src), proposals=props)
    assert props == []


def test_handler_routes_kinds_to_their_rules():
    src = (Path(__file__).resolve().parent.parent / "api" / "handlers.py").read_text()
    assert '"reading-order"' in src and '"structure-map"' in src
    assert src.index('"1.3.2", "Meaningful Sequence"') < src.index('"1.3.1", "Info and Relationships"')


def test_capability_promoted_to_assisted():
    import remediation_capability as cap
    assert cap.mode_for("pdf", "1.3.1") == cap.ASSISTED
