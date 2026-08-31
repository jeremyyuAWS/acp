"""The worker emits a claim line before the handler runs, and one outcome line after.

The 2026-08-30 incident: the worker tier segfaulted (exit 139, after glibc heap corruption), and
which job — let alone which document — was open could not be recovered, because worker.py printed
a job id in only two places, a lease-overrun warning and a generic loop error, neither of which
fires on a native crash.

The claim line is the floor: it is flushed before any handler code runs, so it survives a crash
that emits nothing afterwards. The outcome lines are what make the claim line *useful* — a claim
with no outcome is a job that was open when the process died, and without outcomes every job ever
claimed would look open.

`job.dead` vs `job.retry` matters on its own: attempts-exhausted is the terminal state the
sweeper reached for db40880c03de4b89, and an operator reading the log must be able to see that
automatic retries have STOPPED without going to the database for it.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "claimlog.db")
    return store_mod.Store()


@pytest.fixture()
def lines(monkeypatch):
    """Collect what joblog emitted, without going through stdout capture — the assertions here
    are about WHICH records appear and in what order, not about flushing (that is
    test_joblog_diagnostics.py's job)."""
    import joblog
    out = []
    monkeypatch.setattr(joblog, "emit",
                        lambda event, **f: out.append({"event": event, **f}))
    return out


def _run_one(st, job_type, handler, lines):
    import worker as worker_mod
    worker_mod.HANDLERS[job_type] = handler
    try:
        w = worker_mod.JobWorker(st, worker_id="worker-test")
        return w.run_once()
    finally:
        worker_mod.HANDLERS.pop(job_type, None)


def test_the_claim_line_is_emitted_before_the_handler_runs(st, lines):
    """Ordering is the whole point: a handler that segfaults emits nothing itself, so the claim
    line has to already be out."""
    seen_inside = []

    def handler(payload, job):
        seen_inside.extend(r["event"] for r in lines)

    st.enqueue_job("t_claim", {"k": "v"})
    _run_one(st, "t_claim", handler, lines)

    assert seen_inside == ["job.claim"], (
        f"the claim must be recorded before handler code runs; handler saw {seen_inside}")


def test_the_claim_line_carries_what_a_crash_investigation_needs(st, lines):
    sid = st.create_scan_run(owner_email="a@b.c") if hasattr(st, "create_scan_run") else None
    jid = st.enqueue_job("t_fields", {"k": "v"})
    _run_one(st, "t_fields", lambda p, j: None, lines)

    claim = [r for r in lines if r["event"] == "job.claim"][0]
    assert claim["job_id"] == jid
    assert claim["job_type"] == "t_fields"
    assert claim["worker_id"] == "worker-test"
    assert claim["attempt"] >= 1, "attempt distinguishes a first try from a retry of the same job"
    assert "scan_id" in claim or sid is None


def test_a_successful_job_records_an_outcome(st, lines):
    st.enqueue_job("t_ok", {})
    _run_one(st, "t_ok", lambda p, j: None, lines)
    assert [r["event"] for r in lines] == ["job.claim", "job.complete"], (
        "without a paired outcome, every job ever claimed reads as still open")


def test_a_retryable_failure_records_a_retry_not_a_death(st, lines):
    def boom(payload, job):
        raise RuntimeError("transient")

    st.enqueue_job("t_retry", {})
    _run_one(st, "t_retry", boom, lines)
    events = [r["event"] for r in lines]
    assert events[0] == "job.claim"
    assert "job.retry" in events, f"a first transient failure retries; saw {events}"
    assert "job.dead" not in events


def test_attempts_exhausted_records_a_death_so_the_log_shows_retries_stopped(st, lines):
    def boom(payload, job):
        raise RuntimeError("still failing")

    jid = st.enqueue_job("t_dead", {}, max_attempts=1)
    _run_one(st, "t_dead", boom, lines)

    events = [r["event"] for r in lines]
    assert "job.dead" in events, (
        f"attempts-exhausted must be distinguishable from a retry in the log alone; saw {events}")
    assert st.get_job(jid)["status"] == "dead"


def test_a_cancelled_job_records_a_cancellation(st, lines):
    import worker as worker_mod

    def cancel_midway(payload, job):
        raise worker_mod.JobCancelledError("stopped")

    st.enqueue_job("t_cancel", {})
    _run_one(st, "t_cancel", cancel_midway, lines)
    assert "job.cancelled" in [r["event"] for r in lines]


def test_no_payload_contents_reach_the_records(st, lines):
    """Payloads carry filenames, Drive ids and refresh tokens. None of them belong in a log
    stream whose audience and retention differ from the database's."""
    secret = "Q3-layoffs-confidential.docx"
    st.enqueue_job("t_leak", {"file": secret, "token": "ya29.SECRET"})
    _run_one(st, "t_leak", lambda p, j: None, lines)

    blob = json.dumps(lines)
    assert secret not in blob
    assert "ya29.SECRET" not in blob


def test_an_error_message_is_reduced_to_its_type(st, lines):
    """Exception text routinely quotes the path or URL that failed."""
    def boom(payload, job):
        raise RuntimeError("failed reading /tmp/Q3-layoffs-confidential.docx")

    st.enqueue_job("t_errtext", {})
    _run_one(st, "t_errtext", boom, lines)

    blob = json.dumps(lines)
    assert "Q3-layoffs" not in blob
    outcome = [r for r in lines if r["event"] in ("job.retry", "job.dead")][0]
    assert outcome["error_type"] == "RuntimeError"


# ── outcomes are read back, not assumed ───────────────────────────────────────────────────────

def test_the_outcome_record_reports_the_PERSISTED_status_not_the_attempted_one(st, lines):
    """"We called complete_job" is a statement about intent. The row is the statement about fact,
    and they can differ: fail_job dead-letters on attempts-exhausted of its own accord, and both
    mark_job_cancelled and complete_job are guarded against a zombie worker whose write the
    reclaim-race check suppresses."""
    st.enqueue_job("t_persist", {})
    _run_one(st, "t_persist", lambda p, j: None, lines)

    done = [r for r in lines if r["event"] == "job.complete"][0]
    assert done["status"] == "done", (
        f"the record must carry the status the row actually holds; saw {done.get('status')!r}")


def test_a_suppressed_completion_is_not_reported_as_done(st, lines, monkeypatch):
    """The zombie case, made concrete: complete_job's write is swallowed by the reclaim-race
    guard, so the row stays 'running'. Reporting 'done' here would put a false terminal state in
    the log — the exact class of error this re-read exists to prevent."""
    real = st.complete_job
    monkeypatch.setattr(st, "complete_job", lambda *a, **k: None)   # write suppressed
    st.enqueue_job("t_zombie", {})
    _run_one(st, "t_zombie", lambda p, j: None, lines)
    monkeypatch.setattr(st, "complete_job", real)

    done = [r for r in lines if r["event"] == "job.complete"][0]
    assert done["status"] != "done", (
        f"nothing persisted 'done', so the record must not claim it; saw {done.get('status')!r}")


# ── logging can never change what happens to a job ────────────────────────────────────────────

def test_a_logging_failure_cannot_change_a_job_outcome(st, monkeypatch):
    """A diagnostic that can fail a job is worse than no diagnostic. Every joblog call on the
    worker's path is made to raise; the job must still complete and the row must still say so."""
    import joblog
    monkeypatch.setattr(joblog, "emit",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("log backend down")))

    jid = st.enqueue_job("t_logfail", {})
    handled = _run_one(st, "t_logfail", lambda p, j: None, [])

    assert handled is True
    assert st.get_job(jid)["status"] == "done", (
        "a raising logger must not stop the job being completed and persisted")


