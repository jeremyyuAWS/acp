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

import pytest

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


_XLSX_STYLES_TMPL = """<?xml version="1.0"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="{n}">{fonts}</fonts>
<fills count="{n}">{fills}</fills>
<cellXfs count="{n}">{xfs}</cellXfs>
</styleSheet>"""


def _xlsx(tmp: Path, cell_xml: str, fonts: str, fills: str, xfs: str) -> Path:
    """fonts/fills/xfs: raw inner XML for each block, index-aligned by
    position (font index 0 pairs with fill index 0 pairs with xf index 0)."""
    p = tmp / "book.xlsx"
    styles = _XLSX_STYLES_TMPL.format(n=99, fonts=fonts, fills=fills, xfs=xfs)
    sheet = f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{cell_xml}</sheetData></worksheet>'
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("xl/styles.xml", styles)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
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


def test_docx_distinct_link_sharing_a_target_not_flagged(tmp_path):
    """A distinctly-labelled link that happens to point at the same URL as an
    ambiguous pair must NOT be flagged — only the ambiguous-text links fail 2.4.9
    (regression: the old href-based logic flagged the innocent 'Homepage' link)."""
    doc = """<w:document><w:body>
    <w:p><w:hyperlink r:id="rId2"><w:r><w:t>Read more</w:t></w:r></w:hyperlink></w:p>
    <w:p><w:hyperlink r:id="rId3"><w:r><w:t>Read more</w:t></w:r></w:hyperlink></w:p>
    <w:p><w:hyperlink r:id="rId4"><w:r><w:t>Homepage</w:t></w:r></w:hyperlink></w:p>
    </w:body></w:document>"""
    rels = _RELS_XML.format(rels="\n".join([
        _REL.format(rid="rId2", target="https://example.com/apple"),
        _REL.format(rid="rId3", target="https://example.com/banana"),
        _REL.format(rid="rId4", target="https://example.com/apple"),
    ]))
    findings = os_.docx_checks(_docx(tmp_path, doc, rels))
    # Exactly the two "Read more" links, not "Homepage".
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


# --- docx: 3.3.2 form-field content controls with no label -------------------

def test_docx_checkbox_with_no_alias_flagged(tmp_path):
    doc = """<w:document><w:body>
    <w:sdt><w:sdtPr><w:id w:val="1"/><w:checkbox/></w:sdtPr>
    <w:sdtContent><w:r><w:t>[ ]</w:t></w:r></w:sdtContent></w:sdt>
    </w:body></w:document>"""
    findings = os_.docx_checks(_docx(tmp_path, doc))
    assert any(f["ruleId"] == "DOCX_FORM_FIELD_NO_LABEL" for f in findings)


def test_docx_checkbox_with_empty_alias_flagged(tmp_path):
    doc = """<w:document><w:body>
    <w:sdt><w:sdtPr><w:alias w:val=""/><w:dropDownList><w:listItem w:value="A"/></w:dropDownList></w:sdtPr>
    <w:sdtContent><w:r><w:t>A</w:t></w:r></w:sdtContent></w:sdt>
    </w:body></w:document>"""
    findings = os_.docx_checks(_docx(tmp_path, doc))
    assert any(f["ruleId"] == "DOCX_FORM_FIELD_NO_LABEL" for f in findings)


def test_docx_checkbox_with_alias_not_flagged(tmp_path):
    doc = """<w:document><w:body>
    <w:sdt><w:sdtPr><w:alias w:val="Agree to terms"/><w:id w:val="1"/><w:checkbox/></w:sdtPr>
    <w:sdtContent><w:r><w:t>[ ]</w:t></w:r></w:sdtContent></w:sdt>
    </w:body></w:document>"""
    findings = os_.docx_checks(_docx(tmp_path, doc))
    assert not any(f["ruleId"] == "DOCX_FORM_FIELD_NO_LABEL" for f in findings)


def test_docx_toc_content_control_without_alias_not_flagged(tmp_path):
    """docPartObj (building-block placeholders like a TOC field) is not a
    form-input gallery type — Word uses w:sdt for lots of non-form structural
    content, and flagging every un-aliased sdt would false-positive on it."""
    doc = """<w:document><w:body>
    <w:sdt><w:sdtPr><w:id w:val="2"/>
    <w:docPartObj><w:docPartGallery w:val="Table of Contents"/></w:docPartObj>
    </w:sdtPr><w:sdtContent><w:r><w:t>Contents...</w:t></w:r></w:sdtContent></w:sdt>
    </w:body></w:document>"""
    findings = os_.docx_checks(_docx(tmp_path, doc))
    assert not any(f["ruleId"] == "DOCX_FORM_FIELD_NO_LABEL" for f in findings)


