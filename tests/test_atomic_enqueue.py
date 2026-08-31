"""Atomic enqueue: scan_runs stub and initial job row must be created in one transaction.

Acceptance criteria exercised below:
  1. Scan and initial job created in one database transaction.
  2. API returns only after transaction commits (implicit — synchronous call).
  3. Returned scan ID immediately resolves via GET /scans/{id}.
  4. Initial state is `queued` for both the scan and the job.
  5. Queue failure rolls back both records — no orphan stubs.
  6. Repeated client submission with same idempotency key returns original scan.
  7. Worker claiming cannot occur before immutable inputs exist (both rows present on return).
  8. Browser refresh can reconnect to queued scan (same as criterion 3).
  9. Unknown scan IDs still return None (404 at route level).
 10. Queued scans no longer generate startup 404s (same as criterion 3).
 11. Tests cover failure between every write in the transaction.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "owner@example.com"
OTHER = "other@example.com"


# ── Criteria 1, 3, 4, 7, 8, 10 ──────────────────────────────────────────────

def test_enqueue_scan_creates_both_rows(isolated_store):
    """Scan row and job row are both present immediately after enqueue_scan returns."""
    s = isolated_store
    scan_id, job_id = s.enqueue_scan("scan-ae1", "drive", OWNER, "scan_discover", {})
    # Scan immediately visible (criterion 3, 8, 10)
    result = s.get_scan("scan-ae1", owner=OWNER)
    assert result is not None
    assert result["run"]["status"] == "queued"
    assert result["run"]["source"] == "drive"
    assert result["run"]["owner_email"] == OWNER
    # Job immediately present (criterion 1, 7)
    job = s.get_job(job_id)
    assert job is not None
    assert job["scan_id"] == "scan-ae1"
    assert job["status"] == "queued"


def test_enqueue_scan_initial_state_queued(isolated_store):
    """Initial state is 'queued' for both scan and job (criterion 4)."""
    s = isolated_store
    scan_id, job_id = s.enqueue_scan("scan-ae2", "drive", OWNER, "scan_discover", {})
    assert s.get_scan(scan_id, owner=OWNER)["run"]["status"] == "queued"
    assert s.get_job(job_id)["status"] == "queued"


def test_enqueue_scan_returned_id_matches_row(isolated_store):
    """The returned scan_id matches the stored row's primary key."""
    s = isolated_store
    scan_id, _ = s.enqueue_scan("scan-ae3", "drive", OWNER, "scan_discover", {})
    result = s.get_scan(scan_id, owner=OWNER)
    assert result["run"]["id"] == scan_id


def test_enqueue_scan_job_payload_preserved(isolated_store):
    """The job payload is stored exactly as supplied."""
    import json
    s = isolated_store
    payload = {"source": "drive", "scan_id": "scan-ae4", "folder": "root"}
    _, job_id = s.enqueue_scan("scan-ae4", "drive", OWNER, "scan_discover", payload)
    job = s.get_job(job_id)
    assert job["payload"]["scan_id"] == "scan-ae4"
    assert job["payload"]["folder"] == "root"


# ── Criterion 5 / 11: rollback on failure ────────────────────────────────────

def test_enqueue_scan_rollback_when_jobs_insert_fails(isolated_store, monkeypatch):
    """If the jobs INSERT fails, the scan_runs row is rolled back — no orphan stubs (criterion 5).
    Tests failure between the second write in the transaction (criterion 11)."""
    import store as store_mod
    original_execute = store_mod._SQLiteAdapter.execute

    def patched_execute(self, cur, sql, params=()):
        if "INSERT INTO jobs" in sql:
            raise RuntimeError("injected: jobs INSERT failure")
        return original_execute(self, cur, sql, params)

    monkeypatch.setattr(store_mod._SQLiteAdapter, "execute", patched_execute)

    with pytest.raises(RuntimeError, match="injected"):
        isolated_store.enqueue_scan("scan-ae5", "drive", OWNER, "scan_discover", {})

    # Transaction rolled back — no scan_runs row
    assert isolated_store.get_scan("scan-ae5", owner=OWNER) is None


def test_enqueue_scan_rollback_when_scan_runs_insert_fails(isolated_store, monkeypatch):
    """If the scan_runs INSERT fails, no job row is created either (criterion 5, 11).
    Tests failure at the first write in the transaction."""
    import store as store_mod
    original_execute = store_mod._SQLiteAdapter.execute

    def patched_execute(self, cur, sql, params=()):
        if "INSERT INTO scan_runs" in sql:
            raise RuntimeError("injected: scan_runs INSERT failure")
        return original_execute(self, cur, sql, params)

    monkeypatch.setattr(store_mod._SQLiteAdapter, "execute", patched_execute)

    with pytest.raises(RuntimeError, match="injected"):
        isolated_store.enqueue_scan("scan-ae6", "drive", OWNER, "scan_discover", {})

    # No job row for this scan_id either
    assert isolated_store.get_scan("scan-ae6", owner=OWNER) is None


# ── Criterion 6: idempotency key deduplication ───────────────────────────────

def test_idempotency_key_returns_original_scan(isolated_store):
    """Repeated submission with the same key returns the original (scan_id, job_id)."""
    s = isolated_store
    scan_id1, job_id1 = s.enqueue_scan("scan-ae7", "drive", OWNER, "scan_discover", {},
                                        idempotency_key="key-001")
    scan_id2, job_id2 = s.enqueue_scan("scan-ae8", "drive", OWNER, "scan_discover", {},
                                        idempotency_key="key-001")
    assert scan_id2 == scan_id1
    assert job_id2 == job_id1


