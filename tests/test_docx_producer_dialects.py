"""The same semantics, written the way a different producer writes it.

WHY THIS IS A REAL RISK AND NOT A HYPOTHETICAL. Every .docx detector in this repo is a regex
over OOXML, and every one was written against the XML Microsoft Word emits. The standard permits
more than Word uses: an element may be self-closing or paired, attributes may appear in any
order, relationship ids are opaque strings, and a producer may add attributes Word omits. Google
Docs, LibreOffice, Pages, Aspose, docx4j and python-docx each write valid files that differ from
Word's in exactly these ways.

The codebase has already paid for this twice, which is what makes it worth a suite:

  * `apply_alt._R_EMBED` carries a comment explaining it was deliberately loosened from
    `rId\\d+` to any id, because a stricter pattern "could only ever reject a locator that is in
    fact correct".
  * `images.is_decorative` was a substring test that broke on an inline namespace declaration —
    a dialect difference between what Word writes and what ACP itself writes.

Both were found after the fact. This is the same question asked in advance.

A HOSPITAL'S ESTATE IS NOT WORD-ONLY. Benefits summaries come from a broker's system, consent
forms from a template vendor, policies from whatever wrote them in 2011. A detector that is
silently Word-specific reports those as clean.

WHAT A FAILURE HERE MEANS. Not that the document is unusual — that ACP cannot see a defect it
would catch in the Word-flavoured version of the same file. Silent under-reporting, which is the
failure mode every gap found on 2026-08-09 turned out to share.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import office_structure as osx  # noqa: E402


# ── 2.4.6 / 1.3.1 · heading styles ────────────────────────────────────────────
#
# _HEADING_STYLE requires a SELF-CLOSING tag: `<w:pStyle w:val="Heading1"/>`. The paired form
# `<w:pStyle w:val="Heading1"></w:pStyle>` is equally valid OOXML and is what several producers
# emit. A document whose headings are written that way has no outline as far as ACP is concerned
# — so heading skips, empty headings and the whole 1.3.1 structure check go quiet on it.

HEADING_DIALECTS = [
    pytest.param('<w:pStyle w:val="Heading1"/>', id="word-self-closing"),
    pytest.param('<w:pStyle w:val="Heading1" />', id="space-before-slash"),
    pytest.param('<w:pStyle w:val="Heading1"></w:pStyle>', id="paired-tag"),
]


@pytest.mark.parametrize("frag", HEADING_DIALECTS)
def test_heading_style_is_recognised_in_every_legal_spelling(frag):
    m = osx._HEADING_STYLE.search(frag)
    assert m is not None, f"heading not recognised when written as {frag!r}"
    assert m.group(1) == "1"


# ── 1.4.8 · justified paragraphs ──────────────────────────────────────────────
#
# Same self-closing assumption in _JC_BOTH, and the same consequence: a justified document from
# a non-Word producer reports no 1.4.8 finding at all.

JC_DIALECTS = [
    pytest.param('<w:jc w:val="both"/>', id="word-self-closing"),
    pytest.param('<w:jc w:val="both" />', id="space-before-slash"),
    pytest.param('<w:jc w:val="both"></w:jc>', id="paired-tag"),
    pytest.param('<w:jc w:val="distribute"/>', id="distribute"),
]


@pytest.mark.parametrize("frag", JC_DIALECTS)
def test_justified_alignment_is_recognised_in_every_legal_spelling(frag):
    assert osx._JC_BOTH.search(frag) is not None, f"not recognised when written as {frag!r}"


# ── 2.4.4 / 1.4.1 · hyperlinks ────────────────────────────────────────────────
#
# _HYPERLINK captures `r:id="(rId\\w+)"`. A relationship id is an OPAQUE STRING in the standard —
# "rId3" is Word's convention, not a rule. This is precisely the assumption apply_alt._R_EMBED
# was loosened to remove, with a comment saying a stricter pattern "could only ever reject a
# locator that is in fact correct". The same tightness is still here.
#
# It also assumes `r:id` precedes the closing angle bracket with no intervening `>`, which holds,
# and that the id attribute is present at all — an ANCHOR-only hyperlink (internal bookmark) has
# `w:anchor` and no `r:id`, and is legitimately out of scope for link-purpose.

LINK_DIALECTS = [
    pytest.param('<w:hyperlink r:id="rId7"><w:r><w:t>click here</w:t></w:r></w:hyperlink>',
                 True, id="word-rId7"),
    pytest.param('<w:hyperlink w:history="1" r:id="rId7"><w:r><w:t>click here</w:t></w:r>'
                 '</w:hyperlink>', True, id="attribute-before-id"),
    pytest.param('<w:hyperlink r:id="docRId7"><w:r><w:t>click here</w:t></w:r></w:hyperlink>',
                 True, id="non-word-id-prefix"),
    pytest.param('<w:hyperlink r:id="R3f2a91c"><w:r><w:t>click here</w:t></w:r></w:hyperlink>',
                 True, id="opaque-guid-style-id"),
]


@pytest.mark.parametrize("frag,expected", LINK_DIALECTS)
def test_hyperlinks_are_found_whatever_the_relationship_id_looks_like(frag, expected):
    found = osx._HYPERLINK.findall(frag)
    assert bool(found) == expected, (
        f"hyperlink {'missed' if expected else 'wrongly matched'} for {frag[:60]!r} — a "
        "relationship id is an opaque string, and only Word's happens to start 'rId'")


def test_an_anchor_only_hyperlink_is_not_treated_as_an_external_link():
    """The control. An internal bookmark jump has no r:id and is not what 2.4.4 is about; a
    pattern loosened too far would start reporting them."""
    frag = '<w:hyperlink w:anchor="_Toc123"><w:r><w:t>see above</w:t></w:r></w:hyperlink>'
    assert osx._HYPERLINK.findall(frag) == []


# ── 1.4.1 · removed underline ─────────────────────────────────────────────────
#
# _W_U_NONE is already attribute-order tolerant (`<w:u\\b[^>]*w:val="none"`). Pinned so it stays
# that way — this is the shape the others should have.

U_DIALECTS = [
    pytest.param('<w:u w:val="none"/>', True, id="bare"),
    pytest.param('<w:u w:color="auto" w:val="none"/>', True, id="attribute-before-val"),
    pytest.param('<w:u w:val="none" w:color="auto"/>', True, id="attribute-after-val"),
    pytest.param('<w:u w:val="none"></w:u>', True, id="paired-tag"),
    pytest.param('<w:u w:val="single"/>', False, id="underlined-is-not-a-finding"),
]


@pytest.mark.parametrize("frag,expected", U_DIALECTS)
def test_removed_underline_is_recognised_however_it_is_written(frag, expected):
    assert bool(osx._W_U_NONE.search(frag)) == expected


# ── 1.4.11 · shape outline colour ─────────────────────────────────────────────
#
# _SOLID_SRGB requires `<a:solidFill>` then `<a:srgbClr val=`. THEME colours (`<a:schemeClr
# val="accent1"/>`) are not matched by _SOLID_SRGB directly — they go through _resolve_solidfill,
# which looks them up in the document's theme XML. The registry reason for docx 1.4.11 must
# reflect that schemeClr is now resolved — this pins the declaration against the code.

def test_explicit_srgb_outline_is_measured():
    assert osx._SOLID_SRGB.search('<a:solidFill><a:srgbClr val="BBBBBB"/></a:solidFill>')


def test_scheme_clr_resolved_via_theme_and_registry_says_so():
    """_SOLID_SRGB alone does not match schemeClr — resolution goes through _resolve_solidfill.
    The registry reason must declare that theme colour references are resolved through the
    document theme, not listed as an unexamined gap."""
    import formats.docx  # noqa: F401  — registration runs on import
    import assessment_policy as pol
    assert osx._SOLID_SRGB.search('<a:solidFill><a:schemeClr val="accent1"/></a:solidFill>') is None
    reason = pol._registry_for("1.4.11", "docx").reason
    assert "schemeClr" in reason


# ── the whitespace dimension, across every pattern ────────────────────────────

@pytest.mark.parametrize("pattern,frag", [
    (osx._HEADING_STYLE, '<w:pStyle  w:val="Heading2"/>'),
    (osx._JC_BOTH, '<w:jc  w:val="both"/>'),
])
def test_extra_whitespace_between_element_and_attribute_is_tolerated(pattern, frag):
    """`\\s+` in the patterns covers this, and it is worth pinning: a producer that pretty-prints
    its XML is not writing an unusual document, and a detector that missed it would report a
    formatted file as structureless."""
    assert pattern.search(frag) is not None, f"whitespace defeated the pattern: {frag!r}"
