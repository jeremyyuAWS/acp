"""A worker restart must not park an in-flight scan until its lease expires.

The defect these cover produced three false "the scan is broken" reports on 2026-07-30,
each within minutes of a deploy. A deploy rolls a new worker revision; every job the old
one held stayed in 'running' with nobody executing it, and nothing could touch those rows
until a 30-minute lease ran out. The UI, which only knows how to render "still running",
showed "Analysing documents · 0/N" for half an hour.

The lease could not have fixed this at any setting. It measures silence, not death, so it
has to be long enough for the slowest job that is legitimately quiet — shortening it enough
to make a deploy tolerable would start killing honest work. The fix is to stop inferring:
attribute each lock to the worker PROCESS that took it, and requeue the moment that process
is known to be gone.

The end-to-end restart is test_restart_mid_scan_resumes_in_seconds; the rest pin the
individual rules it depends on, including the ones that must NOT fire.
"""
from __future__ import annotations
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


@pytest.fixture()
def store(monkeypatch):
    import store as store_mod
    tmp = Path(tempfile.mkdtemp()) / "reclaim-test.db"
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", tmp)
    return store_mod.Store()


def _age_instance(store, instance_id, seconds):
    """Backdate an instance's heartbeat — simulates a process that stopped beating."""
    old = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
    with store._db.cursor() as cur:
        store._db.execute(cur, "UPDATE worker_instances SET last_seen=%s WHERE id=%s",
                          (old, instance_id))


def _age_lock(store, job_id, seconds):
    """Backdate a job's lease — simulates a lock held since before the lease window."""
    old = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
    with store._db.cursor() as cur:
        store._db.execute(cur, "UPDATE jobs SET locked_at=%s WHERE id=%s", (old, job_id))


# ── The reproduction ──────────────────────────────────────────────────────────

def test_restart_mid_scan_resumes_in_seconds(store):
    """The whole bug, start to finish: a scan is in flight, the worker holding it dies,
    a replacement boots. The scan's remaining work must be runnable immediately."""
    # Instance A boots and claims two of a scan's three files.
    store.register_instance("replica-a-1111")
    jobs = [store.enqueue_job("scan_file", {"file": f"{n}.docx", "scan_id": "s1"}, scan_id="s1")
            for n in ("a", "b", "c")]
    claimed = [store.claim_job("replica-a-1111:w0"), store.claim_job("replica-a-1111:w1")]
    assert all(j is not None for j in claimed)
    assert store.job_stats() == {"running": 2, "queued": 1}

    # A deploy: instance A drains and publishes its own death (core.stop_workers).
    store.deregister_instance("replica-a-1111")

    # Instance B boots in its place and reclaims before starting its pool.
    store.register_instance("replica-b-2222")
    rescued = store.reclaim_orphaned_jobs(exclude="replica-b-2222")

    assert len(rescued) == 2, "both of A's in-flight files should be requeued at once"
    assert {r["scan_id"] for r in rescued} == {"s1"}
    assert store.job_stats() == {"queued": 3}, "the whole scan is runnable again"

    # And B can actually pick the rescued work up — the requeue is a real requeue, not
    # just a status flip. run_after must not have been left in the future.
    got = {store.claim_job("replica-b-2222:w0")["id"] for _ in range(1)}
    assert got <= set(jobs)

    # No clock was waited on: the lease is untouched and would not have fired.
    assert store.reclaim_stuck_jobs(lease_seconds=600) == 0


def test_crash_with_no_replacement_is_reclaimed_by_staleness(store):
    """An OOM kill or lost node gets no chance to deregister, and may get no replacement
    either — the surviving instances' sweeper must still notice."""
    store.register_instance("replica-a-1111")
    store.enqueue_job("scan_file", {"file": "a.docx"}, scan_id="s1")
    store.claim_job("replica-a-1111:w0")

    # Still beating → nothing is orphaned.
    assert store.reclaim_orphaned_jobs(stale_seconds=90) == []

    # Beat stops. No deregistration — it was killed, not drained.
    _age_instance(store, "replica-a-1111", 200)
    rescued = store.reclaim_orphaned_jobs(stale_seconds=90)
    assert len(rescued) == 1
    assert store.get_job(rescued[0]["id"])["status"] == "queued"


# ── The rules that must NOT fire ──────────────────────────────────────────────

def test_a_live_sibling_replica_is_never_robbed(store):
    """maxReplicas is 3, so a booting instance has live siblings. A long-running job on a
    healthy sibling must survive a neighbour's restart no matter how long it has run —
    this is the failure that would make the fix worse than the bug."""
    store.register_instance("replica-a-1111")
    store.register_instance("replica-b-2222")
    slow = store.enqueue_job("scan_batch", {"n": 400}, scan_id="s1")
    store.claim_job("replica-a-1111:w0")

    # B restarts. A is alive and mid-job.
    store.register_instance("replica-b-2222")
    assert store.reclaim_orphaned_jobs(exclude="replica-b-2222") == []
    assert store.get_job(slow)["status"] == "running"

    # Even far past the lease, orphan reclaim leaves it alone: A is beating, and being
    # slow is not being dead. (The lease is a separate mechanism and still applies.)
    _age_lock(store, slow, 9999)
    assert store.reclaim_orphaned_jobs(exclude="replica-b-2222") == []
    assert store.get_job(slow)["status"] == "running"


