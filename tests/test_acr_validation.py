"""api/acr_validation.py — PRD §15's blocker categories and the publication gate.

The gate and the validation SCREEN call the same function, which is the property most worth
pinning: a separately-computed readiness summary is how a screen ends up green while the gate is
red. Everything else here is one of PRD §15's nine categories.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import acr_catalog  # noqa: E402
import acr_validation as V  # noqa: E402
from acr_model import Evidence  # noqa: E402

SC = "1.4.3"

COMPLETE_METADATA = {f: f"{f}-value" for f in V.REQUIRED_METADATA}
COMPLETE_METADATA.update({f: f"{f}-value" for f in V.ADVISORY_METADATA})
COMPLETE_METADATA["product_version"] = "1.4.0"


def _report(**kw):
    return dict(COMPLETE_METADATA, status="draft", **kw)


def _criterion(num=SC, **kw):
    base = {
        "criterion_num": num, "criterion_name": "Contrast (Minimum)", "level": "AA",
        "principle": "Perceivable", "guideline": "1.4 Distinguishable", "applicable": True,
        "workflow_state": acr_catalog.DECIDED, "final_status": "Supports", "remarks": None,
        "approval_state": "approved", "evaluator": "alice@x.com", "reviewer": "bob@x.com",
    }
    base.update(kw)
    return base


# Evidence timestamps are RELATIVE TO NOW, not fixed dates. A literal date silently crosses the
# 180-day default validity window as the calendar moves, and the whole suite then fails months
# later with "Supports requires supporting evidence" — which reads like a decision-rule bug and is
# actually an expired fixture. Found exactly that way while writing these tests.
_RECENT = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
_LATER = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


def _ev(result="pass", kind="manual", at=_RECENT, version="1.4.0", **kw):
    if kind == "automated":
        kw.setdefault("tool_name", "axe-core")
        kw.setdefault("coverage", "partial")
    else:
        kw.setdefault("tester", "alice@x.com")
    return Evidence(criterion_num=SC, source_kind=kind, result=result, report_id="rep1",
                    product_version=version, tested_at=at, **kw)


def _cats(blockers):
    return {b.category for b in blockers if b.blocking}


# ── a publishable report ──────────────────────────────────────────────────────────────────────

def test_a_complete_report_has_no_blockers():
    blockers = V.validate(_report(), [_criterion()], {SC: [_ev()]})
    assert V.may_publish(blockers), [b.message for b in V.blocking(blockers)]


# ── PRD §21.10 / §15 missing decision ─────────────────────────────────────────────────────────

def test_an_unevaluated_applicable_criterion_blocks_publication():
    crit = _criterion(workflow_state=acr_catalog.NOT_EVALUATED, final_status=None,
                      approval_state="unapproved")
    blockers = V.validate(_report(), [crit], {})
    assert not V.may_publish(blockers)
    assert V.CATEGORY_MISSING_DECISION in _cats(blockers)


def test_a_full_matrix_of_unevaluated_criteria_blocks_publication():
    """The state a report is in one second after creation."""
    matrix = [dict(r, criterion_num=r["criterion_num"]) for r in acr_catalog.build_matrix("rep1")]
    blockers = V.validate(_report(), matrix, {})
    assert not V.may_publish(blockers)
    assert sum(1 for b in blockers
               if b.category == V.CATEGORY_MISSING_DECISION and b.blocking) == 55


def test_a_value_outside_the_vpat_vocabulary_is_caught_on_the_way_out():
    """Defence in depth. acr_model refuses to build one and the store refuses to write one, but
    this is the last layer before an exported conformance table, so it checks again."""
    blockers = V.validate(_report(), [_criterion(final_status="needs_review")], {SC: [_ev()]})
    assert V.CATEGORY_MISSING_DECISION in _cats(blockers)


# ── PRD §21.7 missing remarks ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", ["Partially Supports", "Does Not Support", "Not Applicable"])
def test_the_limitation_statuses_block_without_remarks(status):
    blockers = V.validate(_report(), [_criterion(final_status=status, remarks=None)],
                          {SC: [_ev()]})
    assert V.CATEGORY_MISSING_REMARKS in _cats(blockers)
    ok = V.validate(_report(), [_criterion(final_status=status, remarks="explained")],
                    {SC: [_ev()]})
    assert V.CATEGORY_MISSING_REMARKS not in _cats(ok)


# ── PRD §21.6 missing evidence ────────────────────────────────────────────────────────────────

def test_supports_with_no_evidence_blocks():
    blockers = V.validate(_report(), [_criterion()], {})
    assert V.CATEGORY_MISSING_EVIDENCE in _cats(blockers)


def test_supports_on_automated_evidence_alone_blocks():
    """PRD §4.3 reaching the publication gate, not just the decision endpoint."""
    blockers = V.validate(_report(), [_criterion()], {SC: [_ev(kind="automated")]})
    assert not V.may_publish(blockers)
    assert V.CATEGORY_CONTRADICTORY in _cats(blockers)


# ── PRD §21.8 unresolved failure ──────────────────────────────────────────────────────────────

def test_an_unresolved_failure_behind_supports_blocks_in_its_own_category():
    ev = [_ev(), _ev(result="fail", at=_LATER)]
    blockers = V.validate(_report(), [_criterion()], {SC: ev})
    assert V.CATEGORY_UNRESOLVED_FAILURE in _cats(blockers)


# ── PRD §21.9 stale evidence ──────────────────────────────────────────────────────────────────

def test_only_stale_evidence_behind_a_claim_blocks():
    stale = _ev(version="1.2.0")  # report is 1.4.0
    blockers = V.validate(_report(), [_criterion()], {SC: [stale]})
    assert V.CATEGORY_STALE in _cats(blockers)


def test_stale_evidence_alongside_live_evidence_is_advisory_not_blocking():
    """Retained for audit history and surfaced, but it does not stop a report whose claim rests
    on live evidence."""
    blockers = V.validate(_report(), [_criterion()], {SC: [_ev(), _ev(version="1.2.0")]})
    advisory = [b for b in blockers if b.category == V.CATEGORY_STALE and not b.blocking]
    assert advisory, [b.to_row() for b in blockers]
    assert V.CATEGORY_STALE not in _cats(blockers)
    assert V.may_publish(blockers)


# ── PRD §8 / §16 metadata ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("field", V.REQUIRED_METADATA)
def test_every_required_metadata_field_blocks_publication_when_empty(field):
    """PRD §16: "Publication must fail if required information is missing." §21.15 names version,
    methods, tools, environments and reviewers specifically; all of them are in this list."""
    report = _report()
    report[field] = ""
    blockers = V.validate(report, [_criterion()], {SC: [_ev()]})
    assert V.CATEGORY_INCOMPLETE_METADATA in _cats(blockers)
    assert any(field.replace("_", " ") in b.message for b in blockers)


def test_the_publication_stamped_fields_are_not_required_beforehand():
    """approver and publication date are supplied BY publishing. Requiring them first would make
    publication impossible — a gate that can never open is not a gate."""
    assert "approver" not in V.REQUIRED_METADATA
    assert "report_publication_date" not in V.REQUIRED_METADATA


@pytest.mark.parametrize("field", V.ADVISORY_METADATA)
def test_the_legitimately_empty_fields_are_advisory(field):
    """"No excluded functionality" is a real answer. Demanding prose trains users to type "n/a"."""
    report = _report()
    report[field] = ""
    blockers = V.validate(report, [_criterion()], {SC: [_ev()]})
    assert V.may_publish(blockers)
    assert any(b.category == V.CATEGORY_INCOMPLETE_METADATA and not b.blocking for b in blockers)


# ── PRD §4.2 approval, §15 manual plans ───────────────────────────────────────────────────────

def test_an_unapproved_criterion_blocks_publication():
    blockers = V.validate(_report(), [_criterion(approval_state="unapproved")], {SC: [_ev()]})
    assert V.CATEGORY_UNAPPROVED in _cats(blockers)


def test_an_incomplete_manual_plan_blocks_when_one_is_declared():
    blockers = V.validate(_report(), [_criterion()], {SC: [_ev()]},
                          manual_plan_status={SC: False})
    assert V.CATEGORY_INCOMPLETE_MANUAL_PLAN in _cats(blockers)


def test_no_manual_plan_data_produces_no_manual_plan_blockers():
    """Phase 1 has no plan catalog. The category must produce nothing rather than pretend to
    know — an empty mapping is "we have not asked", not "everything is complete"."""
    blockers = V.validate(_report(), [_criterion()], {SC: [_ev()]})
    assert V.CATEGORY_INCOMPLETE_MANUAL_PLAN not in {b.category for b in blockers}


# ── PRD §13 contradiction after approval ──────────────────────────────────────────────────────

def test_newer_contradicting_evidence_flags_an_approved_decision():
    ev = [_ev(), _ev(result="fail", at=_LATER)]
    blockers = V.validate(_report(), [_criterion(approval_state="approved")], {SC: ev})
    assert V.CATEGORY_CONTRADICTORY in _cats(blockers) or \
           V.CATEGORY_UNRESOLVED_FAILURE in _cats(blockers)


# ── the property the whole module exists for ──────────────────────────────────────────────────

def test_the_screen_and_the_gate_are_the_same_computation():
    """group() and summary() are projections of validate()'s output, never a second computation.
    If they diverged, the validation screen could show zero blockers while publish refuses."""
    ev = {SC: [_ev(kind="automated")]}
    blockers = V.validate(_report(), [_criterion()], ev)
    summary = V.summary(blockers)
    grouped = V.group(blockers)

    assert summary["may_publish"] is V.may_publish(blockers)
    assert summary["blocking_count"] == len(V.blocking(blockers))
    assert sum(len(rows) for rows in grouped.values()) == len(blockers)
    assert set(grouped) <= set(V.CATEGORY_LABELS)


def test_every_prd_15_category_has_a_label():
    """The validation screen groups by category; an unlabelled one renders as a raw token."""
    for name, value in vars(V).items():
        if name.startswith("CATEGORY_") and isinstance(value, str):
            assert value in V.CATEGORY_LABELS, name
