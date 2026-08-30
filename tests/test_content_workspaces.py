"""ACP Managed Content Workspace (ADR 0044) — POST/GET /content-workspaces.

The first slice of PRD Phase 1: the workspace container itself, owner-scoped the same way
every other per-user boundary in this app already is (see ADR 0044's tenant-boundary
decision). `test_a_foreign_workspace_id_404s`, in particular, pins the SAME "an id is never
an existence oracle across owners" contract test_foreign_scan_404.py pins for scans.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "alice@x.com"
OTHER = "bob@y.com"


@pytest.fixture()
def gated_client(monkeypatch, isolated_store):
    """Mirrors tests/test_foreign_scan_404.py's fixture exactly: a real GIS-gated TestClient
    with token==email, so a test can sign in as anybody without touching Google."""
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: e in (OWNER, OTHER))

    client = TestClient(app)

    def as_user(email):
        client.headers.update({"Authorization": f"Bearer {email}"})
        return client

    return as_user


def test_create_returns_the_workspace_with_every_field(gated_client):
    body = {"name": "Public Website Documents", "purpose": "Assess before publication",
            "business_owner": "Jane Doe", "department": "Legal",
            "wcag_standard": "WCAG 2.1 AA",
            "retention_policy": "Delete source and working files 90 days after release",
            "permitted_file_types": ["pdf", "docx"], "processing_region": "us",
            "external_ai_policy": "Allowed for anonymized public-content findings"}
    r = gated_client(OWNER).post("/content-workspaces", json=body)
    assert r.status_code == 200, r.text
    ws = r.json()
    assert ws["name"] == "Public Website Documents"
    assert ws["business_owner"] == "Jane Doe"
    assert ws["wcag_standard"] == "WCAG 2.1 AA"
    assert ws["status"] == "active"
    assert ws["owner_email"] == OWNER
    assert ws["id"]


def test_name_is_required(gated_client):
    r = gated_client(OWNER).post("/content-workspaces", json={"name": "  "})
    assert r.status_code == 422


def test_only_name_is_required_everything_else_defaults_to_none(gated_client):
    r = gated_client(OWNER).post("/content-workspaces", json={"name": "Minimal"})
    assert r.status_code == 200, r.text
    ws = r.json()
    assert ws["purpose"] is None
    assert ws["permitted_file_types"] is None


def test_list_is_scoped_to_the_calling_owner(gated_client):
    gated_client(OWNER).post("/content-workspaces", json={"name": "Alice's workspace"})
    gated_client(OTHER).post("/content-workspaces", json={"name": "Bob's workspace"})

    alice_list = gated_client(OWNER).get("/content-workspaces").json()["workspaces"]
    bob_list = gated_client(OTHER).get("/content-workspaces").json()["workspaces"]
    assert [w["name"] for w in alice_list] == ["Alice's workspace"]
    assert [w["name"] for w in bob_list] == ["Bob's workspace"]


def test_get_by_id_returns_the_created_workspace(gated_client):
    created = gated_client(OWNER).post(
        "/content-workspaces", json={"name": "Onboarding docs"}).json()
    r = gated_client(OWNER).get(f"/content-workspaces/{created['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]


def test_a_foreign_workspace_id_404s_not_403s(gated_client):
    """The SAME contract test_foreign_scan_404.py pins for scans: a workspace id must not be
    an existence oracle across owners. Non-vacuity checked first (the owner's own GET must NOT
    404), same discipline that test file's own docstring insists on."""
    created = gated_client(OWNER).post(
        "/content-workspaces", json={"name": "Alice's private workspace"}).json()

    owner_res = gated_client(OWNER).get(f"/content-workspaces/{created['id']}")
    assert owner_res.status_code == 200, "the seed itself must be reachable by its own owner"

    other_res = gated_client(OTHER).get(f"/content-workspaces/{created['id']}")
    assert other_res.status_code == 404


def test_a_nonexistent_workspace_id_also_404s(gated_client):
    r = gated_client(OWNER).get("/content-workspaces/does-not-exist")
    assert r.status_code == 404


def test_permitted_file_types_round_trips_as_a_list(gated_client):
    r = gated_client(OWNER).post(
        "/content-workspaces", json={"name": "Typed", "permitted_file_types": ["pdf", "docx", "pptx"]})
    assert r.json()["permitted_file_types"] == ["pdf", "docx", "pptx"]


def test_creation_is_logged_to_the_decision_log(gated_client, isolated_store):
    gated_client(OWNER).post("/content-workspaces", json={"name": "Audited workspace"})
    decisions = isolated_store.list_decisions()
    assert any(d["action"] == "content_workspace.created" and d["actor"] == OWNER
              for d in decisions)


def test_admin_reset_wipes_workspaces(gated_client, isolated_store):
    """Caught live by tests/test_reset_purges_blobs.py::test_reset_leaves_no_customer_data —
    a new customer-data table must be classified as wiped or config, never left to fall
    through. content_workspaces is customer data (ADR 0044)."""
    gated_client(OWNER).post("/content-workspaces", json={"name": "Will be wiped"})
    isolated_store.reset_analytics()
    assert isolated_store.list_content_workspaces(OWNER) == []


def test_per_user_reset_wipes_only_that_users_workspaces(gated_client, isolated_store):
    gated_client(OWNER).post("/content-workspaces", json={"name": "Alice's"})
    gated_client(OTHER).post("/content-workspaces", json={"name": "Bob's"})
    isolated_store.reset_user_data(OWNER)
    assert isolated_store.list_content_workspaces(OWNER) == []
    assert [w["name"] for w in isolated_store.list_content_workspaces(OTHER)] == ["Bob's"]
