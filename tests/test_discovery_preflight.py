"""POST /discovery/preflight — a read-only Ready/Degraded/Blocked check on a SPECIFIC source +
scope before a scan starts, distinct from /readyz (deployment-wide, no scan_id, no idea which
folder was picked). Covers:

  1. describe_drive_readiness / describe_sharepoint_readiness — one bounded existence call per
     selected root, never a folder listing or the real BFS walk.
  2. The composing endpoint's verdict logic (blocked/degraded/ready) against worker/queue state.
"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import core


class _FakeRequest:
    """Just enough of fastapi.Request for these functions — they only read .headers."""
    def __init__(self, headers: dict):
        self.headers = headers


# ── describe_drive_readiness ────────────────────────────────────────────────────────────────

def test_drive_readiness_blocked_when_no_token_and_gis_required(monkeypatch):
    from routes.drive import describe_drive_readiness
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "some-client-id", raising=False)
    monkeypatch.setattr(core, "drive_service",
                        lambda request=None: (_ for _ in ()).throw(
                            HTTPException(401, "sign in with Google to connect your Drive")))
    r = describe_drive_readiness(_FakeRequest({}), None)
    assert r["ready"] is False
    assert r["credential_valid"] is False


def test_drive_readiness_ready_when_all_roots_resolve(monkeypatch):
    from routes.drive import describe_drive_readiness
    svc = MagicMock()
    svc.files().get().execute.return_value = {"id": "f1", "name": "Reports", "trashed": False}
    monkeypatch.setattr(core, "drive_service", lambda request=None: svc)
    r = describe_drive_readiness(_FakeRequest({}), ["f1", "f2"])
    assert r["ready"] is True
    assert r["credential_valid"] is True
    assert len(r["roots"]) == 2
    assert all(row["exists"] for row in r["roots"])


def test_drive_readiness_blocked_when_a_root_is_unreachable(monkeypatch):
    from routes.drive import describe_drive_readiness
    svc = MagicMock()

    class _NotFound(Exception):
        resp = MagicMock(status=404)
        content = b'{"error": {"message": "File not found"}}'

    svc.files().get().execute.side_effect = _NotFound()
    monkeypatch.setattr(core, "drive_service", lambda request=None: svc)
    r = describe_drive_readiness(_FakeRequest({}), ["deleted-folder"])
    assert r["ready"] is False
    assert r["roots"][0]["exists"] is False


def test_drive_readiness_blocked_when_root_is_trashed(monkeypatch):
    from routes.drive import describe_drive_readiness
    svc = MagicMock()
    svc.files().get().execute.return_value = {"id": "f1", "name": "Old", "trashed": True}
    monkeypatch.setattr(core, "drive_service", lambda request=None: svc)
    r = describe_drive_readiness(_FakeRequest({}), ["f1"])
    assert r["ready"] is False  # exists, but trashed is not a usable scan root


def test_drive_readiness_checks_synthetic_root_for_whole_drive_scan(monkeypatch):
    from routes.drive import describe_drive_readiness
    svc = MagicMock()
    svc.files().get().execute.return_value = {"id": "root", "name": "My Drive"}
    monkeypatch.setattr(core, "drive_service", lambda request=None: svc)
    r = describe_drive_readiness(_FakeRequest({}), None)
    assert r["roots"][0]["id"] == "root"
    assert r["ready"] is True


# ── describe_sharepoint_readiness ───────────────────────────────────────────────────────────

def test_sharepoint_readiness_blocked_when_no_token():
    from routes.sharepoint import describe_sharepoint_readiness
    r = describe_sharepoint_readiness(_FakeRequest({}), None)
    assert r["ready"] is False
    assert r["credential_valid"] is False


def test_sharepoint_readiness_ready_when_root_exists(monkeypatch):
    import scanner
    from routes.sharepoint import describe_sharepoint_readiness
    monkeypatch.setattr(scanner, "_sp_item_exists",
                        lambda token, drive_id, item_id="root": {"exists": True, "name": "Docs"})
    r = describe_sharepoint_readiness(_FakeRequest({"x-sp-token": "tok"}), ["drive1/item1"])
    assert r["ready"] is True
    assert r["roots"][0]["id"] == "drive1/item1"


def test_sharepoint_readiness_blocked_when_root_unreachable(monkeypatch):
    import scanner
    from routes.sharepoint import describe_sharepoint_readiness
    monkeypatch.setattr(scanner, "_sp_item_exists",
                        lambda token, drive_id, item_id="root": {"exists": False, "error": "404"})
    r = describe_sharepoint_readiness(_FakeRequest({"x-sp-token": "tok"}), ["drive1/gone"])
    assert r["ready"] is False


def test_sharepoint_readiness_splits_drive_and_item_ids_correctly(monkeypatch):
    """A Graph item id is unique only within its drive — the pair must be split apart before
    being handed to _sp_item_exists, the same way sp_folders splits `parent` (found live bug
    class, PR #... — a bare id sent to the wrong drive silently 400s or hits the wrong item)."""
    import scanner
    from routes.sharepoint import describe_sharepoint_readiness
    seen = {}

    def _fake(token, drive_id, item_id="root"):
        seen["drive_id"] = drive_id
        seen["item_id"] = item_id
        return {"exists": True, "name": "ok"}

    monkeypatch.setattr(scanner, "_sp_item_exists", _fake)
    describe_sharepoint_readiness(_FakeRequest({"x-sp-token": "tok"}), ["mydrive/myitem"])
    assert seen == {"drive_id": "mydrive", "item_id": "myitem"}


# ── POST /discovery/preflight — the composing endpoint's verdict logic ─────────────────────

@pytest.fixture()
def gated_client(monkeypatch, isolated_store):
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", "owner@example.com", raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: True)

    client = TestClient(app)

    def as_user(email):
        client.headers.update({"Authorization": f"Bearer {email}"})
        return client

    return as_user


def test_local_source_is_ready_when_workers_are_alive(gated_client, monkeypatch):
    monkeypatch.setattr(core, "WORKERS", 1, raising=False)
    r = gated_client("owner@example.com").post("/discovery/preflight?source=local")
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "ready"
    assert body["blocked_reasons"] == []


def test_blocked_when_no_worker_capacity_at_all(gated_client, monkeypatch):
    # WORKERS=0 and no heartbeat ever stored → capacity_state="unavailable" → blocked
    monkeypatch.setattr(core, "WORKERS", 0, raising=False)
    r = gated_client("owner@example.com").post("/discovery/preflight?source=local")
    body = r.json()
    assert body["verdict"] == "blocked"
    assert "worker_tier_never_started" in body["blocked_reasons"]


def test_degraded_when_queue_is_backlogged(gated_client, monkeypatch, isolated_store):
    monkeypatch.setattr(core, "WORKERS", 1, raising=False)
    for i in range(60):
        isolated_store.enqueue_job("scan", {"n": i})
    r = gated_client("owner@example.com").post("/discovery/preflight?source=local")
    body = r.json()
    assert body["verdict"] == "degraded"
    assert body["queue"]["backlogged"] is True
    assert body["queue"]["queued"] == 60


def test_blocked_takes_priority_over_degraded(gated_client, monkeypatch, isolated_store):
    """A source that cannot run at all is 'blocked' even if the queue also happens to be
    backlogged — the caller needs the more severe verdict, not a coin flip between two true facts."""
    monkeypatch.setattr(core, "WORKERS", 0, raising=False)
    for i in range(60):
        isolated_store.enqueue_job("scan", {"n": i})
    r = gated_client("owner@example.com").post("/discovery/preflight?source=local")
    assert r.json()["verdict"] == "blocked"


def test_drive_source_blocked_when_credential_missing(gated_client, monkeypatch):
    monkeypatch.setattr(core, "WORKERS", 1, raising=False)
    r = gated_client("owner@example.com").post("/discovery/preflight?source=drive")
    body = r.json()
    assert body["verdict"] == "blocked"
    assert body["source"]["ready"] is False


def test_preflight_requires_auth_like_every_other_scan_route(monkeypatch, isolated_store):
    """Not exempted from the fail-closed access gate — same protected-route contract as /scans."""
    from fastapi.testclient import TestClient
    from app import app
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "some-code", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", None, raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    client = TestClient(app)
    r = client.post("/discovery/preflight?source=local")
    assert r.status_code in (401, 403)
