"""api/acr_axe.py — turning an axe-core run into ACR evidence (PRD §7.6, §13).

This module is where an accessibility tool would most easily invent conformance, so the tests are
weighted toward what it must REFUSE to record rather than what it records.

The three refusals, in the order they are easiest to get wrong:

  1. `inapplicable` is not a pass. axe reports a rule inapplicable when no element on the page
     matched it. A page with no <video> says nothing about whether the product captions its
     videos. Recording that as evidence for 1.2.2 manufactures conformance out of absence.
  2. `incomplete` is not a pass. axe is saying it could not decide — contrast over a background
     image is the canonical case. It becomes BLOCKED, which acr_rules already refuses to treat as
     a positive result.
  3. A clean run does not certify. Every row declares PARTIAL coverage, so ingesting a completely
     green axe run moves no criterion to "Supports" (ADR 0031, PRD §4.3).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import acr_axe  # noqa: E402
import acr_rules  # noqa: E402


def _run(violations=(), passes=(), incomplete=(), inapplicable=()):
    return {
        "testEngine": {"name": "axe-core", "version": "4.12.1"},
        "url": "http://localhost:5173/assess",
        "timestamp": "2026-09-01T20:00:00.000Z",
        "violations": list(violations), "passes": list(passes),
        "incomplete": list(incomplete), "inapplicable": list(inapplicable),
    }


def _rule(rid, *tags, help="a rule", nodes=1):
    return {"id": rid, "tags": list(tags), "help": help, "nodes": [{} for _ in range(nodes)]}


# ── tag decoding ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tag,expected", [
    ("wcag111", "1.1.1"),
    ("wcag143", "1.4.3"),
    ("wcag2411", "2.4.11"),   # two-digit criterion — the case a naive 3-char split gets wrong
    ("wcag412", "4.1.2"),
])
def test_axe_tags_decode_to_criteria(tag, expected):
    assert acr_axe.criteria_for_tags([tag]) == [expected]


def test_non_wcag_tags_are_ignored():
    assert acr_axe.criteria_for_tags(["cat.color", "best-practice", "wcag2aa", "ACT"]) == []


def test_a_rule_spanning_two_criteria_yields_both():
    assert acr_axe.criteria_for_tags(["wcag143", "wcag1411"]) == ["1.4.3", "1.4.11"]


def test_the_decoding_matches_the_frontends():
    """frontend/src/htmlAudit.js and A11ySelfCheck.jsx decode the same tags. Three readers of one
    convention is how they drift; this pins the regex against the JS one's source."""
    js = (ACP / "frontend" / "src" / "htmlAudit.js").read_text(encoding="utf-8")
    assert r"/^wcag(\d)(\d)(\d+)$/" in js, "htmlAudit.js changed its tag regex"
    assert acr_axe._TAG.pattern == r"^wcag(\d)(\d)(\d+)$"


# ── the three refusals ────────────────────────────────────────────────────────────────────────

def test_inapplicable_is_never_ingested():
    """THE central refusal. A page with no video tells you nothing about 1.2.2."""
    payload = _run(inapplicable=[_rule("video-caption", "wcag2a", "wcag122", nodes=0),
                                 _rule("audio-caption", "wcag2a", "wcag121", nodes=0)])
    records, report = acr_axe.to_evidence(payload, report_id="r1")
    assert records == []
    assert report["dropped_inapplicable"] == 2
    assert "1.2.1" not in report["criteria"] and "1.2.2" not in report["criteria"]


def test_the_dropped_bucket_is_reported_not_silently_omitted():
    """"312 results, 47 ingested" needs to say where the rest went."""
    payload = _run(passes=[_rule("image-alt", "wcag111")],
                   inapplicable=[_rule("video-caption", "wcag122", nodes=0)])
    summary = acr_axe.summarize(payload)
    assert summary["counts"]["inapplicable"] == 1
    assert "not evidence about the criterion" in summary["dropped_reason"]


def test_incomplete_becomes_blocked_never_a_pass():
    payload = _run(incomplete=[_rule("color-contrast", "wcag143", help="contrast over an image")])
    records, _ = acr_axe.to_evidence(payload, report_id="r1")
    assert [e.result for e in records] == ["blocked"]
    assert "could not decide" in records[0].notes
    # …and acr_rules refuses to read that as a positive result.
    assert not acr_rules.has_human_pass(records)


