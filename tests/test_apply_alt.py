"""Writing an approved alt text into an Office package (WCAG 1.1.1).

These are the guarantees the review loop rests on: the value a human signed their name to
lands on the image they were shown, an unresolvable locator is reported rather than guessed
at, and a document we could not change comes back byte-identical.
"""
from __future__ import annotations
import io
import re
import sys
import zipfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

from apply_alt import apply_alt_text, parse_locator, tag_for_part  # noqa: E402

SLIDE = "ppt/slides/slide1.xml"
DOC = "word/document.xml"


def _pkg(parts: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, body in parts.items():
            z.writestr(n, body)   # bytes stay bytes; a str would be UTF-8 encoded
    return buf.getvalue()


def _part(data: bytes, name: str) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return z.read(name).decode("utf-8")


def _slide(*pics: str) -> bytes:
    return _pkg({SLIDE: "<p:sld>" + "".join(pics) + "</p:sld>",
                 "docProps/core.xml": "<cp:coreProperties/>"})


PIC1 = '<p:pic><p:cNvPr id="2" name="Picture 1"/></p:pic>'
PIC2 = '<p:pic><p:cNvPr id="3" name="Chart 2"/></p:pic>'


def test_locator_parsing():
    assert parse_locator("ppt/slides/slide3.xml#Picture 4") == ("ppt/slides/slide3.xml", "Picture 4")
    # a shape name may contain '#'; a part name may not — split on the FIRST one
    assert parse_locator("word/document.xml#Fig #2") == ("word/document.xml", "Fig #2")
    for bad in ("", None, "no-hash", "#name", "part#"):
        assert parse_locator(bad) is None


def test_tag_for_part_mirrors_the_locator_producer():
    """Asserted against the producer's OWN table, not a hand-copy of it.

    This used to pin the literal "xdr:cNvPr" — which is exactly the stale value the bug lived
    in. When the producer's xlsx entry gained `(?:xdr:)?` to cover default-namespace drawings,
    apply_alt kept the prefixed-only spelling and this test kept agreeing with it, so a table
    that could no longer resolve the locators it minted read as correctly mirrored. Comparing
    to the source makes the mirror structural instead of aspirational.
    """
    from formats.office.images import ALT_TARGETS
    produced = {tag for _pat, tag, _wrapper, _captions in ALT_TARGETS}
    assert tag_for_part(SLIDE) in produced and "cNvPr" in tag_for_part(SLIDE)
    assert tag_for_part(DOC) in produced and "docPr" in tag_for_part(DOC)
    xlsx_tag = tag_for_part("xl/drawings/drawing2.xml")
    assert xlsx_tag in produced
    # both xlsx namespace flavours must match, or a default-namespace workbook's approvals
    # come back unresolved and are silently never written
    for spelling in ("xdr:cNvPr", "cNvPr"):
        assert re.fullmatch(xlsx_tag, spelling), f"{xlsx_tag!r} does not match <{spelling}>"
    assert tag_for_part("ppt/notesSlides/notesSlide1.xml") is None   # carries no images


def test_approved_value_lands_on_the_right_image():
    data = _slide(PIC1, PIC2)
    out, applied, unresolved = apply_alt_text(data, {f"{SLIDE}#Chart 2": "Revenue by quarter."})
    assert unresolved == []
    assert applied == [{"locator": f"{SLIDE}#Chart 2", "before": "(no alt text)",
                        "after": "Revenue by quarter."}]
    xml = _part(out, SLIDE)
    assert '<p:cNvPr id="3" name="Chart 2" descr="Revenue by quarter."/>' in xml
    assert 'name="Picture 1" descr' not in xml          # the other image is untouched


def test_each_image_gets_its_own_value():
    """The reason a single approved_value column could not express this: one row, N images."""
    out, applied, unresolved = apply_alt_text(_slide(PIC1, PIC2), {
        f"{SLIDE}#Picture 1": "A clinician at a desk.",
        f"{SLIDE}#Chart 2": "Revenue by quarter.",
    })
    assert unresolved == [] and len(applied) == 2
    xml = _part(out, SLIDE)
    assert 'name="Picture 1" descr="A clinician at a desk."' in xml
    assert 'name="Chart 2" descr="Revenue by quarter."' in xml


def test_an_existing_description_is_replaced_and_reported_as_before():
    data = _slide('<p:pic><p:cNvPr id="2" name="Picture 1" descr="image1.png"/></p:pic>')
    out, applied, _ = apply_alt_text(data, {f"{SLIDE}#Picture 1": "A parent signing a form."})
    assert applied[0]["before"] == "image1.png"          # real before, for remediation_diff
    xml = _part(out, SLIDE)
    assert 'descr="A parent signing a form."' in xml
    assert "image1.png" not in xml                        # exactly one descr survives
    assert xml.count("descr=") == 1


def test_reviewer_prose_is_xml_escaped():
    """Alt text is free-form human prose. An unescaped quote or ampersand corrupts the part
    and makes the document unopenable — a far worse outcome than an unapplied fix."""
    nasty = 'Q&A: the "big" chart <that> one'
    out, applied, _ = apply_alt_text(_slide(PIC1), {f"{SLIDE}#Picture 1": nasty})
    xml = _part(out, SLIDE)
    assert 'descr="Q&amp;A: the &quot;big&quot; chart &lt;that&gt; one"' in xml
    assert applied[0]["after"] == nasty                   # reported unescaped, as written
    # and the part is still well-formed
    import xml.etree.ElementTree as ET
    ET.fromstring(xml.replace("p:", "p"))


def test_unresolvable_locators_are_reported_never_guessed():
    data = _slide(PIC1)
    out, applied, unresolved = apply_alt_text(data, {
        f"{SLIDE}#Picture 1": "ok",
        f"{SLIDE}#Ghost 9": "an image that is not there",   # element missing
        "ppt/slides/slide7.xml#Picture 1": "a part that is not there",
        "ppt/notesSlides/notesSlide1.xml#Picture 1": "a part with no alt-bearing tag",
        "no-hash-at-all": "malformed",
    })
    assert [a["locator"] for a in applied] == [f"{SLIDE}#Picture 1"]
    assert sorted(unresolved) == sorted([
        f"{SLIDE}#Ghost 9", "ppt/slides/slide7.xml#Picture 1",
        "ppt/notesSlides/notesSlide1.xml#Picture 1", "no-hash-at-all"])
    assert "an image that is not there" not in _part(out, SLIDE)


def test_nothing_to_apply_returns_the_original_bytes_unchanged():
    data = _slide(PIC1)
    for values in ({}, None, {f"{SLIDE}#Picture 1": "   "}, {f"{SLIDE}#Ghost": "x"}):
        out, applied, _ = apply_alt_text(data, values)
        assert out == data, "a rezipped copy would read as a modified document"
        assert applied == []


def test_untouched_parts_survive_the_rewrite_byte_for_byte():
    png = b"\x89PNG\r\n\x1a\n-not-really"          # real binary: must survive untouched
    data = _pkg({SLIDE: f"<p:sld>{PIC1}</p:sld>", "docProps/core.xml": "<cp:coreProperties/>",
                 "ppt/media/image1.png": png})
    out, _, _ = apply_alt_text(data, {f"{SLIDE}#Picture 1": "ok"})
    with zipfile.ZipFile(io.BytesIO(out)) as z:
        assert z.namelist() == [SLIDE, "docProps/core.xml", "ppt/media/image1.png"]
        assert z.read("ppt/media/image1.png") == png
        assert z.read("docProps/core.xml") == b"<cp:coreProperties/>"


def test_docx_uses_docPr_and_self_closing_tags_round_trip():
    data = _pkg({DOC: '<w:body><wp:docPr id="1" name="Figure 1"/></w:body>'})
    out, applied, unresolved = apply_alt_text(data, {f"{DOC}#Figure 1": "A bar chart."})
    assert unresolved == [] and len(applied) == 1
    assert '<wp:docPr id="1" name="Figure 1" descr="A bar chart."/>' in _part(out, DOC)


def test_a_non_self_closing_element_keeps_its_children():
    data = _pkg({DOC: '<wp:docPr id="1" name="Fig"><a:extLst/></wp:docPr>'})
    out, _, _ = apply_alt_text(data, {f"{DOC}#Fig": "alt"})
    xml = _part(out, DOC)
    assert '<wp:docPr id="1" name="Fig" descr="alt">' in xml
    assert "<a:extLst/></wp:docPr>" in xml
