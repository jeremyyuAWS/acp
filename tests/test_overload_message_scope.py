"""The overload 503 may only claim "no changes" when the request could not have made any.

The handler added in #1045 returned one body for every route: "ACP's database was temporarily at
capacity. No changes were made. Try again shortly." Its own docstring conceded the exception in
prose — a handler that already committed an earlier, separate cursor() call before a later one
hits the exhausted pool — while the message asserted the opposite to the user.

That case is real on the most consequential route there is. POST /scans commits enqueue_scan
(scan_runs + jobs + scan_inputs) and THEN calls scan_event() to record scan.queued, which is
another database write. A PoolError there returns this 503 with the scan genuinely created, and
"No changes were made" would be a lie that invites the user to submit a second one.

A read cannot have written anything, so there the claim is provable and is still made.

PRD "Automatic Worker Provisioning" §4.A: responses must distinguish accepted / not accepted /
acceptance unknown, and "do not use a global 'No changes were made' message unless the specific
operation can prove it".
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

pytest.importorskip("psycopg2", reason="the handler is only registered when psycopg2 is present")


@pytest.fixture()
def client(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient
    from app import app
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def exhausted(monkeypatch, isolated_store):
    """Every store read/write raises the incident's own exception."""
    from psycopg2.pool import PoolError

    def boom(*a, **kw):
        raise PoolError("connection pool exhausted")

    for name in ("list_jobs", "job_stats", "worker_tier_status", "oldest_queued_job",
                 "dead_letter_breakdown", "active_scan", "enqueue_scan"):
        if hasattr(isolated_store, name):
            monkeypatch.setattr(isolated_store, name, boom)
    return boom


def test_a_read_may_still_claim_no_changes(client, exhausted):
    """A GET cannot have written anything, so the strong claim is provable and kept."""
    r = client.get("/jobs")
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["changes"] == "none"
    assert "No changes were made" in body["message"]


def test_a_mutating_request_must_not_claim_no_changes(client, exhausted):
    """THE regression. The handler cannot know whether an earlier cursor() already committed."""
    r = client.post("/scans?source=local&queue=true&fanout=true")
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["changes"] == "unknown", "a mutating request claimed a certainty it cannot have"
    assert "No changes were made" not in body["message"], (
        "the overload body told the user nothing was written on a route that may have written")
    # It must point at reconciliation, not at a bare retry that could duplicate the submission.
    assert "could not confirm" in body["message"].lower()


def test_the_response_carries_the_stable_contract(client, exhausted):
    """H-05: a stable code, a request id, and a UTC timestamp — so an incident can be correlated
    rather than only described."""
    r = client.post("/scans?source=local&queue=true&fanout=true")
    body = r.json()
    assert body["detail"] == "database_busy"        # unchanged for callers already reading it
    assert body["code"] == "DB_CAPACITY_BUSY"
    assert body["request_id"] and r.headers["X-Request-Id"] == body["request_id"]
    assert r.headers["Retry-After"] == "5"
    from datetime import datetime
    parsed = datetime.fromisoformat(body["occurred_at"])
    assert parsed.tzinfo is not None, "occurred_at must be unambiguous about its zone"


def test_an_inbound_request_id_is_echoed_rather_than_replaced(client, exhausted):
    """So a correlation id set at the edge survives into the incident record."""
    r = client.get("/jobs", headers={"X-Request-Id": "edge-correlation-1234"})
    assert r.json()["request_id"] == "edge-correlation-1234"
