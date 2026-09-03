"""PDF 2.4.6 Headings and Labels — a hard PDF criterion becomes an assisted proposal card
instead of a bare human-review dead end. A TAGGED PDF that carries no heading struct elements
gets a heading map derived from its font hierarchy (the complement of the 1.3.1 untagged
structure-map proposer). Self-gating and never fabricating (ADR 0016): a heading-tagged PDF
yields nothing, and the proposer mirrors the office_structure detector exactly, so a proposal
only appears where the finding fired.

2.4.4 Link Purpose used to be proposed here too, and no longer is — see
tests/test_pdf_link_purpose_explain_only.py for why, and for the regression that keeps it out.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import remediate_pdf as rp  # noqa: E402

reportlab = pytest.importorskip("reportlab")
pikepdf = pytest.importorskip("pikepdf")
pytest.importorskip("pdfplumber")


# ── 2.4.6 Headings and Labels ───────────────────────────────────────────────────
def _tagged_pdf(tmp: Path, *, headings=True, tagged=True, pages=6) -> Path:
    """A multi-page PDF, optionally tagged with a StructTreeRoot that contains only a
    paragraph (no heading struct element) — the 2.4.6 flagged shape."""
    from reportlab.pdfgen import canvas
    raw = tmp / "raw.pdf"
    c = canvas.Canvas(str(raw))
    for i in range(pages):
        if headings:
            c.setFont("Helvetica-Bold", 22)
            c.drawString(72, 750, "Benefits Overview" if i == 0 else f"Section {i + 1}")
            c.setFont("Helvetica-Bold", 16)
            c.drawString(72, 700, "Eligibility")
        c.setFont("Helvetica", 11)
        c.drawString(72, 640, "Body prose in the modal body size so the ratio anchors.")
        c.drawString(72, 620, "More body prose at the same size to establish the body font.")
        c.showPage()
    c.save()
    if not tagged:
        return raw
    out = tmp / "tagged.pdf"
    pdf = pikepdf.open(str(raw))
    try:
        page = pdf.pages[0].obj
        para = pikepdf.Dictionary(Type=pikepdf.Name("/StructElem"),
                                  S=pikepdf.Name("/P"), Pg=page, K=0)
        para_ref = pdf.make_indirect(para)
        doc = pikepdf.Dictionary(Type=pikepdf.Name("/StructElem"), S=pikepdf.Name("/Document"))
        doc.K = pikepdf.Array([para_ref])
        doc_ref = pdf.make_indirect(doc)
        st = pikepdf.Dictionary(Type=pikepdf.Name("/StructTreeRoot"), K=pikepdf.Array([doc_ref]))
        pdf.Root.StructTreeRoot = pdf.make_indirect(st)
        pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
        pdf.save(str(out))
    finally:
        pdf.close()
    return out


def test_tagged_pdf_without_headings_gets_a_heading_map(tmp_path):
    src = _tagged_pdf(tmp_path)
    props: list = []
    with pikepdf.open(str(src)) as pdf:
        rp._propose_pdf_headings(pdf, str(src), proposals=props)
    assert len(props) == 1
    p = props[0]
    assert p["kind"] == "headings-map"
    v = p["proposed_value"]
    assert 'Heading 1 · “Benefits Overview” (p.1)' in v
    assert 'Heading 2 · “Eligibility” (p.1)' in v
    assert "deterministic" in p["source"]


def test_untagged_pdf_is_left_to_the_structure_map_proposer(tmp_path):
    # No StructTreeRoot → this is 1.3.1's job, not 2.4.6 → no headings-map proposal.
    src = _tagged_pdf(tmp_path, tagged=False)
    props: list = []
    with pikepdf.open(str(src)) as pdf:
        rp._propose_pdf_headings(pdf, str(src), proposals=props)
    assert props == []


def test_tagged_pdf_with_no_distinct_headings_yields_nothing(tmp_path):
    # Tagged, no headings, but uniform font → nothing to derive → stays plain human review.
    src = _tagged_pdf(tmp_path, headings=False)
    props: list = []
    with pikepdf.open(str(src)) as pdf:
        rp._propose_pdf_headings(pdf, str(src), proposals=props)
    assert props == []


# ── wiring ──────────────────────────────────────────────────────────────────────
def test_handler_routes_the_heading_map_to_its_rule():
    src = (Path(__file__).resolve().parent.parent / "api" / "handlers.py").read_text()
    assert '"headings-map"' in src
    assert '"2.4.6", "Headings and Labels"' in src


def test_capability_is_human_without_heading_writeback():
    import remediation_capability as cap
    assert cap.mode_for("pdf", "2.4.6") == cap.HUMAN
