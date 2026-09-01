"""api/acr_freshness.py — PRD §12's five staleness triggers.

Evidence goes stale, and stale evidence that still counts is how an ACR ends up claiming
conformance for a build nobody tested. All five triggers the PRD names are exercised here, plus
the two properties that are easy to get backwards:

  * stale evidence stays VISIBLE (§12: "remains visible for audit history") — it is excluded from
    decisions, never hidden or deleted.
  * staleness is DERIVED, not stored. A stored flag is wrong the moment the report's product
    version is edited, with no write to any evidence row to trigger a recompute.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import acr_freshness as fresh  # noqa: E402
import acr_rules  # noqa: E402
from acr_model import Evidence  # noqa: E402

SC = "1.4.3"
NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)
REPORT = {"product_version": "1.4.0", "build_id": "b-900", "evidence_validity_days": 180}


def _ev(result="pass", version="1.4.0", build="b-900", days_ago=1, workflow=None, kind="manual"):
    return Evidence(criterion_num=SC, source_kind=kind, result=result, report_id="rep1",
                    tester="alice@x.com", product_version=version, build_id=build,
                    workflow=workflow,
                    tested_at=(NOW - timedelta(days=days_ago)).isoformat())


def test_fresh_evidence_is_not_stale():
    e = _ev()
    assert fresh.evaluate(REPORT, [e], now=NOW) == {}


# ── the five PRD §12 triggers ─────────────────────────────────────────────────────────────────

def test_1_evidence_from_a_different_product_version_is_stale():
    e = _ev(version="1.3.0")
    assert fresh.evaluate(REPORT, [e], now=NOW) == {e.id: fresh.STALE_VERSION}


def test_2_a_different_build_marks_the_component_changed():
    e = _ev(build="b-880")
    assert fresh.evaluate(REPORT, [e], now=NOW) == {e.id: fresh.STALE_COMPONENT_CHANGED}


def test_2b_an_explicitly_changed_workflow_marks_its_evidence_stale():
    """Same version, same build, but the screen under test was rebuilt."""
    e = _ev(workflow="remediation-review")
    got = fresh.evaluate(REPORT, [e], now=NOW, changed_workflows={"remediation-review"})
    assert got == {e.id: fresh.STALE_COMPONENT_CHANGED}


def test_3_evidence_past_the_validity_window_is_stale():
    e = _ev(days_ago=200)
    assert fresh.evaluate(REPORT, [e], now=NOW) == {e.id: fresh.STALE_EXPIRED}


def test_3b_the_validity_window_is_per_report():
    e = _ev(days_ago=45)
    assert fresh.evaluate(REPORT, [e], now=NOW) == {}
    strict = dict(REPORT, evidence_validity_days=30)
    assert fresh.evaluate(strict, [e], now=NOW) == {e.id: fresh.STALE_EXPIRED}


def test_4_a_pass_contradicted_by_a_later_failure_is_stale():
    """A regression scan contradicts it (§12)."""
    ok = _ev(result="pass", days_ago=30)
    bad = _ev(result="fail", days_ago=2)
    got = fresh.evaluate(REPORT, [ok, bad], now=NOW)
    assert got == {ok.id: fresh.STALE_CONTRADICTED}, "the failure itself must not be marked stale"


def test_4b_a_failure_is_not_made_stale_by_a_later_pass():
    """The asymmetry is deliberate. A resolved failure must stay visible AS a resolved failure —
    acr_rules.open_failures excludes it from blocking, and that is where resolution belongs.
    Marking it stale here would make the resolution look like an expiry."""
    bad = _ev(result="fail", days_ago=30)
    ok = _ev(result="pass", days_ago=2)
    assert fresh.evaluate(REPORT, [bad, ok], now=NOW) == {}
    assert acr_rules.open_failures([bad, ok]) == []


def test_5_a_reopened_finding_stales_the_pass_that_closed_it():
    ok = _ev(result="pass", days_ago=5)
    got = fresh.evaluate(REPORT, [ok], now=NOW, reopened_criteria={SC})
    assert got == {ok.id: fresh.STALE_REOPENED}


# ── the two properties that are easy to invert ────────────────────────────────────────────────

def test_stale_evidence_remains_visible_but_cannot_support_a_claim():
    """PRD §12's exact wording, both halves. §21.9 depends on it."""
    old = _ev(version="1.3.0")
    stale = fresh.evaluate(REPORT, [old], now=NOW)
    assert old.id in stale

    # Visible: still in the list, and annotate labels it rather than dropping it.
    annotated = fresh.annotate(REPORT, [old], now=NOW)
    assert len(annotated) == 1
    assert annotated[0].stale_reason == fresh.STALE_VERSION

    # Cannot support: Supports is refused when the only evidence is stale.
    v = acr_rules.may_select_final_status("Supports", criterion_num=SC, evidence=[old],
                                          remarks=None, stale_ids=set(stale))
    assert not v.allowed


def test_staleness_follows_the_report_with_no_write_to_the_evidence():
    """The reason it is derived rather than stored. Editing the report's product version changes
    every row's staleness, and nothing writes to any evidence row when that happens."""
    e = _ev(version="1.4.0")
    assert fresh.evaluate(REPORT, [e], now=NOW) == {}
    bumped = dict(REPORT, product_version="1.5.0")
    assert fresh.evaluate(bumped, [e], now=NOW) == {e.id: fresh.STALE_VERSION}


def test_evidence_with_no_recorded_version_is_a_gap_not_a_staleness_verdict():
    """Two different problems need two different words. An unversioned row cannot be compared to
    the report at all — calling it "stale" would imply we checked and it failed. acr_validation
    reports the missing metadata instead."""
    e = _ev(version=None, build=None)
    assert fresh.evaluate(REPORT, [e], now=NOW) == {}


def test_an_unparseable_timestamp_does_not_crash_or_silently_expire():
    e = _ev()
    e.tested_at = "not-a-timestamp"
    assert fresh.evaluate(REPORT, [e], now=NOW) == {}
