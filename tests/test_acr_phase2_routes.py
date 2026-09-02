"""Phase 2 endpoints over HTTP: axe ingestion, evidence gaps, applicability.

The unit-level honesty rules live in test_acr_axe_ingest.py. This file is about the wiring —
that the rules are actually reached through the route, against a real store, and that the new
write endpoints are role-gated the same way Phase 1's are.
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


AXE_RUN = {
    "testEngine": {"name": "axe-core", "version": "4.12.1"},
    "url": "http://localhost:5173/assess",
    "timestamp": "2026-09-01T20:00:00.000Z",
    "violations": [{"id": "color-contrast", "tags": ["wcag2aa", "wcag143"],
                    "help": "Elements must meet contrast", "nodes": [{}, {}]}],
    "passes": [{"id": "image-alt", "tags": ["wcag2a", "wcag111"],
                "help": "Images have alt text", "nodes": [{}]},
               {"id": "landmark-one-main", "tags": ["best-practice"],
                "help": "One main landmark", "nodes": [{}]}],
    "incomplete": [{"id": "color-contrast", "tags": ["wcag2aa", "wcag143"],
                    "help": "Contrast over a background image", "nodes": [{}]}],
    "inapplicable": [{"id": "video-caption", "tags": ["wcag2a", "wcag122"],
                      "help": "Videos need captions", "nodes": []}],
}


# ── ingestion ─────────────────────────────────────────────────────────────────────────────────

def test_preview_reports_what_would_be_written_and_writes_nothing(client, report):
    r = client(ANALYST).post(f"/acr/{report}/evidence/axe",
                             json={"result": AXE_RUN, "preview": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["preview"] is True
    assert body["would_ingest"]["ingested"] == 3
    assert body["run"]["counts"]["inapplicable"] == 1

    # …and nothing landed.
    detail = client(OWNER).get(f"/acr/{report}/criteria/1.4.3").json()
    assert detail["evidence"] == []


def test_ingest_writes_evidence_and_drops_the_inapplicable_bucket(client, report):
    r = client(ANALYST).post(f"/acr/{report}/evidence/axe", json={"result": AXE_RUN})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ingested"]["ingested"] == 3
    assert body["ingested"]["dropped_inapplicable"] == 1
    assert body["ingested"]["unmapped_rules"] == ["landmark-one-main"]

    # 1.2.2 was inapplicable on this page — it must have no evidence at all.
    assert client(OWNER).get(f"/acr/{report}/criteria/1.2.2").json()["evidence"] == []

    detail = client(OWNER).get(f"/acr/{report}/criteria/1.4.3").json()
    results = sorted(e["result"] for e in detail["evidence"])
    assert results == ["blocked", "fail"]


def test_ingested_rows_inherit_the_reports_product_version(client, report):
    client(ANALYST).post(f"/acr/{report}/evidence/axe", json={"result": AXE_RUN})
    ev = client(OWNER).get(f"/acr/{report}/criteria/1.1.1").json()["evidence"][0]
    assert ev["product_version"] == "1.4.0"
    assert ev["build_id"] == "b-900"
    assert ev["tester"] == ANALYST


def test_a_clean_run_drafts_nothing(client, report):
    """PRD §4.3 end to end: the draft the route stores after ingesting a green run is None."""
    clean = dict(AXE_RUN, violations=[], incomplete=[], inapplicable=[])
    r = client(ANALYST).post(f"/acr/{report}/evidence/axe", json={"result": clean})
    assert r.json()["drafts"] == {"1.1.1": None}

    crit = client(OWNER).get(f"/acr/{report}/criteria/1.1.1").json()
    assert crit["criterion"]["draft_status"] is None
    assert crit["criterion"]["final_status"] is None
    assert crit["assessment"]["permitted_statuses"]["Supports"] is False


def test_a_run_with_failures_drafts_partially_supports_for_a_human(client, report):
    client(ANALYST).post(f"/acr/{report}/evidence/axe", json={"result": AXE_RUN})
    crit = client(OWNER).get(f"/acr/{report}/criteria/1.4.3").json()["criterion"]
    assert crit["draft_status"] == "Partially Supports"
    assert crit["final_status"] is None, "a draft is never a decision"


def test_ingestion_is_recorded_in_the_audit_trail(client, report):
    client(ANALYST).post(f"/acr/{report}/evidence/axe", json={"result": AXE_RUN})
    events = client(OWNER).get(f"/acr/{report}/audit").json()["events"]
    ingested = [e for e in events if e["action"] == "evidence.axe_ingested"]
    assert len(ingested) == 1
    assert "inapplicable dropped" in ingested[0]["detail"]
    assert ingested[0]["actor"] == ANALYST


def test_a_non_axe_payload_is_refused(client, report):
    r = client(ANALYST).post(f"/acr/{report}/evidence/axe", json={"result": {"nope": 1}})
    assert r.status_code == 422
    assert "axe-core run" in r.json()["detail"]


def test_ingestion_requires_the_evaluator_role(client, report):
    r = client(RANDOM).post(f"/acr/{report}/evidence/axe", json={"result": AXE_RUN})
    assert r.status_code == 403


# ── gaps (PRD §7.8) ───────────────────────────────────────────────────────────────────────────

def test_a_fresh_report_is_all_gap(client, report):
    g = client(OWNER).get(f"/acr/{report}/gaps").json()
    assert g["total"] == 55
    assert g["counts"]["no_evidence"] == 55
    assert g["with_human_evidence"] == 0


def test_automated_evidence_moves_a_criterion_to_automated_only_not_covered(client, report):
    """The distinction the whole endpoint exists for: a tool looked, so it is no longer 'nobody
    looked' — and it is still a gap, because automated evidence alone never establishes
    conformance."""
    client(ANALYST).post(f"/acr/{report}/evidence/axe", json={"result": AXE_RUN})
    g = client(OWNER).get(f"/acr/{report}/gaps").json()

    assert g["counts"]["automated_only"] == 2          # 1.1.1 and 1.4.3
    assert g["counts"]["no_evidence"] == 53
    assert g["with_human_evidence"] == 0
    touched = {r["criterion_num"] for r in g["buckets"]["automated_only"]}
    assert touched == {"1.1.1", "1.4.3"}
    assert "never establishes conformance" in g["note"]


def test_human_evidence_clears_the_gap(client, report):
    client(ANALYST).post(f"/acr/{report}/evidence/axe", json={"result": AXE_RUN})
    client(ANALYST).post(f"/acr/{report}/criteria/1.1.1/evidence",
                         json={"criterion_num": "1.1.1", "source_kind": "manual",
                               "result": "pass", "method": "reviewed every image"})
    g = client(OWNER).get(f"/acr/{report}/gaps").json()
    assert g["with_human_evidence"] == 1
    assert {r["criterion_num"] for r in g["buckets"]["automated_only"]} == {"1.4.3"}


def test_evidence_for_a_different_version_is_a_stale_gap_not_coverage(client, report):
    """PRD §12 in the gap view: evidence against another build is visible and does not count."""
    client(ANALYST).post(f"/acr/{report}/criteria/2.1.1/evidence",
                         json={"criterion_num": "2.1.1", "source_kind": "keyboard",
                               "result": "pass", "product_version": "0.9.0"})
    g = client(OWNER).get(f"/acr/{report}/gaps").json()
    stale = {r["criterion_num"] for r in g["buckets"]["stale_only"]}
    assert "2.1.1" in stale
    assert g["with_human_evidence"] == 0


# ── applicability (PRD §9) ────────────────────────────────────────────────────────────────────

def test_a_criterion_can_be_marked_inapplicable_with_a_rationale(client, report):
    r = client(ANALYST).post(f"/acr/{report}/criteria/1.2.2/applicability",
                             json={"applicable": False, "rationale": "ACP renders no video"})
    assert r.status_code == 200, r.text
    crit = client(OWNER).get(f"/acr/{report}/criteria/1.2.2").json()["criterion"]
    assert crit["applicable"] in (0, False)


def test_marking_inapplicable_requires_a_rationale(client, report):
    r = client(ANALYST).post(f"/acr/{report}/criteria/1.2.2/applicability",
                             json={"applicable": False})
    assert r.status_code == 422


def test_applicability_does_not_write_a_conformance_status(client, report):
    """The distinction that keeps a triage click from becoming an exported claim. Marking a
    criterion inapplicable is NOT deciding 'Not Applicable', which needs remarks a customer reads
    (PRD §10) — and it must not let the report publish with the criterion undecided."""
    client(ANALYST).post(f"/acr/{report}/criteria/1.2.2/applicability",
                         json={"applicable": False, "rationale": "no video anywhere in ACP"})
    crit = client(OWNER).get(f"/acr/{report}/criteria/1.2.2").json()["criterion"]
    assert crit["final_status"] is None
    assert crit["workflow_state"] == "not_evaluated"

    v = client(OWNER).get(f"/acr/{report}/validation").json()
    blocked = {row["criterion_num"] for rows in v["by_category"].values() for row in rows}
    assert "1.2.2" in blocked, "an inapplicable criterion still needs a decision to publish"


def test_applicability_requires_the_editor_role(client, report):
    r = client(RANDOM).post(f"/acr/{report}/criteria/1.2.2/applicability",
                            json={"applicable": False, "rationale": "x"})
    assert r.status_code == 403


def test_applicability_is_audited(client, report):
    client(ANALYST).post(f"/acr/{report}/criteria/1.2.2/applicability",
                         json={"applicable": False, "rationale": "ACP renders no video"})
    events = client(OWNER).get(f"/acr/{report}/audit").json()["events"]
    row = [e for e in events if e["action"] == "criterion.applicability_changed"][0]
    assert row["criterion_num"] == "1.2.2"
    assert "no video" in row["detail"]