# --- docx: 4.1.2 form-field content controls with no w:tag -------------------
# w:alias is the human-visible label (3.3.2); w:tag is the stable programmatic
# identifier assistive tech reads for Name — a field can have one without the
# other, so this is a separate check from the 3.3.2 alias check above.

def test_docx_checkbox_with_no_tag_flagged(tmp_path):
    doc = """<w:document><w:body>
    <w:sdt><w:sdtPr><w:alias w:val="Agree to terms"/><w:id w:val="1"/><w:checkbox/></w:sdtPr>
    <w:sdtContent><w:r><w:t>[ ]</w:t></w:r></w:sdtContent></w:sdt>
    </w:body></w:document>"""
    findings = os_.docx_checks(_docx(tmp_path, doc))
    assert any(f["ruleId"] == "DOCX_FORM_FIELD_NO_TAG" for f in findings)


def test_docx_checkbox_with_empty_tag_flagged(tmp_path):
    doc = """<w:document><w:body>
    <w:sdt><w:sdtPr><w:alias w:val="Agree to terms"/><w:tag w:val=""/><w:checkbox/></w:sdtPr>
    <w:sdtContent><w:r><w:t>[ ]</w:t></w:r></w:sdtContent></w:sdt>
    </w:body></w:document>"""
    findings = os_.docx_checks(_docx(tmp_path, doc))
    assert any(f["ruleId"] == "DOCX_FORM_FIELD_NO_TAG" for f in findings)


def test_docx_checkbox_with_tag_not_flagged(tmp_path):
    doc = """<w:document><w:body>
    <w:sdt><w:sdtPr><w:alias w:val="Agree to terms"/><w:tag w:val="agree_terms"/><w:id w:val="1"/><w:checkbox/></w:sdtPr>
    <w:sdtContent><w:r><w:t>[ ]</w:t></w:r></w:sdtContent></w:sdt>
    </w:body></w:document>"""
    findings = os_.docx_checks(_docx(tmp_path, doc))
    assert not any(f["ruleId"] == "DOCX_FORM_FIELD_NO_TAG" for f in findings)


def test_docx_toc_content_control_without_tag_not_flagged(tmp_path):
    """Same non-form-input gate as the alias check — a TOC placeholder isn't
    a form field, so a missing w:tag on it is not a 4.1.2 finding."""
    doc = """<w:document><w:body>
    <w:sdt><w:sdtPr><w:id w:val="2"/>
    <w:docPartObj><w:docPartGallery w:val="Table of Contents"/></w:docPartObj>
    </w:sdtPr><w:sdtContent><w:r><w:t>Contents...</w:t></w:r></w:sdtContent></w:sdt>
    </w:body></w:document>"""
    findings = os_.docx_checks(_docx(tmp_path, doc))
    assert not any(f["ruleId"] == "DOCX_FORM_FIELD_NO_TAG" for f in findings)


# --- docx: 2.4.10 section headings -------------------------------------------

def _para(text):
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def test_docx_long_body_with_no_headings_flagged(tmp_path):
    body = "".join(_para(f"Paragraph {i} carries real content.")
                   for i in range(os_._MIN_PARAS_FOR_HEADINGS + 3))
    doc = f"<w:document><w:body>{body}</w:body></w:document>"
    findings = os_.docx_checks(_docx(tmp_path, doc))
    assert any(f["ruleId"] == "DOCX_NO_SECTION_HEADINGS" for f in findings)


def test_docx_long_body_with_a_heading_not_flagged(tmp_path):
    heading = '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Intro</w:t></w:r></w:p>'
    body = heading + "".join(_para(f"Paragraph {i}.") for i in range(os_._MIN_PARAS_FOR_HEADINGS + 3))
    doc = f"<w:document><w:body>{body}</w:body></w:document>"
    findings = os_.docx_checks(_docx(tmp_path, doc))
    assert not any(f["ruleId"] == "DOCX_NO_SECTION_HEADINGS" for f in findings)


