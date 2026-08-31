"""An outcome may only be published by the claim that is currently running the job.

THE GAP THIS CLOSES. #1075 required ownership to RENEW a lease. It did not require ownership to
publish an OUTCOME. complete_job / mark_job_cancelled / fail_job each guarded only against
writing over a job that had already reached a terminal state:

    WHERE id=%s AND status NOT IN ('done','dead','cancelled')

A job being re-run by a replacement worker is 'running'. 'running' is not in that set. So the
guard that exists for exactly this race does not fire while the race is still LIVE — it protects
a job that already finished and leaves an in-flight one open.

The sequence, which every test below walks:

  1. worker-A claims job J. attempts=1, locked_by='worker-A', status='running'.
  2. A wedges (a native parser, a hung socket — see docs/native-isolation-map.md).
  3. The lease lapses. reclaim_stuck_jobs requeues J. worker-B claims it: attempts=2,
     locked_by='worker-B', status='running'.
  4. A finally returns and publishes its outcome for J.

At step 4 the terminal guard passes, because B has not finished. What A writes lands, and B's own
write is then refused as "already terminal" — the suppression message names the WRONG writer.
Each outcome fails differently, which is why they are tested separately rather than as one:

  complete_job         J flips to 'done' while B is still reading documents. The run counts J
                       finished on the strength of an execution that never completed, and
                       _scrub_payload_secrets strips the Drive token out from under B.
  fail_job (requeue)   J flips to 'queued', locked_by=NULL, WHILE B RUNS. A third worker can now
                       claim it alongside B: not a lost update but genuine duplicate execution.
  fail_job (dead)      J flips to 'dead' and _record_dead_scan_files writes failure rows for
                       documents B is processing successfully.
  mark_job_cancelled   J flips to 'cancelled' — a stale attempt's JobCancelledError stops its own
                       replacement. This one compounds #1079: cancellation now reaches more
                       threads, so more attempts can reach this write.

NOT PRESENTED AS AN OBSERVED PRODUCTION FAILURE. These establish the mechanism in the code.
Nothing here says it happened; it is the second half of a gap #1075 opened deliberately and named.
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
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "outcome.db")
    return store_mod.Store()


def _handover(st, job_type="t_outcome"):
    """Run steps 1-3: A claims, the sweeper reclaims, B claims. Returns (jid, a, b).

    Uses reclaim_stuck_jobs rather than a voluntary fail_job, because the sweeper is the path that
    actually produces this interleaving in production — A never chose to give the job up.
    """
    jid = st.enqueue_job(job_type, {"x": 1})
    a = st.claim_job("worker-A")
    assert a["id"] == jid
    assert st.reclaim_stuck_jobs(lease_seconds=0) == 1
    b = st.claim_job("worker-B")
    assert b["id"] == jid and b["locked_by"] == "worker-B"
    assert b["attempts"] > a["attempts"], "the handover must produce a distinct attempt"
    return jid, a, b


# ── the race: a stale claim publishing over a LIVE replacement ────────────────────────────────

def test_a_stale_claim_cannot_complete_a_job_its_replacement_is_still_running(st):
    jid, a, b = _handover(st)

    won = st.complete_job(jid, worker_id="worker-A", attempt=a["attempts"])

    assert won is False, "the stale claim's completion was accepted"
    assert st.get_job(jid)["status"] == "running", (
        "worker-A completed a job worker-B is still running — the run now counts a document set "
        "as finished on the strength of an execution that never finished it")


def test_a_stale_claim_cannot_requeue_a_job_its_replacement_is_still_running(st):
    """The worst of the four: this does not lose an update, it creates a SECOND live execution."""
    jid, a, b = _handover(st)

    outcome = st.fail_job(jid, "transient", backoff_seconds=0,
                          worker_id="worker-A", attempt=a["attempts"])

    assert outcome == "stale", (
        "fail_job named an outcome it did not record — the old return said 'queued' for a "
        "suppressed write, which is what made the suppression invisible to its caller")
    row = st.get_job(jid)
    assert row["status"] == "running", (
        "worker-A requeued a job worker-B is still running — a third worker can now claim it "
        "alongside B and process every document twice")
    assert row["locked_by"] == "worker-B", "B's claim was cleared out from under it"


def test_a_stale_claim_cannot_dead_letter_a_job_its_replacement_is_still_running(st):
    jid, a, b = _handover(st)

    assert st.fail_job(jid, "fatal", force_dead=True,
                       worker_id="worker-A", attempt=a["attempts"]) == "stale"

    assert st.get_job(jid)["status"] == "running", (
        "worker-A dead-lettered a job worker-B is still running — the failure rows describe "
        "documents that were being processed successfully")


def test_a_stale_claim_cannot_cancel_a_job_its_replacement_is_still_running(st):
    """Compounds #1079: cancellation reaches more threads now, so more stale attempts can raise
    JobCancelledError and arrive here."""
    jid, a, b = _handover(st)

    won = st.mark_job_cancelled(jid, worker_id="worker-A", attempt=a["attempts"])

    assert won is False
    assert st.get_job(jid)["status"] == "running", (
        "a stale attempt's cancellation stopped its own replacement")


def test_the_same_worker_on_an_EARLIER_attempt_is_also_stale(st):
    """worker_id alone is not enough. A worker can legitimately re-claim a job it ran before —
    same locked_by, later attempt — and the earlier execution must not publish for the later one.
    Guarding on locked_by only would pass every test above and still fail here."""
    jid = st.enqueue_job("t_outcome", {"x": 1})
    first = st.claim_job("worker-A")
    assert st.reclaim_stuck_jobs(lease_seconds=0) == 1
    second = st.claim_job("worker-A")                     # SAME worker, new attempt
    assert second["locked_by"] == "worker-A"
    assert second["attempts"] > first["attempts"]

    won = st.complete_job(jid, worker_id="worker-A", attempt=first["attempts"])

    assert won is False, "the earlier attempt published for the later one — attempt is unchecked"
    assert st.get_job(jid)["status"] == "running"


# ── the side effect that happens BEFORE the guarded write ─────────────────────────────────────

def test_a_stale_dead_letter_does_not_record_its_documents_as_failed(st):
    """The status guard alone does not cover this, which is the point of testing it separately.

    fail_job's dead branch calls _record_dead_scan_files BEFORE the UPDATE — it has to, because
    scrubbing is what removes the filenames that record needs. So tightening only the SQL leaves
    a stale claim writing a failure row per document while the UPDATE that would have recorded
    the death is refused. Every assertion above would still pass: the STATUS never moves. The
    run would simply count documents as failed that its replacement is processing successfully.

    fail_job therefore bails on ownership before any of that runs. The UPDATE keeps its own
    predicate as the authority (this read is racy); this only stops the writes on the way there.
    """
    sid = "scan-stale-1"
    st.init_scan_run(sid, "drive", 1, "2026-08-31T00:00:00Z", "rubric", "hash", owner="demo")
    st.set_scan_files(sid, 1)
    jid = st.enqueue_job("scan_file", {"scan_id": sid, "file": "a.docx"}, scan_id=sid)

    a = st.claim_job("worker-A")
    assert st.reclaim_stuck_jobs(lease_seconds=0) == 1
    st.claim_job("worker-B")
    assert st.count_files_done(sid) == (0, 1)

    st.fail_job(jid, "stale fatal", force_dead=True,
                worker_id="worker-A", attempt=a["attempts"])

    assert st.count_files_done(sid) == (0, 1), (
        "a stale claim recorded its documents as failed — the status write was correctly "
        "refused, but the failure rows were written before it and the run now counts a "
        "document dead that worker-B is still processing")


# ── fail_job's SQL predicate, with the early bail deliberately defeated ───────────────────────
# The bail above is an optimisation for side effects and is racy BY DESIGN — the job can be
# reclaimed between it returning True and the UPDATE running. The predicate compiled into the
# UPDATE is what actually makes the refusal atomic. But while the bail is in place it catches
# every stale call first, so the two tests above would pass with fail_job's ownership predicate
# deleted entirely: measured, not assumed — removing `_CLAIM_OWNED` reddens the complete_job and
# mark_job_cancelled tests (they have no bail) and NOTHING in fail_job's.
#
# So these force the TOCTOU the bail cannot cover: the check passes, then the row moves.

@pytest.fixture()
def _bail_always_passes(monkeypatch):
    """Make _claim_is_current lie, leaving the UPDATE's own predicate as the only guard."""
    import store as store_mod
    monkeypatch.setattr(store_mod.Store, "_claim_is_current",
                        lambda self, job_id, worker_id, attempt: True)


