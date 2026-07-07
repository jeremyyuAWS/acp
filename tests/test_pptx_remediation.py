"""pptx accessibility remediation + contrast detection.

Self-contained: slides are crafted as XML fragments / a minimal in-memory zip, so
the tests don't depend on the .NET engine or on fixture files the concurrent
corpus reorg churns. They verify the transforms office_structure /
remediate_office apply, which the end-to-end engine re-scan already confirmed
clear the findings on a real deck.
"""
from __future__ import annotations
import io
import re
import sys
import zipfile
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import office_structure as osx          # noqa: E402
import remediate_office as rem          # noqa: E402


def _slide(*shapes: str) -> str:
    inner = "".join(shapes)
    return (
        '<?xml version="1.0"?>'
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
        ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        f"<p:cSld><p:spTree><p:nvGrpSpPr/><p:grpSpPr/>{inner}</p:spTree></p:cSld></p:sld>"
    )


def _shape(*, fill: str | None = None, text: str = "", color: str | None = None, y: int = 0) -> str:
    sppr_fill = f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>' if fill else ""
    sppr = f'<p:spPr><a:xfrm><a:off x="0" y="{y}"/><a:ext cx="1" cy="1"/></a:xfrm>{sppr_fill}</p:spPr>'
    rpr = f'<a:rPr><a:solidFill><a:srgbClr val="{color}"/></a:solidFill></a:rPr>' if color else "<a:rPr/>"
    body = f"<p:txBody><a:p><a:r>{rpr}<a:t>{text}</a:t></a:r></a:p></p:txBody>" if text else ""
    return f"<p:sp><p:nvSpPr/>{sppr}{body}</p:sp>"


def _pptx_from(slide_xml: str, tmp_path: Path) -> Path:
    p = tmp_path / "deck.pptx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("ppt/slides/slide1.xml", slide_xml)
    return p


# ── contrast detection (office_structure) ─────────────────────────────────────
def test_contrast_ratio_matches_wcag():
    # white on the brand orange from the real deck fails AA; black on white is max.
    assert round(osx._contrast_ratio("F07D00", "FFFFFF"), 2) == 2.75
    assert round(osx._contrast_ratio("FFFFFF", "000000"), 1) == 21.0


def test_pptx_contrast_flags_low_contrast(tmp_path):
    slide = _slide(_shape(fill="F07D00", text="Low contrast label", color="FFFFFF"))
    findings = osx.pptx_contrast_checks(_pptx_from(slide, tmp_path))
    wcags = {f["wcag"] for f in findings}
    assert "1.4.3 Contrast (Minimum)" in wcags        # 2.75:1 < 3.0 large-text AA
    assert "1.4.6 Contrast (Enhanced)" in wcags
    assert "2.7:1" in findings[0]["detail"] and "#F07D00" in findings[0]["detail"]


def test_pptx_contrast_passes_high_contrast(tmp_path):
    slide = _slide(_shape(fill="FFFFFF", text="Readable", color="000000"))
    assert osx.pptx_contrast_checks(_pptx_from(slide, tmp_path)) == []


def test_pptx_contrast_skips_text_without_explicit_fill(tmp_path):
    # No shape fill -> background is inherited/unknown -> not guessed (conservative).
    slide = _slide(_shape(text="on unknown background", color="FFFFFF"))
    assert osx.pptx_contrast_checks(_pptx_from(slide, tmp_path)) == []


# ── remediation transforms (remediate_office) ─────────────────────────────────
def test_add_title_to_titleless_slide():
    slide = _slide(_shape(text="Body only", color="000000", fill="FFFFFF"))
    assert not rem._pptx_has_title(slide)
    fixed = rem._pptx_add_title(slide, "Derived Title")
    assert rem._pptx_has_title(fixed)
    assert 'type="title"' in fixed and "Derived Title" in fixed


def test_remediate_pptx_slides_applies_all_three():
    # One slide: no title, a low-contrast run, and two shapes out of reading order.
    slide = _slide(
        _shape(fill="F07D00", text="brand banner", color="FFFFFF", y=5_000_000),
        _shape(fill="FFFFFF", text="body text", color="000000", y=100_000),
    )
    entries = {"ppt/slides/slide1.xml": slide.encode("utf-8")}
    applied = rem._remediate_pptx_slides(entries)
    joined = " | ".join(applied)
    assert "title" in joined and "contrast" in joined and "reading order" in joined

    out = entries["ppt/slides/slide1.xml"].decode("utf-8")
    assert rem._pptx_has_title(out)
    # the white run on the orange fill was recoloured (>=4.5:1 -> black on this orange).
    orange_sp = re.search(r'val="F07D00".*?</p:sp>', out, re.S).group(0)
    assert 'srgbClr val="FFFFFF"' not in orange_sp
    assert 'srgbClr val="000000"' in orange_sp


def test_reorder_sorts_shapes_by_visual_position():
    # Already titled + high contrast, so ONLY the reorder fires; distinct markers.
    titled = (
        '<p:sp><p:nvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>'
        '<p:spPr><a:xfrm><a:off x="0" y="-9"/><a:ext cx="1" cy="1"/></a:xfrm></p:spPr>'
        "<p:txBody><a:p><a:r><a:rPr/><a:t>The Title</a:t></a:r></a:p></p:txBody></p:sp>"
    )
    slide = _slide(
        titled,
        _shape(fill="FFFFFF", text="MARKER_BOTTOM", color="000000", y=9_000_000),
        _shape(fill="FFFFFF", text="MARKER_TOP", color="000000", y=100_000),
    )
    entries = {"ppt/slides/slide1.xml": slide.encode("utf-8")}
    applied = rem._remediate_pptx_slides(entries)
    assert any("reading order" in a for a in applied)
    assert not any("title" in a or "contrast" in a for a in applied)   # neither needed
    out = entries["ppt/slides/slide1.xml"].decode("utf-8")
    assert out.index("MARKER_TOP") < out.index("MARKER_BOTTOM")


def test_remediate_pptx_slides_noop_on_compliant_slide():
    # Titled, high-contrast, single shape, already ordered -> no contrast/title work.
    slide = (
        '<?xml version="1.0"?>'
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
        ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        "<p:cSld><p:spTree><p:nvGrpSpPr/><p:grpSpPr/>"
        '<p:sp><p:nvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>'
        '<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="1" cy="1"/></a:xfrm></p:spPr>'
        "<p:txBody><a:p><a:r><a:rPr/><a:t>Real Title</a:t></a:r></a:p></p:txBody></p:sp>"
        "</p:spTree></p:cSld></p:sld>"
    )
    entries = {"ppt/slides/slide1.xml": slide.encode("utf-8")}
    applied = rem._remediate_pptx_slides(entries)
    assert not any("title" in a or "contrast" in a for a in applied)
