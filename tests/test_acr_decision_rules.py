"""api/acr_rules.py — what evidence permits, and what it never permits (ADR 0047).

This is the file that keeps the ACR honest, so it is the file worth reading before changing any
of the rules. Three PRD guarantees live here, and each has a way of quietly eroding:

  §4.3   an automated pass never produces "Supports". Erodes by someone adding a "the tool is
         accurate enough now" exception — which is the wrong axis (ADR 0031: coverage, not
         confidence).
  §21.8  a known unresolved failure blocks "Supports". Erodes by treating any later pass as
         resolution, including one recorded against a build that no longer exists.
  §10    Partially Supports / Does Not Support / Not Applicable require remarks. Erodes by a
         caller passing a whitespace string.

Tests construct Evidence objects directly — no store, no HTTP. The rules are pure functions over
records precisely so this is possible.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import acr_rules  # noqa: E402
from acr_model import AcrValidationError, CriterionDecision, Evidence  # noqa: E402

SC = "1.4.3"          # Contrast (Minimum), AA — the Phase 1 vertical slice
REPORT = "rep1"
VERSION = "1.4.0"


def _auto(result="pass", coverage="partial", at="2026-01-01T00:00:00+00:00", **kw):
    """An axe-core result. `coverage` defaults to PARTIAL because that is what axe actually is:
    it has a rule for this criterion and that rule does not reach the whole criterion."""
    kw.setdefault("tool_name", "axe-core")
    kw.setdefault("tool_version", "4.12.1")
    kw.setdefault("rule_id", "color-contrast")
    return Evidence(criterion_num=SC, source_kind="automated", result=result, report_id=REPORT,
                    coverage=coverage, product_version=VERSION, tested_at=at, **kw)


def _manual(result="pass", at="2026-01-02T00:00:00+00:00", kind="manual", **kw):
    kw.setdefault("tester", "alice@x.com")
    return Evidence(criterion_num=SC, source_kind=kind, result=result, report_id=REPORT,
                    product_version=VERSION, tested_at=at, **kw)


# ── PRD §4.3 — an automated pass is not a pass ────────────────────────────────────────────────

def test_a_clean_automated_result_does_not_draft_supports():
    draft, why = acr_rules.may_draft(SC, [_auto()])
    assert draft is None
    assert "coverage=partial" in why


def test_a_clean_automated_result_does_not_permit_supports():
    v = acr_rules.may_select_final_status("Supports", criterion_num=SC, evidence=[_auto()],
                                          remarks=None)
    assert not v.allowed
    assert "automated evidence alone" in v.reason


@pytest.mark.parametrize("coverage", ["declared", "heuristic", "partial"])
def test_no_sub_full_coverage_can_certify_a_pass(coverage):
    """The rule is coverage-gated, not tool-gated. Any technique that does not reach the whole
    criterion produces the same answer, however exact it is about the part it does reach."""
    assert acr_rules.may_draft(SC, [_auto(coverage=coverage)])[0] is None


def test_full_coverage_is_the_one_automated_case_that_drafts_supports():
    """The escape hatch exists, and it is the same one the document pipeline uses
    (assessment.CAN_CERTIFY_PASS == {Coverage.FULL}). No axe rule declares FULL today, so this is
    currently unreachable in practice — it is asserted so that the rule is coverage-gated rather
    than a blanket ban that would be wrong the day a complete technique exists."""
    draft, why = acr_rules.may_draft(SC, [_auto(coverage="full")])
    assert draft == "Supports"
    assert "FULL coverage" in why


def test_automated_evidence_must_declare_its_coverage_at_construction():
    """An undeclared coverage would reach the gate as "unknown", and unknown must never quietly
    mean "fine". Refused where the caller can still say what its tool reaches."""
    with pytest.raises(AcrValidationError, match="coverage"):
        Evidence(criterion_num=SC, source_kind="automated", result="pass", report_id=REPORT,
                 tool_name="axe-core")


def test_automated_evidence_must_name_its_tool():
    with pytest.raises(AcrValidationError, match="tool"):
        Evidence(criterion_num=SC, source_kind="automated", result="pass", report_id=REPORT,
                 coverage="partial")


# ── human evidence completes the picture ──────────────────────────────────────────────────────

def test_a_human_pass_alongside_the_automated_one_permits_supports():
    ev = [_auto(), _manual()]
    assert acr_rules.may_draft(SC, ev)[0] == "Supports"
    assert acr_rules.may_select_final_status("Supports", criterion_num=SC, evidence=ev,
                                             remarks=None).allowed


@pytest.mark.parametrize("kind", ["keyboard", "screen_reader", "visual", "code", "user",
                                  "documentation", "external", "remediation_verification"])
def test_every_non_automated_kind_counts_as_human_evaluation(kind):
    """PRD §4.3 names keyboard, screen-reader, visual, cognitive, content and usability judgement
    as the things that must reach a person. An external assessor's report is human judgement too
    — ACP did not perform it, but a person did."""
    assert acr_rules.may_draft(SC, [_auto(), _manual(kind=kind)])[0] == "Supports"


def test_a_blocked_human_test_is_not_a_pass():
    """A tester who could not complete the test has not established anything. Drafting Supports
    here would invent the conclusion they declined to reach."""
    draft, why = acr_rules.may_draft(SC, [_auto(), _manual(result="blocked")])
    assert draft is None
    # …and specifically because the HUMAN result is not a pass. The automated row beside it IS a
    # pass, so a rule asking "did anything pass?" would answer yes here — which is the bug this
    # test found.
    assert "no passing human result" in why
    v = acr_rules.may_select_final_status("Supports", criterion_num=SC,
                                          evidence=[_auto(), _manual(result="blocked")],
                                          remarks=None)
    assert not v.allowed and "blocked test is not a pass" in v.reason


def test_a_not_applicable_human_result_alone_does_not_draft_supports():
    assert acr_rules.may_draft(SC, [_auto(), _manual(result="not_applicable")])[0] is None


# ── PRD §21.8 — an unresolved failure blocks Supports ─────────────────────────────────────────

def test_an_open_failure_blocks_supports():
    ev = [_auto(), _manual(), _manual(result="fail", at="2026-03-01T00:00:00+00:00")]
    v = acr_rules.may_select_final_status("Supports", criterion_num=SC, evidence=ev, remarks=None)
    assert not v.allowed
    assert "unresolved failure" in v.reason
    assert len(acr_rules.open_failures(ev)) == 1


def test_newer_passing_evidence_resolves_the_contradiction():
    """PRD §21.8's escape hatch: "explicitly resolved by newer evidence"."""
    ev = [_manual(result="fail", at="2026-03-01T00:00:00+00:00"),
          _manual(result="pass", at="2026-04-01T00:00:00+00:00")]
    assert acr_rules.open_failures(ev) == []
    assert acr_rules.may_select_final_status("Supports", criterion_num=SC, evidence=ev,
                                             remarks=None).allowed