def test_fail_jobs_requeue_predicate_refuses_a_stale_claim_that_won_the_check(st, _bail_always_passes):
    jid, a, b = _handover(st)

    st.fail_job(jid, "transient", backoff_seconds=0,
                worker_id="worker-A", attempt=a["attempts"])

    row = st.get_job(jid)
    assert row["status"] == "running" and row["locked_by"] == "worker-B", (
        "with the pre-check defeated, fail_job's UPDATE requeued a job its replacement is "
        "running — the ownership predicate is missing from the SQL, so the guard is only as "
        "good as a check that races")


def test_fail_jobs_dead_letter_predicate_refuses_a_stale_claim_that_won_the_check(st, _bail_always_passes):
    jid, a, b = _handover(st)

    st.fail_job(jid, "fatal", force_dead=True,
                worker_id="worker-A", attempt=a["attempts"])

    assert st.get_job(jid)["status"] == "running", (
        "with the pre-check defeated, fail_job's dead-letter UPDATE landed on a job its "
        "replacement is running")


# ── the invariants: the ordinary path must keep working (pass before AND after) ────────────────

def test_the_current_holder_completes_normally(st):
    jid = st.enqueue_job("t_outcome", {"x": 1})
    job = st.claim_job("worker-A")
    assert st.complete_job(jid, worker_id="worker-A", attempt=job["attempts"]) is True
    assert st.get_job(jid)["status"] == "done"


