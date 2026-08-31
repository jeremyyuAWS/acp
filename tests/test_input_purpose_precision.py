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

    user's own data          16/17 matched     (true positives)
    organisation/3rd party   15/20 matched     (FALSE POSITIVES)
    unrelated fields          0/12 matched     (correctly quiet)

    precision 52%

So the prediction was right, and now has a number on it: roughly half of what this detector would
report on a business form would be wrong. That is the cost of wiring it, stated in the unit the
decision needs.

TWO THINGS THE MEASUREMENT FOUND THAT THE PREDICTION DID NOT.

1. The vocabulary is not indiscriminate. Zero of twelve ordinary business fields (Invoice Number,
   Project Name, Delivery Date...) match, and bare "Name" does not match — only the qualified
   forms do. The problem is precisely and only that the regex has no notion of WHOSE data the
   field collects. That is worth knowing because it says what a fix would have to be: negative
   context ("company", "employer", "billing", "vendor", "site"), not a narrower vocabulary.

2. "Date of Birth" — the commonest English phrasing — does NOT match, while "Birth Date",
   "Birthdate", "Birth Day" and "DOB" all do. A false NEGATIVE hiding inside a detector whose
   documented weakness is false positives.

WHAT THIS FILE DOES NOT DO. It does not wire the detector, widen it, or fix either defect. The
standing instruction is that these stay visibly unproven until their behaviour justifies enabling
them; this supplies the behaviour, so the decision can be made on evidence. Fixing the regex
while it is uninvoked would change nothing a user sees and would spend the measurement.

A NOTE ON THE THIRD DETECTOR, because "three uninvoked heuristics" is not quite right. pdf 2.5.3
(`label_in_name`) is NOT a heuristic: it compares a push button's caption (/MK /CA) against its
accessible name (/TU or /T) by exact case-insensitive containment, and its registration is
PARTIAL coverage with HIGH confidence. Its limit is which fields it can see — only push buttons
carry a caption in the AcroForm dictionary — not how often it is wrong. It has no false-positive
rate to measure, and lumping it in with the other two overstates the risk of wiring it.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "api") not in sys.path:
    sys.path.insert(0, str(ROOT / "api"))

from formats.docx.detectors.input_purpose import _PERSONAL  # noqa: E402

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

_matches = lambda labels: [l for l in labels if _PERSONAL.search(l)]  # noqa: E731


def test_the_two_1_3_5_detectors_share_one_vocabulary():
    """docx and pdf match field labels against the same compiled pattern, so every number in this
    file describes both cells — and a fix to either is one edit, not two that can diverge."""
    from formats.pdf.detectors.input_purpose import _PERSONAL as PDF_PERSONAL
    assert _PERSONAL.pattern == PDF_PERSONAL.pattern, (
        "the docx and pdf 1.3.5 vocabularies have diverged — this file's measurement now "
        "describes only the docx cell, and the pdf one needs its own")


def test_it_finds_the_fields_it_is_for():
    """The detector is not useless, and saying so matters: a measurement that only reported the
    false positives would argue for deleting something that mostly works."""
    hits = _matches(USER_OWN)
    assert len(hits) >= 16, f"only {len(hits)}/{len(USER_OWN)} user-data labels matched: {hits}"


def test_THE_COST_organisational_fields_false_positive_at_the_measured_rate():
    """The number the wiring decision needs. 15 of 20 organisational or third-party labels are
    reported as personal-data fields — none of which WCAG 1.3.5 covers.

    Asserted as a floor, not an equality: this pins the finding without failing every time
    somebody adds one more example label to the list above.
    """
    fp = _matches(NOT_THE_USER)
    assert len(fp) >= 15, (
        f"only {len(fp)} organisational labels false-positive now — if the vocabulary learned "
        f"negative context, update the 52% precision figure in this file's docstring and in "
        f"tests/test_orphaned_detectors.py before wiring anything")
    # The specific ones the registration named, so its own prediction is pinned as confirmed.
    assert _PERSONAL.search("Company Address")
    assert _PERSONAL.search("Billing Address")


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
    assert 0.45 <= precision <= 0.60, (
        f"measured precision is now {precision:.0%}, outside the 45-60% band this file records. "
        f"That is a real behaviour change — update the docstring and re-take the wiring decision")


def test_a_false_NEGATIVE_hiding_in_a_detector_known_for_false_positives():
    """'Date of Birth' is the commonest English phrasing of the field and it does not match,
    while every other spelling of the same thing does. Recorded because it is the opposite of
    the defect this detector is documented as having, and would not be found by looking for
    more false positives."""
    assert _PERSONAL.search("Birth Date")
    assert _PERSONAL.search("Birthdate")
    assert _PERSONAL.search("DOB")
    assert not _PERSONAL.search("Date of Birth"), (
        "'Date of Birth' now matches — the vocabulary was widened; re-measure precision, since "
        "widening it is exactly what raises the false-positive rate this file exists to bound")


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
