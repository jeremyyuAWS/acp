"""Phase 1b Review-Recommended detectors (ADR 0023): 1.4.1 Use of Color, 2.4.3 Focus Order,
1.4.11 Non-text Contrast. Each emits an advisory REVIEW finding (severity REVIEW) with concrete
evidence when its signal is present, and nothing when it isn't — never a fabricated pass.

Hand-built zip/XML fixtures (same posture as test_office_structure_controls.py).
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import office_structure as os_  # noqa: E402


def _zip(tmp: Path, name: str, parts: dict[str, str]) -> Path:
    p = tmp / name
    with zipfile.ZipFile(p, "w") as z:
        for n, data in parts.items():
            z.writestr(n, data)
    return p


def _sheet(inner: str) -> str:
    return ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetData/>' + inner + '</worksheet>')


def _slide(*shapes: str) -> str:
    return f'<p:sld><p:cSld><p:spTree>{"".join(shapes)}</p:spTree></p:cSld></p:sld>'


def _sp(ph_type: str | None = None, spPr: str = "") -> str:
    ph = f'<p:ph type="{ph_type}"/>' if ph_type else ""
    return f'<p:sp><p:nvSpPr><p:nvPr>{ph}</p:nvPr></p:nvSpPr><p:spPr>{spPr}</p:spPr></p:sp>'


def _wcags(findings):
    return {f["wcag"] for f in findings}


def _all_review(findings):
    return all(f["severity"] == "REVIEW" and f.get("advisory") is True for f in findings)


# ── 1.4.1 Use of Color ───────────────────────────────────────────────────────
def test_xlsx_color_scale_flags_use_of_color(tmp_path):
    sheet = _sheet('<conditionalFormatting sqref="A1:A9"><cfRule type="colorScale" priority="1">'
                   '<colorScale/></cfRule></conditionalFormatting>')
    p = _zip(tmp_path, "cf.xlsx", {"xl/worksheets/sheet1.xml": sheet})
    f = os_.office_color_only_checks(p, ".xlsx")
    assert _wcags(f) == {"1.4.1 Use of Color"} and _all_review(f)
    assert "1 conditional-formatting rule" in f[0]["detail"]


def test_xlsx_dxf_fill_rule_flags(tmp_path):
    sheet = _sheet('<conditionalFormatting sqref="B1"><cfRule type="cellIs" dxfId="0" operator="greaterThan">'
                   '<formula>5</formula></cfRule></conditionalFormatting>')
    p = _zip(tmp_path, "dxf.xlsx", {"xl/worksheets/sheet1.xml": sheet})
    assert os_.office_color_only_checks(p, ".xlsx")


def test_xlsx_icon_set_is_not_color_only(tmp_path):
    # iconSet pairs colour WITH an icon → NOT colour-only, must not flag.
    sheet = _sheet('<conditionalFormatting sqref="C1"><cfRule type="iconSet" priority="1">'
                   '<iconSet/></cfRule></conditionalFormatting>')
    p = _zip(tmp_path, "icon.xlsx", {"xl/worksheets/sheet1.xml": sheet})
    assert os_.office_color_only_checks(p, ".xlsx") == []


def test_xlsx_no_conditional_formatting_is_silent(tmp_path):
    p = _zip(tmp_path, "plain.xlsx", {"xl/worksheets/sheet1.xml": _sheet("")})
    assert os_.office_color_only_checks(p, ".xlsx") == []


def test_docx_color_only_link_flags(tmp_path):
    doc = ('<w:document><w:body><w:p>'
           '<w:hyperlink r:id="rId1"><w:r><w:rPr><w:color w:val="0000FF"/><w:u w:val="none"/></w:rPr>'
           '<w:t>our report</w:t></w:r></w:hyperlink></w:p></w:body></w:document>')
    p = _zip(tmp_path, "link.docx", {"word/document.xml": doc})
    f = os_.office_color_only_checks(p, ".docx")
    assert _wcags(f) == {"1.4.1 Use of Color"} and _all_review(f)


def test_docx_underlined_link_not_flagged(tmp_path):
    doc = ('<w:document><w:body><w:p>'
           '<w:hyperlink r:id="rId1"><w:r><w:rPr><w:color w:val="0000FF"/><w:u w:val="single"/></w:rPr>'
           '<w:t>our report</w:t></w:r></w:hyperlink></w:p></w:body></w:document>')
    p = _zip(tmp_path, "ok.docx", {"word/document.xml": doc})
    assert os_.office_color_only_checks(p, ".docx") == []


# ── 2.4.3 Focus Order ────────────────────────────────────────────────────────
def test_pptx_title_not_first_flags_focus_order(tmp_path):
    xml = _slide(_sp("body"), _sp("title"))   # body placeholder before the title
    p = _zip(tmp_path, "order.pptx", {"ppt/slides/slide1.xml": xml})
    f = os_.pptx_focus_order_checks(p)
    assert _wcags(f) == {"2.4.3 Focus Order"} and _all_review(f)
    assert "slide 1" in f[0]["detail"]


def test_pptx_title_first_not_flagged(tmp_path):
    xml = _slide(_sp("title"), _sp("body"))
    p = _zip(tmp_path, "ok.pptx", {"ppt/slides/slide1.xml": xml})
    assert os_.pptx_focus_order_checks(p) == []


def test_pptx_single_placeholder_not_flagged(tmp_path):
    xml = _slide(_sp("title"))
    p = _zip(tmp_path, "one.pptx", {"ppt/slides/slide1.xml": xml})
    assert os_.pptx_focus_order_checks(p) == []


# ── 1.4.11 Non-text Contrast ─────────────────────────────────────────────────
_FILL = '<a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill>'


def test_pptx_faint_outline_flags_nontext_contrast(tmp_path):
    spPr = ('<a:ln><a:solidFill><a:srgbClr val="EEEEEE"/></a:solidFill></a:ln>' + _FILL)
    xml = _slide(_sp("body", spPr=spPr))
    p = _zip(tmp_path, "faint.pptx", {"ppt/slides/slide1.xml": xml})
    f = os_.pptx_nontext_contrast_checks(p)
    assert _wcags(f) == {"1.4.11 Non-text Contrast"} and _all_review(f)
    assert "EEEEEE" in f[0]["detail"] and "FFFFFF" in f[0]["detail"]


def test_pptx_high_contrast_outline_not_flagged(tmp_path):
    spPr = ('<a:ln><a:solidFill><a:srgbClr val="000000"/></a:solidFill></a:ln>' + _FILL)
    xml = _slide(_sp("body", spPr=spPr))
    p = _zip(tmp_path, "ok.pptx", {"ppt/slides/slide1.xml": xml})
    assert os_.pptx_nontext_contrast_checks(p) == []


def test_pptx_no_outline_not_flagged(tmp_path):
    xml = _slide(_sp("body", spPr=_FILL))
    p = _zip(tmp_path, "noln.pptx", {"ppt/slides/slide1.xml": xml})
    assert os_.pptx_nontext_contrast_checks(p) == []


def _docx_shape(spPr):
    """A word/document.xml carrying one DrawingML (<wps:wsp>) shape with the given <wps:spPr>."""
    return (f"<w:document><w:body><w:p><w:r><w:drawing><wp:inline><a:graphic><a:graphicData>"
            f"<wps:wsp><wps:spPr>{spPr}</wps:spPr></wps:wsp>"
            f"</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p></w:body></w:document>")


def test_docx_faint_shape_outline_flags_nontext_contrast(tmp_path):
    spPr = '<a:ln><a:solidFill><a:srgbClr val="EEEEEE"/></a:solidFill></a:ln>' + _FILL
    p = _zip(tmp_path, "faint.docx", {"word/document.xml": _docx_shape(spPr)})
    f = os_.docx_nontext_contrast_checks(p)
    assert _wcags(f) == {"1.4.11 Non-text Contrast"} and _all_review(f)
    assert "EEEEEE" in f[0]["detail"] and "FFFFFF" in f[0]["detail"]
    # routed through the docx dispatcher too
    assert any(x["wcag"].startswith("1.4.11") for x in os_.checks_for(p, ".docx"))


def test_docx_high_contrast_and_no_outline_not_flagged(tmp_path):
    ok = '<a:ln><a:solidFill><a:srgbClr val="000000"/></a:solidFill></a:ln>' + _FILL
    assert os_.docx_nontext_contrast_checks(_zip(tmp_path, "ok.docx", {"word/document.xml": _docx_shape(ok)})) == []
    assert os_.docx_nontext_contrast_checks(_zip(tmp_path, "noln.docx", {"word/document.xml": _docx_shape(_FILL)})) == []
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"not a zip")
    assert os_.docx_nontext_contrast_checks(bad) == []


# ── dispatcher wiring + robustness ───────────────────────────────────────────
def test_checks_for_routes_all_three(tmp_path):
    xlsx = _zip(tmp_path, "cf.xlsx", {"xl/worksheets/sheet1.xml": _sheet(
        '<conditionalFormatting sqref="A1"><cfRule type="colorScale"/></conditionalFormatting>')})
    assert any(f["wcag"].startswith("1.4.1") for f in os_.checks_for(xlsx, ".xlsx"))
    faint = ('<a:ln><a:solidFill><a:srgbClr val="EEEEEE"/></a:solidFill></a:ln>' + _FILL)
    pptx = _zip(tmp_path, "s.pptx", {"ppt/slides/slide1.xml": _slide(_sp("body", spPr=faint), _sp("title"))})
    pptx_scs = {f["wcag"] for f in os_.checks_for(pptx, ".pptx")}
    assert any(w.startswith("2.4.3") for w in pptx_scs)     # body-before-title focus order
    assert any(w.startswith("1.4.11") for w in pptx_scs)    # faint outline


def test_corrupt_zip_never_raises(tmp_path):
    p = tmp_path / "bad.xlsx"
    p.write_bytes(b"not a zip")
    assert os_.office_color_only_checks(p, ".xlsx") == []
    assert os_.pptx_focus_order_checks(p) == []
    assert os_.pptx_nontext_contrast_checks(p) == []