def test_docx_short_body_with_no_headings_not_flagged(tmp_path):
    body = "".join(_para(f"Line {i}.") for i in range(os_._MIN_PARAS_FOR_HEADINGS - 5))
    doc = f"<w:document><w:body>{body}</w:body></w:document>"
    findings = os_.docx_checks(_docx(tmp_path, doc))
    assert not any(f["ruleId"] == "DOCX_NO_SECTION_HEADINGS" for f in findings)


def test_docx_many_empty_paragraphs_not_flagged(tmp_path):
    body = "<w:p></w:p>" * (os_._MIN_PARAS_FOR_HEADINGS + 5)
    doc = f"<w:document><w:body>{body}</w:body></w:document>"
    findings = os_.docx_checks(_docx(tmp_path, doc))
    assert not any(f["ruleId"] == "DOCX_NO_SECTION_HEADINGS" for f in findings)


# --- docx: 1.4.8 justified body text -----------------------------------------

def _jpara(text):
    return f'<w:p><w:pPr><w:jc w:val="both"/></w:pPr><w:r><w:t>{text}</w:t></w:r></w:p>'


def test_docx_justified_body_text_flagged(tmp_path):
    body = "".join(_jpara(f"Justified block {i}.") for i in range(os_._MIN_JUSTIFIED_PARAS + 1))
    doc = f"<w:document><w:body>{body}</w:body></w:document>"
    findings = os_.docx_checks(_docx(tmp_path, doc))
    assert any(f["ruleId"] == "DOCX_JUSTIFIED_TEXT" for f in findings)


def test_docx_one_justified_paragraph_not_flagged(tmp_path):
    # A single incidental justified line (e.g. a banner) is below the block floor.
    body = _jpara("One justified line.") + "".join(_para(f"Left {i}.") for i in range(5))
    doc = f"<w:document><w:body>{body}</w:body></w:document>"
    findings = os_.docx_checks(_docx(tmp_path, doc))
    assert not any(f["ruleId"] == "DOCX_JUSTIFIED_TEXT" for f in findings)


def test_docx_left_aligned_text_not_flagged(tmp_path):
    body = "".join(_para(f"Left-aligned line {i}.") for i in range(6))
    doc = f"<w:document><w:body>{body}</w:body></w:document>"
    findings = os_.docx_checks(_docx(tmp_path, doc))
    assert not any(f["ruleId"] == "DOCX_JUSTIFIED_TEXT" for f in findings)


def test_docx_empty_justified_paragraphs_not_flagged(tmp_path):
    body = '<w:p><w:pPr><w:jc w:val="both"/></w:pPr></w:p>' * (os_._MIN_JUSTIFIED_PARAS + 2)
    doc = f"<w:document><w:body>{body}</w:body></w:document>"
    findings = os_.docx_checks(_docx(tmp_path, doc))
    assert not any(f["ruleId"] == "DOCX_JUSTIFIED_TEXT" for f in findings)


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


def test_pptx_empty_title_with_idx_attr_flagged(tmp_path):
    """The title placeholder may carry extra attributes (idx) — the check must
    still fire (regression: a strict type=".."/> match silently skipped these)."""
    xml = _SLIDE_TMPL.format(ph='<p:ph type="title" idx="0"/>', body="")
    findings = os_.pptx_checks(_pptx(tmp_path, xml))
    assert any(f["ruleId"] == "PPTX_TITLE_EMPTY" for f in findings)


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

def _xlsx_cell(ref: str, style_idx: int, text: str) -> str:
    return f'<c r="{ref}" s="{style_idx}"><is><t>{text}</t></is></c>'


def test_xlsx_light_grey_on_default_white_flagged(tmp_path):
    # font[0]=theme (default, unused directly), font[1]=explicit light grey;
    # fill[0]=no pattern (resolves to white), fill[1]=unused (paired w/ font[1]).
    fonts = '<font><color theme="1"/></font><font><color rgb="00CCCCCC"/></font>'
    fills = '<fill><patternFill/></fill><fill><patternFill/></fill>'
    xfs = '<xf fontId="0" fillId="0"/><xf fontId="1" fillId="1"/>'
    cells = _xlsx_cell("A1", 1, "Low contrast text")
    findings = os_.xlsx_contrast_checks(_xlsx(tmp_path, cells, fonts, fills, xfs))
    ids = {f["ruleId"] for f in findings}
    assert ids == {"XLSX_LOW_CONTRAST_AA", "XLSX_LOW_CONTRAST_AAA"}


