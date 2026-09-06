"""Tests for apply_pptx_slide_titles — the write-back for pptx 2.4.6 slide titles."""
from __future__ import annotations

import io
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import apply_pptx_slide_titles as _mod  # noqa: E402

_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _pptx(slides: dict[int, str]) -> bytes:
    """Build a minimal pptx.  slides maps slide number → slide XML string."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for num, xml in slides.items():
            z.writestr(f"ppt/slides/slide{num}.xml", xml)
    return buf.getvalue()


def _read_slide(data: bytes, num: int) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return z.read(f"ppt/slides/slide{num}.xml").decode()


def _slide_with_empty_title() -> str:
    return (
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
        ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<p:cSld><p:spTree><p:grpSpPr/>'
        '<p:sp>'
        '<p:nvSpPr>'
        '<p:cNvPr id="2" name="Title 1"/>'
        '<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
        '<p:nvPr><p:ph type="title"/></p:nvPr>'
        '</p:nvSpPr>'
        '<p:spPr/>'
        '<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr/></a:p></p:txBody>'
        '</p:sp>'
        '</p:spTree></p:cSld></p:sld>'
    )


def _slide_without_title() -> str:
    return (
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
        ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<p:cSld><p:spTree><p:grpSpPr/>'
        '<p:sp>'
        '<p:nvSpPr><p:cNvPr id="3" name="Content"/>'
        '<p:cNvSpPr/><p:nvPr><p:ph idx="1"/></p:nvPr>'
        '</p:nvSpPr>'
        '<p:spPr/>'
        '<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>Body text</a:t></a:r></a:p></p:txBody>'
        '</p:sp>'
        '</p:spTree></p:cSld></p:sld>'
    )


# ── basic write-back ───────────────────────────────────────────────────────────

def test_fills_empty_title_placeholder():
    data = _pptx({1: _slide_with_empty_title()})
    fixed, applied, unresolved = _mod.apply_pptx_slide_titles(data, {"slide 1": "Quarterly Results"})
    xml = _read_slide(fixed, 1)
    assert "Quarterly Results" in xml
    assert len(applied) == 1
    assert applied[0]["locator"] == "slide 1"
    assert applied[0]["after"] == "Quarterly Results"
    assert unresolved == []


def test_leaves_slide_without_title_placeholder_unresolved():
    data = _pptx({1: _slide_without_title()})
    fixed, applied, unresolved = _mod.apply_pptx_slide_titles(data, {"slide 1": "Some Title"})
    assert applied == []
    assert "slide 1" in unresolved


def test_multiple_slides_only_matching_one_written():
    data = _pptx({1: _slide_with_empty_title(), 2: _slide_without_title()})
    fixed, applied, unresolved = _mod.apply_pptx_slide_titles(
        data, {"slide 1": "Executive Summary", "slide 2": "Details"}
    )
    xml1 = _read_slide(fixed, 1)
    assert "Executive Summary" in xml1
    assert len(applied) == 1
    assert applied[0]["locator"] == "slide 1"
    # slide 2 has no title placeholder → unresolved
    assert "slide 2" in unresolved


def test_xml_special_chars_escaped():
    data = _pptx({1: _slide_with_empty_title()})
    fixed, applied, _ = _mod.apply_pptx_slide_titles(
        data, {"slide 1": "Q&A Results < 2024 >"}
    )
    xml = _read_slide(fixed, 1)
    assert "Q&amp;A Results &lt; 2024 &gt;" in xml
    assert len(applied) == 1


def test_nonexistent_slide_number_unresolved():
    data = _pptx({1: _slide_with_empty_title()})
    fixed, applied, unresolved = _mod.apply_pptx_slide_titles(
        data, {"slide 99": "Missing"}
    )
    assert applied == []
    assert "slide 99" in unresolved


def test_empty_values_returns_original_unchanged():
    data = _pptx({1: _slide_with_empty_title()})
    fixed, applied, unresolved = _mod.apply_pptx_slide_titles(data, {})
    assert fixed == data
    assert applied == []
    assert unresolved == []


def test_invalid_locator_format_unresolved():
    data = _pptx({1: _slide_with_empty_title()})
    fixed, applied, unresolved = _mod.apply_pptx_slide_titles(
        data, {"pptx:slide:1": "Bad Locator"}
    )
    assert applied == []
    assert "pptx:slide:1" in unresolved


def test_other_parts_preserved_unchanged():
    """Non-slide parts in the zip must survive unmodified."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("ppt/slides/slide1.xml", _slide_with_empty_title())
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("ppt/presentation.xml", "<Presentation/>")
    data = buf.getvalue()
    fixed, applied, _ = _mod.apply_pptx_slide_titles(data, {"slide 1": "Title"})
    with zipfile.ZipFile(io.BytesIO(fixed)) as z:
        assert z.read("[Content_Types].xml") == b"<Types/>"
        assert z.read("ppt/presentation.xml") == b"<Presentation/>"
    assert len(applied) == 1
