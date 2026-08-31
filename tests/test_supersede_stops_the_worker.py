"""Superseding a scan must actually stop the worker already running it.

supersede_scan (and cancel_scan, via the shared _end_running_scan) marks the run terminal and its
jobs 'dead'. That is the CORRECTNESS half, and it landed with the resurrection guard in #1051. It
is not the CAPACITY half: a worker that has already CLAIMED the job never learns to stop, because
`worker.check_cancel()` reads exactly one field — `cancel_requested_at` — and _end_running_scan
never set it.

store.finalize_scan_run's own docstring records the consequence, and this test exists to close
what it names as the follow-up:

    "a worker already executing that job never stops. […] The window is not small. It is the
     whole remaining duration of the superseded run, because nothing interrupts it. Making
     supersession actually stop the worker — setting cancel_requested_at so check_cancel()
     fires — is the follow-up that would also stop it burning Drive quota and DB connections."

The cost is concrete: a superseded discovery keeps listing Drive, keeps holding pool connections,
and keeps competing with the run that replaced it, for as long as the original would have taken.

WHY SETTING BOTH IS SAFE. The worker's cancellation path calls store.mark_job_cancelled(), whose
UPDATE is guarded `WHERE id=%s AND status NOT IN ('done','dead','cancelled')`. Against a job
already marked 'dead' by supersession that write no-ops and logs a zombie-worker line, so the job
KEEPS its 'dead' status and dead-letter accounting is unchanged. The two mechanisms compose
without either clobbering the other, and the tests below pin that.
"""
from __future__ import annotations
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from conftest import held

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "owner@example.com"
_NOW = datetime.now(timezone.utc).isoformat()


def _scan_with_claimed_job(store, sid="s1", owner=OWNER):
    """A durable scan whose job a worker has claimed and is executing."""
    scan_id, job_id = store.enqueue_scan(sid, "local", owner, "scan", {"scan_id": sid})
    store.init_scan_run(scan_id, "local", total=5, started_at=_NOW,
                        rubric_name="WCAG 2.1 AA", rubric_hash="abc123",
                        owner=owner, status="running")
    claimed = store.claim_job("worker-test-1")
    assert claimed is not None and claimed["id"] == job_id, "the fixture must hand the worker a job"
    return scan_id, job_id


def test_superseding_signals_the_running_worker_to_stop(isolated_store):
    """THE regression. Without this the worker runs to completion on a scan nobody wants."""
    s = isolated_store
    scan_id, job_id = _scan_with_claimed_job(s)
    assert s.is_job_cancelled(job_id) is False

    assert s.supersede_scan(scan_id, owner=OWNER) is True

    assert s.is_job_cancelled(job_id) is True, (
        "supersede marked the job dead but never set cancel_requested_at — the only field "
        "worker.check_cancel() reads — so a worker already executing it never stops")


def test_the_job_still_reads_as_dead_so_accounting_is_unchanged(isolated_store):
    """The signal must not quietly reclassify the job. dead_letter_breakdown counts status='dead',
    and a superseded run's jobs have always been counted there."""
    s = isolated_store
    scan_id, job_id = _scan_with_claimed_job(s)
    s.supersede_scan(scan_id, owner=OWNER)

    job = s.get_job(job_id)
    assert job["status"] == "dead"


def test_the_workers_own_cancel_write_cannot_clobber_that(isolated_store):
    """The composition, pinned. mark_job_cancelled is what the worker calls once check_cancel
    fires; against an already-dead job it must no-op rather than flip the status to 'cancelled'."""
    s = isolated_store
    scan_id, job_id = _scan_with_claimed_job(s)
    # The claim as it stood BEFORE supersede killed the job — held() reads the row, and by then
    # the row is 'dead' with no holder. This is the worker's own in-memory claim, which is what
    # it would still be passing when its handler finally returns.
    claim = {"worker_id": s.get_job(job_id)["locked_by"],
             "attempt": s.get_job(job_id)["attempts"]}
    s.supersede_scan(scan_id, owner=OWNER)

    assert s.mark_job_cancelled(job_id, **claim) is False, "expected a no-op against a terminal job"
    assert s.get_job(job_id)["status"] == "dead"


def test_cancel_scan_stops_the_worker_too(isolated_store):
    """The Stop button shares _end_running_scan, and has the same reason to interrupt work."""
    s = isolated_store
    scan_id, job_id = _scan_with_claimed_job(s)

    assert s.cancel_scan(scan_id, owner=OWNER) is True
    assert s.is_job_cancelled(job_id) is True


def test_an_earlier_explicit_cancellation_timestamp_is_preserved(isolated_store):
    """A user's own Stop already stamped the moment they asked. Superseding afterwards must not
    rewrite when cancellation was requested — that timestamp is evidence, not a flag."""
    s = isolated_store
    scan_id, job_id = _scan_with_claimed_job(s)

    assert s.request_job_cancellation(job_id) is True
    with s._db.cursor() as cur:
        s._db.execute(cur, "SELECT cancel_requested_at FROM jobs WHERE id=%s", (job_id,))
        first = s._db.fetchone(cur)["cancel_requested_at"]

    s.supersede_scan(scan_id, owner=OWNER)

    with s._db.cursor() as cur:
        s._db.execute(cur, "SELECT cancel_requested_at FROM jobs WHERE id=%s", (job_id,))
        after = s._db.fetchone(cur)["cancel_requested_at"]
    assert after == first, "supersession overwrote the original cancellation timestamp"


def test_a_scan_with_nothing_running_is_unaffected(isolated_store):
    """The invariant: supersede still returns False when there is genuinely nothing to stop, and
    invents no cancellation signal. Passes before and after."""
    s = isolated_store
    scan_id, _job_id = s.enqueue_scan("s2", "local", OWNER, "scan", {"scan_id": "s2"})
    s.init_scan_run(scan_id, "local", total=1, started_at=_NOW, rubric_name="R",
                    rubric_hash="h", owner=OWNER, status="completed")
    s.cancel_queued_job(scan_id)          # drain the queued job so nothing is outstanding

    assert s.supersede_scan(scan_id, owner=OWNER) is False
