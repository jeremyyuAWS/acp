"""Regression: a scan conflict must not overwrite the job to phase='discovered' (0 files).

When _scan_discover detects that another scan is already active for the same source, it marks the
conflicting scan_run as failed, writes phase='error' to the job record, and returns without raising.
Before the fix (routes/scans.py), the next line unconditionally wrote phase='discovered' / done=True
to the job, clobbering that error and making 0 files look like a completed empty-corpus discovery —
indistinguishable from a real Drive source that genuinely contains no documents.

The fix reads the job state after _scan_discover returns and skips the phase='discovered' overwrite
when phase='error' is already set.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "testuser@example.com"
_CONFLICT_MSG = "Discovery already active for source 'local': scan existing-1 is still running"


@pytest.fixture()
def _client(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: True)

    client = TestClient(app, raise_server_exceptions=False)
    client.headers.update({"Authorization": f"Bearer {OWNER}"})
    return client, core


def _wait_for_job(core, job_id, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = core.get_job_state(job_id) or {}
        if state.get("done"):
            return state
        time.sleep(0.05)
    return core.get_job_state(job_id) or {}


def test_conflict_leaves_job_at_error_not_discovered(monkeypatch, _client):
    """A conflict-detected _scan_discover must not be overwritten to phase='discovered'.

    Reproduces the exact failure mode: _scan_discover returns without raising after writing
    phase='error', and the next unconditional update_job call (before the fix) clobbered it.
    """
    import handlers as handlers_mod

    client, core = _client

    # Force the deferred-discover path (the branch that calls _scan_discover from work()).
    monkeypatch.setattr(handlers_mod, "_defer_analysis_to_assess", lambda: True)

    def _fake_scan_discover(payload, job):
        # Simulate _scan_discover detecting a conflict: write phase=error and return (no raise).
        # This is the exact shape the real conflict handler takes after the Phase 1 fix.
        job_id = job.get("id")
        if job_id:
            core.update_job(job_id, {"phase": "error", "done": True, "error": _CONFLICT_MSG})

    monkeypatch.setattr(handlers_mod, "_scan_discover", _fake_scan_discover)

    r = client.post("/scans?source=local")
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]

    state = _wait_for_job(core, job_id)

    assert state.get("done"), "job never reached done=True"
    assert state.get("phase") == "error", (
        f"expected phase='error' from a conflicted scan, got {state.get('phase')!r}; "
        "the unconditional phase='discovered' overwrite is clobbering the conflict error"
    )
    assert _CONFLICT_MSG in (state.get("error") or ""), (
        f"conflict message not in job error: {state.get('error')!r}"
    )
