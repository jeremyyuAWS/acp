"""A worker that dies holding a job leaves no trace, and the run goes on looking untouched.

MEASURED IN PRODUCTION, 2026-08-31, scan 128d4bf609b4:

    06:17:15  worker w8 claimed attempt 1
    06:19:13  worker logged `double free or corruption (!prev)`
    06:19:14  Azure recorded termination, exit code 139
    06:27:09  worker w6 claimed the SAME job, attempt 2

Eight minutes, and no surface anywhere said so.

WHY THE SILENCE IS TOTAL. A process killed by the OS runs no code on the way out — no `except`,
no `finally`, no `on_retry` hook. The graceful failure path emits `scan.retrying` carrying the
attempt number (worker.py), and routes/scans.py threads `attempt` out of scan_events and NOWHERE
ELSE. So for a crash there is no event, therefore no attempt, therefore nothing for the UI to
render but the ordinary in-progress checklist it was already showing.

And it does not end when the job restarts: `claim_job` sets `phase=NULL` on every claim, so the
moment attempt 2 begins it is byte-for-byte indistinguishable from attempt 1.

WHAT WAS ALREADY THERE. `scan.interrupted` was already in SCAN_EVENT_KINDS, and
frontend/src/scanHistory.js already maps it to "Interrupted" and counts it among the BAD
outcomes. The vocabulary and the reader both existed. Only the emitter was missing — so this is
wiring, not invention.

WHY NOT REUSE 'retrying'. It would have rendered the existing card, and the card says "a previous
attempt failed — waiting to retry". Nothing failed. The worker died. Telling an operator that a
handler raised, when the process segfaulted, sends them to the wrong logs.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "crash.db")
    return store_mod.Store()


def _claimed_job_with_expired_lease(st, sid="s-crash", worker="w8"):
    """A job held by a worker that is never coming back — the state a SIGSEGV leaves behind."""
    st.init_scan_run(sid, "drive", 1, "2026-08-31T00:00:00Z", "r", "h",
                     owner="demo@example.com", status="running")
    jid = st.enqueue_job("scan_discover", {"scan_id": sid}, scan_id=sid)
    job = st.claim_job(worker)
    assert job and job["id"] == jid
    # The handler had got somewhere before the process died.
    st.set_job_phase(jid, "discovering")
    with st._db.cursor() as cur:                      # expire the lease, as time would
        st._db.execute(cur,
            "UPDATE jobs SET lease_expires_at=%s, locked_at=%s WHERE id=%s",
            ("1970-01-01T00:00:00+00:00", "1970-01-01T00:00:00+00:00", jid))
    return sid, jid


def _events(st, sid):
    for name in ("list_scan_events", "get_scan_events", "scan_events"):
        fn = getattr(st, name, None)
        if callable(fn):
            try:
                return fn(sid) or []
            except TypeError:
                continue
    with st._db.cursor() as cur:                      # fall back to the table itself
        st._db.execute(cur, "SELECT kind, attempt, phase, worker_id, job_id FROM scan_events "
                            "WHERE scan_id=%s ORDER BY seq", (sid,))
        return st._db.fetchall(cur) or []


# ── the reclaim itself still works ────────────────────────────────────────────────────────────

def test_the_job_is_still_requeued(st):
    """The control. Narrating the interruption must not change whether the job comes back — that
    recovery is the one thing that was already working."""
    _sid, jid = _claimed_job_with_expired_lease(st)
    assert st.reclaim_stuck_jobs() == 1
    job = st.get_job(jid)
    assert job["status"] == "queued"
    assert job["locked_by"] is None


# ── …and now it says so ───────────────────────────────────────────────────────────────────────

def test_the_waiting_job_says_it_was_interrupted_rather_than_still_working(st):
    """THE regression. Before this the row kept `phase='discovering'` — the last thing the dead
    worker wrote — so every reader saw a job that was actively discovering. It was not; it was
    lying on the floor waiting for a sweeper."""
    _sid, jid = _claimed_job_with_expired_lease(st)
    st.reclaim_stuck_jobs()
    assert st.get_job(jid)["phase"] == "reclaimed", (
        "the reclaimed job still reports the phase its dead worker last wrote — a reader cannot "
        "tell it apart from a job that is genuinely mid-discovery")


def test_an_interrupted_event_carries_the_attempt_into_the_stream(st):
    """`attempt` reaches the UI only through scan_events (routes/scans.py). No event, no attempt,
    no way to say 'attempt 2'."""
    sid, jid = _claimed_job_with_expired_lease(st, worker="w8")
    st.reclaim_stuck_jobs()

    rows = [e for e in _events(st, sid) if e.get("kind") == "scan.interrupted"]
    assert len(rows) == 1, f"expected exactly one scan.interrupted, got {_events(st, sid)}"
    ev = rows[0]
    assert ev.get("attempt") == 1, "the attempt that died is not on the event"
    assert ev.get("worker_id") == "w8", "the event does not name the worker that stopped"
    assert ev.get("job_id") == jid


def test_it_names_the_worker_that_died_not_the_one_that_takes_over(st):
    """The whole point of the event is forensic: which process stopped. Reading locked_by AFTER
    the UPDATE would clear it to NULL, and reading it after the next claim would name the
    innocent replacement."""
    sid, _jid = _claimed_job_with_expired_lease(st, worker="w8")
    st.reclaim_stuck_jobs()
    st.claim_job("w6")                                 # the replacement picks it up
    ev = [e for e in _events(st, sid) if e.get("kind") == "scan.interrupted"][0]
    assert ev.get("worker_id") == "w8"


def test_a_second_sweep_does_not_narrate_the_same_interruption_twice(st):
    """The sweeper runs every tick. Only rows it actually reclaims may produce an event, or an
    incident view fills with duplicates of one crash."""
    sid, _jid = _claimed_job_with_expired_lease(st)
    assert st.reclaim_stuck_jobs() == 1
    assert st.reclaim_stuck_jobs() == 0
    assert len([e for e in _events(st, sid) if e.get("kind") == "scan.interrupted"]) == 1


def test_a_healthy_running_job_is_untouched_and_unnarrated(st):
    """A job whose lease is alive is not interrupted, and must not be described as though it
    were — this sweeper runs constantly against a queue that is mostly fine."""
    sid = "s-healthy"
    st.init_scan_run(sid, "drive", 1, "2026-08-31T00:00:00Z", "r", "h", status="running")
    st.enqueue_job("scan_discover", {"scan_id": sid}, scan_id=sid)
    job = st.claim_job("w1")
    st.set_job_phase(job["id"], "discovering")

    assert st.reclaim_stuck_jobs() == 0
    assert st.get_job(job["id"])["phase"] == "discovering", "a live job's phase was overwritten"
    assert [e for e in _events(st, sid) if e.get("kind") == "scan.interrupted"] == []


# ── the narration must never cost the recovery ────────────────────────────────────────────────

def test_the_job_is_reclaimed_even_if_the_event_write_fails(st, monkeypatch):
    """Narration is best-effort and the ORDER encodes that: the UPDATE lands first, the event is
    attempted after. A telemetry failure that stranded a job in 'running' would turn a crash into
    a permanent stall — strictly worse than the silence this replaces."""
    _sid, jid = _claimed_job_with_expired_lease(st)

    def _boom(*a, **k):
        raise RuntimeError("scan_events is unavailable")

    monkeypatch.setattr(st, "append_scan_event", _boom)
    assert st.reclaim_stuck_jobs() == 1
    assert st.get_job(jid)["status"] == "queued", (
        "a failed event write prevented the job from being reclaimed")


def test_a_job_with_no_scan_id_reclaims_without_an_event(st):
    """Not every job belongs to a scan; scan_events is scan-anchored and append_scan_event raises
    on a missing scan_id. Such a job must still be recovered."""
    jid = st.enqueue_job("housekeeping", {})
    st.claim_job("w1")
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "UPDATE jobs SET lease_expires_at=%s, locked_at=%s WHERE id=%s",
            ("1970-01-01T00:00:00+00:00", "1970-01-01T00:00:00+00:00", jid))
    assert st.reclaim_stuck_jobs() == 1
    assert st.get_job(jid)["status"] == "queued"


# ── the waiting state must not read as stalled ────────────────────────────────────────────────

def test_a_reclaimed_job_is_not_also_reported_as_stalled():
    """core._job_is_stale exempts 'retrying' because a job sitting out a backoff has no worker
    and so no heartbeat. A reclaimed job is in exactly that position — nothing holds it — so
    without the same exemption the UI would stack a "stalled" warning on top of the interruption
    notice and describe one event twice."""
    import core
    assert core._job_is_stale({"phase": "reclaimed", "updated_at": None}) is False
    assert core._job_is_stale({"phase": "retrying", "updated_at": None}) is False
    # The control: an ordinary phase with no liveness signal IS stale, or the exemption above
    # would be indistinguishable from the check being switched off.
    assert core._job_is_stale({"phase": "discovering", "updated_at": None}) is True
