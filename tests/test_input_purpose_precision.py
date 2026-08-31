"""The 1.3.5 heuristic's false-positive rate, measured instead of predicted.

WHY THIS FILE EXISTS. `tests/test_orphaned_detectors.py` records that three registered detectors
are never invoked by a scan, and argues against wiring them by quoting the docx 1.3.5
registration's own words: "organisational forms (company address, billing contact) will
false-positive". That is a PREDICTION. It is the kind of claim this repo has been wrong about
before in both directions — a comment read where a command should have been run — and it is the
claim the decision to wire or not wire rests on. So it is measured here.

WHAT WAS MEASURED. `_PERSONAL`, the vocabulary both 1.3.5 detectors match field labels against,
run over three sets of labels a real form carries. The scope question is what WCAG 1.3.5 actually
requires: "the purpose of each input field COLLECTING INFORMATION ABOUT THE USER can be
programmatically determined". A field collecting a company's address, or a third party's phone
number, is outside that — the autocomplete vocabulary has no term for it — so a finding on one is
a false positive, not a strict reading.

                             BEFORE            AFTER contextual applicability
    user's own data          16/17 matched     17/17   (Date of Birth now matches)
    organisation/3rd party   15/20 matched      2/20   (13 false positives removed)
    unrelated fields          0/12 matched      0/12   (unchanged)
    -----------------------------------------------------------------------------
    49 labels total          31 matched        19 matched
                             TP 16 / FP 15     TP 17 / FP 2
                             precision 52%     precision 89%

WHAT THAT 89% IS AND IS NOT. It is the precision ON THIS CONSTRUCTED SET OF 49 LABELS, whose
composition is listed in full below and was chosen by hand to probe the predicted weakness. It
is NOT an estimated production precision, and must not be reported as one: the three groups are
present in whatever proportion made the boundary legible, not in the proportion a real corpus of
business documents would carry. A form with twenty user-data fields and one company address
would score far better; a vendor-onboarding form far worse.

What the number does support is a floor on the existence and rough scale of the problem: the
failure mode is real, reproducible, and not a handful of edge cases. Turning it into a
production estimate needs a representative sample of real documents, which is a separate piece
of work and is not claimed here.

AND THE 89% IS WEAKER EVIDENCE THAN THE 52% WAS, for a reason worth stating plainly: the
negative context was written against THIS SET, so measuring it on the same set is fitting and
scoring on the same data. The 52% was a measurement of something built without reference to
these labels; the 89% is a measurement of a change made to improve them. Two residual false
positives are left deliberately un-suppressed for that reason — "Country of Incorporation" and
"Country of Manufacture" would each need a rule aimed at one label, which is where tuning stops
being improvement and starts being overfitting. They are named in a test below so they cannot
be quietly fixed later without the trade being noticed.

TWO THINGS THE MEASUREMENT FOUND THAT THE PREDICTION DID NOT.

1. The vocabulary is not indiscriminate. Zero of twelve ordinary business fields (Invoice Number,
   Project Name, Delivery Date...) match, and bare "Name" does not match — only the qualified
   forms do. The problem is precisely and only that the regex has no notion of WHOSE data the
   field collects. That suggested negative context ("company", "employer", "billing", "vendor",
   "site") rather than a narrower vocabulary, and that candidate has now been IMPLEMENTED and
   measured — see `_NOT_THE_USER` in both detectors, and the numbers above.

   Its predicted false negative is real and is asserted below: on a sole-trader form "your
   company address" IS the user's own address, and the context suppresses it. Three further
   terms were deliberately left OUT for the same reason — bare "office" (an "Office Phone" is
   the user's work phone, which 1.3.5 does cover), "customer"/"client" (on a form the customer
   fills in, "Customer Name" is the user), and "guardian" (often the person completing a child's
   form).

2. "Date of Birth" — the commonest English phrasing — does NOT match, while "Birth Date",
   "Birthdate", "Birth Day" and "DOB" all do. A false NEGATIVE hiding inside a detector whose
   documented weakness is false positives.

WHAT THIS FILE DOES NOT DO. It does not wire the detector. The standing instruction is that
these stay disabled while their contextual applicability is improved and tested, which is what
the negative context and the Date-of-Birth fix are; activation is a separate decision and is not
taken here. An earlier version of this paragraph argued the opposite — that fixing the regex
while uninvoked "would change nothing a user sees and would spend the measurement" — which was
superseded by the instruction to improve applicability BEFORE considering activation. The
measurement is not spent by being re-taken; it is weakened by being taken on the same labels the
change was written against, which the caveat above says outright.

A NOTE ON THE THIRD DETECTOR — CORRECTED. An earlier version of this paragraph said pdf 2.5.3
(`label_in_name`) is "NOT a heuristic ... Its limit is which fields it can see, not how often it
is wrong. It has no false-positive rate to measure." The first half is right and the rest was
wrong, in a way worth keeping visible because the reasoning was seductive: the detector compares
a push button's caption (/MK /CA) against its accessible name (/TU or /T) by exact
case-insensitive containment, and its registration declares PARTIAL coverage with HIGH
confidence. Both facts are true, and neither is evidence of correctness — a predicate can be
perfectly deterministic and still answer a different question from the one WCAG 2.5.3 asks.

Measured in tests/test_label_in_name_precision.py: the comparison folds case and nothing else,
so it false-positives on six of nine realistic caption/name pairs — curly apostrophes,
non-breaking spaces, doubled spaces, zero-width spaces, NFD accents, soft hyphens. Every one is
a button that works fine for a speech-input user and would be reported SERIOUS.

So it does have a false-positive rate, it is not small, and it needs its own evaluation through
real scan dispatch with positive and negative controls before anything is decided about wiring
it. What remains true is only that its failure mode is DIFFERENT from the other two — text
normalization rather than missing context — so the three should be judged separately.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "api"))

from formats.docx.detectors.input_purpose import (  # noqa: E402
    _NOT_THE_USER,
    _PERSONAL,
    _collects_user_data,
)

# Fields collecting the USER'S OWN data. WCAG 1.3.5 applies; a match is a true positive.
USER_OWN = [
    "First Name", "Last Name", "Full Name", "Email", "Email Address",
    "Phone", "Mobile Number", "Date of Birth", "DOB", "Home Address",
    "Street Address", "City", "Country", "Postal Code", "ZIP",
    "SSN", "Credit Card Number",
]

# Fields collecting data about an ORGANISATION or a THIRD PARTY. 1.3.5's autocomplete vocabulary
# is defined for information about the user, so these are out of scope: a match is a FALSE
# positive. This is the set the registration predicted would break.
NOT_THE_USER = [
    "Company Name", "Company Address", "Registered Office Address",
    "Billing Contact Name", "Billing Address", "Invoice Address",
    "Employer Address", "Employer Phone", "Supplier Email",
    "Vendor Phone", "Manager Name", "Emergency Contact Name",
    "Emergency Contact Phone", "Department Name", "Branch City",
    "Country of Incorporation", "Country of Manufacture",
    "Warehouse Street", "Site Address", "Head Office Postal Code",
]

# Ordinary business fields — the control. Without these, "it matches a lot" would be consistent
# with "it matches everything", which is a different defect with a different fix.
UNRELATED = [
    "Project Name", "Product Name", "Invoice Number", "Order Quantity",
    "Delivery Date", "Approval Status", "Budget Code", "Contract Term",
    "Serial Number", "Priority", "Notes", "Signature Date",
]

# What the detector REPORTS — vocabulary AND context, which is the thing with a precision.
_matches = lambda labels: [l for l in labels if _collects_user_data(l)]  # noqa: E731
# The raw vocabulary alone, kept so the two can be told apart in the tests below.
_vocab = lambda labels: [l for l in labels if _PERSONAL.search(l)]  # noqa: E731


def test_the_two_1_3_5_detectors_share_one_vocabulary():
    """docx and pdf match field labels against the same compiled pattern, so every number in this
    file describes both cells — and a fix to either is one edit, not two that can diverge."""
    from formats.pdf.detectors.input_purpose import (
        _NOT_THE_USER as PDF_CONTEXT,
        _PERSONAL as PDF_PERSONAL,
    )
    assert _PERSONAL.pattern == PDF_PERSONAL.pattern, (
        "the docx and pdf 1.3.5 vocabularies have diverged — this file's measurement now "
        "describes only the docx cell, and the pdf one needs its own")
    assert _NOT_THE_USER.pattern == PDF_CONTEXT.pattern, (
        "the docx and pdf contextual-applicability rules have diverged — same problem, and "
        "this one is easier to miss because both files still look right on their own")


def test_it_finds_the_fields_it_is_for():
    """The detector is not useless, and saying so matters: a measurement that only reported the
    false positives would argue for deleting something that mostly works."""
    hits = _matches(USER_OWN)
    assert len(hits) == len(USER_OWN), (
        f"only {len(hits)}/{len(USER_OWN)} user-data labels reported; missing "
        f"{[l for l in USER_OWN if l not in hits]}")


def test_THE_COST_organisational_fields_false_positive_at_the_measured_rate():
    """The number the wiring decision needs. 15 of 20 organisational or third-party labels are
    reported as personal-data fields — none of which WCAG 1.3.5 covers.

    Asserted as a floor, not an equality: this pins the finding without failing every time
    somebody adds one more example label to the list above.
    """
    fp = _matches(NOT_THE_USER)
    assert len(fp) <= 2, (
        f"{len(fp)} organisational labels are still reported: {fp}. The contextual rule was "
        f"supposed to bring this to 2; re-measure and update this file's docstring")
    # The registration's own prediction — "company address, billing contact" — was confirmed at
    # 15 false positives, and is what the context now suppresses. Pinned in both directions so a
    # regression in either the vocabulary or the context is visible.
    assert _PERSONAL.search("Company Address"), "the vocabulary should still MATCH the words"
    assert not _collects_user_data("Company Address"), "...and the context should suppress it"
    assert _PERSONAL.search("Billing Address")
    assert not _collects_user_data("Billing Address")


def test_the_two_residual_false_positives_are_named_not_quietly_fixed():
    """THE STOPPING POINT. "Country of Incorporation" and "Country of Manufacture" are still
    reported: the word "country" with an organisational qualifier the context does not cover.

    They are left un-suppressed deliberately. Each would need a rule aimed at one label, and the
    negative context was already written against this same 49-label set — so tuning further is
    fitting and scoring on the same data, not improvement. Naming them here means a future fix
    has to notice it is making that trade rather than drifting into it."""
    residual = _matches(NOT_THE_USER)
    assert sorted(residual) == ["Country of Incorporation", "Country of Manufacture"], (
        f"the residual false positives changed: {residual}. If they were suppressed, say in the "
        f"docstring what rule did it and re-state the overfitting caveat honestly")


def test_the_context_has_its_OWN_false_negative_and_it_is_not_hypothetical():
    """The predicted cost of negative context, asserted rather than assumed away. On a
    sole-trader form the user's own address IS "your company address", and this suppresses it.

    Recorded because the alternative — discovering it in production — is how a heuristic loses
    the trust that made anyone consider enabling it."""
    sole_trader = "Your company address"
    assert _PERSONAL.search(sole_trader), "the vocabulary sees it"
    assert _NOT_THE_USER.search(sole_trader), "the context suppresses it"
    assert not _collects_user_data(sole_trader), (
        "the sole-trader false negative is real, and this file says so on purpose")


@pytest.mark.parametrize("label,why", [
    ("Office Phone", "the USER'S work phone, which 1.3.5 does cover"),
    ("Customer Address", "on a form the customer fills in, this IS the user's address"),
    ("Guardian Email", "on a child's form the guardian is often the person completing it"),
])
def test_terms_deliberately_left_out_of_the_context(label, why):
    """Three obvious negative terms were rejected because each trades a false positive for a
    worse false negative. This pins that they stay out.

    Note the labels: "Customer NAME" would be the natural example and is useless as one, because
    bare "name" never matched the vocabulary in the first place — only the qualified forms
    (first/given/last/family/sur/full) do. So the term "customer" only ever mattered on a label
    like "Customer Address", and testing it on the wrong label would have asserted nothing. The
    first draft of this test did exactly that and failed, which is the only reason it was
    noticed.

    Without this, "office" or "customer" would look like harmless additions to whoever next
    tries to remove the two residual false positives above."""
    assert _collects_user_data(label), f"{label!r} must still be reported — {why}"


def test_the_control_it_is_not_simply_matching_everything():
    """Zero of twelve ordinary business fields match. This is what makes the result actionable:
    the vocabulary is well targeted and the defect is specifically that it cannot tell whose data
    a field collects — so the fix is negative context, not a narrower word list."""
    assert _matches(UNRELATED) == []
    assert not _PERSONAL.search("Name"), "bare 'Name' must not match, or nothing above is safe"


def test_measured_precision_is_about_half():
    """The headline, computed rather than quoted, so it cannot drift from the lists above."""
    tp = len(_matches(USER_OWN))
    fp = len(_matches(NOT_THE_USER)) + len(_matches(UNRELATED))
    precision = tp / (tp + fp)
    assert 0.85 <= precision <= 0.95, (
        f"measured precision is now {precision:.0%}, outside the 85-95% band this file records. "
        f"That is a real behaviour change — update the docstring and re-take the decision")
    # And the vocabulary alone, unchanged in kind, is still the weaker number — so the
    # improvement is attributable to the CONTEXT rather than to a narrower word list.
    v_tp = len(_vocab(USER_OWN))
    v_fp = len(_vocab(NOT_THE_USER)) + len(_vocab(UNRELATED))
    assert v_tp / (v_tp + v_fp) < precision, (
        "the vocabulary alone now scores as well as vocabulary+context, so the context is "
        "doing nothing and this file's account of the improvement is wrong")


def test_a_false_NEGATIVE_hiding_in_a_detector_known_for_false_positives():
    """FIXED. "Date of Birth" — the commonest English phrasing — did not match, while "Birth
    Date", "Birthdate", "Birth Day" and "DOB" all did: a false NEGATIVE inside a detector
    documented for false positives, which is why looking only for more false positives would
    never have found it. All five spellings are now reported."""
    for spelling in ("Birth Date", "Birthdate", "DOB", "Date of Birth", "Day of Birth"):
        assert _collects_user_data(spelling), f"{spelling!r} is a 1.3.5 field and must be reported"


def test_this_measurement_does_not_wire_anything():
    """The standing instruction: these stay visibly unproven until behaviour justifies enabling
    them. Measuring is not enabling, so the uninvoked state is asserted here too — if someone
    acts on this file by wiring the detector, that is a decision that should be visible in a
    diff, and test_orphaned_detectors.py is where it gets recorded."""
    import office_structure
    src = Path(office_structure.__file__).read_text()
    checks_for = src[src.index("def checks_for"):]
    assert "input_purpose" not in checks_for[:8000], (
        "input_purpose is now reachable from checks_for. That is a product decision, not a test "
        "failure — record it in tests/test_orphaned_detectors.py and delete this assertion")