def test_xlsx_black_on_default_white_not_flagged(tmp_path):
    fonts = '<font><color theme="1"/></font><font><color rgb="00000000"/></font>'
    fills = '<fill><patternFill/></fill><fill><patternFill/></fill>'
    xfs = '<xf fontId="0" fillId="0"/><xf fontId="1" fillId="1"/>'
    cells = _xlsx_cell("A1", 1, "Good contrast text")
    findings = os_.xlsx_contrast_checks(_xlsx(tmp_path, cells, fonts, fills, xfs))
    assert findings == []


def test_xlsx_theme_font_color_not_flagged(tmp_path):
    """A default-styled cell (theme font, no fill) is unresolvable by design —
    guessing at theme colors is the exact false-positive risk this check must
    avoid, since Excel's built-in header/table styles use theme colors."""
    fonts = '<font><color theme="1"/></font>'
    fills = '<fill><patternFill/></fill>'
    xfs = '<xf fontId="0" fillId="0"/>'
    cells = _xlsx_cell("A1", 0, "Default styled text")
    findings = os_.xlsx_contrast_checks(_xlsx(tmp_path, cells, fonts, fills, xfs))
    assert findings == []


def test_xlsx_indices_scoped_to_real_blocks(tmp_path):
    """Regression: a real workbook has <cellStyleXfs> (named styles) before
    <cellXfs>, and <dxfs> (conditional-format) fonts/fills sharing the tag names.
    A cell's s="N" indexes ONLY into cellXfs; counting the other blocks shifts
    every index and resolves the wrong colour. Here s=1 -> cellXfs[1] = light
    grey on white must still be flagged despite the decoy blocks."""
    styles = (
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><color rgb="FF000000"/></font>'
        '<font><color rgb="FFCCCCCC"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFFFFFFF"/></patternFill></fill></fills>'
        '<cellStyleXfs count="2"><xf fontId="0" fillId="0"/><xf fontId="0" fillId="0"/></cellStyleXfs>'
        '<cellXfs count="2"><xf fontId="0" fillId="0"/><xf fontId="1" fillId="1"/></cellXfs>'
        '<dxfs count="1"><dxf><font><color rgb="FFFF0000"/></font></dxf></dxfs>'
        '</styleSheet>'
    )
    sheet = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<sheetData><row><c r="A1" s="1"><v>text</v></c></row></sheetData></worksheet>')
    p = tmp_path / "real.xlsx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("xl/styles.xml", styles)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    ids = {f["ruleId"] for f in os_.xlsx_contrast_checks(p)}
    assert ids == {"XLSX_LOW_CONTRAST_AA", "XLSX_LOW_CONTRAST_AAA"}


def test_xlsx_non_solid_pattern_fill_not_flagged(tmp_path):
    """A half-tone/stripe pattern fill (e.g. gray125) has no single resolvable
    background color — skipped rather than guessed at."""
    fonts = '<font><color rgb="00CCCCCC"/></font>'
    fills = '<fill><patternFill patternType="gray125"/></fill>'
    xfs = '<xf fontId="0" fillId="0"/>'
    cells = _xlsx_cell("A1", 0, "Halftone background text")
    findings = os_.xlsx_contrast_checks(_xlsx(tmp_path, cells, fonts, fills, xfs))
    assert findings == []


def test_xlsx_empty_cell_with_low_contrast_style_not_flagged(tmp_path):
    fonts = '<font><color rgb="00CCCCCC"/></font>'
    fills = '<fill><patternFill/></fill>'
    xfs = '<xf fontId="0" fillId="0"/>'
    cells = '<c r="A1" s="0"/>'  # styled but empty — nothing rendered, nothing to contrast-check
    findings = os_.xlsx_contrast_checks(_xlsx(tmp_path, cells, fonts, fills, xfs))
    assert findings == []


def test_xlsx_no_styles_file_returns_no_findings(tmp_path):
    p = tmp_path / "nostyles.xlsx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", "<worksheet/>")
    assert os_.xlsx_contrast_checks(p) == []