def test_a_failing_status_read_does_not_break_the_job_or_invent_a_status(st, lines, monkeypatch):
    """The re-read added for persisted outcomes is itself on the job's path, so it gets the same
    treatment: when it cannot be done the record says so rather than asserting a status."""
    st.enqueue_job("t_readfail", {})

    import worker as worker_mod

    # Broken only AFTER the completion has persisted, so this isolates the re-read. get_job is
    # not private to the diagnostic — claim_job, complete_job and fail_job all call it — so
    # breaking it any earlier fails the claim or the completion and the test would be measuring
    # something else entirely. (Both earlier attempts did exactly that.)
    real_complete = st.complete_job

    def complete_then_break(*a, **k):
        result = real_complete(*a, **k)
        monkeypatch.setattr(st, "get_job",
                            lambda *a2, **k2: (_ for _ in ()).throw(RuntimeError("db gone")))
        return result

    monkeypatch.setattr(st, "complete_job", complete_then_break)
    worker_mod.HANDLERS["t_readfail"] = lambda p, j: None
    try:
        w = worker_mod.JobWorker(st, worker_id="worker-test")
        assert w.run_once() is True
    finally:
        worker_mod.HANDLERS.pop("t_readfail", None)

    done = [r for r in lines if r["event"] == "job.complete"][0]
    assert done["status"] == "unread"
