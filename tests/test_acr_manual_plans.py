"""Guided manual test plans (PRD §14) — the catalog, the completeness rules, and the seam.

THE ONE THING THIS PHASE CHANGES ABOUT PUBLICATION. `acr_validation.validate()` has accepted a
`manual_plan_status` map since Phase 1 and defined the `incomplete_manual_test_plan` blocker, and
until now nobody supplied it — the category produced no rows rather than pretend it knew. Phase 3
plugs `acr_plans` into it. `test_the_seam_is_actually_plugged_in` is the assertion that this
happened; without it the whole phase could ship and change nothing about what may publish.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import acr_plans  # noqa: E402
import acr_validation  # noqa: E402


# ── the catalog ────────────────────────────────────────────────────────────────

def test_every_applicable_criterion_has_at_least_one_plan():
    """Not a completeness nicety — it is PRD §4.3 expressed as data.

    Automation finishes NO criterion: every acr_axe row declares Coverage.PARTIAL and
    CAN_CERTIFY_PASS is {FULL} (ADR 0031). So a criterion with no manual plan would be one the
    workspace can never legitimately move to Supports, with nothing telling the tester so.
    """
    import acr_catalog
    for num in acr_catalog.numbers():
        assert acr_plans.required_plan_ids(num), f"{num} has no manual test plan"


def test_the_catalog_says_on_its_face_that_it_is_derived():
    """PRD §19 forbids inventing evidence. The plan catalog is DERIVED from WCAG 2.2 rather than
    transcribed from PRD §14, which this repo does not contain — and a reader must be able to
    discover that from the artifact itself, not only from a commit message."""
    meta = acr_plans.catalog()["_meta"]
    assert "DERIVED" in meta["derivation"]
    assert "not transcribed" in meta["derivation"].lower()
    assert meta["derived_from"] == "https://www.w3.org/TR/WCAG22/"


def test_a_plan_only_demands_metadata_the_evidence_record_can_store():
    """A plan that required a field acr_evidence has no column for would make a run look
    reproducible while the durable record silently dropped it."""
    import acr_model
    storable = set(acr_model.Evidence.__dataclass_fields__)
    for plan in acr_plans.all_plans():
        assert set(plan["needs"]) <= storable, f"{plan['plan_id']} needs {plan['needs']}"


def test_plans_declaring_a_screen_reader_ask_for_the_at_by_name():
    """A screen-reader result is not portable between NVDA and VoiceOver, or between browser
    pairings. A plan driven through an AT that did not record which one would produce evidence
    nobody can reproduce (PRD §4.5)."""
    at_plans = [p for p in acr_plans.all_plans() if "screen reader" in p["title"].lower()]
    assert at_plans, "expected at least one screen-reader plan"
    for plan in at_plans:
        assert "assistive_tech" in plan["needs"], plan["plan_id"]


# ── completeness ───────────────────────────────────────────────────────────────

def _run(plan_id, criterion, *, steps=None, tester="alice@x.com", env=None):
    plan = acr_plans.plan(plan_id)
    if steps == "all":
        steps = {str(i): acr_plans.STEP_PASS for i in range(len(plan["steps"]))}
    return {"id": "run1", "plan_id": plan_id, "criterion_num": criterion,
            "tester": tester, "steps": steps or {},
            "environment": env if env is not None
            else {f: "recorded" for f in plan["needs"]}}


def test_an_unanswered_step_leaves_the_plan_incomplete():
    run = _run("keyboard-operability", "2.1.1", steps={"0": "pass"})
    ok, why = acr_plans.instance_complete(run)
    assert not ok
    assert "3 of 4 steps" in why


def test_a_failing_step_still_completes_the_plan():
    """Completeness is about whether the tester LOOKED, never about what they found. Conflating
    the two is how a checklist becomes a rubber stamp — and it would also mean a product that
    fails a criterion could never finish its own evaluation of it."""
    plan = acr_plans.plan("keyboard-operability")
    steps = {str(i): acr_plans.STEP_PASS for i in range(len(plan["steps"]))}
    steps["2"] = acr_plans.STEP_FAIL
    ok, why = acr_plans.instance_complete(_run("keyboard-operability", "2.1.1", steps=steps))
    assert ok, why


def test_a_finished_run_with_no_tester_is_not_complete():
    run = _run("keyboard-operability", "2.1.1", steps="all", tester="")
    ok, why = acr_plans.instance_complete(run)
    assert not ok and "tester" in why


def test_a_finished_run_missing_its_declared_metadata_is_not_complete():
    """The plan declares what it needs; the run has to have it. This is what makes the evidence
    reproducible rather than merely recorded."""
    run = _run("screen-reader-structure", "1.3.1", steps="all",
               env={"browser": "Firefox 128", "assistive_tech": "", "environment": "macOS 15"})
    ok, why = acr_plans.instance_complete(run)
    assert not ok
    assert "assistive_tech" in why


def test_a_started_plan_left_unfinished_blocks_even_beside_other_evidence():
    """THE CASE THE GATE EXISTS FOR. The plan catalog is structure, not a gate — directly recorded
    manual evidence satisfies a criterion (see below). But a plan somebody STARTED and abandoned is
    a half-done evaluation being carried into a published conformance claim, and no amount of other
    evidence makes that finished."""
    half = [_run("keyboard-operability", "2.1.1", steps={"0": "pass"})]
    ok, why = acr_plans.criterion_complete("2.1.1", half, has_human_evidence=True)
    assert not ok
    assert "3 of 4 steps" in why


def test_directly_recorded_human_evidence_satisfies_the_criterion():
    """The plan catalog is structure, not a gate. An expert who ran a thorough keyboard sweep and
    recorded it through the evidence form HAS evaluated the criterion; refusing to count that would
    make the product demand process compliance in place of evidence, and PRD §4.1 is "evidence
    before claims", not "checklists before claims".

    A criterion with no human evidence at all is still blocked — by acr_validation's own
    missing-evidence and unapproved categories, which this module does not duplicate.
    """
    ok, _ = acr_plans.criterion_complete("2.1.1", [], has_human_evidence=True)
    assert ok
    ok, why = acr_plans.criterion_complete("2.1.1", [], has_human_evidence=False)
    assert not ok
    assert "no human has evaluated this criterion" in why


def test_a_criterion_covered_by_two_plans_needs_both_once_started():
    """The catalog maps a criterion to a LIST, so finishing one of two started plans is not
    finishing the criterion."""
    num = next((n for n in ("1.3.1", "2.1.1", "4.1.2")
                if len(acr_plans.required_plan_ids(n)) > 1), None)
    if num is None:
        pytest.skip("no criterion in the catalog is covered by more than one plan")
    plan_ids = sorted(acr_plans.required_plan_ids(num))
    runs = [_run(plan_ids[0], num, steps="all"),
            _run(plan_ids[1], num, steps={"0": "pass"})]
    ok, why = acr_plans.criterion_complete(num, runs)
    assert not ok
    assert plan_ids[1] in why


def test_an_inapplicable_criterion_acquires_no_plan_obligation():
    """Applicability is Phase 2's workspace triage. It must not create a manual-plan duty the
    report then fails — but note it does NOT let the report publish either; acr_validation still
    demands a final status for every row."""
    criteria = [{"criterion_num": "1.2.4", "applicable": False}]
    assert acr_plans.manual_plan_status(criteria, []) == {}


# ── the seam ───────────────────────────────────────────────────────────────────

def test_the_seam_is_actually_plugged_in():
    """The assertion the whole phase turns on.

    Phase 1 wired `manual_plan_status` into validate() and passed nothing, so the blocker category
    produced no rows. If Phase 3 built a plan catalog and a UI but never supplied that map, every
    test above could pass and NOTHING about publication would have changed.
    """
    report = {"report_title": "t", "product_name": "p", "product_version": "1",
              "vendor_name": "v", "evaluators": "e"}
    criteria = [{"criterion_num": "2.1.1", "final_status": "Supports",
                 "approval_state": "approved", "applicable": True}]

    without = acr_validation.validate(report, criteria, {}, manual_plan_status={})
    with_gap = acr_validation.validate(report, criteria, {},
                                       manual_plan_status={"2.1.1": False})

    cat = acr_validation.CATEGORY_INCOMPLETE_MANUAL_PLAN
    assert not [b for b in without if b.category == cat], \
        "Phase 1's behaviour: an unsupplied map produces no rows"
    assert [b for b in with_gap if b.category == cat], \
        "an incomplete plan must block publication once the map is supplied"


def test_the_route_supplies_the_map_rather_than_an_empty_dict():
    """Reads the call site itself. A regression here is silent: publication simply stops caring
    about manual plans again, and no test of acr_plans in isolation would notice."""
    source = (ACP / "api" / "routes" / "acr.py").read_text(encoding="utf-8")
    assert "manual_plan_status=_manual_plan_status(" in source, \
        "routes/acr.py must pass the real map into acr_validation.validate"


def test_the_plans_module_stays_free_of_io():
    """Same contract as acr_rules and acr_freshness: pure functions over records, so the rules can
    be tested against constructed runs with no database."""
    source = (ACP / "api" / "acr_plans.py").read_text(encoding="utf-8")
    for forbidden in ("core.store", "cursor(", "SELECT ", "INSERT "):
        assert forbidden not in source, f"acr_plans contains {forbidden!r}"


def test_the_committed_catalog_is_what_the_generator_produces():
    """Freshness guard, following test_acr_catalog.py's idiom rather than adding a CI step.

    The repo enforces gen_wcag_catalog the same way — a pytest test, not a workflow entry — so
    this runs inside the existing backend job on every PR. Editing config/acr-manual-test-plans
    .json by hand, or changing the generator without regenerating, fails here with the command to
    run.
    """
    import subprocess

    proc = subprocess.run(
        [sys.executable, str(ACP / "scripts" / "gen_acr_plan_catalog.py"), "--check"],
        capture_output=True, text=True)
    assert proc.returncode == 0, (
        f"{proc.stdout}{proc.stderr}\nRun: python scripts/gen_acr_plan_catalog.py")


def test_the_catalog_records_the_axe_measurement_it_was_built_from():
    """The claim "32 criteria have no axe rule" is load-bearing for why every criterion needs a
    plan. Recording the axe version it was measured against is what lets a future reader tell
    whether the number is still true rather than assuming it."""
    meta = acr_plans.catalog()["_meta"]
    assert meta["axe_version_measured"]
    assert meta["criteria_with_any_axe_rule"] + meta["criteria_with_no_axe_rule"] == \
        meta["criteria_covered"]