def test_a_worker_does_not_reclaim_its_own_in_flight_jobs(store):
    """`exclude` guards the boot ordering: the reclaiming instance is registering and
    claiming at the same moment, and must not requeue what its own threads just took."""
    store.register_instance("replica-a-1111")
    store.enqueue_job("scan_file", {"file": "a.docx"}, scan_id="s1")
    store.claim_job("replica-a-1111:w0")

    # Its own registry row is somehow stale (slow first beat, paused process, clock skew)
    # — `exclude` has to hold even then, because the caller knows it is alive.
    _age_instance(store, "replica-a-1111", 500)
    assert store.reclaim_orphaned_jobs(stale_seconds=90, exclude="replica-a-1111") == []


def test_unattributable_legacy_locks_are_left_to_the_lease(store):
    """Rows locked by the old scheme carry a bare 'w0' — a thread ordinal that every
    replica reuses. It cannot be traced to a process, so it must be treated as neither
    dead nor alive: guessing dead would steal a live job during the rollout of this very
    change. The lease, which is what those rows already depended on, still covers them."""
    jid = store.enqueue_job("scan_file", {"file": "a.docx"}, scan_id="s1")
    store.claim_job("w0")                       # pre-registry lock shape

    assert store.reclaim_orphaned_jobs(stale_seconds=0) == []
    assert store.get_job(jid)["status"] == "running"

    _age_lock(store, jid, 700)
    assert store.reclaim_stuck_jobs(lease_seconds=600) == 1
    assert store.get_job(jid)["status"] == "queued"


def test_instance_of_splits_ids_and_refuses_to_guess():
    from store import Store
    assert Store.instance_of("replica-a-1111:w0") == "replica-a-1111"
    assert Store.instance_of("host-with-dashes-abc123:w15") == "host-with-dashes-abc123"
    assert Store.instance_of("w0") is None       # legacy: unattributable, not "dead"
    assert Store.instance_of(None) is None
    assert Store.instance_of("") is None


# ── Registry bookkeeping ──────────────────────────────────────────────────────

def test_a_recycled_instance_id_is_not_read_as_its_predecessors_corpse(store):
    """ACA reuses replica names. If a new process inherited the id of the one it replaced,
    registration would have to clear the death flag or the fresh process would look dead
    and its own jobs would be requeued out from under it."""
    store.register_instance("replica-a-1111")
    store.deregister_instance("replica-a-1111")
    assert "replica-a-1111" not in store.live_instances()

    store.register_instance("replica-a-1111")            # same id, new process
    assert "replica-a-1111" in store.live_instances()

    store.enqueue_job("scan_file", {"file": "a.docx"}, scan_id="s1")
    store.claim_job("replica-a-1111:w0")
    assert store.reclaim_orphaned_jobs() == []


def test_touch_instance_keeps_it_live(store):
    store.register_instance("replica-a-1111")
    _age_instance(store, "replica-a-1111", 500)
    assert "replica-a-1111" not in store.live_instances(stale_seconds=90)

    store.touch_instance("replica-a-1111")
    assert "replica-a-1111" in store.live_instances(stale_seconds=90)


def test_prune_keeps_instances_that_still_hold_a_running_job(store):
    """The registry must not shed a row that a running job still points at — losing it
    would make that job's lock unattributable and push it back onto the lease."""
    store.register_instance("replica-a-1111")
    store.register_instance("replica-b-2222")
    store.enqueue_job("scan_file", {"file": "a.docx"}, scan_id="s1")
    store.claim_job("replica-a-1111:w0")
    _age_instance(store, "replica-a-1111", 60 * 60 * 48)
    _age_instance(store, "replica-b-2222", 60 * 60 * 48)

    assert store.prune_worker_instances(older_than_hours=24) == 1
    assert store.instance_of("replica-a-1111:w0") == "replica-a-1111"
    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT id FROM worker_instances")
        assert {r["id"] for r in store._db.fetchall(cur)} == {"replica-a-1111"}


# ── The safety requirement: a reclaimed job must be safe to re-run ────────────

def test_reclaimed_scan_file_does_not_double_write_findings(store):
    """Reclaiming means re-running, and re-running a file that already persisted must
    converge on the same rows rather than accumulate a second set. This is the property
    the whole change rests on — the hang would be preferable to duplicated findings."""
    result = {
        "file": "benefits-guide.docx", "engine": "office", "status": "uncertain",
        "score": 72, "compliant": 0, "skipped_rules": 1,
        "issues": [{"ruleId": "SC_1_1_1", "wcag": "1.1.1", "severity": "serious",
                    "detail": "image missing alt text", "page": 1, "location": "p1"}],
    }
    now = datetime.now(timezone.utc).isoformat()
    store.save_file_result("s1", result, now)
    store.save_file_result("s1", result, now)          # the re-run after a reclaim

    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT COUNT(*) AS n FROM file_records WHERE scan_id=%s", ("s1",))
        assert store._db.fetchone(cur)["n"] == 1
        store._db.execute(cur, "SELECT COUNT(*) AS n FROM issue_records WHERE scan_id=%s", ("s1",))
        assert store._db.fetchone(cur)["n"] == 1, "findings must not double up on a re-run"

    # And the finalize trigger counts rows rather than incrementing, so a re-run cannot
    # push a scan past its own file count and finalize it early.
    store.init_scan_run("s1", "drive", 2, now, "r", "h")
    assert store.count_files_done("s1") == (1, 2)


def test_finalize_is_claimed_exactly_once_across_a_reclaim(store):
    """The one job whose re-run WOULD be visible: scan_finalize emits HITL routing and the
    audit row. A second run must no-op rather than route everything twice."""
    now = datetime.now(timezone.utc).isoformat()
    store.init_scan_run("s1", "drive", 1, now, "r", "h")
    assert store.mark_finalized("s1") is True
    assert store.mark_finalized("s1") is False       # the reclaimed duplicate no-ops
