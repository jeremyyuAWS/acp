"""Relationship parsing must not depend on attribute ORDER.

XML attributes are unordered and .rels writers disagree: Word/PowerPoint emit
Id first, openpyxl emits Type/Target/TargetMode/Id — Id LAST. A regex that
required Id-then-Target matched the first family and silently returned {} for
the second, so every openpyxl-written workbook lost all its hyperlinks (no
2.4.9 duplicate-href detection, no 2.4.4 link-text proposals). Each test below
builds the SAME fixture twice — Id first and Id last — and asserts identical
results.
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import office_structure as os_  # noqa: E402
import proposals as prop  # noqa: E402

_RELNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_RELNS = "http://schemas.openxmlformats.org/package/2006/relationships"

_ID_FIRST = '<Relationship Id="{rid}" Type="{ns}/hyperlink" Target="{target}" TargetMode="External"/>'
_ID_LAST = '<Relationship Type="{ns}/hyperlink" Target="{target}" TargetMode="External" Id="{rid}"/>'  # openpyxl's order


def _rels(order: str, pairs: list[tuple[str, str]]) -> str:
    tmpl = _ID_FIRST if order == "id-first" else _ID_LAST
    body = "".join(tmpl.format(rid=rid, ns=_RELNS, target=t) for rid, t in pairs)
    return f'<?xml version="1.0"?><Relationships xmlns="{_PKG_RELNS}">{body}</Relationships>'


def _zip(path: Path, parts: dict[str, str]) -> Path:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, xml in parts.items():
            zf.writestr(name, xml)
    path.write_bytes(buf.getvalue())
    return path


# ── the parser itself ──────────────────────────────────────────────────────────

def test_relationships_reads_both_attribute_orders(tmp_path):
    pairs = [("rId1", "https://a.example/one"), ("rId2", "https://b.example/two")]
    expected = dict(pairs)
    for order in ("id-first", "id-last"):
        p = _zip(tmp_path / f"{order}.docx", {"word/_rels/document.xml.rels": _rels(order, pairs)})
        with zipfile.ZipFile(p) as zf:
            assert os_._relationships(zf, "word/_rels/document.xml.rels") == expected, order


def test_target_mode_is_not_mistaken_for_target(tmp_path):
    # TargetMode precedes Target in the Id-last form; a loose attribute match would
    # capture "External" as the href.
    p = _zip(tmp_path / "tm.docx", {"word/_rels/document.xml.rels": _rels("id-last", [("rId1", "https://a.example/x")])})
    with zipfile.ZipFile(p) as zf:
        assert os_._relationships(zf, "word/_rels/document.xml.rels") == {"rId1": "https://a.example/x"}


# ── docx: 2.4.9 duplicate-href detection + link-text proposals ─────────────────

_DOC_XML = (
    '<?xml version="1.0"?><w:document xmlns:w="w" xmlns:r="r"><w:body>'
    '<w:p><w:hyperlink r:id="rId1"><w:r><w:t>click here</w:t></w:r></w:hyperlink></w:p>'
    '<w:p><w:hyperlink r:id="rId2"><w:r><w:t>click here</w:t></w:r></w:hyperlink></w:p>'
    "</w:body></w:document>"
)
_DOC_PAIRS = [("rId1", "https://a.example/one"), ("rId2", "https://b.example/two")]


def _docx(tmp_path: Path, order: str) -> Path:
    return _zip(tmp_path / f"{order}.docx", {
        "word/document.xml": _DOC_XML,
        "word/_rels/document.xml.rels": _rels(order, _DOC_PAIRS),
    })


def test_docx_ambiguous_link_detected_with_id_last_rels(tmp_path):
    for order in ("id-first", "id-last"):
        ids = [f["ruleId"] for f in os_.docx_checks(_docx(tmp_path, order))]
        assert "DOCX_LINK_PURPOSE_AMBIGUOUS" in ids, order


def test_docx_links_extracted_with_id_last_rels(tmp_path):
    expected = [("click here", "https://a.example/one"), ("click here", "https://b.example/two")]
    for order in ("id-first", "id-last"):
        assert prop.extract_office_links(_docx(tmp_path, order), "docx") == expected, order


# ── pptx: same, per slide ──────────────────────────────────────────────────────

_SLIDE_XML = (
    '<?xml version="1.0"?><p:sld xmlns:p="p" xmlns:a="a" xmlns:r="r">'
    '<a:r><a:rPr><a:hlinkClick r:id="rId1"/></a:rPr><a:t>click here</a:t></a:r>'
    '<a:r><a:rPr><a:hlinkClick r:id="rId2"/></a:rPr><a:t>click here</a:t></a:r>'
    "</p:sld>"
)


def _pptx(tmp_path: Path, order: str) -> Path:
    return _zip(tmp_path / f"{order}.pptx", {
        "ppt/slides/slide1.xml": _SLIDE_XML,
        "ppt/slides/_rels/slide1.xml.rels": _rels(order, _DOC_PAIRS),
    })


def test_pptx_ambiguous_link_detected_with_id_last_rels(tmp_path):
    for order in ("id-first", "id-last"):
        ids = [f["ruleId"] for f in os_.pptx_checks(_pptx(tmp_path, order))]
        assert "PPTX_LINK_PURPOSE_AMBIGUOUS" in ids, order


def test_pptx_links_extracted_with_id_last_rels(tmp_path):
    expected = [("click here", "https://a.example/one"), ("click here", "https://b.example/two")]
    for order in ("id-first", "id-last"):
        assert prop.extract_office_links(_pptx(tmp_path, order), "pptx") == expected, order


# ── xlsx: cell hyperlinks (the openpyxl case that lost everything) ─────────────

def _xlsx(tmp_path: Path, order: str) -> Path:
    ws = ('<?xml version="1.0"?><worksheet xmlns:r="r"><sheetData/><hyperlinks>'
          '<hyperlink ref="A1" r:id="rId1" display="click here"/>'
          '</hyperlinks></worksheet>')
    return _zip(tmp_path / f"{order}.xlsx", {
        "xl/workbook.xml": '<workbook><sheets><sheet name="Sheet1"/></sheets></workbook>',
        "xl/worksheets/sheet1.xml": ws,
        "xl/worksheets/_rels/sheet1.xml.rels": _rels(order, [("rId1", "mailto:sales@acme.com")]),
    })


def test_xlsx_links_extracted_with_id_last_rels(tmp_path):
    for order in ("id-first", "id-last"):
        assert prop.extract_office_links(_xlsx(tmp_path, order), "xlsx") == [
            ("click here", "mailto:sales@acme.com")], order


def test_xlsx_vague_link_proposal_survives_id_last_rels(tmp_path):
    for order in ("id-first", "id-last"):
        props = prop.propose_link_texts(_xlsx(tmp_path, order), "xlsx", ai_enabled=False)
        assert props and props[0]["proposed_value"] == "Email sales@acme.com", order
