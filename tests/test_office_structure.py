"""First-party OOXML/PDF structural checks (api/office_structure.py).

Fixtures are hand-built zip/XML (mirroring test_ocr.py's _docx() helper) rather
than via python-docx/python-pptx — those aren't declared project dependencies,
only used ad hoc for verification during development. PDF fixtures use
reportlab, which is a real declared dependency (api/requirements.txt).
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import office_structure as os_  # noqa: E402

_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
{rels}
</Relationships>"""

_REL = '<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="{target}" TargetMode="External"/>'


def _docx(tmp: Path, document_xml: str, rels_xml: str = "") -> Path:
    p = tmp / "doc.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", document_xml)
        if rels_xml:
            z.writestr("word/_rels/document.xml.rels", rels_xml)
    return p


def _pptx(tmp: Path, *slide_xmls: str, rels_xmls: dict[int, str] | None = None) -> Path:
    p = tmp / "deck.pptx"
    rels_xmls = rels_xmls or {}
    with zipfile.ZipFile(p, "w") as z:
        for i, xml in enumerate(slide_xmls, start=1):
            z.writestr(f"ppt/slides/slide{i}.xml", xml)
            if i in rels_xmls:
                z.writestr(f"ppt/slides/_rels/slide{i}.xml.rels", rels_xmls[i])
    return p


def _pdf(tmp: Path, *, light=False, dark=False) -> Path:
    from reportlab.lib.colors import Color
    from reportlab.pdfgen import canvas

    p = tmp / "doc.pdf"
    c = canvas.Canvas(str(p))
    if dark:
        c.setFillColor(Color(0.1, 0.1, 0.1))
        c.drawString(72, 700, "Dark text is readable")
    if light:
        c.setFillColor(Color(0.8, 0.8, 0.8))
        c.drawString(72, 650, "Light grey text is low contrast")
    c.save()
    return p


# --- docx: 2.4.6 heading skip -------------------------------------------------

def test_docx_heading_skip_detected(tmp_path):
    doc = """<w:document><w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Title</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="Heading3"/></w:pPr><w:r><w:t>Sub</w:t></w:r></w:p>
    </w:body></w:document>"""
    findings = os_.docx_checks(_docx(tmp_path, doc))
    assert any(f["ruleId"] == "DOCX_HEADING_SKIP" for f in findings)


def test_docx_sequential_headings_not_flagged(tmp_path):
    doc = """<w:document><w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Title</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Sub</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="Heading3"/></w:pPr><w:r><w:t>SubSub</w:t></w:r></w:p>
    </w:body></w:document>"""
    findings = os_.docx_checks(_docx(tmp_path, doc))
    assert not any(f["ruleId"] == "DOCX_HEADING_SKIP" for f in findings)


# --- docx: 2.4.9 duplicate link text -----------------------------------------

def test_docx_duplicate_link_text_different_targets_flagged(tmp_path):
    doc = """<w:document><w:body>
    <w:p><w:hyperlink r:id="rId2"><w:r><w:t>View details</w:t></w:r></w:hyperlink></w:p>
    <w:p><w:hyperlink r:id="rId3"><w:r><w:t>View details</w:t></w:r></w:hyperlink></w:p>
    </w:body></w:document>"""
    rels = _RELS_XML.format(rels="\n".join([
        _REL.format(rid="rId2", target="https://example.com/apple"),
        _REL.format(rid="rId3", target="https://example.com/banana"),
    ]))
    findings = os_.docx_checks(_docx(tmp_path, doc, rels))
    assert sum(1 for f in findings if f["ruleId"] == "DOCX_LINK_PURPOSE_AMBIGUOUS") == 2


def test_docx_same_link_text_same_target_not_flagged(tmp_path):
    doc = """<w:document><w:body>
    <w:p><w:hyperlink r:id="rId2"><w:r><w:t>View details</w:t></w:r></w:hyperlink></w:p>
    <w:p><w:hyperlink r:id="rId3"><w:r><w:t>View details</w:t></w:r></w:hyperlink></w:p>
    </w:body></w:document>"""
    rels = _RELS_XML.format(rels="\n".join([
        _REL.format(rid="rId2", target="https://example.com/apple"),
        _REL.format(rid="rId3", target="https://example.com/apple"),
    ]))
    findings = os_.docx_checks(_docx(tmp_path, doc, rels))
    assert not any(f["ruleId"] == "DOCX_LINK_PURPOSE_AMBIGUOUS" for f in findings)


def test_docx_non_hyperlink_xml_returns_no_findings(tmp_path):
    findings = os_.docx_checks(_docx(tmp_path, "<w:document><w:body/></w:document>"))
    assert findings == []


# --- pptx: 2.4.6 title placeholder present but empty -------------------------

_SLIDE_TMPL = """<p:sld><p:cSld><p:spTree>
<p:sp><p:nvSpPr><p:nvPr>{ph}</p:nvPr></p:nvSpPr><p:spPr/>
<p:txBody><a:bodyPr/><a:lstStyle/><a:p>{body}</a:p></p:txBody></p:sp>
</p:spTree></p:cSld></p:sld>"""


def test_pptx_empty_title_flagged(tmp_path):
    xml = _SLIDE_TMPL.format(ph='<p:ph type="title"/>', body="")
    findings = os_.pptx_checks(_pptx(tmp_path, xml))
    assert any(f["ruleId"] == "PPTX_TITLE_EMPTY" for f in findings)


