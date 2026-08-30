"""A rejected scan submission must not destroy the run it would have replaced (PRD H-03).

Found by code review after the 2026-08-30 production incident. `POST /scans?queue=true` ran its
single-flight guard — active_scan() then supersede_scan() — 46 lines BEFORE enqueue_scan(), the
transaction that actually creates the new run, with three more database round trips in between
(list_ai_provider_configs, list_disposition_policies, get_ai_enabled). Any of those raising left
the caller's in-flight scan killed and nothing put in its place: the request 500'd, so the UI
reported a failure, and the running scan it had silently destroyed was simply gone.

That is not hypothetical machinery. On 2026-08-30 the API replica's Postgres pool (10 connections,
`max(2, ACP_WORKERS) + 8` with ACP_WORKERS=0) was exhausted and `psycopg2.pool.PoolError` came out
of exactly this route — 88 terminal occurrences across five revisions. The incident's own POST
/scans failed at the active_scan() READ on line 131, one line before the destructive call, which
is the only reason no run was lost that minute.

The guard itself is still wanted (test_scan_single_flight.py): two concurrent discoveries for one
owner waste Drive quota and DB connections. It is the ORDER that was wrong. Acceptance is durable
first; the stop follows it.
"""
from __future__ import annotations
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "jeremyyu.movate@gmail.com"
_NOW = datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def gated_client(monkeypatch, isolated_store):
    """Same shape as test_scan_single_flight.py's fixture."""
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

    def as_user(email):
        client.headers.update({"Authorization": f"Bearer {email}"})
        return client

    return as_user


def _start_queued(client_fn, owner, source="local", headers=None):
    r = client_fn(owner).post(f"/scans?source={source}&queue=true&fanout=true",
                              headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()["scan_id"]


def _mark_running(store, scan_id, owner):
    """A freshly enqueued scan sits at 'queued' until a worker claims it; active_scan() only
    reports 'running'. Simulate the claim the way a real worker's init_scan_run call would."""
    store.init_scan_run(scan_id, "local", total=5, started_at=_NOW,
                        rubric_name="WCAG 2.1 AA", rubric_hash="abc123",
                        owner=owner, status="running")


def test_a_failed_submission_leaves_the_running_scan_alone(gated_client, isolated_store,
                                                           monkeypatch):
    """THE regression. enqueue_scan raises the incident's own exception type; the prior run
    must survive, and no replacement may be left behind."""
    s1 = _start_queued(gated_client, OWNER)
    _mark_running(isolated_store, s1, OWNER)
    assert isolated_store.get_scan(s1, owner=OWNER)["run"]["status"] == "running"

    from psycopg2.pool import PoolError

    def _exhausted(*a, **kw):
        raise PoolError("connection pool exhausted")

    monkeypatch.setattr(isolated_store, "enqueue_scan", _exhausted)

    before = {r["id"] for r in isolated_store.list_scans_including_discovered(owner=OWNER)}
    r = gated_client(OWNER).post("/scans?source=local&queue=true&fanout=true")

    # #1045's handler turns PoolError into this contract, and this PR's ordering fix is what
    # makes the OUTCOME below true: the caller's running scan survives a rejected submission.
    #
    # The body deliberately does NOT claim "No changes were made" here, and this assertion
    # changed when that was scoped (tests/test_overload_message_scope.py). The handler cannot
    # know whether an earlier cursor() in the same request already committed — on this very
    # route, scan_event() writes AFTER enqueue_scan commits — so on a mutating request the
    # honest answer is that the outcome is unknown. The client half agrees: submitIntent's
    # outcomeIsUncertain() treats a 503 as uncertain and retains the idempotency key, so a retry
    # resolves to any job that does exist rather than creating a second one.
    assert r.status_code == 503, f"expected the pool-exhaustion contract, got {r.status_code}"
    assert r.json()["detail"] == "database_busy"
    assert r.json()["changes"] == "unknown"

    # The point of the whole test: the user's run is still theirs.
    assert isolated_store.get_scan(s1, owner=OWNER)["run"]["status"] == "running", (
        "a rejected submission superseded the caller's in-flight scan — the H-03 defect")

    after = {r["id"] for r in isolated_store.list_scans_including_discovered(owner=OWNER)}
    assert after == before, f"a rejected submission left scan rows behind: {after - before}"


def test_the_guard_still_supersedes_on_the_success_path(gated_client, isolated_store):
    """Deferring the stop must not disable it — the concurrency guard is still wanted."""
    s1 = _start_queued(gated_client, OWNER)
    _mark_running(isolated_store, s1, OWNER)

    s2 = _start_queued(gated_client, OWNER)

    assert s2 != s1
    assert isolated_store.get_scan(s1, owner=OWNER)["run"]["status"] == "superseded"
    assert isolated_store.get_scan(s2, owner=OWNER)["run"]["status"] == "queued"


def test_an_idempotent_retry_does_not_supersede_the_scan_it_returns(gated_client,
                                                                    isolated_store):
    """A retry carrying the same Idempotency-Key gets the ORIGINAL scan back. If the guard ran
    against it, the retry would kill the very job it was handed — the submission destroying
    itself. Reaching that state needs the returned scan to be the one active_scan() reports,
    which is exactly what a worker claiming it between the two calls produces."""
    key = "submit-intent-abc123"
    s1 = _start_queued(gated_client, OWNER, headers={"Idempotency-Key": key})
    _mark_running(isolated_store, s1, OWNER)

    s2 = _start_queued(gated_client, OWNER, headers={"Idempotency-Key": key})

    assert s2 == s1, "idempotent replay should return the original scan"
    assert isolated_store.get_scan(s1, owner=OWNER)["run"]["status"] == "running", (
        "an idempotent retry superseded the scan it was returning to the caller")


def test_a_failure_to_stop_the_prior_run_does_not_fail_an_accepted_scan(gated_client,
                                                                        isolated_store,
                                                                        monkeypatch):
    """Once enqueue_scan has committed, the scan exists. Raising out of the tidy-up afterwards
    would report a failed submission that in fact succeeded — and the retry it invites enqueues
    a genuine duplicate."""
    s1 = _start_queued(gated_client, OWNER)
    _mark_running(isolated_store, s1, OWNER)

    from psycopg2.pool import PoolError

    def _exhausted(*a, **kw):
        raise PoolError("connection pool exhausted")

    monkeypatch.setattr(isolated_store, "supersede_scan", _exhausted)

    r = gated_client(OWNER).post("/scans?source=local&queue=true&fanout=true")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["queued"] is True and body["scan_id"] and body["job_id"]
    # And the identifiers handed back are real, not a hopeful echo.
    assert isolated_store.get_scan(body["scan_id"], owner=OWNER) is not None
