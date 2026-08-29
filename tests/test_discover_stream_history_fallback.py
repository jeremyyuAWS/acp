"""The discover stream's not-live fallback frame, filled from the durable lifecycle log
(ADR 0042 PR 4 of 4).

WHAT THIS PR ACTUALLY CLOSES. `test_discover_stream_checkpoint_fallback.py` already covers the
case where `scan_runs.live_checkpoint` exists. The gap was the case where it does NOT:
`core._maybe_checkpoint` flushes on a phase/done/error transition or every 20s, so a job whose
replica died inside its first seconds has no checkpoint at all — and the stream sent the terminal
error with no data frame before it, leaving an empty panel on a run that demonstrably started.
`scan_events` has rows for exactly that run. This is the whole behaviour change.

WHAT DID NOT CHANGE, and these are re-asserted here rather than assumed, because this is the file
with four fixes behind it:
  * still ONE frame, still `live: false`, still followed by the SAME `event: error` and close.
  * `event: done` and `event: error` both still mean "the stream ended" — the 2026-08-26 fix
    documented in frontend/src/api.js. No new terminal state, no new frame type.
  * no checkpoint AND no events still emits no frame at all (the existing regression test in
    test_discover_stream_checkpoint_fallback.py asserts this and is deliberately left untouched).
  * `seq`, `done` and `error` are never synthesized — see the helper's docstring for why each
    would be actively harmful, particularly `seq` against liveJobStateGuard.js.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "jeremyyu.movate@gmail.com"


# ── the pure frame builder ────────────────────────────────────────────────────

def _frame(checkpoint, checkpoint_at, events):
    from routes.scans import _discover_fallback_frame
    return _discover_fallback_frame(checkpoint, checkpoint_at, events)


def _ev(seq, kind, *, phase=None, attempt=None, detail=None, at=None):
    return {"seq": seq, "kind": kind, "phase": phase, "attempt": attempt,
            "detail": detail, "occurred_at": at or f"2026-08-29T09:0{seq}:00+00:00"}


def test_nothing_to_say_returns_no_frame():
    """The premise the existing regression test guards: a run with neither a checkpoint nor
    events must not have one fabricated for it."""
    assert _frame(None, None, []) is None
    assert _frame({}, None, []) is None


def test_a_checkpoint_alone_behaves_exactly_as_before():
    frame = _frame({"phase": "lifecycle", "files_evaluated": 40}, "2026-08-29T09:00:00Z", [])
    assert frame == {"phase": "lifecycle", "files_evaluated": 40,
                     "live": False, "checkpoint_at": "2026-08-29T09:00:00Z"}


def test_events_alone_produce_a_frame_where_there_was_none():
    """THE behaviour change. A run that died before its first checkpoint flush now has something
    honest to show instead of an empty panel."""
    frame = _frame(None, None, [
        _ev(1, "scan.queued", phase="queued"),
        _ev(2, "scan.claimed", phase="queued", attempt=1),
        _ev(3, "scan.listing_started", phase="discovering", attempt=1),
        _ev(4, "scan.listing_complete", phase="discovering", attempt=1,
            detail={"files_found": 4100}, at="2026-08-29T09:04:00+00:00"),
    ])
    assert frame["phase"] == "discovering", "the phase the run actually reached"
    assert frame["files_found"] == 4100
    assert frame["attempt"] == 1
    assert frame["live"] is False
    assert frame["checkpoint_at"] == "2026-08-29T09:04:00+00:00", (
        "with no checkpoint the frame is as-of the last EVENT, so 'last known state, Ns ago' "
        "measures the instant the frame was actually built from")


def test_the_checkpoint_wins_wherever_it_speaks():
    """Events FILL gaps; they never overwrite. The checkpoint is accumulated job state and is
    strictly richer than an event row, so letting the coarser source win would make the frame
    worse than it was before this PR."""
    frame = _frame({"phase": "saving", "files_found": 4100}, "2026-08-29T09:09:00Z", [
        _ev(1, "scan.listing_complete", phase="discovering", detail={"files_found": 7}),
    ])
    assert frame["phase"] == "saving"
    assert frame["files_found"] == 4100
    assert frame["checkpoint_at"] == "2026-08-29T09:09:00Z", "the checkpoint's own stamp is kept"


def test_events_fill_only_the_fields_the_checkpoint_lacks():
    frame = _frame({"files_evaluated": 40}, "2026-08-29T09:09:00Z", [
        _ev(1, "scan.lifecycle_applied", phase="lifecycle", attempt=2),
    ])
    assert frame["files_evaluated"] == 40          # from the checkpoint
    assert frame["phase"] == "lifecycle"           # filled from the event
    assert frame["attempt"] == 2


def test_the_newest_event_wins_among_events():
    frame = _frame(None, None, [
        _ev(1, "scan.listing_started", phase="discovering"),
        _ev(2, "scan.inventory_saved", phase="saving"),
    ])
    assert frame["phase"] == "saving"


def test_files_found_is_never_invented_from_an_event_that_did_not_count():
    """`detail` is per-kind narration. A missing key means the event never knew the number —
    which is not the same as zero, and a fabricated 0 on a run that listed thousands would be
    the most misleading thing this frame could say."""
    frame = _frame(None, None, [_ev(1, "scan.claimed", phase="queued", detail={"source": "drive"})])
    assert "files_found" not in frame


def test_seq_done_and_error_are_never_synthesized():
    """Each would be actively harmful:
      seq   — liveJobStateGuard.js compares it against Redis's HINCRBY counter; an invented one
              would suppress this frame or a real later one.
      done  — would end the client's progress UI on a run that merely lost its replica.
      error — the terminal `event: error` already says the stream ended; an error IN the data
              frame would make a recoverable gap read as a failed scan.
    """
    frame = _frame(None, None, [
        _ev(1, "scan.claimed", phase="queued", attempt=1),
        _ev(2, "scan.failed", phase="error", attempt=1, detail={"reason": "listing_failed"}),
    ])
    assert "seq" not in frame
    assert "done" not in frame
    assert "error" not in frame
    assert frame["phase"] == "error", "the PHASE may say error — that is the run's own recorded phase"


def test_a_checkpoint_carrying_done_still_carries_it():
    """The rule is that nothing is SYNTHESIZED, not that these keys are stripped: a checkpoint
    that genuinely recorded done=True keeps it, exactly as before this PR."""
    frame = _frame({"phase": "done", "done": True}, "2026-08-29T09:09:00Z", [])
    assert frame["done"] is True


# ── through the real endpoint ─────────────────────────────────────────────────

@pytest.fixture()
def gated_client(monkeypatch, isolated_store):
    """Same shape as test_discover_stream_checkpoint_fallback.py's fixture."""
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
    # No job is ever claimed for these scans, so the stream falls through to the fallback.
    monkeypatch.setattr(core, "get_job_id_for_scan", lambda scan_id: None)

    client = TestClient(app)

    def as_user(email):
        client.headers.update({"Authorization": f"Bearer {email}"})
        return client

    return as_user


