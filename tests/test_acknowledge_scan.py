"""Acknowledgement persistence for the discovery snapshot (PRD §EX-10).

The operator reviews lifecycle recommendations and explicitly approves the snapshot before
Assess can consume it. These tests cover the store methods and the REST endpoints.
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "jeremyyu.movate@gmail.com"
OTHER = "other@example.com"


def _make_scan(s, scan_id="scan-1", owner=OWNER):
    s.init_scan_run(scan_id, "drive", total=5,
                    started_at=datetime.now(timezone.utc).isoformat(),
                    rubric_name="r", rubric_hash="h", owner=owner)
    return scan_id


# ── store.acknowledge_scan ──────────────────────────────────────────────────────

def test_acknowledge_returns_true_for_valid_scan(isolated_store):
    _make_scan(isolated_store)
    assert isolated_store.acknowledge_scan("scan-1", actor=OWNER, owner=OWNER) is True


def test_acknowledge_stamps_acknowledged_flag(isolated_store):
    _make_scan(isolated_store)
    isolated_store.acknowledge_scan("scan-1", actor=OWNER, owner=OWNER)
    run = isolated_store.get_scan("scan-1")["run"]
    assert run["acknowledged"]  # SQLite may return 1 rather than True
    assert run["acknowledged_by"] == OWNER
    assert run["acknowledged_at"] is not None


def test_acknowledge_is_idempotent(isolated_store):
    _make_scan(isolated_store)
    isolated_store.acknowledge_scan("scan-1", actor=OWNER, owner=OWNER)
    assert isolated_store.acknowledge_scan("scan-1", actor=OWNER, owner=OWNER) is True
    run = isolated_store.get_scan("scan-1")["run"]
    assert run["acknowledged"]


def test_acknowledge_returns_false_for_missing_scan(isolated_store):
    assert isolated_store.acknowledge_scan("no-such", actor=OWNER, owner=OWNER) is False


def test_acknowledge_returns_false_for_wrong_owner(isolated_store):
    _make_scan(isolated_store, owner=OWNER)
    assert isolated_store.acknowledge_scan("scan-1", actor=OTHER, owner=OTHER) is False
    run = isolated_store.get_scan("scan-1")["run"]
    assert not run.get("acknowledged")


def test_acknowledge_without_owner_check_skips_auth(isolated_store):
    """owner=None bypasses ownership check — useful for admin callers."""
    _make_scan(isolated_store, owner=OWNER)
    assert isolated_store.acknowledge_scan("scan-1", actor=OTHER, owner=None) is True


# ── store.unacknowledge_scan ────────────────────────────────────────────────────

def test_unacknowledge_clears_the_stamp(isolated_store):
    _make_scan(isolated_store)
    isolated_store.acknowledge_scan("scan-1", actor=OWNER, owner=OWNER)
    assert isolated_store.unacknowledge_scan("scan-1", owner=OWNER) is True
    run = isolated_store.get_scan("scan-1")["run"]
    assert not run.get("acknowledged")
    assert run.get("acknowledged_at") is None
    assert run.get("acknowledged_by") is None


def test_unacknowledge_returns_false_for_missing_scan(isolated_store):
    assert isolated_store.unacknowledge_scan("no-such", owner=OWNER) is False


def test_unacknowledge_returns_false_for_wrong_owner(isolated_store):
    _make_scan(isolated_store, owner=OWNER)
    isolated_store.acknowledge_scan("scan-1", actor=OWNER, owner=OWNER)
    assert isolated_store.unacknowledge_scan("scan-1", owner=OTHER) is False
    run = isolated_store.get_scan("scan-1")["run"]
    assert run["acknowledged"]  # SQLite may return 1 rather than True


# ── REST endpoints ──────────────────────────────────────────────────────────────

@pytest.fixture()
def gated_client(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: e == OWNER)

    client = TestClient(app)

    def as_user(email):
        client.headers.update({"Authorization": f"Bearer {email}"})
        return client

    return as_user


def test_put_acknowledge_returns_200(gated_client, isolated_store):
    _make_scan(isolated_store)
    r = gated_client(OWNER).put("/scans/scan-1/acknowledge")
    assert r.status_code == 200
    body = r.json()
    assert body["acknowledged"] is True
    assert body["scan_id"] == "scan-1"


def test_put_acknowledge_persists_to_store(gated_client, isolated_store):
    _make_scan(isolated_store)
    gated_client(OWNER).put("/scans/scan-1/acknowledge")
    run = isolated_store.get_scan("scan-1")["run"]
    assert run["acknowledged"]  # SQLite may return 1 rather than True
    assert run["acknowledged_by"] == OWNER


def test_put_acknowledge_404_for_unknown_scan(gated_client):
    r = gated_client(OWNER).put("/scans/no-such-scan/acknowledge")
    assert r.status_code == 404


def test_delete_acknowledge_returns_200(gated_client, isolated_store):
    _make_scan(isolated_store)
    isolated_store.acknowledge_scan("scan-1", actor=OWNER, owner=OWNER)
    r = gated_client(OWNER).delete("/scans/scan-1/acknowledge")
    assert r.status_code == 200
    assert r.json()["acknowledged"] is False


def test_delete_acknowledge_clears_store(gated_client, isolated_store):
    _make_scan(isolated_store)
    isolated_store.acknowledge_scan("scan-1", actor=OWNER, owner=OWNER)
    gated_client(OWNER).delete("/scans/scan-1/acknowledge")
    run = isolated_store.get_scan("scan-1")["run"]
    assert not run.get("acknowledged")


def test_delete_acknowledge_404_for_unknown_scan(gated_client):
    r = gated_client(OWNER).delete("/scans/no-such-scan/acknowledge")
    assert r.status_code == 404
