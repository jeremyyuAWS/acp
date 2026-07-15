"""PDF 2.4.4 Link Purpose + 2.4.6 Headings and Labels — the two hard PDF criteria become
assisted proposal cards instead of a bare human-review dead end.

Neither can be auto-applied (rewriting a link label re-flows text runs; adding heading tags
re-authors the file), but both are machine-DERIVABLE:
  * 2.4.4 — a link whose visible text is the raw URL gets a descriptive label derived from
    the link target (proposals.derive_link_text), deterministically.
  * 2.4.6 — a TAGGED PDF that carries no heading struct elements gets a heading map derived
    from its font hierarchy (the complement of the 1.3.1 untagged structure-map proposer).

Both are self-gating and never fabricate (ADR 0016): a descriptive-link / heading-tagged PDF
yields nothing. The proposers mirror the office_structure detectors exactly, so a proposal
only appears where the finding fired.
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


# ── 2.4.4 Link Purpose ────────────────────────────────────────────────────────
def _pdf_with_link(tmp: Path, url: str, *, visible_text: str | None = None) -> Path:
    """A one-page PDF with a /Link annotation to `url`; the visible text drawn on the page is
    `visible_text` (defaults to the raw URL, which is the flagged case)."""
    from reportlab.pdfgen import canvas
    p = tmp / "link.pdf"
    c = canvas.Canvas(str(p))
    text = visible_text if visible_text is not None else url
    c.setFont("Helvetica", 12)
    c.drawString(72, 700, text)
    c.linkURL(url, (72, 695, 400, 715), relative=0)
    c.drawString(72, 650, "Body prose so the page carries readable text for extraction.")
    c.save()
    return p


def test_raw_url_link_gets_a_derived_label(tmp_path):
    src = _pdf_with_link(tmp_path, "https://example.com/annual-report-2026.pdf")
    props: list = []
    with pikepdf.open(str(src)) as pdf:
        rp._propose_pdf_link_purpose(pdf, str(src), ai_enabled=False, proposals=props)
    assert len(props) == 1
    p = props[0]
    assert p["kind"] == "link-purpose"
    assert p["locator"] == "https://example.com/annual-report-2026.pdf"
    # Deterministic label derived from the download target, no AI.
    assert p["proposed_value"] == "Download Annual Report 2026 (PDF)"
    assert "deterministic" in p["source"]


def test_descriptive_link_proposes_nothing(tmp_path):
    # The visible text is NOT the raw URL → the detector never flags → no proposal.
    src = _pdf_with_link(tmp_path, "https://example.com/annual-report-2026.pdf",
                         visible_text="Read the 2026 annual report")
    props: list = []
    with pikepdf.open(str(src)) as pdf:
        rp._propose_pdf_link_purpose(pdf, str(src), ai_enabled=False, proposals=props)
    assert props == []


def test_opaque_url_with_ai_off_yields_nothing(tmp_path):
    # A bare domain isn't derivable from its target; with AI off we never fabricate a label.
    src = _pdf_with_link(tmp_path, "https://example.com")
    props: list = []
    with pikepdf.open(str(src)) as pdf:
        rp._propose_pdf_link_purpose(pdf, str(src), ai_enabled=False, proposals=props)
    assert props == []


def test_no_links_yields_nothing(tmp_path):
    from reportlab.pdfgen import canvas
    p = tmp_path / "plain.pdf"
    c = canvas.Canvas(str(p))
    c.drawString(72, 700, "Just prose, no links at all.")
    c.save()
    props: list = []
    with pikepdf.open(str(p)) as pdf:
        rp._propose_pdf_link_purpose(pdf, str(p), ai_enabled=False, proposals=props)
    assert props == []


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
def test_handler_routes_both_new_kinds_to_their_rules():
    src = (Path(__file__).resolve().parent.parent / "api" / "handlers.py").read_text()
    assert '"headings-map"' in src and '"link-purpose"' in src
    assert '"2.4.6", "Headings and Labels"' in src
    assert '"2.4.4", "Link Purpose (In Context)"' in src


def test_capability_promoted_to_assisted():
    import remediation_capability as cap
    assert cap.CAPABILITY["pdf"]["2.4.4"] == cap.ASSISTED
    assert cap.CAPABILITY["pdf"]["2.4.6"] == cap.ASSISTED