def test_an_older_pass_does_not_resolve_a_newer_failure():
    """The direction matters. A pass recorded BEFORE the failure is not a resolution of it."""
    ev = [_manual(result="pass", at="2026-01-01T00:00:00+00:00"),
          _manual(result="fail", at="2026-04-01T00:00:00+00:00")]
    assert len(acr_rules.open_failures(ev)) == 1


def test_stale_passing_evidence_cannot_resolve_a_failure():
    """PRD §12: stale evidence "cannot independently support publication". A pass against a build
    that no longer exists must not be able to clear a live failure."""
    fail = _manual(result="fail", at="2026-03-01T00:00:00+00:00")
    stale_pass = _manual(result="pass", at="2026-04-01T00:00:00+00:00")
    assert acr_rules.open_failures([fail, stale_pass]) == []
    assert len(acr_rules.open_failures([fail, stale_pass], {stale_pass.id})) == 1


def test_a_failure_is_still_reported_as_a_failure_when_a_later_pass_exists():
    """Resolution must be VISIBLE as a resolution, not a disappearance — the audit history is the
    point. The failing row stays in the evidence list; only open_failures excludes it."""
    ev = [_manual(result="fail", at="2026-03-01T00:00:00+00:00"),
          _manual(result="pass", at="2026-04-01T00:00:00+00:00")]
    summary = acr_rules.summarize(SC, ev)
    assert summary["evidence_total"] == 2
    assert summary["open_failures"] == []


