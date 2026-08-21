"""Cancelling a scan that is still queued and has never been claimed by a worker — found live
2026-08-21: a scan stuck at "Waiting for a worker to pick up the scan…" had no way out. The
sibling gap to test_scan_cancel_selfheal.py's 2026-07-11 fix: THAT covers a scan already
`status='running'` (a scan_runs row exists); this covers the earlier window where the job is
merely `status='queued'` and no scan_runs row exists yet at all — `cancel_scan` requires one and
so cannot reach it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "jeremyyu.movate@gmail.com"


# ── store.cancel_queued_job ─────────────────────────────────────────────────────

def test_cancels_a_never_claimed_queued_job(isolated_store):
    s = isolated_store
    s.enqueue_job("scan_discover", {"scan_id": "s1"}, scan_id="s1")
    assert s.cancel_queued_job("s1") is True
    assert s.job_stats().get("queued", 0) == 0
    assert s.job_stats().get("dead", 0) == 1


def test_does_not_touch_a_job_already_claimed(isolated_store):
    """Once a worker has claimed it (status moved past 'queued'), this is no longer the queued-
    unclaimed case — cancel_scan (which now has a real scan_runs row to act on) is the right call,
    not this one. Confirms cancel_queued_job stays scoped to exactly the gap it exists for."""
    s = isolated_store
    s.enqueue_job("scan_discover", {"scan_id": "s2"}, scan_id="s2")
    s.claim_job("worker-1")   # advances status to 'running'
    assert s.cancel_queued_job("s2") is False
    assert s.job_stats().get("running", 0) == 1   # untouched


def test_false_for_a_scan_id_with_no_job_at_all(isolated_store):
    assert isolated_store.cancel_queued_job("no-such-scan") is False


def test_cancelling_twice_is_false_the_second_time(isolated_store):
    s = isolated_store
    s.enqueue_job("scan_discover", {"scan_id": "s3"}, scan_id="s3")
    assert s.cancel_queued_job("s3") is True
    assert s.cancel_queued_job("s3") is False   # already dead, nothing left to cancel


# ── POST /scans/{sid}/cancel — the route, falling back to cancel_queued_job ────

@pytest.fixture()
def gated_client(monkeypatch, isolated_store):
    """Same shape as test_undo_fix_route.py's fixture."""
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


def test_route_cancels_a_queued_unclaimed_scan(gated_client, isolated_store):
    isolated_store.enqueue_job("scan_discover", {"scan_id": "s-route1"}, scan_id="s-route1")
    r = gated_client(OWNER).post("/scans/s-route1/cancel")
    assert r.status_code == 200
    assert r.json() == {"scan_id": "s-route1", "status": "cancelled", "was_queued": True}
    assert isolated_store.job_stats().get("dead", 0) == 1


def test_route_still_409s_when_there_is_truly_nothing_to_cancel(gated_client):
    r = gated_client(OWNER).post("/scans/does-not-exist/cancel")
    assert r.status_code == 409


def test_route_prefers_the_running_scan_cancel_when_a_scan_run_exists(gated_client, isolated_store):
    """A scan that's actually running (scan_runs row present) must go through cancel_scan's real
    close-out — completed_at, assessed_at stamping, etc. — not the bare job-kill this fallback
    does. Confirms the route tries cancel_scan FIRST, not that the fallback races ahead of it."""
    from datetime import datetime, timezone
    isolated_store.init_scan_run("s-route2", "drive", total=1,
                                 started_at=datetime.now(timezone.utc).isoformat(),
                                 rubric_name="r", rubric_hash="h", owner=OWNER)
    isolated_store.enqueue_job("scan_file", {"scan_id": "s-route2"}, scan_id="s-route2")

    r = gated_client(OWNER).post("/scans/s-route2/cancel")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "cancelled"
    assert "was_queued" not in body   # the real cancel_scan path, not the queued fallback
    assert isolated_store.get_scan("s-route2")["run"]["status"] == "cancelled"
