"""1.4.1 use-of-color must judge a footer's colour-only link like the body's.

`office_color_only_checks` (docx) flags hyperlinks whose underline is removed — a link set apart
from body text by colour alone, which fails for colour-blind users. It read `word/document.xml`
alone, so a "privacy policy" or bare-URL link sitting in a page FOOTER with its underline stripped
— one of the commonest real cases — was silently missed. That is the same header/footer/note
population #214 made link purpose (2.4.4) read, and #226 made language-of-parts (3.1.2) read; this
pins the same symmetry for 1.4.1.

The body cases are controls: they prove the footer coverage is new reach, not a change to what the
body already did.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import office_structure as osx  # noqa: E402

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _link(text: str, *, underline_none: bool) -> str:
    """A hyperlink run. underline_none=True strips the underline (the colour-only case);
    False leaves a normal underlined link."""
    u = '<w:u w:val="none"/>' if underline_none else '<w:u w:val="single"/>'
    return (f'<w:hyperlink r:id="rId1"><w:r><w:rPr>{u}</w:rPr>'
            f'<w:t xml:space="preserve">{text}</w:t></w:r></w:hyperlink>')


def _build(path: Path, *, in_footer: bool, underline_none: bool) -> Path:
    link = _link("privacy policy", underline_none=underline_none)
    with zipfile.ZipFile(path, "w") as z:
        if in_footer:
            z.writestr("word/document.xml", f'<w:document xmlns:w="{W}"><w:body><w:p/></w:body></w:document>')
            z.writestr("word/footer1.xml", f'<w:ftr xmlns:w="{W}" xmlns:r="{R}"><w:p>{link}</w:p></w:ftr>')
        else:
            z.writestr("word/document.xml",
                       f'<w:document xmlns:w="{W}" xmlns:r="{R}"><w:body><w:p>{link}</w:p></w:body></w:document>')
    return path


def _fires_141(path: Path) -> bool:
    return any(f.get("ruleId") == "DOCX_COLOR_ONLY_LINK"
               for f in osx.office_color_only_checks(path, ".docx"))


def test_underline_removed_link_in_body_fires(tmp_path):
    """Control: an underline-removed link in the body is colour-only — as it always has been."""
    p = _build(tmp_path / "body_colour.docx", in_footer=False, underline_none=True)
    assert _fires_141(p)


def test_normal_underlined_link_in_body_does_not_fire(tmp_path):
    """Control: a link that keeps its underline is not distinguished by colour alone."""
    p = _build(tmp_path / "body_underlined.docx", in_footer=False, underline_none=False)
    assert not _fires_141(p)


def test_underline_removed_link_in_footer_fires(tmp_path):
    """The blind spot: a colour-only link in a page footer must fail 1.4.1 as it would in the body."""
    p = _build(tmp_path / "footer_colour.docx", in_footer=True, underline_none=True)
    assert _fires_141(p)


def test_normal_underlined_link_in_footer_does_not_fire(tmp_path):
    """And a normal underlined footer link must NOT fire — the fix widens where it reads, not what
    it flags."""
    p = _build(tmp_path / "footer_underlined.docx", in_footer=True, underline_none=False)
    assert not _fires_141(p)
