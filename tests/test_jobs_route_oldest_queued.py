"""GET /jobs reports the oldest queued job's age (2026-08-29).

A worker heartbeat proves the container is up, not that anything is actually claiming work — see
worker.py's own max_unverified_lease_s docstring, and the two live bugs (#935/#936) that produced
exactly that gap in the same investigation this comes from: a worker pool that silently booted at
zero threads, and a Drive HTTP client with no socket timeout that could hang a claimed job forever.
Both looked identical to "online" from the heartbeat alone. A queued job's own age is a fact the
worker tier cannot fake by merely existing — this is what lets the frontend say so.
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


def _seed_scan(st, scan_id="s1", owner="demo"):
    st.save_scan({
        "_scan_id": scan_id, "started_at": "2026-08-29T00:00:00+00:00",
        "completed_at": "2026-08-29T00:01:00+00:00", "source": "drive",
        "owner": owner, "rubric": {"name": "r", "hash": "h"},
        "summary": {"files": 0, "certifiable": 0, "uncertain": 0, "error": 0, "avg_score": 0},
        "files": [],
    })


def test_reports_none_when_the_queue_is_empty(client):
    c, st = client
    body = c.get("/jobs").json()
    assert body["oldest_queued"] is None


def test_reports_the_oldest_queued_job(client):
    c, st = client
    _seed_scan(st)
    jid = st.enqueue_job("scan_discover", {}, scan_id="s1")
    body = c.get("/jobs").json()
    assert body["oldest_queued"]["id"] == jid
    assert body["oldest_queued"]["type"] == "scan_discover"
    assert "created_at" in body["oldest_queued"]


def test_omits_a_claimed_job_from_oldest_queued(client):
    c, st = client
    _seed_scan(st)
    st.enqueue_job("scan_discover", {}, scan_id="s1")
    st.claim_job("worker-1")
    body = c.get("/jobs").json()
    assert body["oldest_queued"] is None


def test_oldest_queued_is_global_not_owner_scoped(client):
    """Unlike `jobs`/`stats` (owner-scoped so payloads never cross tenants), `oldest_queued`
    carries no payload and answers a question about the shared worker tier, not this caller's own
    queue — so it must stay visible even when the CALLING user has nothing queued themselves."""
    c, st = client
    _seed_scan(st, scan_id="s1", owner="someone-else@example.com")
    jid = st.enqueue_job("scan_discover", {}, scan_id="s1")
    # The default TestClient caller in this fixture is "demo" (core.OWNER_EMAIL fallback / no
    # auth header), which owns nothing here — the per-owner `jobs`/`stats` fields would be empty.
    body = c.get("/jobs").json()
    assert body["stats"] == {} or body["stats"].get("queued", 0) == 0
    assert body["oldest_queued"]["id"] == jid
