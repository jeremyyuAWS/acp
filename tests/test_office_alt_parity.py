"""The 1.1.1 detector and the 1.1.1 remediator must answer "is this decorative?" identically.

formats/office/images.py has said so in prose since it was written, and tests/... it named
(`test_office_alt_parity.py`) did not exist. This is that file.

WHY IT MATTERS, concretely. `apply_alt` writes the decorative marker as a standalone fragment,
so it must declare the namespace inline:

    <adec:decorative xmlns:adec="…/2017/decorative" val="1"/>

The detector's predicate was a substring test for `decorative val="1"`. The xmlns declaration
sits BETWEEN those two tokens, so it never matched — the detector said "still undescribed" about
a marker the remediator had just written and would now skip. That is a permanently unclearable
1.1.1 finding on a CONFORMING image, and it only appears on files ACP itself remediated: Word
declares xmlns:adec on the document root and emits a bare `<adec:decorative val="1"/>`, which the
substring did match. Word-authored files looked fine, which is why nothing caught it.

tests/test_alt_text_decorative_marker.py covers the same ground for the vendored .NET rule, but
needs the built CLI and self-skips without it. These assertions are pure predicate checks, so
they run everywhere — which is the point of having them.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import apply_alt  # noqa: E402
from formats.office import images  # noqa: E402

_URI = "{C183D7F6-B498-43B3-948B-1728B52AA6E4}"


def _docpr(inner: str) -> str:
    return f'<wp:docPr id="1" name="Picture 1" descr="">{inner}</wp:docPr>'


def _extlst(mark: str) -> str:
    return (f'<a:extLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            f'<a:ext uri="{_URI}">{mark}</a:ext></a:extLst>')


# Every shape a real decorative marker turns up in. The first is what ACP writes, the second is
# what Word writes, the rest are spelling variants both predicates have always claimed to accept.
DECORATIVE = [
    pytest.param(apply_alt._DECORATIVE_MARK, id="acp-inline-xmlns"),
    pytest.param('<adec:decorative val="1"/>', id="word-ancestor-xmlns"),
    pytest.param('<adec:decorative val="true"/>', id="val-true"),
    pytest.param("<adec:decorative val='1'/>", id="single-quotes"),
]


@pytest.mark.parametrize("mark", DECORATIVE)
def test_detector_sees_every_marker_the_remediator_can_write(mark):
    assert images.is_decorative(_docpr(_extlst(mark))) is True


@pytest.mark.parametrize("mark", DECORATIVE)
def test_both_predicates_agree(mark):
    block = _docpr(_extlst(mark))
    assert images.is_decorative(block) == bool(apply_alt._HAS_MARKER.search(block))


def test_they_are_literally_the_same_expression():
    """Not merely equal today. A second expression of one rule is what broke last time."""
    assert apply_alt._HAS_MARKER is images._DECORATIVE_MARKER


def test_an_undecorated_image_is_not_decorative():
    """The predicate must stay narrow — a permissive one certifies undescribed images."""
    assert images.is_decorative(_docpr("")) is False
    assert images.is_decorative(_docpr(_extlst('<adec:decorative val="0"/>'))) is False


@pytest.mark.parametrize("mark", DECORATIVE)
def test_the_remediator_skips_an_image_marked_decorative(mark):
    """The THIRD site, and the one with the worst symptom.

    `_inject_descr` kept its own inline substring test alongside the detector's and the
    applier's. It did not recognise ACP's own inline-namespace marker, so a decorative image
    came back `deferred=1` — routed to a human as "needs alt text". A reviewer marked the image
    decorative, and the next scan asked them to describe it again. And the next one.

    Measured before the fix (deferred=1) and after (deferred=0), not reasoned about.
    """
    import remediate_office

    xml = ('<w:document xmlns:w="w" xmlns:wp="wp"><w:drawing>'
           + _docpr(_extlst(mark))
           + '<a:blip r:embed="rId4"/></w:drawing></w:document>')
    _new, fixed, deferred = remediate_office._inject_descr(
        xml, "wp:docPr", pic_only_within=None, captions=False, entries={},
        part_name="word/document.xml", vision_enabled=False, context_file="doc.docx",
        applied_fixes=[], proposals=[], evidence=[])

    assert deferred == 0, "a decorative image must not be sent to a human for alt text"
    assert fixed == [], "a decorative image must not have alt text written into it"


def test_acp_marked_decorative_image_is_not_reported_as_undescribed():
    """The round trip, at the level the detector actually runs: mark it, then re-detect.

    This is the assertion that would have failed. `undescribed_in_part` is what the scan calls,
    and it returned the image's name for a document ACP had just marked decorative.
    """
    xml = ('<w:document xmlns:w="w" xmlns:wp="wp"><w:drawing>'
           + _docpr(_extlst(apply_alt._DECORATIVE_MARK))
           + "</w:drawing></w:document>")
    assert images.undescribed_in_part(xml, "wp:docPr", "w:drawing") == []
