"""1.4.11 non-text contrast must judge a header/footer shape like the body's.

`docx_nontext_contrast_checks` measures the outline-on-fill contrast of DrawingML shapes and, when
one is below 3:1, raises a Review finding so a human can decide whether that shape conveys meaning.
It read `word/document.xml` alone — but a banner shape or a rule line drawn into a running HEADER
or FOOTER (a very common home for exactly those graphics) has the same faint boundary and the same
1.4.11 question. Reading document.xml alone was the same header/footer blind spot #214 closed for
link purpose (2.4.4), #226 for language of parts (3.1.2), #227 for use of colour (1.4.1) and #229
for form controls — `_DOCX_STORY_PART` is that same set of parts.

The detector reports only the single WORST shape across the whole document, so widening the scan to
headers/footers cannot multiply findings — it can only surface the worst shape when that shape lives
in a header. The body cases here are controls: they prove the header/footer coverage is new reach,
not a change to what the body already did, and that a body-only document is verdict-neutral.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import office_structure as osx  # noqa: E402

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
WPS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"


def _shape(border_hex: str, fill_hex: str) -> str:
    """A DrawingML text-box shape whose outline is `border_hex` over a `fill_hex` fill — the same
    `<wps:spPr>` / `<a:ln>` structure Word emits and the detector matches on."""
    return (
        f'<wps:wsp xmlns:wps="{WPS}" xmlns:a="{A}"><wps:spPr>'
        f'<a:ln><a:solidFill><a:srgbClr val="{border_hex}"/></a:solidFill></a:ln>'
        f'<a:solidFill><a:srgbClr val="{fill_hex}"/></a:solidFill>'
        f'</wps:spPr></wps:wsp>'
    )


def _build(path: Path, *, where: str, border_hex: str, fill_hex: str) -> Path:
    """A docx with one shape. `where` places it in the body, a header, or a footer; the two other
    stories are left empty so the shape is the only one in the document."""
    shape = _shape(border_hex, fill_hex)
    with zipfile.ZipFile(path, "w") as z:
        body = shape if where == "body" else ""
        z.writestr("word/document.xml",
                   f'<w:document xmlns:w="{W}"><w:body><w:p>{body}</w:p></w:body></w:document>')
        if where == "header":
            z.writestr("word/header1.xml", f'<w:hdr xmlns:w="{W}"><w:p>{shape}</w:p></w:hdr>')
        if where == "footer":
            z.writestr("word/footer1.xml", f'<w:ftr xmlns:w="{W}"><w:p>{shape}</w:p></w:ftr>')
    return path


def _fires_1411(path: Path) -> bool:
    return any(f.get("ruleId") == "DOCX_NONTEXT_LOW_CONTRAST"
               for f in osx.docx_nontext_contrast_checks(path))


# faint: #C8C8C8 outline on a #FFFFFF fill is ~1.6:1, well under 3:1.
FAINT = ("C8C8C8", "FFFFFF")
# strong: #000000 outline on a #FFFFFF fill is 21:1, comfortably over 3:1.
STRONG = ("000000", "FFFFFF")


def test_faint_shape_in_body_fires(tmp_path):
    """Control: a faint-outline shape in the body is below 3:1 — as it always has been."""
    assert _fires_1411(_build(tmp_path / "body_faint.docx", where="body", border_hex=FAINT[0], fill_hex=FAINT[1]))


def test_strong_shape_in_body_does_not_fire(tmp_path):
    """Control: a shape whose outline clears 3:1 is not a finding, in the body."""
    assert not _fires_1411(_build(tmp_path / "body_strong.docx", where="body", border_hex=STRONG[0], fill_hex=STRONG[1]))


def test_faint_shape_in_header_fires(tmp_path):
    """The blind spot: a faint-outline banner shape in a running header must raise 1.4.11 — the
    body carries no shape at all, so a body-only scan would have said nothing."""
    assert _fires_1411(_build(tmp_path / "header_faint.docx", where="header", border_hex=FAINT[0], fill_hex=FAINT[1]))


def test_faint_shape_in_footer_fires(tmp_path):
    """A faint rule line drawn into a page footer is the same defect in the same place-that-was-missed."""
    assert _fires_1411(_build(tmp_path / "footer_faint.docx", where="footer", border_hex=FAINT[0], fill_hex=FAINT[1]))


def test_strong_shape_in_header_does_not_fire(tmp_path):
    """A header shape that clears 3:1 stays silent — the widened scan reaches headers, it does not
    lower the bar there."""
    assert not _fires_1411(_build(tmp_path / "header_strong.docx", where="header", border_hex=STRONG[0], fill_hex=STRONG[1]))


def test_a_document_with_no_shapes_is_silent(tmp_path):
    """Verdict-neutral for the common case: no DrawingML shapes anywhere, no finding."""
    p = tmp_path / "plain.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="{W}"><w:body><w:p/></w:body></w:document>')
        z.writestr("word/header1.xml", f'<w:hdr xmlns:w="{W}"><w:p/></w:hdr>')
    assert not _fires_1411(p)