def test_pdf_low_contrast_text_flags_both_aa_and_aaa(tmp_path):
    findings = os_.pdf_contrast_checks(_pdf(tmp_path, light=True))
    ids = {f["ruleId"] for f in findings}
    assert ids == {"PDF_LOW_CONTRAST_AA", "PDF_LOW_CONTRAST_AAA"}


def test_pdf_dark_text_only_not_flagged(tmp_path):
    findings = os_.pdf_contrast_checks(_pdf(tmp_path, dark=True))
    assert findings == []


# --- pdf 1.4.3/1.4.6: the ratio is measured against the RESOLVED background ----
# These pin the three ways the old declared-luma-vs-assumed-white threshold was wrong.

def _pdf_text_on(tmp: Path, text_rgb, *, panel_rgb=None, full_page_rgb=None,
                 size=12, name="doc.pdf") -> Path:
    """One line of `text_rgb` text, optionally over a `panel_rgb` rect or a `full_page_rgb`
    page fill. Channels are 0..255."""
    from reportlab.lib.colors import Color
    from reportlab.pdfgen import canvas

    def _c(rgb):
        return Color(*(v / 255 for v in rgb))

    p = tmp / name
    c = canvas.Canvas(str(p), pagesize=(400, 400))
    if full_page_rgb:
        c.setFillColor(_c(full_page_rgb))
        c.rect(0, 0, 400, 400, stroke=0, fill=1)
    if panel_rgb:
        c.setFillColor(_c(panel_rgb))
        c.rect(20, 20, 360, 360, stroke=0, fill=1)
    c.setFillColor(_c(text_rgb))
    c.setFont("Helvetica", size)
    c.drawString(60, 200, "The quick brown fox")
    c.save()
    return p


def test_pdf_white_text_on_dark_panel_is_not_flagged(tmp_path):
    """White on black is 21:1 — it passes AA *and* AAA. The declared-luma model called it a
    SERIOUS 1.4.3 failure because it assumed the page was white."""
    src = _pdf_text_on(tmp_path, (255, 255, 255), panel_rgb=(0, 0, 0))
    assert os_.pdf_contrast_checks(src) == []


def test_pdf_white_text_on_full_page_dark_fill_is_not_flagged(tmp_path):
    """Same defect via the other common shape: a dark cover page, not a panel."""
    src = _pdf_text_on(tmp_path, (255, 255, 255), full_page_rgb=(0x10, 0x1C, 0x3A))
    assert os_.pdf_contrast_checks(src) == []


def test_pdf_dark_text_on_dark_background_is_flagged(tmp_path):
    """The mirror miss: #4C4C4C on #262626 is 1.76:1 and fired nothing, because both lumas
    sit below the old floors."""
    src = _pdf_text_on(tmp_path, (0x4C, 0x4C, 0x4C), full_page_rgb=(0x26, 0x26, 0x26))
    findings = {f["ruleId"]: f for f in os_.pdf_contrast_checks(src)}
    assert set(findings) == {"PDF_LOW_CONTRAST_AA", "PDF_LOW_CONTRAST_AAA"}
    assert findings["PDF_LOW_CONTRAST_AA"]["evidence"]["value"] == pytest.approx(1.76, abs=0.01)


def test_pdf_muted_grey_body_text_fails_aa(tmp_path):
    """#787878 on white is 4.42:1 — a real AA failure the luma floor (0.62 ≈ #9E9E9E) never
    fired on. The whole muted-body-text band was under-reported this way."""
    findings = {f["ruleId"]: f for f in
                os_.pdf_contrast_checks(_pdf_text_on(tmp_path, (0x78, 0x78, 0x78)))}
    assert "PDF_LOW_CONTRAST_AA" in findings
    ev = findings["PDF_LOW_CONTRAST_AA"]["evidence"]
    assert ev["value"] == pytest.approx(4.42, abs=0.01) and ev["required"] == 4.5


def test_pdf_large_text_judged_at_the_large_text_bar(tmp_path):
    """#808080 on white is 3.95:1 — an AA failure as body text, and compliant at 24pt, where
    WCAG's bar is 3:1. Measuring a real ratio only helps if it's held to the right bar."""
    grey = (0x80, 0x80, 0x80)
    large = {f["ruleId"] for f in
             os_.pdf_contrast_checks(_pdf_text_on(tmp_path, grey, size=24))}
    small = {f["ruleId"] for f in
             os_.pdf_contrast_checks(_pdf_text_on(tmp_path, grey, size=10, name="small.pdf"))}
    assert "PDF_LOW_CONTRAST_AA" not in large and "PDF_LOW_CONTRAST_AA" in small


