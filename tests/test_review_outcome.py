"""Review-aware per-criterion outcome (ADR 0023, Option A): store._rule_outcome +
REVIEW_FORMATS + _split_sc_counts.

A review-lane (criterion, format) resolves to REVIEW when its detector fires an advisory
(severity REVIEW) finding and to NOT_EVALUATED when it does not — NEVER to PASS, because a
review detector doesn't certify conformance (ADR 0016). A blocking FAIL always outranks an
advisory REVIEW. Pass/fail-lane criteria are unaffected unless an advisory finding rides them.
"""
from __future__ import annotations

import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import store  # noqa: E402


# ── review-lane resolution (4.1.2 is a catalog rule; office is its review lane) ──
def test_review_lane_no_signal_is_not_evaluated_never_pass():
    # A control-free office doc: no advisory finding → genuine N/A, NOT a fabricated pass.
    assert store._rule_outcome("4.1.2", "docx", 0, 0) == store.NOT_EVALUATED
    assert store._rule_outcome("2.1.2", "pptx", 0, 0) == store.NOT_EVALUATED


def test_review_lane_with_signal_is_review():
    assert store._rule_outcome("4.1.2", "docx", 0, 1) == store.REVIEW
    assert store._rule_outcome("2.1.2", "xlsx", 0, 3) == store.REVIEW


def test_review_lane_blocking_finding_outranks_review():
    # If a definite FAIL also landed on a review-lane criterion, FAIL wins.
    assert store._rule_outcome("4.1.2", "docx", 1, 2) == "FAIL"


def test_review_lane_is_format_scoped():
    # 4.1.2's REVIEW_FORMATS lane is office-only, and pdf is not in it. pdf reaches REVIEW by a
    # different route: it is registered in the capability registry with PARTIAL coverage (the
    # AcroForm technique in formats/pdf/detectors/name_role_value.py), and partial coverage
    # cannot certify a pass. Same token, different reason — which is the point of the coverage
    # axis. It read NOT_EVALUATED before the registry, despite the detector having shipped.
    assert store._rule_outcome("4.1.2", "pdf", 0, 0) == store.REVIEW
    # The two routes to REVIEW differ in when they fire, and that difference is real. A
    # REVIEW_FORMATS lane needs a signal — its detector surfaces evidence or says nothing — so
    # docx with no findings is still "we did not look". A registry lane with PARTIAL coverage
    # reports REVIEW on a CLEAN scan, because the technique ran and covered part of the
    # criterion. Same token; one is "found something to look at", the other "looked partially".
    assert store._rule_outcome("4.1.2", "docx", 0, 0) == store.NOT_EVALUATED
    assert store._rule_outcome("4.1.2", "docx", 0, 1) == store.REVIEW
    # A format with neither a review lane nor a registry entry still reads "we did not look".
    assert store._rule_outcome("2.4.3", "xlsx", 0, 0) == store.NOT_EVALUATED
    # html keeps its real pass/fail lane for 4.1.2.
    assert store._rule_outcome("4.1.2", "html", 0, 0) == "PASS"
    assert store._rule_outcome("4.1.2", "html", 1, 0) == "FAIL"


# ── pass/fail lane still behaves for 🟢 auto-assess criteria ────────────────────
def test_pass_fail_lane_unchanged_for_auto_assess():
    # 3.1.1 Language is 🟢 auto-assess (deterministic present/absent) → a clean scan is a real PASS.
    assert store._rule_outcome("3.1.1", "pdf", 0, 0) == "PASS"
    assert store._rule_outcome("3.1.1", "pdf", 2, 0) == "FAIL"
    assert store._rule_outcome("1.3.4", "docx", 0, 0) == store.NOT_EVALUATED  # html-only rule


def test_review_lane_criterion_clean_is_review_not_a_certified_pass():
    # 1.1.1 is a 🟡 review-lane criterion (alt adequacy is a judgement) — a scan that finds no
    # missing alt is NOT a certified pass; it stays REVIEW ("verify"), never green (audit #174).
    assert store._rule_outcome("1.1.1", "pdf", 0, 0) == store.REVIEW
    assert store._rule_outcome("1.3.3", "docx", 0, 0) == store.REVIEW
    # …but a real FAIL still wins over the review lane.
    assert store._rule_outcome("1.1.1", "pdf", 2, 0) == "FAIL"


def test_advisory_review_on_a_pass_fail_criterion_surfaces_as_review():
    # An advisory finding on an in-scope pass/fail criterion (no blocking finding) → REVIEW.
    assert store._rule_outcome("1.1.1", "pdf", 0, 1) == store.REVIEW
    # …but a real FAIL still wins.
    assert store._rule_outcome("1.1.1", "pdf", 1, 1) == "FAIL"


def test_three_arg_call_is_back_compatible():
    # Existing callers pass 3 args; review_count defaults to 0.
    assert store._rule_outcome("3.1.1", "pdf", 0) == "PASS"           # 🟢 auto → pass
    assert store._rule_outcome("1.1.1", "pdf", 0) == store.REVIEW     # 🟡 review-lane → verify
    assert store._rule_outcome("4.1.2", "docx", 0) == store.NOT_EVALUATED


# ── count split by advisory severity ────────────────────────────────────────────
def test_split_sc_counts_separates_advisory_from_blocking():
    issues = [
        {"ruleId": "X", "wcag": "1.1.1 Non-text Content", "severity": "CRITICAL"},
        {"ruleId": "Y", "wcag": "1.1.1 Non-text Content", "severity": "SERIOUS"},
        {"ruleId": "OFFICE_INTERACTIVE_CONTROL_NAME_ROLE", "wcag": "4.1.2 Name, Role, Value", "severity": "REVIEW"},
        {"ruleId": "OFFICE_INTERACTIVE_CONTROL_KEYBOARD", "wcag": "2.1.2 No Keyboard Trap", "severity": "REVIEW"},
    ]
    fail, review = store._split_sc_counts(issues)
    assert fail == {"1.1.1": 2}
    assert review == {"4.1.2": 1, "2.1.2": 1}


def test_split_sc_counts_ignores_findings_with_no_sc():
    fail, review = store._split_sc_counts([{"ruleId": "Z", "wcag": "not-a-criterion", "severity": "MINOR"}])
    assert fail == {} and review == {}


def test_review_is_a_distinct_outcome_token():
    assert store.REVIEW == "REVIEW"
    assert store.REVIEW not in (store.NOT_EVALUATED, "PASS", "FAIL")
