"""complete_job / mark_job_cancelled / fail_job must not clobber a job that already reached a
DIFFERENT terminal state via another writer (PRD §20 idempotency audit, 2026-08-28).

reclaim_stuck_jobs() requeues a job whose lease expired so a SECOND worker can claim and finish
it — but does nothing to stop the FIRST (zombie) worker's handler from finishing its own work
later and calling complete_job/mark_job_cancelled/fail_job on the same job_id, unaware it lost
the lease. Before this fix none of the three had a status guard, so whichever writer ran LAST
silently won — a zombie's late fail_job(force_dead=True) could flip a job a second worker had
already completed successfully back to 'dead', with no error raised anywhere and no test catching
it. The fix guards every terminal-state UPDATE to `WHERE status NOT IN ('done','dead','cancelled')`
and returns False/leaves status alone when it loses the race.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


def _enqueue(st, *, type="test"):
    return st.enqueue_job(type, {"x": 1})


# ── the ordinary, non-racing path still works ────────────────────────────────────────────────

def test_complete_job_wins_and_returns_true_when_not_yet_terminal(isolated_store):
    st = isolated_store
    _enqueue(st)
    job = st.claim_job("w1")
    assert st.complete_job(job["id"]) is True
    assert st.get_job(job["id"])["status"] == "done"


def test_mark_job_cancelled_wins_and_returns_true_when_not_yet_terminal(isolated_store):
    st = isolated_store
    _enqueue(st)
    job = st.claim_job("w1")
    assert st.mark_job_cancelled(job["id"]) is True
    assert st.get_job(job["id"])["status"] == "cancelled"


def test_fail_job_requeue_still_works_when_not_yet_terminal(isolated_store):
    st = isolated_store
    _enqueue(st)
    job = st.claim_job("w1")
    assert st.fail_job(job["id"], "transient error", backoff_seconds=0) == "queued"
    assert st.get_job(job["id"])["status"] == "queued"


def test_fail_job_dead_letter_still_works_when_not_yet_terminal(isolated_store):
    st = isolated_store
    _enqueue(st)
    job = st.claim_job("w1")
    assert st.fail_job(job["id"], "fatal error", force_dead=True) == "dead"
    assert st.get_job(job["id"])["status"] == "dead"


# ── the zombie-writer race: a second call after the job is already terminal ─────────────────

def test_complete_job_does_not_clobber_a_job_already_dead(isolated_store):
    st = isolated_store
    _enqueue(st)
    job = st.claim_job("w1")
    st.fail_job(job["id"], "fatal", force_dead=True)
    assert st.get_job(job["id"])["status"] == "dead"

    # A zombie worker, unaware the job was already dead-lettered, finishes its own handler run
    # and calls complete_job — must not resurrect it to 'done'.
    assert st.complete_job(job["id"]) is False
    assert st.get_job(job["id"])["status"] == "dead"


def test_mark_job_cancelled_does_not_clobber_a_job_already_completed(isolated_store):
    """The exact scenario from the idempotency audit: reclaim_stuck_jobs() lets a SECOND worker
    finish the job while the FIRST (zombie) worker is still running. The zombie later receives a
    stray cancel signal and calls mark_job_cancelled — this must not flip a successfully
    completed job back to 'cancelled'."""
    st = isolated_store
    _enqueue(st)
    job = st.claim_job("w1")

    # Simulate the lease expiring and the sweeper reclaiming it for a second worker.
    st.reclaim_stuck_jobs(lease_seconds=0)
    assert st.get_job(job["id"])["status"] == "queued"
    reclaimed = st.claim_job("w2")
    assert reclaimed["id"] == job["id"]

    # Worker B finishes the job successfully.
    assert st.complete_job(job["id"]) is True
    assert st.get_job(job["id"])["status"] == "done"

    # Worker A (the zombie, still holding its stale in-memory job dict) finally gets a cancel
    # signal for what it thinks is its own in-flight job and calls mark_job_cancelled.
    assert st.mark_job_cancelled(job["id"]) is False
    assert st.get_job(job["id"])["status"] == "done"


def test_fail_job_dead_letter_does_not_clobber_a_job_already_completed_by_a_second_worker(isolated_store):
    """Same reclaim race as above, but the zombie's late failure is a force_dead fail_job call
    instead of a cancel — this is the concrete worst case the audit flagged: a completed job
    silently flipped to 'dead' with no error surfaced anywhere."""
    st = isolated_store
    _enqueue(st)
    job = st.claim_job("w1")

    st.reclaim_stuck_jobs(lease_seconds=0)
    reclaimed = st.claim_job("w2")
    assert reclaimed["id"] == job["id"]
    assert st.complete_job(job["id"]) is True

    # fail_job still reports "dead" (it does not know it lost the race), but the row itself
    # must not actually move.
    assert st.fail_job(job["id"], "zombie's late fatal error", force_dead=True) == "dead"
    assert st.get_job(job["id"])["status"] == "done"


def test_fail_job_requeue_does_not_clobber_a_job_already_completed(isolated_store):
    """A zombie's late TRANSIENT failure (not force_dead) must not requeue a job a second worker
    already completed — that would hand a 'done' job back to the queue for a third claim."""
    st = isolated_store
    _enqueue(st)
    job = st.claim_job("w1")

    st.reclaim_stuck_jobs(lease_seconds=0)
    st.claim_job("w2")
    assert st.complete_job(job["id"]) is True

    st.fail_job(job["id"], "zombie's late transient error", backoff_seconds=0)
    assert st.get_job(job["id"])["status"] == "done"


def test_fail_job_dead_letter_does_not_clobber_a_cancelled_job(isolated_store):
    st = isolated_store
    _enqueue(st)
    job = st.claim_job("w1")
    st.mark_job_cancelled(job["id"])
    assert st.get_job(job["id"])["status"] == "cancelled"

    assert st.fail_job(job["id"], "late error", force_dead=True) == "dead"
    assert st.get_job(job["id"])["status"] == "cancelled"


def test_complete_job_does_not_clobber_an_already_cancelled_job(isolated_store):
    st = isolated_store
    _enqueue(st)
    job = st.claim_job("w1")
    st.mark_job_cancelled(job["id"])

    assert st.complete_job(job["id"]) is False
    assert st.get_job(job["id"])["status"] == "cancelled"