def _seed_run(store, sid):
    store.init_scan_run(sid, "drive", total=10,
                        started_at=datetime.now(timezone.utc).isoformat(),
                        rubric_name="r", rubric_hash="h", owner=OWNER, status="running")


def test_a_run_with_events_but_no_checkpoint_now_gets_a_frame(gated_client, isolated_store):
    """The empty panel this PR exists to close, end to end."""
    _seed_run(isolated_store, "s-hist1")
    isolated_store.append_scan_event("s-hist1", "scan.claimed", phase="queued",
                                     job_id="j1", attempt=1, owner_email=OWNER)
    isolated_store.append_scan_event("s-hist1", "scan.listing_complete", phase="discovering",
                                     job_id="j1", attempt=1, owner_email=OWNER,
                                     detail={"files_found": 4100})

    with gated_client(OWNER).stream("GET", "/scans/s-hist1/discover/stream") as r:
        assert r.status_code == 200
        body = "".join(r.iter_text())

    assert '"phase": "discovering"' in body or '"phase":"discovering"' in body
    assert '"files_found": 4100' in body or '"files_found":4100' in body
    assert '"live": false' in body or '"live":false' in body
    assert body.count("data:") == 2, (
        f"still exactly ONE data frame plus the terminal error's own data line: {body!r}")
    assert "event: error" in body, "and it still ends in the same terminal error as before"
    assert "event: done" not in body


