"""`Last-Event-ID` resume on the remediation stream — ADR 0051.

ADR 0042 built the log and deferred this, calling it "genuinely the riskiest thing in this space:
it changes the reconnect *contract*, not just a frame." So these tests are mostly about the
contract's edges rather than the happy path: what the server does with a cursor it CANNOT honour.

The dangerous case is the quiet one. A cursor ahead of the log replays nothing, and "nothing to
replay" is byte-identical to "you are caught up" — a client would believe it had missed nothing.
That is why `_resume_plan` distinguishes them and why most of this file is about reconcile
reasons rather than about replayed rows.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "owner@example.com"
OTHER = "stranger@example.com"


@pytest.fixture()
def gated_client(monkeypatch, isolated_store):
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
    client = TestClient(app)

    def as_user(email):
        client.headers.update({"Authorization": f"Bearer {email}"})
        return client
    return as_user


# ── the decision function, tested without a stream ───────────────────────────

def _plan(monkeypatch, store, sid, cursor):
    import core
    import routes.scans as scans
    monkeypatch.setattr(core, "store", store)
    return scans._resume_plan(sid, cursor)


def test_no_cursor_is_a_first_connection_not_a_reconcile(monkeypatch, isolated_store):
    """The overwhelmingly common case, and it must not be treated as an error: a browser opening
    the tab has missed nothing and needs no backfill."""
    assert _plan(monkeypatch, isolated_store, "s1", None) == (None, None)
    assert _plan(monkeypatch, isolated_store, "s1", "") == (None, None)
    assert _plan(monkeypatch, isolated_store, "s1", "   ") == (None, None)


def test_a_cursor_ahead_of_the_log_reconciles_rather_than_replaying_nothing(
        monkeypatch, isolated_store):
    """THE DANGEROUS CASE. Replaying "everything after 99" against a 3-event log returns [], which
    on the wire is indistinguishable from "you are caught up" — the client would believe it had
    missed nothing when in fact its cursor belongs to another scan or to rows that are gone."""
    for _ in range(3):
        isolated_store.append_scan_event("s-ahead", "remediate.fix_applied", owner_email=OWNER)
    assert _plan(monkeypatch, isolated_store, "s-ahead", "99") == (None, "cursor_ahead_of_log")
    # ...and the boundary is inclusive: a cursor AT the newest seq is caught up, not ahead.
    assert _plan(monkeypatch, isolated_store, "s-ahead", "3") == (3, None)


def test_a_cursor_against_an_empty_log_reconciles(monkeypatch, isolated_store):
    assert _plan(monkeypatch, isolated_store, "s-empty", "1") == (None, "no_events")


def test_a_malformed_cursor_reconciles_rather_than_being_guessed_at(monkeypatch, isolated_store):
    isolated_store.append_scan_event("s-bad", "remediate.accepted", owner_email=OWNER)
    for junk in ("abc", "1.5", "', 'x", "-1", "1e3"):
        after, reason = _plan(monkeypatch, isolated_store, "s-bad", junk)
        assert (after, reason) == (None, "malformed_cursor"), junk


def test_a_usable_cursor_replays_from_it(monkeypatch, isolated_store):
    for _ in range(5):
        isolated_store.append_scan_event("s-ok", "remediate.fix_applied", owner_email=OWNER)
    assert _plan(monkeypatch, isolated_store, "s-ok", "2") == (2, None)
    assert _plan(monkeypatch, isolated_store, "s-ok", "0") == (0, None)


def test_the_pruned_branch_is_written_even_though_nothing_prunes_yet(monkeypatch, isolated_store):
    """Retention is DECIDED (PRD §22: 24h or 10,000 events per run) and NOT IMPLEMENTED — nothing
    deletes scan_events today, so this condition cannot fire in production.

    It is tested by constructing the state pruning would leave behind, because the day retention
    lands is the day resume would otherwise start losing events silently, in exactly the window
    where nobody is looking for it.
    """
    for _ in range(5):
        isolated_store.append_scan_event("s-pruned", "remediate.fix_applied", owner_email=OWNER)
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur, "DELETE FROM scan_events WHERE scan_id=%s AND seq<=%s",
                                   ("s-pruned", 3))
    assert isolated_store.scan_event_bounds("s-pruned") == (4, 5)
    # A cursor of 1 needs events 2..5; 2 and 3 are gone, so it cannot be honoured.
    assert _plan(monkeypatch, isolated_store, "s-pruned", "1") == (None, "events_pruned")
    # A cursor of 3 needs 4..5, both of which survive — replayable, not a gap.
    assert _plan(monkeypatch, isolated_store, "s-pruned", "3") == (3, None)


# ── bounds ───────────────────────────────────────────────────────────────────

def test_bounds_of_an_empty_log_are_not_zero(isolated_store):
    """(None, None) is "this scan has no events"; (0, 0) would be a real range containing a real
    seq. Returning zeroes here would make an empty log look replayable from the start."""
    assert isolated_store.scan_event_bounds("s-none") == (None, None)


def test_bounds_never_raise_on_an_unreadable_log(isolated_store, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("db is down")
    monkeypatch.setattr(isolated_store._db, "cursor", _boom)
    assert isolated_store.scan_event_bounds("s-any") == (None, None)


# ── the wire ─────────────────────────────────────────────────────────────────

def _frames(text: str) -> list[dict]:
    """Parse an SSE body into {event, id, data} dicts — the server's half of what the browser's
    parseSSEFrames does, so the two can be asserted against the same shape."""
    out = []
    for block in text.split("\n\n"):
        if not block.strip() or block.startswith(":"):
            continue
        frame = {"event": "message", "id": None, "data": None}
        for line in block.split("\n"):
            if line.startswith("event:"):
                frame["event"] = line[6:].strip()
            elif line.startswith("id:"):
                frame["id"] = line[3:].strip()
            elif line.startswith("data:"):
                frame["data"] = line[5:].strip()
        if frame["data"] is not None:
            out.append(frame)
    return out


def test_a_stranger_cannot_resume_someone_elses_stream(gated_client, isolated_store):
    sid, _ = isolated_store.enqueue_scan("s-res-owner", "local", OWNER, "scan_discover", {})
    r = gated_client(OTHER).get(f"/scans/{sid}/remediation/stream",
                                headers={"Last-Event-ID": "1"})
    assert r.status_code == 404


def test_replayed_events_carry_their_seq_as_the_sse_id(gated_client, isolated_store):
    """`id:` is the whole mechanism — without it the client has nothing to send back next time."""
    sid, _ = isolated_store.enqueue_scan("s-res-replay", "local", OWNER, "scan_discover", {})
    for i in range(4):
        isolated_store.append_scan_event(sid, "remediate.fix_applied", owner_email=OWNER,
                                         detail={"file": f"{i}.docx"})
    with gated_client(OWNER).stream("GET", f"/scans/{sid}/remediation/stream",
                                    headers={"Last-Event-ID": "2"}) as r:
        assert r.status_code == 200
        body = ""
        for chunk in r.iter_text():
            body += chunk
            if "event: done" in body or body.count("\n\n") > 6:
                break
    events = [f for f in _frames(body) if f["event"] == "remediation-event"]
    assert [f["id"] for f in events] == ["3", "4"], body[:400]


def test_an_unhonourable_cursor_gets_a_reconciliation_frame_and_no_replay(
        gated_client, isolated_store):
    sid, _ = isolated_store.enqueue_scan("s-res-gap", "local", OWNER, "scan_discover", {})
    isolated_store.append_scan_event(sid, "remediate.accepted", owner_email=OWNER)
    with gated_client(OWNER).stream("GET", f"/scans/{sid}/remediation/stream",
                                    headers={"Last-Event-ID": "500"}) as r:
        body = ""
        for chunk in r.iter_text():
            body += chunk
            if "event: done" in body or body.count("\n\n") > 4:
                break
    frames = _frames(body)
    assert frames[0]["event"] == "reconciliation-required", body[:400]
    assert "cursor_ahead_of_log" in frames[0]["data"]
    assert not [f for f in frames if f["event"] == "remediation-event"]


def test_a_client_that_sends_no_cursor_gets_no_backfill(gated_client, isolated_store):
    """A browser that just opened the tab has missed nothing. Replaying a finished run's whole
    history to it is not a resume, it is a backfill nobody asked for — and it would make the
    activity feed's first paint a wall of old events."""
    sid, _ = isolated_store.enqueue_scan("s-res-fresh", "local", OWNER, "scan_discover", {})
    for i in range(6):
        isolated_store.append_scan_event(sid, "remediate.fix_applied", owner_email=OWNER,
                                         detail={"file": f"{i}.docx"})
    with gated_client(OWNER).stream("GET", f"/scans/{sid}/remediation/stream") as r:
        body = ""
        for chunk in r.iter_text():
            body += chunk
            if "event: done" in body or body.count("\n\n") > 4:
                break
    assert not [f for f in _frames(body) if f["event"] == "remediation-event"], body[:400]


def test_the_snapshot_frame_is_unchanged_for_a_client_that_ignores_all_of_this(
        gated_client, isolated_store):
    """The rollout-safety property. The shipped progress bar consumes the default `message` frame;
    resume is additive on the wire, so a client that knows nothing about it is unaffected."""
    sid, _ = isolated_store.enqueue_scan("s-res-compat", "local", OWNER, "scan_discover", {})
    with gated_client(OWNER).stream("GET", f"/scans/{sid}/remediation/stream") as r:
        body = ""
        for chunk in r.iter_text():
            body += chunk
            if "event: done" in body:
                break
    import json as _json
    snapshots = [f for f in _frames(body) if f["event"] == "message"]
    assert snapshots, body[:400]
    payload = _json.loads(snapshots[0]["data"])
    for key in ("in_flight", "queued", "running", "failed", "activity", "workers", "snapshot"):
        assert key in payload, key
