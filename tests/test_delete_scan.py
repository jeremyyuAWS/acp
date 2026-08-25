"""Tests for the per-scan deletion path (P3.3 — Healthcare hardening, BAA right-to-erasure).

Covers:
  1. store.delete_scan — DB purge of all scan-keyed rows, owner isolation
  2. blob.purge_scan  — per-scan blob prefix deletion (mocked)
  3. DELETE /scans/{sid} route — integration through the FastAPI layer
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import store as store_mod


# ── store.delete_scan ────────────────────────────────────────────────────────

def _seed_scan(s: store_mod.Store, scan_id: str, owner: str) -> None:
    """Insert a minimal scan_run + file_record + issue_record."""
    with s._db.cursor() as cur:
        s._db.execute(cur,
            "INSERT INTO scan_runs (id, owner_email, completed_at, files, certifiable, "
            "uncertain, error, avg_score) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (scan_id, owner, "2026-08-01T00:00:00", 1, 1, 0, 0, 100))
        s._db.execute(cur,
            "INSERT INTO file_records (scan_id, file, engine, status, score, compliant) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (scan_id, "report.pdf", "pdf", "analysed", 100, 1))
        s._db.execute(cur,
            "INSERT INTO issue_records (scan_id, file, rule_id, wcag, severity) "
            "VALUES (%s,%s,%s,%s,%s)",
            (scan_id, "report.pdf", "pdf.tagged", "SC_1_3_1", "CRITICAL"))
        s._db.execute(cur,
            "INSERT INTO pii_findings (scan_id, file, pii_type, count, severity) "
            "VALUES (%s,%s,%s,%s,%s)",
            (scan_id, "report.pdf", "EMAIL", 2, "HIGH"))


def _count(s: store_mod.Store, table: str, scan_id: str) -> int:
    with s._db.cursor() as cur:
        s._db.execute(cur, f"SELECT COUNT(*) AS n FROM {table} WHERE scan_id=%s", (scan_id,))
        rows = s._db.fetchall(cur)
        return rows[0]["n"] if rows else 0


def test_delete_scan_removes_scan_run(isolated_store):
    _seed_scan(isolated_store, "s1", "alice@example.com")
    result = isolated_store.delete_scan("s1", "alice@example.com")
    assert result == {"scan_id": "s1", "owner": "alice@example.com"}
    # scan_runs row gone
    assert isolated_store.get_scan("s1") is None


def test_delete_scan_removes_child_rows(isolated_store):
    _seed_scan(isolated_store, "s1", "alice@example.com")
    isolated_store.delete_scan("s1", "alice@example.com")
    assert _count(isolated_store, "file_records", "s1") == 0
    assert _count(isolated_store, "issue_records", "s1") == 0
    assert _count(isolated_store, "pii_findings", "s1") == 0


def test_delete_scan_wrong_owner_returns_none(isolated_store):
    _seed_scan(isolated_store, "s1", "alice@example.com")
    # Bob cannot delete Alice's scan
    result = isolated_store.delete_scan("s1", "bob@example.com")
    assert result is None
    # Alice's scan is untouched
    assert isolated_store.get_scan("s1", owner="alice@example.com") is not None


def test_delete_scan_nonexistent_returns_none(isolated_store):
    result = isolated_store.delete_scan("does-not-exist", "alice@example.com")
    assert result is None


def test_delete_scan_does_not_affect_other_scans(isolated_store):
    _seed_scan(isolated_store, "s1", "alice@example.com")
    _seed_scan(isolated_store, "s2", "alice@example.com")
    isolated_store.delete_scan("s1", "alice@example.com")
    # s2 unaffected
    assert isolated_store.get_scan("s2", owner="alice@example.com") is not None
    assert _count(isolated_store, "file_records", "s2") == 1


def test_delete_scan_idempotent(isolated_store):
    """Deleting an already-deleted scan returns None without raising."""
    _seed_scan(isolated_store, "s1", "alice@example.com")
    isolated_store.delete_scan("s1", "alice@example.com")
    result = isolated_store.delete_scan("s1", "alice@example.com")
    assert result is None


# ── blob.purge_scan ──────────────────────────────────────────────────────────

def test_purge_scan_no_blob_storage():
    """Returns {} when blob storage is not configured."""
    import blob as blob_mod
    with patch.object(blob_mod, "_service_client", return_value=None):
        result = blob_mod.purge_scan("alice@example.com", "s1")
    assert result == {}


def test_purge_scan_deletes_by_prefix():
    """Calls delete_blob for each blob under {owner}/{scan_id}/ prefix."""
    import blob as blob_mod

    fake_blob = MagicMock()
    fake_blob.name = "alice@example.com/s1/report.pdf"
    fake_container = MagicMock()
    fake_container.list_blobs.return_value = [fake_blob]
    fake_service = MagicMock()
    fake_service.get_container_client.return_value = fake_container

    with patch.object(blob_mod, "_service_client", return_value=fake_service):
        result = blob_mod.purge_scan("alice@example.com", "s1")

    # Each container should have been listed with the right prefix
    for call in fake_container.list_blobs.call_args_list:
        assert call.kwargs.get("name_starts_with") == "alice@example.com/s1/"
    assert fake_container.delete_blob.called
    # All three containers attempted
    assert len(result) == 3


# ── DELETE /scans/{sid} route ─────────────────────────────────────────────────

@pytest.fixture()
def app_client(isolated_store, monkeypatch):
    """A TestClient for the FastAPI app pointed at the isolated store."""
    from fastapi.testclient import TestClient
    import core as core_mod
    monkeypatch.setattr(core_mod, "store", isolated_store)
    import app as app_mod
    return TestClient(app_mod.app, raise_server_exceptions=True)


def test_route_delete_scan_returns_200(app_client, isolated_store):
    _seed_scan(isolated_store, "scan-abc", "demo")
    import blob as blob_mod
    with patch.object(blob_mod, "_service_client", return_value=None):
        resp = app_client.delete("/scans/scan-abc")
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] is True
    assert body["scan_id"] == "scan-abc"


def test_route_delete_scan_404_for_missing(app_client):
    resp = app_client.delete("/scans/does-not-exist")
    assert resp.status_code == 404


def test_route_delete_scan_404_for_wrong_owner(app_client, isolated_store):
    _seed_scan(isolated_store, "scan-xyz", "alice@example.com")
    # Default test user is "demo" — cannot delete alice's scan
    import blob as blob_mod
    with patch.object(blob_mod, "_service_client", return_value=None):
        resp = app_client.delete("/scans/scan-xyz")
    assert resp.status_code == 404


def test_route_delete_scan_appends_decision_log(app_client, isolated_store):
    _seed_scan(isolated_store, "scan-log", "demo")
    import blob as blob_mod
    with patch.object(blob_mod, "_service_client", return_value=None):
        app_client.delete("/scans/scan-log")
    # decision_log should have an entry for this deletion
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(
            cur,
            "SELECT action, scan_id FROM decision_log WHERE scan_id=%s",
            ("scan-log",),
        )
        rows = isolated_store._db.fetchall(cur)
    assert any(r["action"] == "delete_scan" for r in rows)
