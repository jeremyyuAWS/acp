"""The relative gate on pseudo-heading promotion: is this line larger than THIS document's body?

`looks_like_pseudo_heading` asks an absolute question — is the text ≥14pt — and its own comment
records the assumption underneath it: "body text is ~22 (11pt)". That is a property of a
document, not a fact about documents.

In a large-print document, body set at 14pt or 16pt, every short paragraph clears the absolute
floor. `_remediate_docx_structure` then writes w:pStyle unattended on all of them, and a
document whose structure was fine comes back with a heading outline built out of its body copy.
Nothing on screen says so, and the documents most exposed are the ones already remediated for
low vision — the exact population this product exists to serve.

So promotion now asks a second, RELATIVE question. Detection is untouched: a flagged paragraph
is still flagged. This only decides auto-fix versus review.

Unit-level and dependency-free on purpose — these three functions are pure, and the arithmetic
is where the decision actually lives. The end-to-end proof that a large-print document survives
remediation is the round-trip in test_remediate_docx_heading_skip.py, which needs python-docx.
"""
from __future__ import annotations

import sys
from pathlib import Path

ACP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ACP / "api"))

import office_structure as osx      # noqa: E402

PLAIN = dict(styled_heading=False)


# ── the document default, read from styles.xml ────────────────────────────────────────────────

def test_the_default_comes_from_docDefaults():
    xml = ('<w:styles><w:docDefaults><w:rPrDefault><w:rPr><w:sz w:val="28"/>'
           '</w:rPr></w:rPrDefault></w:docDefaults></w:styles>')
    assert osx.default_run_half_pt(xml) == 28


def test_the_Normal_style_is_the_fallback():
    xml = ('<w:styles><w:style w:type="paragraph" w:styleId="Normal"><w:rPr>'
           '<w:sz w:val="24"/></w:rPr></w:style></w:styles>')
    assert osx.default_run_half_pt(xml) == 24


def test_a_style_without_a_size_does_not_borrow_the_next_style_s():
    """The bug this regex was written with, kept as a test.

    An unbounded `styleId="Normal".*?<w:sz>` runs past </w:style> and matches the first size in
    whatever style follows. Measured on three real fixtures — python-docx's default template and
    two Word-authored files — Normal carries no explicit size and the unbounded pattern returned
    the HEADING style's 28. That is wrong in the damaging direction: an inflated baseline makes
    real headings look undistinguished and routes correct auto-fixes to review.
    """
    xml = ('<w:styles>'
           '<w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
           '<w:style w:type="paragraph" w:styleId="Heading1"><w:rPr><w:sz w:val="28"/>'
           '</w:rPr></w:style></w:styles>')
    assert osx.default_run_half_pt(xml) == 0, "leaked into the Heading style"


def test_szCs_is_not_a_run_size():
    """<w:szCs> is the COMPLEX-SCRIPT size and routinely differs from <w:sz>. Matching it would
    read a Latin document's baseline off a value that does not describe its body text."""
    xml = ('<w:styles><w:docDefaults><w:rPrDefault><w:rPr><w:szCs w:val="96"/>'
           '</w:rPr></w:rPrDefault></w:docDefaults></w:styles>')
    assert osx.default_run_half_pt(xml) == 0


def test_bytes_and_absent_styles_are_both_handled():
    assert osx.default_run_half_pt(None) == 0
    assert osx.default_run_half_pt(b'<w:docDefaults><w:rPrDefault><w:rPr>'
                                   b'<w:sz w:val="22"/></w:rPr></w:rPrDefault></w:docDefaults>') == 22


# ── the baseline ──────────────────────────────────────────────────────────────────────────────

def test_the_baseline_is_the_most_common_paragraph_size():
    assert osx.body_baseline_half_pt([22, 22, 22, 36, 44]) == 22


def test_a_tie_breaks_to_the_smaller_size():
    """Mistaking a heading for body costs one missed promotion. Mistaking body for a heading
    restyles body copy unattended. On a tie, take the error that is cheap."""
    assert osx.body_baseline_half_pt([22, 22, 36, 36]) == 22


def test_no_sizes_means_no_baseline_not_a_baseline_of_zero():
    assert osx.body_baseline_half_pt([]) == 0
    assert osx.body_baseline_half_pt([0, 0]) == 0


# ── the gate ──────────────────────────────────────────────────────────────────────────────────

def test_an_ordinary_document_is_unaffected():
    """11pt body — the assumption the absolute floor was written under. Everything that was
    promoted before is still promoted, or this change would be a regression dressed as a fix."""
    assert osx.heading_signal("Executive Summary", bold=True, max_half_pt=36,
                              body_half_pt=22, **PLAIN) == "strong"
    assert osx.heading_signal("Scope", bold=False, max_half_pt=28,
                              body_half_pt=22, **PLAIN) == "strong"


def test_a_large_print_document_routes_its_body_to_review_not_to_a_heading_style():
    """THE defect. 14pt body, 14pt bold line: heading-like by the absolute floor, and utterly
    undistinguished from the text around it."""
    assert osx.heading_signal("Scope", bold=True, max_half_pt=28,
                              body_half_pt=28, **PLAIN) == "weak"


def test_the_margins_are_relative_and_bold_earns_a_smaller_one():
    # +1pt is enough WITH bold, and not enough without it.
    assert osx.heading_signal("Scope", bold=True, max_half_pt=30,
                              body_half_pt=28, **PLAIN) == "strong"
    assert osx.heading_signal("Scope", bold=False, max_half_pt=30,
                              body_half_pt=28, **PLAIN) == "weak"
    # +2pt is enough on size alone.
    assert osx.heading_signal("Scope", bold=False, max_half_pt=32,
                              body_half_pt=28, **PLAIN) == "strong"


def test_the_same_paragraph_flips_on_the_baseline_alone():
    """Mutation check. The candidate is IDENTICAL in both calls — only the document around it
    differs. If this ever passes with the baseline ignored, the gate is not doing its job."""
    same = dict(text="Eligibility", bold=True, max_half_pt=28)
    assert osx.heading_signal(**same, body_half_pt=22, **PLAIN) == "strong"
    assert osx.heading_signal(**same, body_half_pt=28, **PLAIN) == "weak"


def test_an_unmeasurable_document_keeps_the_old_behaviour():
    """No explicit sizes anywhere → no baseline → the gate has no evidence to narrow on, so it
    does not narrow. Downgrading every promotion to review here would remove a working fix
    rather than sharpen it."""
    assert osx.heading_signal("Scope", bold=True, max_half_pt=28,
                              body_half_pt=0, **PLAIN) == "strong"


def test_the_gate_never_widens_what_detection_flags():
    """heading_signal's first question IS looks_like_pseudo_heading, so anything the detector
    rejects stays rejected however the sizes fall — furniture, real headings, and long prose."""
    assert osx.heading_signal("Scope", bold=True, max_half_pt=36, body_half_pt=22,
                              styled_heading=True) is None          # already a heading
    assert osx.heading_signal("$4.2B", bold=True, max_half_pt=88, **PLAIN,
                              body_half_pt=22) is None              # a pull figure
    assert osx.heading_signal("“We grew faster than the market.”", bold=True,
                              max_half_pt=40, body_half_pt=22, **PLAIN) is None   # a pull quote
    assert osx.heading_signal("Ordinary body prose with enough words in it to read as a real "
                              "paragraph.", bold=False, max_half_pt=36,
                              body_half_pt=22, **PLAIN) is None     # too long to be a heading
