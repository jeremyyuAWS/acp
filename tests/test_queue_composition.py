"""The shared queue's composition and rates — what the Live Operations drawer draws its queue
visualization from.

The invariant under test is the one the drawer depends on: each of the four states is a DIFFERENT
question, and the pairs that are easy to blend are the ones that mislead. Waiting work and retrying
work both sit at status='queued' and mean opposite things about capacity; a deliberately stopped
job and a failed one are both status='dead' and only one is a fault.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from api.routes import system
from conftest import held


def _scan(scan_id="scan-queue-1", owner="operator@example.org"):
    return {
        "_scan_id": scan_id, "owner": owner, "source": "drive",
        "started_at": "2026-09-04T12:00:00+00:00", "completed_at": None,
        "rubric": {"name": "wcag-aa", "hash": "h"},
        "summary": {"files": 3, "certifiable": 0, "uncertain": 0, "error": 0, "avg_score": 0},
        "files": [],
    }


def test_waiting_and_retrying_are_counted_apart(isolated_store):
    """Both are status='queued'. A retry storm and a capacity shortage look identical if they are
    added together, and they call for opposite responses."""
    isolated_store.save_scan(_scan())
    # One job that failed once and was requeued in place (fail_job does not insert a new row) …
    retried = isolated_store.enqueue_job("scan_file", {"file": "b.docx"}, scan_id="scan-queue-1")
    claimed = isolated_store.claim_job("worker-1")
    assert claimed["id"] == retried
    assert isolated_store.fail_job(retried, "transient", **held(isolated_store, retried)) == "queued"
    # … and one that has never been attempted.
    isolated_store.enqueue_job("scan_file", {"file": "a.docx"}, scan_id="scan-queue-1")

    composition = isolated_store.queue_composition()
    assert composition["retrying"] == 1
    assert composition["waiting"] == 1
    # The single number both would otherwise disappear into.
    assert composition["waiting"] + composition["retrying"] == \
        len(isolated_store.list_jobs(status="queued", limit=100))


def test_running_waiting_and_dead_letters_are_separate_states(isolated_store):
    isolated_store.save_scan(_scan())
    # Enqueued and claimed one at a time: claim_job is FIFO, so the order below is what puts each
    # job in the state this test names.
    dead = isolated_store.enqueue_job("scan_file", {"file": "dead.docx"}, scan_id="scan-queue-1")
    assert isolated_store.claim_job("worker-2")["id"] == dead
    assert isolated_store.fail_job(dead, "boom", force_dead=True, **held(isolated_store, dead)) == "dead"
    running = isolated_store.enqueue_job("scan_file", {"file": "running.docx"}, scan_id="scan-queue-1")
    assert isolated_store.claim_job("worker-1")["id"] == running
    isolated_store.enqueue_job("scan_file", {"file": "waiting.docx"}, scan_id="scan-queue-1")

    composition = isolated_store.queue_composition()
    assert composition["running"] == 1
    assert composition["waiting"] == 1
    assert composition["failed"] == 1


def test_a_deliberate_stop_is_not_reported_as_a_failure(isolated_store):
    """Stopping a scan marks its jobs 'dead'. Counting those as failures is how pressing Stop on a
    200-document run adds 200 faults to an operator's queue view — the same _FAILED split
    dead_letter_breakdown already makes."""
    isolated_store.save_scan(_scan())
    isolated_store.enqueue_job("scan_file", {"file": "stopped.docx"}, scan_id="scan-queue-1")
    isolated_store.cancel_scan("scan-queue-1")
    assert isolated_store.queue_composition()["failed"] == 0


def test_rates_count_only_the_window_they_report(isolated_store):
    isolated_store.save_scan(_scan())
    job = isolated_store.enqueue_job("scan_file", {"file": "done.docx"}, scan_id="scan-queue-1")
    claimed = isolated_store.claim_job("worker-1")
    isolated_store.complete_job(job, worker_id="worker-1", attempt=claimed["attempts"])

    inside = isolated_store.queue_composition(window_s=900)
    assert inside["arrived"] == 1
    assert inside["completed"] == 1
    assert inside["window_s"] == 900
    # A zero-length window contains nothing, which is what makes `window_s` a fact the reader can
    # divide by rather than an assumption.
    outside = isolated_store.queue_composition(window_s=0)
    assert outside == {**inside, "arrived": 0, "completed": 0, "window_s": 0,
                       "oldest_queued_at": outside["oldest_queued_at"]}


def test_oldest_wait_is_an_instant_not_a_counter(isolated_store):
    """The activity stream emits only when its payload changes. An elapsed-seconds field would
    change on every two-second build, turning one waiting job into a frame every two seconds."""
    isolated_store.save_scan(_scan())
    isolated_store.enqueue_job("scan_file", {"file": "waiting.docx"}, scan_id="scan-queue-1")
    composition = isolated_store.queue_composition()
    assert composition["oldest_queued_at"]
    assert "oldest_queued_wait_s" not in composition
    assert isolated_store.queue_composition() == composition


def test_a_job_in_retry_backoff_is_not_evidence_of_a_stalled_queue(isolated_store):
    """`claim_job`'s own gate is run_after <= now. A job parked behind a backoff is not claimable,
    so reporting it as the oldest wait would read as a worker tier that has stopped draining."""
    isolated_store.save_scan(_scan())
    job = isolated_store.enqueue_job("scan_file", {"file": "backoff.docx"}, scan_id="scan-queue-1")
    claimed = isolated_store.claim_job("worker-1")
    assert claimed["id"] == job
    isolated_store.fail_job(job, "transient", backoff_seconds=600, **held(isolated_store, job))

    composition = isolated_store.queue_composition()
    assert composition["retrying"] == 1
    assert composition["oldest_queued_at"] is None


def test_the_activity_snapshot_carries_the_queue_block(isolated_store, monkeypatch):
    isolated_store.save_scan(_scan())
    isolated_store.enqueue_job("scan_file", {"file": "waiting.docx"}, scan_id="scan-queue-1")
    monkeypatch.setattr(system.core, "store", isolated_store)
    summary = system._admin_activity_snapshot()["summary"]
    assert summary["queue"]["waiting"] == 1
    assert summary["queue"]["window_s"] == 900


def test_the_snapshot_omits_the_block_rather_than_reporting_zeroes(monkeypatch):
    """A store that cannot answer must leave the key ABSENT. The drawer renders a missing row as
    "Not reported"; an empty dict of zeroes would render as a measured, healthy queue."""
    class OlderStore:
        def worker_tier_status(self):
            return {"alive": True, "pool_size": 2}

        def worker_roles_status(self):
            return {}

        def job_stats(self, owner=None):
            return {"done": 0}

        def admin_live_activity(self):
            return []

    monkeypatch.setattr(system.core, "store", OlderStore())
    assert "queue" not in system._admin_activity_snapshot()["summary"]


def test_the_block_is_absent_when_the_query_itself_fails(monkeypatch):
    class BrokenStore:
        def worker_tier_status(self):
            return {"alive": True, "pool_size": 2}

        def worker_roles_status(self):
            return {}

        def job_stats(self, owner=None):
            return {"done": 0}

        def admin_live_activity(self):
            return []

        def queue_composition(self):
            raise RuntimeError("database is unavailable")

    monkeypatch.setattr(system.core, "store", BrokenStore())
    summary = system._admin_activity_snapshot()["summary"]
    assert "queue" not in summary
    # The rest of the snapshot still composes — a queue read that fails must not take the map down.
    assert summary["worker_slots"] == 2


def test_the_queue_view_is_global_and_carries_no_tenant_data(isolated_store):
    """Global on purpose: 'is the SHARED queue draining' is not a per-caller question. What makes
    that safe is that nothing here reads a payload, an error string or a filename."""
    isolated_store.save_scan(_scan("scan-a", "a@example.org"))
    isolated_store.save_scan(_scan("scan-b", "b@example.org"))
    isolated_store.enqueue_job("scan_file", {"file": "Private Report.docx", "secret": "never-return"},
                               scan_id="scan-a")
    isolated_store.enqueue_job("scan_file", {"file": "Other Tenant.docx"}, scan_id="scan-b")
    composition = isolated_store.queue_composition()
    assert composition["waiting"] == 2
    assert "secret" not in str(composition)
    assert "Private Report" not in str(composition)


def test_a_future_window_boundary_does_not_swallow_current_work(isolated_store):
    """Guards the cutoff's direction: `>= cutoff`, not `<=`. Reversed, a busy queue reports zero
    arrivals and an idle one reports every job it ever took."""
    isolated_store.save_scan(_scan())
    isolated_store.enqueue_job("scan_file", {"file": "now.docx"}, scan_id="scan-queue-1")
    ancient = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur, "UPDATE jobs SET created_at=%s WHERE 1=1", (ancient,))
    assert isolated_store.queue_composition(window_s=900)["arrived"] == 0
    assert isolated_store.queue_composition(window_s=4 * 3600)["arrived"] == 1
