"""Link-purpose (2.4.4) is judged in headers, footers and foot/endnotes — not only the body.

THE GAP THIS PINS, measured before it was closed. `office_structure.docx_checks` read exactly one
part, `word/document.xml`, and every link-purpose and heading check ran against that string alone.
A Word document keeps running-header text, page-footer text and footnote/endnote text in SEPARATE
parts (`word/header1.xml`, `word/footer1.xml`, `word/footnotes.xml`, `word/endnotes.xml`), so a
"click here" link sitting in a page footer — a common place for one — produced ZERO findings. Not
a pass, not a review: silence, indistinguishable from a document whose footer link is fine. That
is the worst direction to be wrong in, because nothing ever complains about a finding that was
never made.

Each case below plants a vague link in ONE part with a clean body, so a failure names the exact
part still unread rather than a general "links are missed". The body control proves the fixture is
not vacuous: a clean body on its own yields no 2.4.4 finding, so the finding that appears when a
part is added came from that part.

Built in memory rather than shipped as a binary: the trigger is a handful of bytes of OOXML, and
a constructed package shows precisely what is and is not present — a .docx checked into the tree
would hide its own contents behind a zip.
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import office_structure as os_  # noqa: E402

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _rels(target: str) -> str:
    return (f'<Relationships xmlns="{R}/relationships">'
            f'<Relationship Id="rId1" Type="{R}/hyperlink" Target="{target}" '
            f'TargetMode="External"/></Relationships>')


def _link_para(text: str) -> str:
    return f'<w:p><w:hyperlink r:id="rId1"><w:r><w:t>{text}</w:t></w:r></w:hyperlink></w:p>'


def _wrap(tag: str, body: str) -> str:
    return (f'<w:{tag} xmlns:w="{W}" xmlns:r="{R}">{body}</w:{tag}>')


def _doc(body: str) -> str:
    return f'<w:document xmlns:w="{W}" xmlns:r="{R}"><w:body>{body}</w:body></w:document>'


# A CLEAN body link — descriptive text, so the body alone trips no 2.4.4. Any finding therefore
# comes from the part under test, which is the whole point.
CLEAN_BODY = _doc(_link_para('Annual Benefits Report'))

# part name -> (part xml, its .rels), a vague link in that part and nothing in the body.
PARTS = {
    'header': ('word/header1.xml', _wrap('hdr', _link_para('click here'))),
    'footer': ('word/footer1.xml', _wrap('ftr', _link_para('click here'))),
    'footnote': ('word/footnotes.xml',
                 _wrap('footnotes', f'<w:footnote w:id="1">{_link_para("read more")}</w:footnote>')),
    'endnote': ('word/endnotes.xml',
                _wrap('endnotes', f'<w:endnote w:id="1">{_link_para("read more")}</w:endnote>')),
}


def _build(part_name: str | None, tmp_path: Path) -> Path:
    p = tmp_path / f"{part_name or 'bodyonly'}.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", CLEAN_BODY)
        z.writestr("word/_rels/document.xml.rels", _rels("https://example.org/report"))
        if part_name:
            part, xml = PARTS[part_name]
            z.writestr(part, xml)
            rels = part.replace("word/", "word/_rels/") + ".rels"
            z.writestr(rels, _rels("https://example.org/elsewhere"))
    return p


def _vague_2_4_4(path: Path) -> list[dict]:
    return [f for f in os_.docx_checks(path)
            if f["ruleId"] == "DOCX_LINK_PURPOSE_VAGUE" and f["wcag"].startswith("2.4.4")]


def test_a_clean_body_is_the_non_vacuous_control(tmp_path):
    """No part, descriptive body link -> no 2.4.4. If this ever fires, the cases below prove
    nothing, because the finding they check for would appear with no vague link present."""
    assert _vague_2_4_4(_build(None, tmp_path)) == []


@pytest.mark.parametrize("part", list(PARTS))
def test_a_vague_link_in_a_secondary_part_is_caught(part, tmp_path):
    """A "click here" in a header / footer / footnote / endnote fails 2.4.4 exactly as it would
    in the body — a screen-reader user tabbing the links gets the same contextless label wherever
    it lives. Before header/footer/note parts were read, every one of these was silent."""
    findings = _vague_2_4_4(_build(part, tmp_path))
    assert findings, (
        f"a vague link in {part!r} produced no 2.4.4 finding — docx_checks is still reading "
        "word/document.xml only, so the defect is invisible rather than failing or flagged")
