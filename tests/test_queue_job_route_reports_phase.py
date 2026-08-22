"""GET /jobs/{job_id} reports phase + locked_at (2026-08-22).

Added so AssessRunner's deferred-Assess poll can distinguish "queued, waiting for a worker" from
"a worker has been on this for 40s" -- both used to render identically as a bare "Opening &
assessing 0 of N…" with no way to tell whether the run was about to start or genuinely stuck. The
store already carried both fields (phase is written by job handlers as they work; locked_at is
stamped on claim) -- this route just wasn't returning them.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


@pytest.fixture()
def client(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient
    from app import app
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", "", raising=False)
    return TestClient(app), isolated_store


def _seed_scan_and_job(st, *, status="queued", phase=None):
    st.save_scan({
        "_scan_id": "s1", "started_at": "2026-08-22T00:00:00+00:00",
        "completed_at": "2026-08-22T00:01:00+00:00", "source": "drive",
        "owner": "demo", "rubric": {"name": "r", "hash": "h"},
        "summary": {"files": 0, "certifiable": 0, "uncertain": 0, "error": 0, "avg_score": 0},
        "files": [],
    })
    jid = st.enqueue_job("scan_assess", {"scan_id": "s1"}, scan_id="s1")
    if status != "queued":
        claimed = st.claim_job("worker-1")
        assert claimed and claimed["id"] == jid
        if status == "running" and phase:
            st.set_job_phase(jid, phase)
        elif status == "dead":
            for _ in range(10):
                st.fail_job(jid, "boom", backoff_seconds=0)
                nxt = st.claim_job("worker-1")
                if nxt is None:
                    break
    return jid


def test_a_queued_job_reports_status_queued_with_no_phase(client):
    c, st = client
    jid = _seed_scan_and_job(st, status="queued")
    body = c.get(f"/jobs/{jid}").json()
    assert body["status"] == "queued"
    assert body["phase"] is None
    assert body["locked_at"] is None


def test_a_claimed_running_job_reports_its_phase_and_when_it_was_claimed(client):
    c, st = client
    jid = _seed_scan_and_job(st, status="running", phase="opening report.pdf")
    body = c.get(f"/jobs/{jid}").json()
    assert body["status"] == "running"
    assert body["phase"] == "opening report.pdf"
    assert body["locked_at"] is not None


def test_a_job_with_no_phase_written_yet_reports_none_not_a_placeholder(client):
    """A handler that hasn't reported anything shows nothing -- not an empty string or a fake
    'working...' that would misrepresent silence as information."""
    c, st = client
    jid = _seed_scan_and_job(st, status="running")
    body = c.get(f"/jobs/{jid}").json()
    assert body["phase"] is None


def test_a_dead_job_still_reports_its_error_alongside_the_new_fields(client):
    c, st = client
    jid = _seed_scan_and_job(st, status="dead")
    body = c.get(f"/jobs/{jid}").json()
    assert body["status"] == "dead"
    assert body["error"]
    # New fields present on every response shape, not just the happy path.
    assert "phase" in body and "locked_at" in body