def test_pptx_empty_ctr_title_flagged(tmp_path):
    """ctrTitle is the Title-Slide-layout variant of the title placeholder —
    verified via python-pptx that slide_layouts[0] emits type="ctrTitle" while
    other layouts emit plain type="title"; both must be checked."""
    xml = _SLIDE_TMPL.format(ph='<p:ph type="ctrTitle"/>', body="")
    findings = os_.pptx_checks(_pptx(tmp_path, xml))
    assert any(f["ruleId"] == "PPTX_TITLE_EMPTY" for f in findings)


def test_pptx_filled_title_not_flagged(tmp_path):
    xml = _SLIDE_TMPL.format(ph='<p:ph type="title"/>', body="<a:r><a:t>My Title</a:t></a:r>")
    findings = os_.pptx_checks(_pptx(tmp_path, xml))
    assert not any(f["ruleId"] == "PPTX_TITLE_EMPTY" for f in findings)


def test_pptx_no_title_placeholder_not_flagged(tmp_path):
    """A blank-layout slide with no title slot at all is a legitimate design
    choice — not the same as a title placeholder present-but-empty."""
    xml = """<p:sld><p:cSld><p:spTree></p:spTree></p:cSld></p:sld>"""
    findings = os_.pptx_checks(_pptx(tmp_path, xml))
    assert not any(f["ruleId"] == "PPTX_TITLE_EMPTY" for f in findings)


# --- pptx: 2.4.9 duplicate link text -----------------------------------------

_LINK_SLIDE = """<p:sld><p:cSld><p:spTree>
<p:sp><p:txBody>
<a:p><a:r><a:rPr><a:hlinkClick r:id="rId2"/></a:rPr><a:t>View details</a:t></a:r></a:p>
<a:p><a:r><a:rPr><a:hlinkClick r:id="rId3"/></a:rPr><a:t>View details</a:t></a:r></a:p>
</p:txBody></p:sp>
</p:spTree></p:cSld></p:sld>"""


def test_pptx_duplicate_link_text_different_targets_flagged(tmp_path):
    rels = _RELS_XML.format(rels="\n".join([
        _REL.format(rid="rId2", target="https://example.com/apple"),
        _REL.format(rid="rId3", target="https://example.com/banana"),
    ]))
    findings = os_.pptx_checks(_pptx(tmp_path, _LINK_SLIDE, rels_xmls={1: rels}))
    assert sum(1 for f in findings if f["ruleId"] == "PPTX_LINK_PURPOSE_AMBIGUOUS") == 2


def test_pptx_same_link_text_same_target_not_flagged(tmp_path):
    rels = _RELS_XML.format(rels="\n".join([
        _REL.format(rid="rId2", target="https://example.com/apple"),
        _REL.format(rid="rId3", target="https://example.com/apple"),
    ]))
    findings = os_.pptx_checks(_pptx(tmp_path, _LINK_SLIDE, rels_xmls={1: rels}))
    assert not any(f["ruleId"] == "PPTX_LINK_PURPOSE_AMBIGUOUS" for f in findings)


# --- pdf: 1.4.3 / 1.4.6 contrast ---------------------------------------------

def test_pdf_low_contrast_text_flags_both_aa_and_aaa(tmp_path):
    findings = os_.pdf_contrast_checks(_pdf(tmp_path, light=True))
    ids = {f["ruleId"] for f in findings}
    assert ids == {"PDF_LOW_CONTRAST_AA", "PDF_LOW_CONTRAST_AAA"}


def test_pdf_dark_text_only_not_flagged(tmp_path):
    findings = os_.pdf_contrast_checks(_pdf(tmp_path, dark=True))
    assert findings == []


def test_pdf_luma_rejects_malformed_color():
    assert os_._pdf_luma(None) is None
    assert os_._pdf_luma((0.5,)) is None
    assert os_._pdf_luma("not-a-color") is None


# --- pdf: 2.4.1 bypass blocks (bookmark/outline tree) -------------------------

def _pikepdf_pdf(tmp: Path, n_pages: int, bookmark_titles: list[str] | None = None) -> Path:
    import pikepdf
    p = tmp / "outline.pdf"
    doc = pikepdf.new()
    for _ in range(n_pages):
        doc.add_blank_page(page_size=(612, 792))
    if bookmark_titles:
        with doc.open_outline() as outline:
            for i, title in enumerate(bookmark_titles):
                outline.root.append(pikepdf.OutlineItem(title, i))
    doc.save(p)
    return p


def test_pdf_short_document_not_flagged_even_without_bookmarks(tmp_path):
    p = _pikepdf_pdf(tmp_path, os_._MIN_PAGES_FOR_OUTLINE - 1)
    assert os_.pdf_bypass_blocks_check(p) == []


def test_pdf_long_document_without_bookmarks_flagged(tmp_path):
    p = _pikepdf_pdf(tmp_path, os_._MIN_PAGES_FOR_OUTLINE)
    findings = os_.pdf_bypass_blocks_check(p)
    assert any(f["ruleId"] == "PDF_NO_BOOKMARKS" for f in findings)


def test_pdf_long_document_with_bookmarks_not_flagged(tmp_path):
    p = _pikepdf_pdf(tmp_path, os_._MIN_PAGES_FOR_OUTLINE, bookmark_titles=["Intro", "Body"])
    assert os_.pdf_bypass_blocks_check(p) == []


# --- dispatcher ----------------------------------------------------------

def test_checks_for_dispatches_by_extension(tmp_path):
    assert os_.checks_for(tmp_path / "x.txt", ".txt") == []
    assert os_.checks_for(_pdf(tmp_path, dark=True), ".pdf") == []