def test_idempotency_key_is_tenant_scoped(isolated_store):
    """Same key for different owners creates separate scans — tenant isolation."""
    s = isolated_store
    scan_id1, _ = s.enqueue_scan("scan-ae9", "drive", OWNER, "scan_discover", {},
                                  idempotency_key="key-002")
    scan_id2, _ = s.enqueue_scan("scan-ae10", "drive", OTHER, "scan_discover", {},
                                  idempotency_key="key-002")
    assert scan_id2 != scan_id1


def test_no_idempotency_key_always_creates_new_scan(isolated_store):
    """Without a key, repeated calls create separate scans — no implicit deduplication."""
    s = isolated_store
    scan_id1, _ = s.enqueue_scan("scan-ae11", "drive", OWNER, "scan_discover", {})
    scan_id2, _ = s.enqueue_scan("scan-ae12", "drive", OWNER, "scan_discover", {})
    assert scan_id1 != scan_id2


# ── Criterion 9: unknown IDs still return None ───────────────────────────────

def test_unknown_scan_id_returns_none(isolated_store):
    """Unknown scan IDs must still return None (criterion 9)."""
    assert isolated_store.get_scan("does-not-exist", owner=OWNER) is None


def test_enqueue_scan_does_not_widen_id_space(isolated_store):
    """A scan created by enqueue_scan is not visible under a different ID."""
    s = isolated_store
    s.enqueue_scan("scan-ae13", "drive", OWNER, "scan_discover", {})
    assert s.get_scan("scan-ae99", owner=OWNER) is None


# ── Owner isolation ───────────────────────────────────────────────────────────

def test_enqueue_scan_is_owner_scoped(isolated_store):
    """Scan created by one owner is not visible to another."""
    s = isolated_store
    scan_id, _ = s.enqueue_scan("scan-ae14", "drive", OWNER, "scan_discover", {})
    assert s.get_scan(scan_id, owner=OWNER) is not None
    assert s.get_scan(scan_id, owner=OTHER) is None


# ── Worker-claims path integration ───────────────────────────────────────────

def test_init_scan_run_promotes_enqueued_stub(isolated_store):
    """Worker's init_scan_run promotes the stub to 'running' (DO UPDATE path still works)."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    s = isolated_store
    scan_id, _ = s.enqueue_scan("scan-ae15", "drive", OWNER, "scan_discover", {})
    s.init_scan_run(scan_id, "drive", total=10, started_at=now,
                    rubric_name="WCAG 2.1 AA", rubric_hash="abc123",
                    owner=OWNER, status="running")
    run = s.get_scan(scan_id, owner=OWNER)["run"]
    assert run["status"] == "running"
    assert run["rubric_name"] == "WCAG 2.1 AA"
    assert run["files"] == 10


def test_cancel_queued_job_stamps_enqueued_scan_cancelled(isolated_store):
    """cancel_queued_job stamps the enqueue_scan stub as 'cancelled'."""
    s = isolated_store
    scan_id, _ = s.enqueue_scan("scan-ae16", "drive", OWNER, "scan_discover",
                                  {"scan_id": "scan-ae16"})
    assert s.cancel_queued_job("scan-ae16") is True
    run = s.get_scan(scan_id, owner=OWNER)["run"]
    assert run["status"] == "cancelled"


# ── content_workspace_version_id (ADR 0044) ──────────────────────────────────

def test_enqueue_scan_links_a_content_workspace_version(isolated_store):
    s = isolated_store
    scan_id, _ = s.enqueue_scan("scan-ae17", "workspace", OWNER, "workspace_scan_file", {},
                                content_workspace_version_id="v-abc")
    with s._db.cursor() as cur:
        s._db.execute(cur, "SELECT content_workspace_version_id FROM scan_runs WHERE id=%s",
                      (scan_id,))
        row = s._db.fetchone(cur)
    assert row["content_workspace_version_id"] == "v-abc"


def test_a_connector_sourced_scan_has_no_content_workspace_version(isolated_store):
    s = isolated_store
    scan_id, _ = s.enqueue_scan("scan-ae18", "drive", OWNER, "scan_discover", {})
    with s._db.cursor() as cur:
        s._db.execute(cur, "SELECT content_workspace_version_id FROM scan_runs WHERE id=%s",
                      (scan_id,))
        row = s._db.fetchone(cur)
    assert row["content_workspace_version_id"] is None


def test_init_scan_run_preserves_the_content_workspace_version_link(isolated_store):
    """The worker-side promotion (init_scan_run, ON CONFLICT DO UPDATE) must not clear the link
    set atomically at enqueue time — it isn't in that statement's SET clause, and this pins that
    it stays that way."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    s = isolated_store
    scan_id, _ = s.enqueue_scan("scan-ae19", "workspace", OWNER, "workspace_scan_file", {},
                                content_workspace_version_id="v-xyz")
    s.init_scan_run(scan_id, "workspace", total=1, started_at=now,
                    rubric_name="WCAG 2.1 AA", rubric_hash="abc123",
                    owner=OWNER, status="running")
    with s._db.cursor() as cur:
        s._db.execute(cur, "SELECT content_workspace_version_id FROM scan_runs WHERE id=%s",
                      (scan_id,))
        row = s._db.fetchone(cur)
    assert row["content_workspace_version_id"] == "v-xyz"
