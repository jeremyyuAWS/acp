"""1.4.1 use-of-color: pptx hyperlinks with their underline removed are colour-only.

DrawingML text runs that carry an <a:hlinkClick> AND <a:rPr u="none"> are set apart from
surrounding text by colour alone — a failure for colour-blind users. This mirrors the docx
branch of office_color_only_checks; the same logic applies to every slide part.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import office_structure as osx  # noqa: E402

def _run(text: str, *, underline_none: bool, has_hlink: bool) -> str:
    """One DrawingML text run. Namespaces declared at the slide root, not here.

    underline_none=True puts u="none" on <a:rPr> (the colour-only indicator);
    has_hlink=True adds an <a:hlinkClick> child — together that is the failing case.
    """
    hlink = '<a:hlinkClick r:id="rId1"/>' if has_hlink else ""
    u_attr = ' u="none"' if underline_none else ""
    return f'<a:r><a:rPr{u_attr}>{hlink}</a:rPr><a:t>{text}</a:t></a:r>'


def _slide(body: str) -> str:
    """Minimal slide XML with namespace declarations at the root, matching real PPTX layout."""
    return (
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
        ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<p:cSld><p:spTree><p:sp><p:txBody><a:p>{body}</a:p>'
        '</p:txBody></p:sp></p:spTree></p:cSld></p:sld>'
    )


def _build(path: Path, *, run_xml: str) -> Path:
    """Minimal PPTX with one slide containing run_xml."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("ppt/slides/slide1.xml", _slide(run_xml))
    return path


def _fires(path: Path) -> bool:
    return any(f.get("ruleId") == "PPTX_COLOR_ONLY_LINK"
               for f in osx.office_color_only_checks(path, ".pptx"))


def test_hlink_with_underline_removed_fires(tmp_path):
    """A hyperlink run with u="none" is colour-only — must fire PPTX_COLOR_ONLY_LINK."""
    p = _build(tmp_path / "colour_only.pptx",
               run_xml=_run("click here", underline_none=True, has_hlink=True))
    assert _fires(p)


def test_hlink_with_underline_kept_does_not_fire(tmp_path):
    """A hyperlink run without u="none" is not colour-only — must NOT fire."""
    p = _build(tmp_path / "underlined.pptx",
               run_xml=_run("click here", underline_none=False, has_hlink=True))
    assert not _fires(p)


def test_plain_run_with_underline_removed_does_not_fire(tmp_path):
    """u="none" without a hyperlink is just styled text — must NOT fire."""
    p = _build(tmp_path / "no_hlink.pptx",
               run_xml=_run("plain text", underline_none=True, has_hlink=False))
    assert not _fires(p)


def test_slide_with_no_links_does_not_fire(tmp_path):
    """A slide with no hyperlinks at all must NOT fire."""
    p = _build(tmp_path / "no_links.pptx", run_xml="<a:r><a:t>plain body text</a:t></a:r>")
    assert not _fires(p)


def test_multiple_colour_only_links_count_is_reported(tmp_path):
    """When several runs are colour-only, the evidence value reflects the count."""
    run = _run("link", underline_none=True, has_hlink=True)
    path = tmp_path / "three_links.pptx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("ppt/slides/slide1.xml", _slide(run + run + run))
    findings = osx.office_color_only_checks(path, ".pptx")
    assert len(findings) == 1
    assert findings[0]["evidence"]["value"] == 3


def test_colour_only_links_across_multiple_slides(tmp_path):
    """Links on slide 2 must be detected even when slide 1 has none."""
    empty_slide = (
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        '<p:cSld><p:spTree/></p:cSld></p:sld>'
    )
    path = tmp_path / "two_slides.pptx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("ppt/slides/slide1.xml", empty_slide)
        z.writestr("ppt/slides/slide2.xml",
                   _slide(_run("see here", underline_none=True, has_hlink=True)))
    assert _fires(path)
