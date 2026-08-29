"""GET /scans/{sid}/history — the durable run-history read surface (ADR 0042, PR 3 of 4).

The run-level counterpart to /scans/{sid}/timeline, which answers the same question about one
document. What these pin:

  * OWNER SCOPING IS THE get_scan GATE, and it must NOT also be list_scan_events' own `owner`
    filter. Events written before an owner is known carry owner_email=NULL — the thread path mints
    a scan_id before it has a user — so double-filtering would silently drop the queued/claimed
    rows that explain a stuck scan, from its rightful owner. That is a subtle wrong-direction bug
    (it hides data rather than leaking it), so it gets its own test rather than being trusted to
    the route's comment.
  * ALWAYS 200. A supplementary narration panel must not break a run-detail screen, so an unknown
    or foreign scan degrades to {"available": false} like /live and /status — never a 404 and
    never a 500.
  * after_seq IS EXCLUSIVE, and `latest_seq` is the cursor for the next call.
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
    """A scan owned by `owner` — "demo" is _owner()'s unauthenticated default, so the route
    resolves it without an auth header."""
    st.init_scan_run(sid, "drive", 1, "2026-08-29T00:00:00Z", "default", "rh",
                     owner=owner, status="discovered")


# ── the happy path ────────────────────────────────────────────────────────────

def test_returns_the_runs_events_oldest_first(client, isolated_store):
    _seed(isolated_store, "s1")
    for kind in ("scan.queued", "scan.claimed", "scan.discovered"):
        isolated_store.append_scan_event("s1", kind, owner_email="demo")

    body = client.get("/scans/s1/history").json()
    assert body["available"] is True
    assert body["scan_id"] == "s1"
    assert [e["kind"] for e in body["events"]] == [
        "scan.queued", "scan.claimed", "scan.discovered"]
    assert [e["seq"] for e in body["events"]] == [1, 2, 3]
    assert body["count"] == 3
    assert body["latest_seq"] == 3, "the cursor for the next call"


def test_detail_comes_back_as_an_object_not_a_json_string(client, isolated_store):
    _seed(isolated_store, "s1")
    isolated_store.append_scan_event("s1", "scan.listing_complete", owner_email="demo",
                                     detail={"files_found": 4100, "truncated": False})

    (event,) = client.get("/scans/s1/history").json()["events"]
    assert event["detail"] == {"files_found": 4100, "truncated": False}


# ── the subtle one: owner scoping must not double-filter ─────────────────────

def test_the_owners_own_pre_owner_events_are_returned(client, isolated_store):
    """The bug this route's comment exists to prevent, asserted rather than trusted.

    A run's earliest events can carry owner_email=NULL, because the thread path assigns a scan_id
    before it knows the user. Passing `owner=` to list_scan_events would drop exactly those rows —
    the queued/claimed pair that explains a scan stuck before it ever started — for the very user
    entitled to see them. The get_scan gate above is the access check; this filter is not.
    """
    _seed(isolated_store, "s1")
    isolated_store.append_scan_event("s1", "scan.queued")                       # no owner yet
    isolated_store.append_scan_event("s1", "scan.claimed", owner_email="demo")

    kinds = [e["kind"] for e in client.get("/scans/s1/history").json()["events"]]
    assert kinds == ["scan.queued", "scan.claimed"], (
        "the owner's own pre-owner events were dropped — the route is double-filtering")


def test_another_owners_scan_is_not_readable(client, isolated_store):
    _seed(isolated_store, "s-theirs", owner="someone-else@x")
    isolated_store.append_scan_event("s-theirs", "scan.queued", owner_email="someone-else@x")

    body = client.get("/scans/s-theirs/history").json()
    assert body["available"] is False
    assert body["reason"] == "scan_not_found", (
        "a foreign scan must be indistinguishable from a missing one — a scan id must not be "
        "usable as an existence oracle across accounts")
    assert "events" not in body


# ── always 200 ────────────────────────────────────────────────────────────────

def test_unknown_scan_degrades_rather_than_404ing(client):
    r = client.get("/scans/never-existed/history")
    assert r.status_code == 200, "a narration panel must not break the screen around it"
    assert r.json() == {"available": False, "reason": "scan_not_found"}


def test_a_run_with_no_events_is_available_but_empty(client, isolated_store):
    """Distinct from the unavailable case above, and the distinction is the point: a run that
    predates ADR 0042 exists and has no history, which is not the same as a run you cannot see."""
    _seed(isolated_store, "s-old")
    body = client.get("/scans/s-old/history").json()
    assert body["available"] is True
    assert body["events"] == []
    assert body["count"] == 0
    assert body["latest_seq"] is None, (
        "an empty page must not report latest_seq=0 — 0 is a real cursor meaning 'from the "
        "start', so a caught-up client would re-request the whole history every poll")


# ── the cursor ────────────────────────────────────────────────────────────────

def test_after_seq_is_exclusive_and_returns_only_what_was_missed(client, isolated_store):
    _seed(isolated_store, "s1")
    for kind in ("scan.queued", "scan.claimed", "scan.listing_started", "scan.discovered"):
        isolated_store.append_scan_event("s1", kind, owner_email="demo")

    body = client.get("/scans/s1/history?after_seq=2").json()
    assert [e["seq"] for e in body["events"]] == [3, 4], "after_seq=2 means 2 was already seen"
    assert body["latest_seq"] == 4

    caught_up = client.get("/scans/s1/history?after_seq=4").json()
    assert caught_up["events"] == [] and caught_up["latest_seq"] is None


def test_limit_is_honoured_and_bounded(client, isolated_store):
    _seed(isolated_store, "s1")
    for _ in range(5):
        isolated_store.append_scan_event("s1", "scan.retrying", owner_email="demo")

    body = client.get("/scans/s1/history?limit=2").json()
    assert [e["seq"] for e in body["events"]] == [1, 2], "the limit takes the oldest"
    assert body["latest_seq"] == 2, "so the cursor resumes from the page, not the tail"
    # The route caps the limit rather than letting a caller ask for the whole table.
    assert client.get("/scans/s1/history?limit=99999").status_code == 422
    assert client.get("/scans/s1/history?after_seq=-1").status_code == 422
