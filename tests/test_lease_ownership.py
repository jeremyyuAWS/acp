"""A lease may only be renewed by the worker that currently holds it, on the attempt it claimed.

THE RACE. `touch_job` updated `WHERE id=%s AND status='running'` — nothing about who holds the
job. So any process that still believes it owns a job can extend that job's lease, including one
whose claim was reclaimed by the sweeper minutes earlier.

The sequence, which the first test below walks:

  1. worker-A claims job J. attempts=1, locked_by='worker-A', status='running'.
  2. A's handler wedges. Its heartbeat thread keeps calling touch_job(J) — worker.py starts that
     thread for the life of the handler, and it survives whatever the handler is stuck on.
  3. The lease lapses; reclaim_stuck_jobs requeues J; worker-B claims it. attempts=2,
     locked_by='worker-B'.
  4. A's heartbeat fires again. Under the old predicate it MATCHED — J is still 'running' — and
     extended B's lease.

WHY THAT IS WORSE THAN A WASTED WRITE. The lease is the only mechanism that recovers a job from
a dead worker. While A keeps renewing it, B's death is invisible: the lease never goes stale, the
sweeper never reclaims, and the job sits 'running' forever behind a heartbeat from a process that
is not doing the work. The zombie masks the failure of its own replacement.

It is bounded but not small: worker.max_unverified_lease_s caps A's extensions at
ACP_JOB_MAX_LEASE_S (default 3600s), so the window is up to an hour per stale worker.

`attempts` is checked as well as `locked_by`, because a worker can legitimately re-claim a job it
previously ran — same `locked_by`, later attempt — and the earlier execution's heartbeat must not
renew the later one's lease.

NOT PRESENTED AS AN OBSERVED PRODUCTION FAILURE. These tests establish the mechanism in the code;
nothing here says it happened on 2026-08-30. It is a gap worth closing before concurrency rises,
which is when stale claims and reclaims become common.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

from conftest import held

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "lease.db")
    return store_mod.Store()


def _lease(st, job_id):
    return st.get_job(job_id)["lease_expires_at"]


def test_a_reclaimed_job_cannot_be_renewed_by_the_previous_worker(st):
    """The race itself. Fails on the old predicate, which matched on status alone."""
    jid = st.enqueue_job("t_lease", {})

    a = st.claim_job("worker-A")
    assert a["id"] == jid and a["locked_by"] == "worker-A"
    a_attempt = a["attempts"]

    # The sweeper reclaims it and worker-B takes over.
    st.fail_job(jid, "lease lapsed", backoff_seconds=0, **held(st, jid))
    b = st.claim_job("worker-B")
    assert b["id"] == jid and b["locked_by"] == "worker-B"
    assert b["attempts"] > a_attempt

    before = _lease(st, jid)
    st.touch_job(jid, worker_id="worker-A", attempt=a_attempt)     # the zombie's heartbeat
    assert _lease(st, jid) == before, (
        "a worker whose claim was reclaimed must not extend the new holder's lease — while it "
        "does, the new holder's own death can never be detected")


def test_the_current_holder_can_renew_its_own_lease(st):
    """The invariant. Tightening the predicate must not break the mechanism it guards; this
    passes before AND after."""
    jid = st.enqueue_job("t_lease", {})
    job = st.claim_job("worker-A")

    st.touch_job(jid, worker_id="worker-A", attempt=job["attempts"])
    assert _lease(st, jid) is not None
    assert st.get_job(jid)["status"] == "running"


def test_a_later_attempt_by_the_SAME_worker_is_still_a_different_claim(st):
    """`locked_by` alone is not enough. A worker can re-claim a job it previously ran, and the
    earlier execution's heartbeat must not renew the later one."""
    jid = st.enqueue_job("t_lease", {})
    first = st.claim_job("worker-A")
    st.fail_job(jid, "retry", backoff_seconds=0, **held(st, jid))
    second = st.claim_job("worker-A")
    assert second["attempts"] > first["attempts"]

    before = _lease(st, jid)
    st.touch_job(jid, worker_id="worker-A", attempt=first["attempts"])
    assert _lease(st, jid) == before, "same worker, older attempt — still a stale claim"


def test_renewing_a_finished_job_is_a_no_op(st):
    """Unchanged behaviour, kept explicit: the status guard still applies."""
    jid = st.enqueue_job("t_lease", {})
    job = st.claim_job("worker-A")
    st.complete_job(jid, **held(st, jid))

    st.touch_job(jid, worker_id="worker-A", attempt=job["attempts"])
    assert st.get_job(jid)["status"] == "done"


def test_touch_job_never_raises_on_a_missing_job(st):
    """It runs on a timer inside the worker; it must not be able to kill the heartbeat thread."""
    st.touch_job("no-such-job", worker_id="worker-A", attempt=1)


def test_the_worker_passes_its_own_identity_when_it_heartbeats(st, monkeypatch):
    """The store-level guard is only worth having if the caller supplies the right values. This
    pins the wiring: worker.py must send ITS worker_id and the attempt it claimed."""
    import worker as worker_mod

    seen = []
    monkeypatch.setattr(st, "touch_job",
                        lambda job_id, **kw: seen.append({"job_id": job_id, **kw}))
    monkeypatch.setattr(worker_mod, "HEARTBEAT_INTERVAL_S", 0.01)

    claimed = {}

    def handler(payload, job):
        claimed.update(job)
        import time as _t
        _t.sleep(0.08)                      # let the heartbeat thread fire at least once

    worker_mod.HANDLERS["t_hb"] = handler
    try:
        st.enqueue_job("t_hb", {})
        worker_mod.JobWorker(st, worker_id="worker-A").run_once()
    finally:
        worker_mod.HANDLERS.pop("t_hb", None)

    assert seen, "the heartbeat never fired — this test would otherwise assert nothing"
    for call in seen:
        assert call["job_id"] == claimed["id"]
        assert call["worker_id"] == "worker-A"
        assert call["attempt"] == claimed["attempts"]