def test_the_checkpoint_frame_is_unchanged_when_events_add_nothing(gated_client, isolated_store):
    """The pre-existing path must behave exactly as it did — a run with both a checkpoint and
    events gets one frame, and the checkpoint's own values survive."""
    _seed_run(isolated_store, "s-hist2")
    at = datetime.now(timezone.utc).isoformat()
    isolated_store.checkpoint_scan_progress("s-hist2", {"phase": "lifecycle",
                                                        "files_evaluated": 40}, at)
    isolated_store.append_scan_event("s-hist2", "scan.listing_started", phase="discovering",
                                     owner_email=OWNER)

    with gated_client(OWNER).stream("GET", "/scans/s-hist2/discover/stream") as r:
        body = "".join(r.iter_text())

    assert '"phase": "lifecycle"' in body or '"phase":"lifecycle"' in body, (
        "the event's older 'discovering' must not have overwritten the checkpoint's phase")
    assert '"files_evaluated": 40' in body or '"files_evaluated":40' in body
    assert body.count("data:") == 2
    assert "event: error" in body


def test_a_broken_event_log_does_not_cost_the_checkpoint_frame(gated_client, isolated_store,
                                                               monkeypatch):
    """Best-effort, in the direction that matters: reading the log must never lose the client a
    frame it would have had without this PR at all."""
    _seed_run(isolated_store, "s-hist3")
    at = datetime.now(timezone.utc).isoformat()
    isolated_store.checkpoint_scan_progress("s-hist3", {"phase": "lifecycle"}, at)

    def _boom(*a, **kw):
        raise RuntimeError("the event log is on fire")

    monkeypatch.setattr(isolated_store, "list_scan_events", _boom)

    with gated_client(OWNER).stream("GET", "/scans/s-hist3/discover/stream") as r:
        assert r.status_code == 200
        body = "".join(r.iter_text())

    assert '"phase": "lifecycle"' in body or '"phase":"lifecycle"' in body
    assert "event: error" in body


def test_ownership_is_still_the_gate_and_a_foreign_scan_404s(gated_client, isolated_store):
    """PR 3's lesson in the other direction: the events read passes no owner filter, so the
    get_scan gate is the ONLY thing standing between a foreign caller and this run's history.
    It still 404s — and a 404, not a 403, so a scan id is not an existence oracle."""
    _seed_run(isolated_store, "s-hist4")
    isolated_store.append_scan_event("s-hist4", "scan.claimed", phase="queued", owner_email=OWNER)

    r = gated_client("someone-else@example.com").get("/scans/s-hist4/discover/stream")
    assert r.status_code == 404


def test_the_owners_own_pre_owner_events_still_fill_the_frame(gated_client, isolated_store):
    """A run's earliest events carry owner_email=NULL. They are exactly the rows that explain a
    scan which died before it started, so the fallback must still see them."""
    _seed_run(isolated_store, "s-hist5")
    isolated_store.append_scan_event("s-hist5", "scan.claimed", phase="queued")   # no owner yet

    with gated_client(OWNER).stream("GET", "/scans/s-hist5/discover/stream") as r:
        body = "".join(r.iter_text())

    assert '"phase": "queued"' in body or '"phase":"queued"' in body, (
        "a NULL-owner event was dropped — the fallback is filtering by owner it must not")
    assert '"live": false' in body or '"live":false' in body