# ── PRD §10 — remarks, and the other three statuses ───────────────────────────────────────────

@pytest.mark.parametrize("status", ["Partially Supports", "Does Not Support", "Not Applicable"])
def test_the_three_limitation_statuses_require_remarks(status):
    ev = [_auto(), _manual()]
    assert not acr_rules.may_select_final_status(status, criterion_num=SC, evidence=ev,
                                                 remarks=None).allowed
    assert not acr_rules.may_select_final_status(status, criterion_num=SC, evidence=ev,
                                                 remarks="   ").allowed, "whitespace is not remarks"
    assert acr_rules.may_select_final_status(status, criterion_num=SC, evidence=ev,
                                             remarks="a real explanation").allowed


def test_supports_does_not_require_remarks_but_does_require_evidence():
    """The asymmetry is deliberate: Supports is gated on evidence, the limitation statuses on
    explanation. PRD §21.6 — "every final status has evidence OR a required explanation"."""
    assert acr_rules.may_select_final_status("Supports", criterion_num=SC,
                                             evidence=[_auto(), _manual()], remarks=None).allowed
    v = acr_rules.may_select_final_status("Supports", criterion_num=SC, evidence=[], remarks=None)
    assert not v.allowed and "evidence" in v.reason


def test_does_not_support_needs_no_evidence():
    """Reporting a limitation honestly must never be harder than claiming conformance. The
    limitation IS the finding."""
    assert acr_rules.may_select_final_status("Does Not Support", criterion_num=SC, evidence=[],
                                             remarks="dialog traps focus").allowed


def test_partially_supports_needs_evidence_because_it_describes_evaluated_behaviour():
    v = acr_rules.may_select_final_status("Partially Supports", criterion_num=SC, evidence=[],
                                          remarks="some of it works")
    assert not v.allowed


def test_an_internal_workflow_state_is_never_a_conformance_level():
    """PRD §9 permits internal states and forbids them appearing as VPAT levels."""
    for bad in ("not_evaluated", "needs_review", "decided", "Supported", ""):
        assert not acr_rules.may_select_final_status(bad, criterion_num=SC, evidence=[],
                                                     remarks="x").allowed
    with pytest.raises(AcrValidationError):
        CriterionDecision(report_id=REPORT, criterion_num=SC, final_status="needs_review",
                          decided_by="alice@x.com")


def test_a_decision_must_record_who_made_it():
    with pytest.raises(AcrValidationError, match="who made it"):
        CriterionDecision(report_id=REPORT, criterion_num=SC, final_status="Supports",
                          decided_by="")


# ── PRD §13 — newer evidence contradicting an approved decision ───────────────────────────────

def test_a_contradiction_after_approval_is_flagged_not_auto_corrected():
    """PRD §13: ACP must "never change a final conformance status automatically after approval",
    only "flag approved decisions when newer evidence contradicts them"."""
    ev = [_manual(), _manual(result="fail", at="2026-06-01T00:00:00+00:00")]
    why = acr_rules.contradicts_approved_decision("Supports", ev)
    assert why and "re-review" in why
    assert acr_rules.contradicts_approved_decision("Does Not Support", ev) is None


def test_summarize_and_the_gate_never_disagree():
    """The screen renders summarize(); the POST calls may_select_final_status(). If they could
    differ, the UI would offer a button the server rejects."""
    ev = [_auto()]
    summary = acr_rules.summarize(SC, ev)
    for status, allowed in summary["permitted_statuses"].items():
        direct = acr_rules.may_select_final_status(status, criterion_num=SC, evidence=ev,
                                                   remarks="(pending)")
        assert direct.allowed == allowed, status
