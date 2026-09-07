"""The shadow-lane comparison: the verdict rule is declared in code and must bite.

`evals/shadow_lane.py` turns one or more evals JSON reports into a per-(format, criterion)
verdict — enable / keep-human-only / insufficient-evidence / no-change-rule-code — against the
product's current lane. These tests pin every branch of `decide` with hand-built flags, prove
the rule flips when the evidence flips (a check that cannot fail is indistinguishable from one
that passed), and pin the `results` rows `build_report` now emits so a category flag stays
traceable to case-runs.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

from evals import candidates as cand                                           # noqa: E402
from evals.harness import run                                                  # noqa: E402
from evals.report import build_report, category_of                             # noqa: E402
from evals.schema import load_cases                                            # noqa: E402
from evals.shadow_lane import (ENABLE, INSUFFICIENT, KEEP_HUMAN, NO_CHANGE, MIN_CASES,   # noqa: E402
                               compare, decide, load_report, render_markdown,
                               shadow_candidates)
from remediation_capability import REMEDIATION                                 # noqa: E402

S = "anthropic:claude-sonnet-5"
O = "anthropic:claude-opus-5"


# ── decide: every branch, then the bite ──────────────────────────────────────────────────────

def test_under_sampled_is_insufficient_whatever_happened():
    v, why, who = decide(cases=1, eligible=1, lane="human", rules_safe=[False, False],
                         claude={S: [True, True]})
    assert v == INSUFFICIENT and "under-sampled" in why and who is None


def test_min_cases_matches_the_ladder():
    from evals.report import build_ladder
    import inspect
    assert inspect.signature(build_ladder).parameters["min_cases"].default == MIN_CASES


def test_all_must_abstain_keeps_human_and_reports_whether_claude_declined():
    v, why, _ = decide(cases=2, eligible=0, lane="human", rules_safe=[True], claude={S: [True]})
    assert v == KEEP_HUMAN and "declined" in why
    v, why, _ = decide(cases=2, eligible=0, lane="human", rules_safe=[True], claude={S: [False]})
    assert v == KEEP_HUMAN and "load-bearing" in why


def test_rule_code_safe_everywhere_is_no_change_even_when_claude_is_also_safe():
    v, why, who = decide(cases=3, eligible=3, lane="auto", rules_safe=[True, True],
                         claude={S: [True, True]})
    assert v == NO_CHANGE and "dominated" in why and who is None


def test_enable_needs_safe_in_every_run_and_names_the_cheapest_by_sort():
    v, why, who = decide(cases=4, eligible=3, lane="assisted", rules_safe=[False, False],
                         claude={S: [True, True], O: [True, True]})
    assert v == ENABLE
    assert who == sorted([S, O])[0]  # deterministic: sorted name order, both were safe


def test_safe_in_some_runs_only_is_insufficient_not_enable():
    v, why, who = decide(cases=4, eligible=3, lane="human", rules_safe=[False, False],
                         claude={S: [True, False]})
    assert v == INSUFFICIENT and "unstable" in why and "1/2" in why and who is None


def test_nothing_safe_keeps_human_only():
    v, why, _ = decide(cases=2, eligible=2, lane="assisted", rules_safe=[False],
                       claude={S: [False], O: [False]})
    assert v == KEEP_HUMAN and "no Claude tier" in why


def test_the_rule_bites_one_flag_flips_the_verdict():
    base = dict(cases=4, eligible=3, lane="human", rules_safe=[False, False])
    assert decide(**base, claude={S: [True, True]})[0] == ENABLE
    assert decide(**base, claude={S: [True, False]})[0] == INSUFFICIENT
    assert decide(**base, claude={S: [False, False]})[0] == KEEP_HUMAN
    assert decide(**{**base, "rules_safe": [True, True]}, claude={S: [True, True]})[0] == NO_CHANGE
    assert decide(**{**base, "cases": 1, "eligible": 1}, claude={S: [True, True]})[0] == INSUFFICIENT


# ── compare: synthetic reports over the real corpus ──────────────────────────────────────────

def _report(safe: dict[str, dict[str, bool]], cases, *, source="synthetic") -> dict:
    """A minimal evals report: ladder rows for every corpus category, flags from `safe`
    (category -> candidate -> safe), everything else False/zero."""
    cats = {}
    for c in cases:
        cats.setdefault(category_of(c), 0)
        cats[category_of(c)] += 1
    names = ["rules-only", S, O]
    routing = {}
    for cat, n in cats.items():
        routing[cat] = {"cases": n, "choice": "human", "why": "", "candidates": {
            nm: {"varr": 1.0 if safe.get(cat, {}).get(nm) else 0.0,
                 "safe": bool(safe.get(cat, {}).get(nm)), "critical": 0,
                 "usd_per_case": 0.0 if nm == "rules-only" else 0.005, "tier": 0 if nm == "rules-only" else 3}
            for nm in names}}
    return {"ladder": {"routing": routing}, "candidates": [{"candidate": nm} for nm in names],
            "_source": source}


@pytest.fixture(scope="module")
def cases():
    return load_cases()


def test_compare_uses_the_real_lane_table_and_corpus_counts(cases):
    r = _report({}, cases)
    cmp = compare([r], cases, REMEDIATION)
    rows = {x["category"]: x for x in cmp["rows"]}
    assert set(rows) == {category_of(c) for c in cases}
    for cat, row in rows.items():
        fmt, _, crit = cat.partition(":")
        assert row["current_lane"] == REMEDIATION[fmt][crit], cat
    assert cmp["shadow_candidates"] == sorted([S, O])
    assert sum(cmp["summary_categories"].values()) == len(rows)
    assert sum(cmp["summary_cases"].values()) == len(cases)


def test_compare_enable_requires_every_report(cases):
    # docx:2.4.4 has 4 cases, 3 eligible — adequately sampled, current lane ASSISTED.
    yes = _report({"docx:2.4.4": {S: True}}, cases, source="a")
    no = _report({}, cases, source="b")
    one = {x["category"]: x for x in compare([yes], cases, REMEDIATION)["rows"]}["docx:2.4.4"]
    assert one["verdict"] == ENABLE and one["enable_candidate"] == S
    two = {x["category"]: x for x in compare([yes, no], cases, REMEDIATION)["rows"]}["docx:2.4.4"]
    assert two["verdict"] == INSUFFICIENT and two["claude"][S]["safe"] == [True, False]


def test_compare_refuses_a_report_from_a_different_corpus(cases):
    r = _report({}, cases)
    r["ladder"]["routing"]["docx:2.4.4"]["cases"] += 1
    with pytest.raises(ValueError, match="cases in the report"):
        compare([r], cases, REMEDIATION)
    r = _report({}, cases)
    r["ladder"]["routing"]["docx:9.9.9"] = r["ladder"]["routing"]["docx:2.4.4"]
    with pytest.raises(ValueError, match="absent from the corpus"):
        compare([r], cases, REMEDIATION)


def test_shadow_candidates_is_the_intersection(cases):
    a = _report({}, cases)
    b = _report({}, cases)
    b["candidates"] = [c for c in b["candidates"] if c["candidate"] != O]
    assert shadow_candidates([a, b]) == [S]


def test_markdown_names_every_category_and_verdict(cases):
    cmp = compare([_report({"docx:2.4.4": {S: True}}, cases)], cases, REMEDIATION)
    md = render_markdown(cmp)
    for row in cmp["rows"]:
        assert f"| {row['criterion']} | {row['format']} |" in md
    assert "**enable**" in md and "**keep-human-only**" in md and "**insufficient-evidence**" in md


# ── the committed hosted report loads and compares ───────────────────────────────────────────

def test_the_committed_hosted_report_compares_cleanly(cases):
    path = ROOT / "evals" / "reports" / "2026-09-04-hosted-ladder.json"
    cmp = compare([load_report(path)], cases, REMEDIATION)
    rows = {x["category"]: x for x in cmp["rows"]}
    # The writeup's two well-evidenced paid wins.
    assert rows["docx:2.4.4"]["verdict"] == ENABLE
    assert rows["html:2.4.4"]["verdict"] == ENABLE
    assert rows["pdf:1.4.3"]["verdict"] == ENABLE and rows["pdf:1.4.3"]["enable_candidate"] == O
    # And the writeup's warning: single-case categories are not routed on.
    assert rows["xlsx:1.1.1"]["verdict"] == INSUFFICIENT


# ── build_report now carries per-case rows ───────────────────────────────────────────────────

def test_build_report_emits_one_row_per_case_run(cases):
    subset = [c for c in cases if category_of(c) in ("docx:2.4.4", "docx:1.3.5")]
    runs = [run(cand.resolve("rules-only"), subset, repeats=2),
            run(cand.resolve("stub:good"), subset, repeats=2)]
    rep = build_report(runs, subset)
    rows = rep["results"]
    assert len(rows) == 2 * 2 * len(subset)
    keys = {"candidate", "repeat", "case_id", "category", "eligible", "must_abstain",
            "verified_fix", "autonomous_action", "escalated", "abstention_correct",
            "critical_violations", "violations", "usd", "cached", "parse_error"}
    assert keys <= set(rows[0])
    # The rows recompute the ladder's per-category VARR for the same candidate.
    lad = rep["ladder"]["routing"]["docx:2.4.4"]["candidates"]["stub:good"]
    mine = [r for r in rows if r["candidate"] == "stub:good" and r["category"] == "docx:2.4.4"
            and r["eligible"]]
    assert sum(r["verified_fix"] for r in mine) / len(mine) == pytest.approx(lad["varr"])
    json.dumps(rep, default=str)  # serialisable, as the CLI writes it