def test_pdf_recolor_plan_abstains_when_no_colour_suits_every_background(tmp_path):
    """One text colour on backgrounds that pull opposite ways: white and #333333 admit no
    single colour clearing 4.5:1 on both, so the fixer is given nothing to apply and the
    finding stays a finding. (White and BLACK do admit one — #767676 — and it is offered.)"""
    assert os_._pdf_recolor_for_all("808080", {"FFFFFF", "333333"}, 4.5, 7.0) is None
    assert os_._pdf_recolor_for_all("808080", {"FFFFFF", "000000"}, 4.5, 7.0) == "767676"


def test_pdf_text_over_image_is_left_to_the_review_lane(tmp_path, monkeypatch):
    """A glyph whose background is an image can't be resolved structurally, so this detector
    abstains rather than judging it against a guessed page colour."""
    src = _pdf_text_on(tmp_path, (0xCC, 0xCC, 0xCC))
    real = os_._pdf_char_background
    monkeypatch.setattr(os_, "_pdf_char_background", lambda *a, **k: None)
    assert os_.pdf_contrast_checks(src) == []
    monkeypatch.setattr(os_, "_pdf_char_background", real)
    assert os_.pdf_contrast_checks(src)            # same file, background resolvable


def test_pdf_background_tolerates_snug_panels_and_grazed_rules():
    """Real glyph boxes don't line up with real fills. A char whose font box overhangs its
    panel by a few points is still on the panel; a char beside a table rule's thin filled
    rect is not on the rule. Only a genuine straddle resolves to nothing."""
    ch = {"x0": 100.0, "top": 100.0, "x1": 110.0, "bottom": 110.0}   # a 10x10 glyph box
    snug = [(100.0, 101.0, 110.0, 110.0, "101C3A")]                  # panel 1pt short at top
    rule = [(0.0, 109.5, 400.0, 110.5, "000000")]                    # 1pt rule under the text
    straddle = [(105.0, 100.0, 400.0, 110.0, "000000")]              # covers half the glyph
    assert os_._pdf_char_background(ch, snug, []) == "101C3A"
    assert os_._pdf_char_background(ch, rule, []) == os_._PDF_DEFAULT_BG
    assert os_._pdf_char_background(ch, straddle, []) is None


def test_pdf_contrast_reports_its_character_cap(tmp_path, monkeypatch):
    """ADR 0026: pdf_contrast_checks was the one PDF detector that truncated silently."""
    monkeypatch.setattr(os_, "_MAX_CHARS_PER_PAGE", 5)
    detail = os_.pdf_contrast_checks(_pdf_text_on(tmp_path, (0xCC, 0xCC, 0xCC)))[0]["detail"]
    assert "measured the first 5 characters on 1 page" in detail


def test_pdf_luma_rejects_malformed_color():
    assert os_._pdf_luma(None) is None
    assert os_._pdf_luma(()) is None
    assert os_._pdf_luma("not-a-color") is None
    assert os_._pdf_luma((0.1, 0.2, 0.3, 0.4, 0.5)) is None  # 5-tuple = unknown space


def test_pdf_luma_handles_gray_rgb_and_cmyk():
    # DeviceGray single value (float or 1-tuple) — a common way grey text is set.
    assert os_._pdf_luma(0.8) == 0.8
    assert os_._pdf_luma((0.8,)) == 0.8
    # RGB.
    assert round(os_._pdf_luma((0.1, 0.1, 0.1)), 2) == 0.1
    # CMYK light-grey (0,0,0,0.1) must read ~0.9 (light), not 0 (a bare RGB slice
    # of the CMYK tuple mis-read it as pure black → never flagged).
    assert round(os_._pdf_luma((0, 0, 0, 0.1)), 2) == 0.9


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
    fonts = '<font><color rgb="00000000"/></font>'
    fills = '<fill><patternFill/></fill>'
    xfs = '<xf fontId="0" fillId="0"/>'
    xlsx_path = _xlsx(tmp_path, _xlsx_cell("A1", 0, "fine"), fonts, fills, xfs)
    assert os_.checks_for(xlsx_path, ".xlsx") == []
