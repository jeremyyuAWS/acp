"""Guided manual test plans over HTTP (PRD §14, Phase 3).

The completeness rules themselves are unit-tested in test_acr_manual_plans.py. This file is about
the wiring: that a run really persists, that a completed run produces the evidence row a reader of
the ACR would see, and — the one that matters most — that finishing the plans actually MOVES the
publish gate. A phase that built a plan catalog nothing consulted would pass every unit test.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

OWNER = "owner@acp.test"
ANALYST = "analyst@acp.test"
RANDOM = "random@acp.test"

# A short plan, so a test can finish one without twelve requests. Chosen by NAME rather than by
# index: a catalog reordering must not silently retarget these tests at a different plan.
PLAN = "status-messages"
CRITERION = "4.1.3"


@pytest.fixture()
def client(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "OPEN_ACCESS", True, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: e in (OWNER, ANALYST, RANDOM))

    c = TestClient(app)

    def as_user(email):
        c.headers.update({"Authorization": f"Bearer {email}"})
        return c
    return as_user


@pytest.fixture()
def report(client):
    rid = client(OWNER).post("/acr", json={"product_version": "1.4.0",
                                           "build_id": "b-900"}).json()["report_id"]
    client(OWNER).put(f"/acr/{rid}/roles", json={"email": ANALYST, "role": "editor"})
    return rid


def _start(c, rid, plan=PLAN, criterion=CRITERION):
    r = c.post(f"/acr/{rid}/criteria/{criterion}/plans/start", json={"plan_id": plan})
    assert r.status_code == 200, r.text
    return r.json()["run_id"]


def _answer_all(c, rid, run_id, plan=PLAN, outcome="pass"):
    import acr_plans
    for i in range(acr_plans.step_count(plan)):
        r = c.post(f"/acr/{rid}/plans/runs/{run_id}/step",
                   json={"step_index": i, "outcome": outcome})
        assert r.status_code == 200, r.text
    return r.json()


def _complete(c, rid, run_id, **over):
    body = {"result": "pass", "tester": ANALYST, "browser": "Firefox 128",
            "assistive_tech": "NVDA 2024.4", "environment": "Windows 11"}
    body.update(over)
    return c.post(f"/acr/{rid}/plans/runs/{run_id}/complete", json=body)


# ── the workflow ───────────────────────────────────────────────────────────────

def test_a_criterion_lists_the_plans_it_needs(client, report):
    r = client(ANALYST).get(f"/acr/{report}/criteria/{CRITERION}/plans")
    assert r.status_code == 200
    body = r.json()
    assert [p["plan_id"] for p in body["plans"]] == [PLAN]
    assert body["complete"] is False
    assert body["plans"][0]["started"] is False
    # The screen must never imply that finishing a plan is a conformance result.
    assert "not a pass" in body["note"]


def test_a_run_records_steps_and_completes_into_an_evidence_row(client, report):
    c = client(ANALYST)
    run_id = _start(c, report)
    _answer_all(c, report, run_id)
    r = _complete(c, report, run_id)
    assert r.status_code == 200, r.text
    ev_id = r.json()["evidence_id"]

    # The evidence a reader of the ACR would actually see — with the environment on it.
    detail = c.get(f"/acr/{report}/criteria/{CRITERION}").json()
    row = next(e for e in detail["evidence"] if e["id"] == ev_id)
    assert row["source_kind"] == "manual"
    assert row["assistive_tech"] == "NVDA 2024.4"
    assert row["browser"] == "Firefox 128"
    assert PLAN in row["method"]


def test_completing_is_refused_while_a_step_is_unanswered(client, report):
    """And the refusal says what is left, in the same sentence the screen renders — so the UI
    cannot offer a Complete button the server then rejects."""
    c = client(ANALYST)
    run_id = _start(c, report)
    c.post(f"/acr/{report}/plans/runs/{run_id}/step", json={"step_index": 0, "outcome": "pass"})
    r = _complete(c, report, run_id)
    assert r.status_code == 400
    assert "steps still have no recorded outcome" in r.json()["detail"]


def test_completing_is_refused_when_the_plans_declared_metadata_is_missing(client, report):
    c = client(ANALYST)
    run_id = _start(c, report)
    _answer_all(c, report, run_id)
    r = _complete(c, report, run_id, assistive_tech="")
    assert r.status_code == 400
    assert "assistive_tech" in r.json()["detail"]


def test_a_failing_run_still_completes(client, report):
    """A product that fails a criterion must still be able to finish evaluating it."""
    c = client(ANALYST)
    run_id = _start(c, report)
    _answer_all(c, report, run_id, outcome="fail")
    r = _complete(c, report, run_id, result="fail")
    assert r.status_code == 200, r.text


def test_a_plan_cannot_be_run_against_a_criterion_it_does_not_cover(client, report):
    """Otherwise a tester could attach a keyboard sweep as evidence for captions."""
    r = client(ANALYST).post(f"/acr/{report}/criteria/1.2.2/plans/start",
                             json={"plan_id": "keyboard-operability"})
    assert r.status_code == 400
    assert "does not cover" in r.json()["detail"]


def test_an_unknown_step_index_is_refused(client, report):
    c = client(ANALYST)
    run_id = _start(c, report)
    r = c.post(f"/acr/{report}/plans/runs/{run_id}/step",
               json={"step_index": 99, "outcome": "pass"})
    assert r.status_code == 400
    assert "there is no step 99" in r.json()["detail"]


def test_an_unknown_outcome_is_refused(client, report):
    c = client(ANALYST)
    run_id = _start(c, report)
    r = c.post(f"/acr/{report}/plans/runs/{run_id}/step",
               json={"step_index": 0, "outcome": "probably fine"})
    assert r.status_code == 400


def test_a_completed_run_is_closed_to_further_steps(client, report):
    """Its evidence row is already written and acr_evidence is append-only, so editing the run
    behind it would leave the record and the run saying different things."""
    c = client(ANALYST)
    run_id = _start(c, report)
    _answer_all(c, report, run_id)
    _complete(c, report, run_id)
    r = c.post(f"/acr/{report}/plans/runs/{run_id}/step",
               json={"step_index": 0, "outcome": "fail"})
    assert r.status_code == 409


def test_re_recording_a_step_replaces_it(client, report):
    """A tester fixing a mis-click is correcting a typo, not retracting a finding — the finding is
    the evidence row, which stays append-only."""
    c = client(ANALYST)
    run_id = _start(c, report)
    c.post(f"/acr/{report}/plans/runs/{run_id}/step", json={"step_index": 0, "outcome": "fail"})
    c.post(f"/acr/{report}/plans/runs/{run_id}/step", json={"step_index": 0, "outcome": "pass"})
    body = c.get(f"/acr/{report}/criteria/{CRITERION}/plans").json()
    assert body["plans"][0]["answered_steps"] == 1


# ── the gate ───────────────────────────────────────────────────────────────────

def test_deciding_a_criterion_without_finishing_its_plan_blocks_publication(client, report):
    """The end-to-end version of the seam test. Phase 1 shipped this blocker category and it has
    produced zero rows in every release since, because nobody supplied the map.

    NOTE WHERE THE BLOCKER ACTUALLY BITES, which is sharper than it first looks. validate() hits
    `continue` on a criterion with no final status — an undecided criterion reports "has not been
    evaluated" and nothing else, because telling someone their test plan is unfinished when they
    have not even decided would be noise. So this blocker's real target is the dangerous case:
    a criterion someone has DECIDED while the manual evaluation behind it is still unfinished.
    Found by this test failing against the assumption that any started-but-unfinished plan would
    surface here.
    """
    import core
    c = client(ANALYST)
    _start(c, report)  # started, no steps answered

    core.store.save_acr_decision(report, CRITERION, owner_email=OWNER,
                                 final_status="Supports", remarks="", decided_by=ANALYST)

    cats = c.get(f"/acr/{report}/validation").json()["by_category"]
    assert "incomplete_manual_test_plan" in cats, sorted(cats)
    assert any(row["criterion_num"] == CRITERION
               for row in cats["incomplete_manual_test_plan"])


def test_finishing_the_plan_clears_that_blocker(client, report):
    """The other half — a gate that can never be satisfied is as broken as one that never fires."""
    c = client(ANALYST)
    run_id = _start(c, report)
    _answer_all(c, report, run_id)
    _complete(c, report, run_id)
    v = c.get(f"/acr/{report}/validation").json()
    rows = v["by_category"].get("incomplete_manual_test_plan", [])
    assert not [r for r in rows if r["criterion_num"] == CRITERION], rows


# ── authorization ──────────────────────────────────────────────────────────────

def test_a_user_with_no_role_cannot_start_or_record_a_run(client, report):
    """Runs produce evidence rows behind a published conformance claim, so they are writes.
    OPEN_ACCESS is True in this fixture precisely because that is the configuration the gate has
    to survive (see tests/test_acr_authorization.py)."""
    r = client(RANDOM).post(f"/acr/{report}/criteria/{CRITERION}/plans/start",
                            json={"plan_id": PLAN})
    assert r.status_code == 403


def test_reading_the_plans_is_open_to_any_admitted_user(client, report):
    """Reads are not role-gated anywhere in this router — a tester has to be able to see what the
    plan asks before anyone grants them a role."""
    assert client(RANDOM).get(f"/acr/{report}/criteria/{CRITERION}/plans").status_code == 200


def test_a_published_report_refuses_new_runs(client, report, isolated_store):
    """PRD §17/§21.12 — the same edit boundary Phase 1 pinned, extended to the new write routes.

    Published state is set by creating the snapshot rather than by patching `status`: `status` is
    deliberately not in _ACR_REPORT_EDITABLE, because publication is Phase 4 and there is no path
    to it yet. Following test_acr_slice_1_4_3's idiom keeps this test honest about that.
    """
    import acr_catalog
    isolated_store.create_acr_snapshot(
        "snap1", report_id=report, owner_email=OWNER, revision=1,
        catalog_hash=acr_catalog.catalog_hash(), content_json="{}", content_digest="d",
        published_by=OWNER)

    c = client(ANALYST)
    assert c.post(f"/acr/{report}/criteria/{CRITERION}/plans/start",
                  json={"plan_id": PLAN}).status_code == 409