def test_the_current_holder_cancels_normally(st):
    jid = st.enqueue_job("t_outcome", {"x": 1})
    job = st.claim_job("worker-A")
    assert st.mark_job_cancelled(jid, worker_id="worker-A", attempt=job["attempts"]) is True
    assert st.get_job(jid)["status"] == "cancelled"


def test_the_current_holder_requeues_normally(st):
    jid = st.enqueue_job("t_outcome", {"x": 1})
    job = st.claim_job("worker-A")
    assert st.fail_job(jid, "transient", backoff_seconds=0,
                       worker_id="worker-A", attempt=job["attempts"]) == "queued"
    assert st.get_job(jid)["status"] == "queued"


def test_the_current_holder_dead_letters_normally(st):
    jid = st.enqueue_job("t_outcome", {"x": 1})
    job = st.claim_job("worker-A")
    assert st.fail_job(jid, "fatal", force_dead=True,
                       worker_id="worker-A", attempt=job["attempts"]) == "dead"
    assert st.get_job(jid)["status"] == "dead"


def test_the_terminal_guard_from_the_earlier_fix_still_holds(st):
    """Ownership must be ADDED to the terminal guard, not replace it. The current holder writing
    twice must still be a no-op the second time — that is the zombie race #1073-era work closed,
    and it is still the guard for a job whose replacement already finished."""
    jid = st.enqueue_job("t_outcome", {"x": 1})
    job = st.claim_job("worker-A")
    assert st.complete_job(jid, worker_id="worker-A", attempt=job["attempts"]) is True
    assert st.mark_job_cancelled(jid, worker_id="worker-A", attempt=job["attempts"]) is False
    assert st.get_job(jid)["status"] == "done", (
        "the terminal guard was dropped in favour of ownership")
