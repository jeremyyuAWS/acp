"""Queued scan pre-creation: GET /scans/{id} must return 200 from the moment startScanQueued
returns the scan ID.

Previously, enqueue_job returned a scan_id before any scan_runs row existed. Every poll of
GET /scans/{id} during the window between 'job enqueued' and 'worker claimed' received 404,
producing a console 404 flood and an API-contract violation: the caller held an identifier the
server did not yet recognise as valid.

Fix: pre_create_queued_scan writes a minimal scan_runs stub (status='queued') before the job
is enqueued, so the ID is immediately resolvable. init_scan_run promotes it (DO UPDATE) when the
worker begins discovery; cancel_queued_job stamps it 'cancelled' if the job is killed before a
worker claims it.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "owner@example.com"
_NOW = datetime.now(timezone.utc).isoformat()


# ── store.pre_create_queued_scan ────────────────────────────────────────────────

def test_pre_create_makes_scan_immediately_visible(isolated_store):
    """GET /scans/{id} returns the scan row from the moment the ID is issued."""
    s = isolated_store
    s.pre_create_queued_scan("scan-q1", "drive", OWNER)
    result = s.get_scan("scan-q1", owner=OWNER)
    assert result is not None
    assert result["run"]["status"] == "queued"
    assert result["run"]["source"] == "drive"
    assert result["run"]["owner_email"] == OWNER


def test_pre_create_is_owner_scoped(isolated_store):
    """Pre-created stub is invisible to a different owner — per-user isolation is not bypassed."""
    s = isolated_store
    s.pre_create_queued_scan("scan-q2", "drive", OWNER)
    assert s.get_scan("scan-q2", owner="other@example.com") is None


def test_pre_create_is_idempotent(isolated_store):
    """Calling pre_create_queued_scan twice for the same ID is a no-op (ON CONFLICT DO NOTHING)."""
    s = isolated_store
    s.pre_create_queued_scan("scan-q3", "drive", OWNER)
    s.pre_create_queued_scan("scan-q3", "drive", OWNER)  # second call must not raise
    assert s.get_scan("scan-q3", owner=OWNER)["run"]["status"] == "queued"


def test_unknown_scan_still_returns_none(isolated_store):
    """Unknown IDs must still return None — pre-creation does not widen the ID space."""
    assert isolated_store.get_scan("does-not-exist", owner=OWNER) is None


# ── init_scan_run promotes the stub (DO UPDATE) ─────────────────────────────────

def test_init_scan_run_promotes_queued_stub(isolated_store):
    """When a worker calls init_scan_run on a pre-created stub, it overwrites status, rubric,
    and scope — the stub is promoted to a real running row."""
    s = isolated_store
    s.pre_create_queued_scan("scan-q4", "drive", OWNER)
    s.init_scan_run("scan-q4", "drive", total=10, started_at=_NOW,
                    rubric_name="WCAG 2.1 AA", rubric_hash="abc123",
                    owner=OWNER, status="running")
    run = s.get_scan("scan-q4", owner=OWNER)["run"]
    assert run["status"] == "running"
    assert run["rubric_name"] == "WCAG 2.1 AA"
    assert run["files"] == 10


def test_init_scan_run_still_works_without_pre_create(isolated_store):
    """init_scan_run must work identically for paths that never call pre_create_queued_scan
    (the non-durable in-process path, tests, etc.)."""
    s = isolated_store
    s.init_scan_run("scan-q5", "drive", total=5, started_at=_NOW,
                    rubric_name="WCAG 2.1 AA", rubric_hash="def456",
                    owner=OWNER, status="discovered")
    run = s.get_scan("scan-q5", owner=OWNER)["run"]
    assert run["status"] == "discovered"
    assert run["files"] == 5


# ── cancel_queued_job stamps the pre-created stub ──────────────────────────────

def test_cancel_queued_job_stamps_scan_run_cancelled(isolated_store):
    """When a queued job is killed before a worker claims it, the pre-created scan_runs stub
    must show status='cancelled' so callers see a terminal state, not a stale 'queued'."""
    s = isolated_store
    s.pre_create_queued_scan("scan-q6", "drive", OWNER)
    s.enqueue_job("scan_discover", {"scan_id": "scan-q6"}, scan_id="scan-q6")
    assert s.cancel_queued_job("scan-q6") is True
    run = s.get_scan("scan-q6", owner=OWNER)["run"]
    assert run["status"] == "cancelled"


def test_cancel_queued_job_without_pre_create_still_works(isolated_store):
    """cancel_queued_job without a pre-created stub (legacy path) must still return True and
    not raise — the UPDATE on scan_runs is a no-op when no row exists."""
    s = isolated_store
    s.enqueue_job("scan_discover", {"scan_id": "scan-q7"}, scan_id="scan-q7")
    assert s.cancel_queued_job("scan-q7") is True
    # No scan_runs row was created — get_scan returns None, not an error.
    assert s.get_scan("scan-q7", owner=OWNER) is None