def test_a_perfectly_clean_run_moves_nothing_to_supports():
    """PRD §4.3 through the ingestion path, not just the decision endpoint."""
    payload = _run(passes=[_rule("image-alt", "wcag2a", "wcag111"),
                           _rule("color-contrast", "wcag2aa", "wcag143")])
    records, report = acr_axe.to_evidence(payload, report_id="r1", product_version="1.0")
    assert report["by_result"]["pass"] == 2

    for sc in report["criteria"]:
        ev = [e for e in records if e.criterion_num == sc]
        assert acr_rules.may_draft(sc, ev)[0] is None
        assert not acr_rules.may_select_final_status(
            "Supports", criterion_num=sc, evidence=ev, remarks=None).allowed


def test_every_ingested_row_declares_partial_coverage():
    payload = _run(violations=[_rule("color-contrast", "wcag143")],
                   passes=[_rule("image-alt", "wcag111")],
                   incomplete=[_rule("link-name", "wcag244")])
    records, _ = acr_axe.to_evidence(payload, report_id="r1")
    assert {e.coverage for e in records} == {"partial"}
    assert all(e.is_automated for e in records)


# ── provenance (PRD §13) ──────────────────────────────────────────────────────────────────────

def test_the_original_rule_id_tool_version_and_url_are_preserved():
    payload = _run(violations=[_rule("color-contrast", "wcag143")])
    records, _ = acr_axe.to_evidence(payload, report_id="r1")
    e = records[0]
    assert e.tool_name == "axe-core"
    assert e.tool_version == "4.12.1"
    assert e.rule_id == "color-contrast"
    assert e.tested_url == "http://localhost:5173/assess"
    assert e.tested_at == "2026-09-01T20:00:00.000Z", "the run's own timestamp, not ingest time"


def test_one_record_per_rule_and_criterion_pair():
    """A rule tagged for two criteria produces two rows — each criterion's evidence list has to
    stand on its own when a reviewer reads it."""
    payload = _run(violations=[_rule("some-rule", "wcag143", "wcag1411")])
    records, _ = acr_axe.to_evidence(payload, report_id="r1")
    assert sorted(e.criterion_num for e in records) == ["1.4.11", "1.4.3"]
    assert {e.rule_id for e in records} == {"some-rule"}


def test_report_metadata_is_stamped_onto_every_row():
    payload = _run(violations=[_rule("color-contrast", "wcag143")])
    records, _ = acr_axe.to_evidence(payload, report_id="r1", product_version="1.4.0",
                                     build_id="b-900", environment="staging",
                                     workflow="assess", tester="alice@x.com")
    e = records[0]
    assert (e.product_version, e.build_id, e.environment, e.workflow, e.tester) == \
           ("1.4.0", "b-900", "staging", "assess", "alice@x.com")


# ── things that are not criteria ──────────────────────────────────────────────────────────────

def test_best_practice_rules_are_counted_not_attached():
    """axe's best-practice rules are real findings and are not WCAG criteria. They have nowhere to
    go in a conformance report, so they are reported rather than silently dropped."""
    payload = _run(passes=[_rule("landmark-one-main", "cat.semantics", "best-practice")])
    records, report = acr_axe.to_evidence(payload, report_id="r1")
    assert records == []
    assert report["unmapped_rules"] == ["landmark-one-main"]


def test_criteria_outside_the_report_are_skipped_and_counted():
    """A WCAG 2.1-only or AAA tag names a criterion this report's catalog does not carry."""
    payload = _run(violations=[_rule("color-contrast", "wcag143"),
                               _rule("meta-refresh", "wcag221")])
    records, report = acr_axe.to_evidence(payload, report_id="r1", known_criteria={"1.4.3"})
    assert [e.criterion_num for e in records] == ["1.4.3"]
    assert report["skipped_out_of_scope"] == {"2.2.1": 1}


# ── malformed input ───────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [{}, {"foo": 1}, [], "axe", None])
def test_a_payload_that_is_not_an_axe_run_is_refused(bad):
    with pytest.raises(acr_axe.AxeIngestError):
        acr_axe.to_evidence(bad, report_id="r1")


def test_an_empty_but_valid_run_ingests_nothing_without_erroring():
    records, report = acr_axe.to_evidence(_run(), report_id="r1")
    assert records == [] and report["ingested"] == 0


def test_a_rule_with_no_id_still_maps_its_criterion():
    """Defensive: an id-less rule is malformed axe output, but dropping its criterion silently
    would lose a real finding. It is ingested with a null rule_id."""
    payload = _run(violations=[{"tags": ["wcag143"], "nodes": [{}]}])
    records, _ = acr_axe.to_evidence(payload, report_id="r1")
    assert len(records) == 1 and records[0].rule_id is None
