"""GET /scans/{sid}/queue-estimate — the route wrapper around Store.queue_estimate.

Store.queue_estimate's own test file (test_queue_estimate.py) pins the estimate math; this file
pins the route's own responsibilities: kind validation, always-200 degrade for an unknown/foreign
scan (same shape as /status and /history), and the ready_workers computation core.WORKERS vs. the
split-topology worker tier.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))


@pytest.fixture
def client(monkeypatch, isolated_store):
    import core
    monkeypatch.setattr(core, "store", isolated_store)
    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app)


def _seed(st, sid: str, owner: str = "demo"):
    st.init_scan_run(sid, "drive", 1, "2026-08-29T00:00:00Z", "default", "rh",
                     owner=owner, status="running")


def test_unknown_kind_422s(client, isolated_store):
    _seed(isolated_store, "s1")
    r = client.get("/scans/s1/queue-estimate?kind=publish")
    assert r.status_code == 422


def test_unknown_scan_degrades_rather_than_404ing(client):
    r = client.get("/scans/never-existed/queue-estimate?kind=discover")
    assert r.status_code == 200
    assert r.json() == {"available": False, "reason": "scan_not_found"}


def test_another_owners_scan_is_not_readable(client, isolated_store):
    _seed(isolated_store, "s-theirs", owner="someone-else@x")
    r = client.get("/scans/s-theirs/queue-estimate?kind=discover")
    assert r.status_code == 200
    assert r.json() == {"available": False, "reason": "scan_not_found"}


def test_no_live_job_is_available_false(client, isolated_store):
    _seed(isolated_store, "s1")
    r = client.get("/scans/s1/queue-estimate?kind=remediate")
    assert r.status_code == 200
    assert r.json() == {"available": False}


def test_in_process_worker_count_is_used_when_positive(client, isolated_store, monkeypatch):
    import core
    _seed(isolated_store, "s1")
    isolated_store.enqueue_job("scan_batch", {"scan_id": "s1"}, scan_id="s1")
    monkeypatch.setattr(core, "WORKERS", 4)

    r = client.get("/scans/s1/queue-estimate?kind=discover").json()
    assert r["ready_workers"] == 4


def test_split_topology_floors_ready_workers_at_one_when_tier_alive(client, isolated_store, monkeypatch):
    import core
    _seed(isolated_store, "s1")
    isolated_store.enqueue_job("scan_batch", {"scan_id": "s1"}, scan_id="s1")
    monkeypatch.setattr(core, "WORKERS", 0)
    monkeypatch.setattr(isolated_store, "worker_tier_alive", lambda *a, **k: True)

    r = client.get("/scans/s1/queue-estimate?kind=discover").json()
    assert r["ready_workers"] == 1


def test_no_worker_anywhere_reports_zero_ready_workers(client, isolated_store, monkeypatch):
    import core
    _seed(isolated_store, "s1")
    isolated_store.enqueue_job("scan_batch", {"scan_id": "s1"}, scan_id="s1")
    monkeypatch.setattr(core, "WORKERS", 0)
    monkeypatch.setattr(isolated_store, "worker_tier_alive", lambda *a, **k: False)

    r = client.get("/scans/s1/queue-estimate?kind=discover").json()
    assert r["state"] == "no_worker_available"
    assert r["ready_workers"] == 0
