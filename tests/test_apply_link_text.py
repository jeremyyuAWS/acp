"""Writing an approved link text into an Office package (WCAG 2.4.4 / 2.4.9).

Mirrors test_apply_alt.py's guarantees for the link-text write-back lane: the value a human
signed their name to lands on the hyperlink(s) pointing at the approved href, an unresolvable
href is reported rather than guessed at, and a document we could not change comes back
byte-identical.
"""
from __future__ import annotations
import io
import sys
import zipfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

from apply_link_text import apply_link_text  # noqa: E402

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
{rels}
</Relationships>"""

_REL = ('<Relationship Id="{rid}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
        'Target="{target}" TargetMode="External"/>')


def _pkg(parts: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, body in parts.items():
            z.writestr(n, body)
    return buf.getvalue()


def _part(data: bytes, name: str) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return z.read(name).decode("utf-8")


# ── docx ──────────────────────────────────────────────────────────────────────

def _docx(body: str, rels: str) -> bytes:
    return _pkg({
        "word/document.xml": f'<w:document><w:body>{body}</w:body></w:document>',
        "word/_rels/document.xml.rels": _RELS.format(rels=rels),
    })


def test_docx_approved_text_lands_on_the_right_hyperlink():
    data = _docx(
        '<w:hyperlink r:id="rId1"><w:r><w:t>click here</w:t></w:r></w:hyperlink>',
        _REL.format(rid="rId1", target="https://example.com/pricing"))
    out, applied, unresolved = apply_link_text(data, "docx", {"https://example.com/pricing": "Pricing details"})
    assert unresolved == []
    assert applied == [{"locator": "https://example.com/pricing",
                        "before": "click here", "after": "Pricing details"}]
    xml = _part(out, "word/document.xml")
    assert "<w:t xml:space=\"preserve\">Pricing details</w:t>" in xml
    assert "click here" not in xml


def test_docx_preserves_run_formatting():
    data = _docx(
        '<w:hyperlink r:id="rId1"><w:r><w:rPr><w:b/></w:rPr><w:t>click here</w:t></w:r></w:hyperlink>',
        _REL.format(rid="rId1", target="https://example.com/x"))
    out, _, _ = apply_link_text(data, "docx", {"https://example.com/x": "Learn more about X"})
    xml = _part(out, "word/document.xml")
    assert "<w:rPr><w:b/></w:rPr>" in xml
    assert "Learn more about X" in xml


def test_docx_multiple_hyperlinks_to_same_href_all_rewritten():
    data = _docx(
        '<w:hyperlink r:id="rId1"><w:r><w:t>click here</w:t></w:r></w:hyperlink>'
        '<w:hyperlink r:id="rId1"><w:r><w:t>click here</w:t></w:r></w:hyperlink>',
        _REL.format(rid="rId1", target="https://example.com/pricing"))
    out, applied, _ = apply_link_text(data, "docx", {"https://example.com/pricing": "Pricing details"})
    assert len(applied) == 2
    xml = _part(out, "word/document.xml")
    assert xml.count("Pricing details") == 2


def test_docx_reviewer_text_is_xml_escaped():
    data = _docx(
        '<w:hyperlink r:id="rId1"><w:r><w:t>click here</w:t></w:r></w:hyperlink>',
        _REL.format(rid="rId1", target="https://example.com/x"))
    out, applied, _ = apply_link_text(data, "docx", {"https://example.com/x": "Q&A <details>"})
    xml = _part(out, "word/document.xml")
    assert "Q&amp;A &lt;details&gt;" in xml
    assert applied[0]["after"] == "Q&A <details>"          # reported unescaped, as written


# ── pptx ──────────────────────────────────────────────────────────────────────

def _pptx(slide_body: str, rels: str) -> bytes:
    return _pkg({
        "ppt/slides/slide1.xml": f'<p:sld><p:cSld>{slide_body}</p:cSld></p:sld>',
        "ppt/slides/_rels/slide1.xml.rels": _RELS.format(rels=rels),
    })


def test_pptx_approved_text_lands_on_the_right_run():
    data = _pptx(
        '<a:r><a:rPr><a:hlinkClick r:id="rId1"/></a:rPr><a:t>click here</a:t></a:r>',
        _REL.format(rid="rId1", target="https://example.com/pricing"))
    out, applied, unresolved = apply_link_text(data, "pptx", {"https://example.com/pricing": "Pricing details"})
    assert unresolved == []
    assert applied == [{"locator": "https://example.com/pricing",
                        "before": "click here", "after": "Pricing details"}]
    xml = _part(out, "ppt/slides/slide1.xml")
    assert "<a:hlinkClick r:id=\"rId1\"/>" in xml     # rPr (and the hlinkClick inside it) survives
    assert "<a:t>Pricing details</a:t>" in xml
    assert "click here" not in xml


def test_pptx_run_without_hyperlink_untouched():
    data = _pptx(
        '<a:r><a:t>ordinary text</a:t></a:r>'
        '<a:r><a:rPr><a:hlinkClick r:id="rId1"/></a:rPr><a:t>click here</a:t></a:r>',
        _REL.format(rid="rId1", target="https://example.com/x"))
    out, applied, _ = apply_link_text(data, "pptx", {"https://example.com/x": "Learn more"})
    assert len(applied) == 1
    xml = _part(out, "ppt/slides/slide1.xml")
    assert "<a:t>ordinary text</a:t>" in xml
    assert "<a:t>Learn more</a:t>" in xml


# ── xlsx ──────────────────────────────────────────────────────────────────────

def _xlsx(sheet_body: str, rels: str) -> bytes:
    return _pkg({
        "xl/worksheets/sheet1.xml": f'<worksheet>{sheet_body}</worksheet>',
        "xl/worksheets/_rels/sheet1.xml.rels": _RELS.format(rels=rels),
    })


def test_xlsx_approved_text_lands_on_the_right_cell_hyperlink():
    data = _xlsx(
        '<hyperlinks><hyperlink ref="A1" r:id="rId1" display="click here"/></hyperlinks>',
        _REL.format(rid="rId1", target="https://example.com/pricing"))
    out, applied, unresolved = apply_link_text(data, "xlsx", {"https://example.com/pricing": "Pricing details"})
    assert unresolved == []
    assert applied == [{"locator": "https://example.com/pricing",
                        "before": "click here", "after": "Pricing details"}]
    xml = _part(out, "xl/worksheets/sheet1.xml")
    assert 'display="Pricing details"' in xml
    assert 'ref="A1"' in xml                          # cell reference untouched
    assert "click here" not in xml


def test_xlsx_reviewer_text_is_attribute_escaped():
    data = _xlsx(
        '<hyperlinks><hyperlink ref="A1" r:id="rId1" display="click here"/></hyperlinks>',
        _REL.format(rid="rId1", target="https://example.com/x"))
    out, _, _ = apply_link_text(data, "xlsx", {"https://example.com/x": 'Say "hello" & go'})
    xml = _part(out, "xl/worksheets/sheet1.xml")
    assert 'display="Say &quot;hello&quot; &amp; go"' in xml


# ── shared guarantees ───────────────────────────────────────────────────────

def test_unresolvable_hrefs_are_reported_never_guessed():
    data = _docx(
        '<w:hyperlink r:id="rId1"><w:r><w:t>click here</w:t></w:r></w:hyperlink>',
        _REL.format(rid="rId1", target="https://example.com/real"))
    out, applied, unresolved = apply_link_text(data, "docx", {
        "https://example.com/real": "Pricing details",
        "https://example.com/ghost": "a link that is not there",
    })
    assert [a["locator"] for a in applied] == ["https://example.com/real"]
    assert unresolved == ["https://example.com/ghost"]


def test_nothing_to_apply_returns_the_original_bytes_unchanged():
    data = _docx(
        '<w:hyperlink r:id="rId1"><w:r><w:t>click here</w:t></w:r></w:hyperlink>',
        _REL.format(rid="rId1", target="https://example.com/real"))
    for values in ({}, None, {"https://example.com/real": "   "}, {"https://example.com/ghost": "x"}):
        out, applied, _ = apply_link_text(data, "docx", values)
        if values and any((v or "").strip() for v in values.values()):
            assert applied == []                          # ghost href never resolves
        assert out == data or applied == []


def test_unsupported_format_reports_every_href_unresolved():
    out, applied, unresolved = apply_link_text(b"%PDF-1.4", "pdf", {"https://example.com/x": "text"})
    assert out == b"%PDF-1.4"
    assert applied == []
    assert unresolved == ["https://example.com/x"]


def test_untouched_parts_survive_the_rewrite_byte_for_byte():
    png = b"\x89PNG\r\n\x1a\n-not-really"
    data = _pkg({
        "word/document.xml": ('<w:document><w:body>'
                               '<w:hyperlink r:id="rId1"><w:r><w:t>click here</w:t></w:r></w:hyperlink>'
                               '</w:body></w:document>'),
        "word/_rels/document.xml.rels": _RELS.format(
            rels=_REL.format(rid="rId1", target="https://example.com/real")),
        "word/media/image1.png": png,
    })
    out, _, _ = apply_link_text(data, "docx", {"https://example.com/real": "Pricing details"})
    with zipfile.ZipFile(io.BytesIO(out)) as z:
        assert z.read("word/media/image1.png") == png
