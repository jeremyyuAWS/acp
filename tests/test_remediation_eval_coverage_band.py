"""The coverage band: every (format, criterion) category gets a second case, and it is real.

Two hosted runs on the 100-case corpus left 42 of 59 categories with one case, where the
ladder refuses to route and the shadow-lane comparison returns insufficient-evidence whatever
the model did. `build_coverage` adds one case to exactly those categories. These tests pin
that it is exactly those, that each second case is a different call (not a cache hit on the
first), that its lane and eligibility follow REMEDIATION, and that the free candidates handle
it the way they handle the rest of the corpus — the bite check that the new fixtures are
executable, not just valid.
"""
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

from evals import candidates as cand                                     # noqa: E402
from evals.candidates import AUTO_PLAYBOOK, build_prompt                  # noqa: E402
from evals.harness import run                                            # noqa: E402
from evals.report import build_ladder, build_report, category_of          # noqa: E402
from evals.schema import load_cases                                      # noqa: E402
import gen_remediation_eval_corpus as gen                                # noqa: E402
from remediation_capability import AUTO, HUMAN, REMEDIATION              # noqa: E402

CASES = load_cases()
COVERAGE = [c for c in CASES if c.case_id.startswith("rem-x")]
OTHERS = [c for c in CASES if not c.case_id.startswith("rem-x")]


def test_every_category_now_has_at_least_two_cases():
    counts = Counter(category_of(c) for c in CASES)
    assert min(counts.values()) >= 2
    assert build_ladder([], CASES)["share_under_sampled"] == 0.0


def test_the_band_holds_exactly_the_categories_the_other_bands_leave_single():
    single = {cat for cat, n in Counter(category_of(c) for c in OTHERS).items() if n == 1}
    assert {category_of(c) for c in COVERAGE} == single
    # 42 -> 43 when pptx 1.4.5 became ASSISTED: that pair had no case at all while it was HUMAN
    # (a human pair only ever appears as an abstain case, and this one had none), so the corpus
    # gained a category. See EXPECTED_COUNTS in gen_remediation_eval_corpus for the check run.
    assert len(COVERAGE) == len(single) == 43
    # one per category, no double-covering
    assert len({category_of(c) for c in COVERAGE}) == len(COVERAGE)


def test_a_second_case_is_a_second_call_not_a_cache_hit():
    rules = cand.resolve("rules-only")
    by_cat = {}
    for c in OTHERS:
        by_cat.setdefault(category_of(c), []).append(c)
    for c in COVERAGE:
        sibling = by_cat[category_of(c)][0]
        assert rules.prompt_key(c) != rules.prompt_key(sibling), c.case_id
        assert build_prompt(c) != build_prompt(sibling), c.case_id


def test_lane_and_eligibility_follow_the_product_table():
    for c in COVERAGE:
        fmt, crit = c.environment["format"], c.expected_diagnosis["criterion"]
        lane = REMEDIATION[fmt][crit]
        assert c.environment["lane"] == lane, c.case_id
        if lane == HUMAN:
            assert c.must_abstain and not c.automation_eligible, c.case_id
        else:
            # Every non-human second case is eligible: the point of the band is a category
            # that can say whether a tier FIXES its ordinary presentation.
            assert c.automation_eligible and not c.must_abstain, c.case_id
            assert c.acceptable_remediations[0]["action"] == (
                "apply_deterministic" if lane == AUTO else "apply_approved"), c.case_id


def test_the_pptx_reading_order_case_has_its_lane_shape_not_the_docx_template():
    (c,) = [c for c in COVERAGE if category_of(c) == "pptx:1.3.2"]
    assert REMEDIATION["pptx"]["1.3.2"] == AUTO
    assert c.acceptable_remediations[0]["target"] == "slide.shapeOrder"
    assert c.expected_diagnosis["root_cause"] == "shapes_out_of_visual_order"


def test_the_free_candidates_execute_every_coverage_case():
    """The bite: a fixture nothing can act on is a row, not a measurement."""
    good = run(cand.resolve("stub:good"), COVERAGE, repeats=1)
    rules = run(cand.resolve("rules-only"), COVERAGE, repeats=1)
    by_id = {c.case_id: c for c in COVERAGE}
    for r in good.all_results:
        c = by_id[r.case_id]
        assert not r.critical_violations, r.case_id
        if c.automation_eligible:
            assert r.verified_fix, f"stub:good could not verify {r.case_id} ({category_of(c)})"
        else:
            assert r.abstention_correct, r.case_id
    # rules-only verifies exactly the auto cases its playbook covers, and escalates the rest —
    # the same partial coverage it has on the first five bands. Coverage is a (criterion, root
    # cause) question and a scope question, not a criterion question: "1.3.1" alone names a
    # table-header recipe on a document whose 1.3.1 finding is a pseudo-heading, and a recipe
    # right for the root cause can still target an element outside the case's scope.
    verified = {r.case_id for r in rules.all_results if r.verified_fix}
    expected = {c.case_id for c in COVERAGE
                if c.automation_eligible and REMEDIATION[c.environment["format"]][
                    c.expected_diagnosis["criterion"]] == AUTO
                and (c.expected_diagnosis["criterion"],
                     c.expected_diagnosis.get("root_cause")) in AUTO_PLAYBOOK
                and (AUTO_PLAYBOOK[(c.expected_diagnosis["criterion"],
                                    c.expected_diagnosis["root_cause"])](c) or {}
                     ).get("target") in c.scope}
    assert verified == expected
    assert all(r.abstention_correct for r in rules.all_results if by_id[r.case_id].must_abstain)


def test_the_generator_variants_cover_every_criterion_the_band_needs():
    needed = {c.expected_diagnosis["criterion"] for c in COVERAGE
              if REMEDIATION[c.environment["format"]][c.expected_diagnosis["criterion"]] != HUMAN}
    assert needed <= set(gen.VARIANTS) | {crit for _, crit in gen.FORMAT_VARIANTS}
    human = {c.expected_diagnosis["criterion"] for c in COVERAGE if c.must_abstain}
    assert human <= set(gen.HUMAN_CONTEXTS)


def test_reports_carry_the_category_counts_they_were_run_against():
    subset = [c for c in CASES if category_of(c) in ("docx:2.4.4", "html:2.4.9")]
    rep = build_report([run(cand.resolve("rules-only"), subset, repeats=1)], subset)
    cats = rep["corpus"]["categories"]
    assert cats["docx:2.4.4"] == {"cases": 4, "eligible": 3, "must_abstain": 0}
    assert cats["html:2.4.9"] == {"cases": 2, "eligible": 0, "must_abstain": 2}
