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


def test_a_category_whose_case_count_moved_is_dropped_not_judged_on_the_stale_count(cases):
    """The corpus gained a case in this category since the run. The old measurement is of a
    different case set, so the category is unmeasured — not judged on what it used to be."""
    r = _report({}, cases)
    r["ladder"]["routing"]["docx:2.4.4"]["cases"] += 1
    cmp = compare([r], cases, REMEDIATION)
    assert "docx:2.4.4" in cmp["unmeasured_categories"]
    assert "docx:2.4.4" not in {row["category"] for row in cmp["rows"]}
    # Every other category is unaffected: one moved category does not void the comparison.
    assert len(cmp["rows"]) == len({category_of(c) for c in cases}) - 1


def test_compare_refuses_reports_with_nothing_in_common(cases):
    r = _report({}, cases)
    r["ladder"]["routing"] = {"zzz:9.9.9": {"cases": 1, "choice": "human", "why": "",
                                            "candidates": {}}}
    with pytest.raises(ValueError, match="not comparable at all"):
        compare([r], cases, REMEDIATION)


def test_agreement_is_decided_per_category_not_across_the_whole_corpus(cases):
    """Two runs, identical but for one category whose case count moved between them. The 58
    that match are pooled and get two runs of evidence; the one that moved is judged only on
    the run that matches the reference, and the row says so."""
    a = _report({"docx:2.4.4": {S: True}}, cases, source="run-a")
    b = _report({"docx:2.4.4": {S: True}}, cases, source="run-b")
    a["ladder"]["routing"]["docx:3.1.1"]["cases"] += 1        # run-a saw a different case set
    cmp = compare([a, b], cases, REMEDIATION)
    rows = {x["category"]: x for x in cmp["rows"]}
    assert rows["docx:2.4.4"]["runs"] == 2 and rows["docx:2.4.4"]["runs_not_pooled"] == 0
    moved = rows["docx:3.1.1"]
    assert moved["runs"] == 1 and moved["runs_not_pooled"] == 1
    assert "were not pooled into it" in moved["why"]
    assert "docx:3.1.1" in render_markdown(cmp) and "Judged on fewer runs" in render_markdown(cmp)
    # The pooled category still needs BOTH runs safe to enable — pooling is not weakened.
    # Safe in one and not the other is INSUFFICIENT ("unstable across runs"), never ENABLE.
    b2 = _report({}, cases, source="run-b2")
    assert {x["category"]: x for x in compare([a, b2], cases, REMEDIATION)["rows"]
            }["docx:2.4.4"]["verdict"] == INSUFFICIENT


def test_reports_carry_their_own_counts_and_must_agree(cases):
    # A report written after `corpus.categories` was added is judged on the counts IT saw,
    # even when the committed corpus has since grown.
    r = _report({"docx:2.4.4": {S: True}}, cases, source="carried")
    r["corpus"] = {"categories": {cat: {"cases": row["cases"], "eligible": row["cases"],
                                        "must_abstain": 0}
                                  for cat, row in r["ladder"]["routing"].items()}}
    r["corpus"]["categories"]["docx:2.4.4"]["cases"] = 9
    r["ladder"]["routing"]["docx:2.4.4"]["cases"] = 9
    cmp = compare([r], None, REMEDIATION)
    assert cmp["corpus_cases"] == len(cases) + 5
    row = {x["category"]: x for x in cmp["rows"]}["docx:2.4.4"]
    assert row["cases"] == 9 and row["verdict"] == ENABLE
    with pytest.raises(ValueError, match="no corpus was passed"):
        compare([_report({}, cases)], None, REMEDIATION)


def test_the_two_committed_reports_still_compare_on_their_own_100_case_counts(cases):
    reps = [load_report(ROOT / "evals" / "reports" / f"{d}-hosted-ladder.json")
            for d in ("2026-09-04", "2026-09-07")]
    cmp = compare(reps, None, REMEDIATION)
    assert cmp["corpus_cases"] == 100 and len(cases) > 100
    assert all(r["runs"] == 2 for r in cmp["rows"]), "same corpus: every category pools both runs"
    rows = {x["category"]: x for x in cmp["rows"]}
    assert rows["docx:2.4.4"]["verdict"] == ENABLE
    assert rows["xlsx:1.1.1"]["verdict"] == INSUFFICIENT


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
    """Judged on the corpus THAT RUN saw (`cases=None`), which is the only honest reading of a
    historical run: the live corpus has moved several of its categories since."""
    path = ROOT / "evals" / "reports" / "2026-09-04-hosted-ladder.json"
    cmp = compare([load_report(path)], None, REMEDIATION)
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


# ── the enable pick is the CHEAPEST safe tier, not the first alphabetically ───────────────────

def test_enable_names_the_cheapest_safe_tier_not_the_alphabetical_first():
    """Measured on the 142-case run: Opus and Sonnet were both safe on html:2.4.4, and naming
    `sorted(safe)[0]` picked Opus at 4x Sonnet's cost. Cheapest-that-is-safe is the claim."""
    both = {O: [True], S: [True]}
    base = dict(cases=5, eligible=3, lane="assisted", rules_safe=[False])
    v, why, who = decide(**base, claude=both, costs={O: 0.0124, S: 0.0028})
    assert v == ENABLE and who == S, "the cheaper safe tier must be the one named"
    assert "cheapest of 2 safe here" in why and O in why
    # Flip the prices and the pick flips with them — the rule follows the measurement.
    assert decide(**base, claude=both, costs={O: 0.0028, S: 0.0124})[2] == O
    # Alphabetical order alone must not decide it: O sorts first and is the dearer one above.
    assert sorted([O, S])[0] == O


def test_enable_pick_is_deterministic_when_costs_tie_or_are_missing():
    base = dict(cases=5, eligible=3, lane="assisted", rules_safe=[False], claude={O: [True], S: [True]})
    assert decide(**base, costs={O: 0.01, S: 0.01})[2] == sorted([O, S])[0]
    assert decide(**base, costs={})[2] == sorted([O, S])[0]
    assert decide(**base, costs={O: None, S: 0.05})[2] == S  # a priced tier beats an unpriced one


def test_the_committed_142_run_picks_sonnet_for_html_2_4_4(cases):
    path = ROOT / "evals" / "reports" / "2026-09-07-hosted-ladder-142.json"
    if not path.exists():                     # the report lands with its own commit
        pytest.skip("142-case report not committed yet")
    cmp = compare([load_report(path)], None, REMEDIATION)
    rows = {x["category"]: x for x in cmp["rows"]}
    row = rows["html:2.4.4"]
    assert row["verdict"] == ENABLE and row["enable_candidate"] == S
    assert row["claude"][S]["mean_usd_per_case"] < row["claude"][O]["mean_usd_per_case"]


def test_a_corpus_category_the_reports_never_saw_is_reported_as_unmeasured(cases):
    """A lane that moves after a run enters the corpus with no measurement behind it. That is
    no evidence, not insufficient evidence, and it must not vanish from the table."""
    subset = [c for c in cases if category_of(c) != "pptx:1.4.5"]
    r = _report({}, subset)
    cmp = compare([r], cases, REMEDIATION)
    assert "pptx:1.4.5" in cmp["unmeasured_categories"]
    assert "pptx:1.4.5" not in {row["category"] for row in cmp["rows"]}
    assert "pptx:1.4.5" in render_markdown(cmp)
    # A report covering everything reports nothing unmeasured.
    assert compare([_report({}, cases)], cases, REMEDIATION)["unmeasured_categories"] == []
