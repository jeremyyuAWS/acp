"""Durable cancellation (ADR 0004 step 4): cooperative cancel via cancel_requested_at.

Tests:
- request_job_cancellation() sets cancel_requested_at and returns True/False
- is_job_cancelled() reflects the flag
- mark_job_cancelled() moves status to 'cancelled'
- check_cancel() raises JobCancelledError when installed inside a worker turn
- Worker run_once() catches JobCancelledError → status='cancelled'
- Handler that finishes after cancel was requested → status='cancelled' (not 'done')
- Handler that calls check_cancel() mid-work is interrupted at that point
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

from conftest import held  # noqa: E402

import worker as w


class _Ex(Exception):
    pass


def _enqueue(st, **kw):
    return st.enqueue_job("test", {"x": 1}, **kw)


# ── request_job_cancellation ──────────────────────────────────────────────────

def test_request_cancellation_sets_flag(isolated_store):
    st = isolated_store
    jid = _enqueue(st)
    result = st.request_job_cancellation(jid)
    assert result is True
    job = st.get_job(jid)
    assert job["cancel_requested_at"] is not None


def test_request_cancellation_returns_true_for_running(isolated_store):
    st = isolated_store
    jid = _enqueue(st)
    st.claim_job("w1")
    assert st.request_job_cancellation(jid) is True


def test_request_cancellation_returns_false_when_already_set(isolated_store):
    st = isolated_store
    jid = _enqueue(st)
    st.request_job_cancellation(jid)
    assert st.request_job_cancellation(jid) is False


def test_request_cancellation_returns_false_for_done(isolated_store):
    st = isolated_store
    jid = _enqueue(st)
    st.claim_job("w1")
    st.complete_job(jid, **held(st, jid))
    assert st.request_job_cancellation(jid) is False


def test_request_cancellation_returns_false_for_dead(isolated_store):
    st = isolated_store
    jid = _enqueue(st)
    st.claim_job("w1")
    st.fail_job(jid, "fatal", force_dead=True, **held(st, jid))
    assert st.request_job_cancellation(jid) is False


# ── is_job_cancelled ──────────────────────────────────────────────────────────

def test_is_job_cancelled_false_before_request(isolated_store):
    st = isolated_store
    jid = _enqueue(st)
    assert st.is_job_cancelled(jid) is False


def test_is_job_cancelled_true_after_request(isolated_store):
    st = isolated_store
    jid = _enqueue(st)
    st.request_job_cancellation(jid)
    assert st.is_job_cancelled(jid) is True


# ── mark_job_cancelled ────────────────────────────────────────────────────────

def test_mark_job_cancelled_sets_status(isolated_store):
    st = isolated_store
    jid = _enqueue(st)
    st.claim_job("w1")
    st.mark_job_cancelled(jid, **held(st, jid))
    assert st.get_job(jid)["status"] == "cancelled"


# ── check_cancel outside worker turn ─────────────────────────────────────────

def test_check_cancel_noop_outside_worker_turn():
    # No _cancel_local.check installed — must not raise
    w._cancel_local.check = None
    w.check_cancel()  # should not raise


# ── Worker integration ────────────────────────────────────────────────────────

def _make_worker(st):
    return w.JobWorker(st)


def test_run_once_handler_raises_job_cancelled_error(isolated_store):
    """Handler explicitly raises JobCancelledError → status becomes 'cancelled'."""
    st = isolated_store
    jid = _enqueue(st)

    @w.handler("test")
    def _h(payload, job):
        raise w.JobCancelledError("stopped")

    wk = _make_worker(st)
    wk.run_once()
    assert st.get_job(jid)["status"] == "cancelled"


def test_run_once_check_cancel_raises_when_flag_set(isolated_store):
    """Handler calls check_cancel() after flag is set → JobCancelledError → 'cancelled'."""
    st = isolated_store
    jid = _enqueue(st)

    @w.handler("test")
    def _h(payload, job):
        # Flag set before the check
        st.request_job_cancellation(job["id"])
        w.check_cancel()
        # Should not reach here
        raise AssertionError("check_cancel() did not raise")

    wk = _make_worker(st)
    wk.run_once()
    assert st.get_job(jid)["status"] == "cancelled"


def test_run_once_handler_finishes_after_cancel_requested_marks_cancelled(isolated_store):
    """Handler completes normally but cancellation was requested before finish → 'cancelled'."""
    st = isolated_store
    jid = _enqueue(st)

    @w.handler("test")
    def _h(payload, job):
        st.request_job_cancellation(job["id"])
        # Does NOT call check_cancel — finishes normally

    wk = _make_worker(st)
    wk.run_once()
    assert st.get_job(jid)["status"] == "cancelled"


def test_run_once_completes_when_not_cancelled(isolated_store):
    """Normal handler with no cancellation → status='done'."""
    st = isolated_store
    jid = _enqueue(st)

    @w.handler("test")
    def _h(payload, job):
        pass

    wk = _make_worker(st)
    wk.run_once()
    assert st.get_job(jid)["status"] == "done"


def test_check_cancel_mid_work_stops_processing(isolated_store):
    """Handler calls check_cancel() at each checkpoint; cancellation stops it at the right point."""
    st = isolated_store
    jid = _enqueue(st)
    steps_done = []

    @w.handler("test")
    def _h(payload, job):
        steps_done.append("step1")
        st.request_job_cancellation(job["id"])
        w.check_cancel()   # should raise here
        steps_done.append("step2")  # must not reach

    wk = _make_worker(st)
    wk.run_once()

    assert "step1" in steps_done
    assert "step2" not in steps_done
    assert st.get_job(jid)["status"] == "cancelled"


def test_check_cancel_is_cleared_after_run_once(isolated_store):
    """_cancel_local.check is None between turns so stale checks don't leak."""
    st = isolated_store
    _enqueue(st)

    @w.handler("test")
    def _h(payload, job):
        pass

    _make_worker(st).run_once()
    # After the turn, the thread-local must be cleared
    assert getattr(w._cancel_local, "check", None) is None


def test_cancel_flag_does_not_affect_other_job(isolated_store):
    """Cancellation of job A does not affect job B running in another worker."""
    st = isolated_store
    jid_a = _enqueue(st)
    jid_b = _enqueue(st)

    call_order = []

    @w.handler("test")
    def _h(payload, job):
        call_order.append(job["id"])

    wk_a = w.JobWorker(st, worker_id="wA")
    wk_b = w.JobWorker(st, worker_id="wB")

    # Cancel job A before it runs
    st.request_job_cancellation(jid_a)

    wk_a.run_once()
    wk_b.run_once()

    assert st.get_job(jid_a)["status"] == "cancelled"
    assert st.get_job(jid_b)["status"] == "done"
