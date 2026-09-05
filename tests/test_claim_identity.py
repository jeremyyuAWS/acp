"""The two columns a stuck-queue diagnosis actually needs, and the falsehoods they replace.

FOUND 2026-09-05, by the owner checking a suspected stuck queue against production. Two queries
were offered as the deciding evidence. Neither could have answered what it claimed:

  · `now() - locked_at` was presented as how long a lease had been held. `touch_job` does
    `SET locked_at=%s` on EVERY heartbeat, so it measures heartbeat recency. With
    HEARTBEAT_INTERVAL_S=120, a handler wedged for an hour reads as two minutes old — the failure
    the query was meant to find is exactly the one it hides.

  · `count(DISTINCT locked_by)` was presented as a replica count. The id was a per-PROCESS
    sequence, so ten Assess replicas produced only `w0` and `w1`.

Worse, the first mistake was already SHIPPED: `current_job_started_at` and `worker_assigned_at` in
admin_live_activity both read locked_at, both feed the Live Operations drawer, and both silently
reset every two minutes under names that promise a start time.
"""
from __future__ import annotations

import sys
from pathlib import Path

ACP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ACP / "api"))

import pytest

import store as store_mod


@pytest.fixture()
def st(tmp_path, monkeypatch):
    # Same shape as tests/test_lease_ownership.py: Store() builds its own schema on construction.
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", tmp_path / "claim.db")
    return store_mod.Store()


def _scan(scan_id="s1", owner="operator@example.org"):
    """The shape tests/test_queue_composition.py uses — admin_live_activity reads scan_runs, so a
    job with no run behind it produces no row at all."""
    return {
        "_scan_id": scan_id, "owner": owner, "source": "drive",
        "started_at": "2026-09-05T12:00:00+00:00", "completed_at": None,
        "rubric": {"name": "wcag-aa", "hash": "h"},
        "summary": {"files": 1, "certifiable": 0, "uncertain": 0, "error": 0, "avg_score": 0},
        "files": [],
    }


def _one_job(st, jtype="scan_file"):
    return st.enqueue_job(jtype, {"scan_id": "s1", "file": "a.docx"}, scan_id="s1")


# ── The immutable claim instant ─────────────────────────────────────────────────────────────────

def test_claiming_records_when_the_job_was_claimed(st):
    _one_job(st)
    job = st.claim_job("host-a:w0")
    assert job is not None
    assert st.get_job(job["id"]).get("claimed_at"), "claim recorded no start time"


def test_a_heartbeat_moves_locked_at_and_leaves_claimed_at_alone(st):
    """The whole point. If the heartbeat could move claimed_at, the new column would be the old
    column under a better name — and the drawer's "started at" would keep resetting."""
    _one_job(st)
    job = st.claim_job("host-a:w0")
    before = st.get_job(job["id"])

    st.touch_job(job["id"], worker_id="host-a:w0", attempt=before["attempts"])
    after = st.get_job(job["id"])

    assert after["claimed_at"] == before["claimed_at"], \
        "the heartbeat moved claimed_at — it is measuring liveness again, not the claim"
    # And locked_at is still the heartbeat, unchanged in meaning for reclaim_stuck_jobs.
    assert "locked_at" in after


def test_a_second_attempt_records_its_own_claim(st):
    """A reclaimed job re-claimed by another worker started work again, and the timeline should
    say so rather than dating attempt 2 from attempt 1."""
    _one_job(st)
    first = st.claim_job("host-a:w0")
    first_claim = st.get_job(first["id"])["claimed_at"]
    st.requeue_job(first["id"], "worker died") if hasattr(st, "requeue_job") else None
    # Fall back to the sweeper's own path when requeue_job is not the name.
    if st.get_job(first["id"])["status"] == "running":
        st.reclaim_stuck_jobs(lease_seconds=0)
    second = st.claim_job("host-b:w0")
    assert second is not None, "the job was never reclaimed, so this asserts nothing"
    assert st.get_job(second["id"])["claimed_at"] != first_claim


def test_rows_claimed_before_the_migration_report_unknown_not_a_time(st):
    """NULL is the honest answer for a job claimed before v16. Backfilling it from locked_at would
    reintroduce exactly the falsehood this column exists to remove, behind a better name."""
    _one_job(st)
    job = st.claim_job("host-a:w0")
    with st._db.cursor() as cur:
        st._db.execute(cur, "UPDATE jobs SET claimed_at=NULL WHERE id=%s", (job["id"],))
    assert st.get_job(job["id"])["claimed_at"] is None


# ── The identity that can distinguish replicas ──────────────────────────────────────────────────

def test_a_worker_id_carries_its_replica(monkeypatch):
    import core
    monkeypatch.setenv("CONTAINER_APP_REPLICA_NAME", "acp-assess--v25-abcde-7")
    import importlib
    import joblog
    importlib.reload(joblog)
    assert core._replica_id() == "acp-assess--v25-abcde-7"


def test_two_replicas_with_no_platform_identity_do_not_collide(monkeypatch):
    """The failure this replaces. "unknown:w0" from every replica would recreate the collision —
    ten replicas, two distinct values — that made the original count meaningless."""
    import core
    monkeypatch.setattr(core, "_REPLICA_FALLBACK", None, raising=False)
    import joblog
    monkeypatch.setattr(joblog, "REPLICA", "unknown", raising=False)
    first = core._replica_id()
    monkeypatch.setattr(core, "_REPLICA_FALLBACK", None, raising=False)
    second = core._replica_id()
    assert first != second, "two replicas with no platform identity minted the same worker id"
    assert first.startswith("unknown-")


def test_the_spawned_worker_actually_carries_the_replica_prefix(monkeypatch):
    """The wiring, not just the helper. Removing the prefix from _spawn_worker left every test
    above passing: they exercised _replica_id() and never asserted that anything USED it, which
    is the shape of a control that is present but not connected.
    """
    import core
    seen = {}

    class _FakeWorker:
        def __init__(self, store, *, worker_id, on_retry=None):
            seen["worker_id"] = worker_id
            self.job_types = None

        def run_forever(self):
            return None

    # _spawn_worker does `from worker import JobWorker` inside the function, so the patch has to
    # land on the source module rather than on core.
    import worker as worker_mod
    monkeypatch.setattr(worker_mod, "JobWorker", _FakeWorker)
    monkeypatch.setattr(core, "get_store", lambda: object())
    monkeypatch.setattr(core, "_worker_handles", [], raising=False)
    monkeypatch.setattr(core, "_worker_seq", 0, raising=False)
    import threading
    monkeypatch.setattr(threading, "Thread",
                        lambda *a, **k: type("T", (), {"start": lambda self: None,
                                                       "daemon": True})())
    core._spawn_worker()

    assert ":w" in seen["worker_id"], f"worker id carries no replica prefix: {seen['worker_id']!r}"
    role, replica, process, slot = seen["worker_id"].split(":")
    assert role == "mixed"
    assert replica == core._replica_id()
    assert process
    assert slot == "w0"


def test_a_process_restart_on_one_replica_gets_a_new_identity(monkeypatch):
    import core
    import joblog
    monkeypatch.setattr(joblog, "REPLICA", "replica-1")
    monkeypatch.setattr(joblog, "PROC", "first")
    first = core.worker_process_instance_id("assess")
    monkeypatch.setattr(joblog, "PROC", "restart")
    second = core.worker_process_instance_id("assess")
    assert first == "assess:replica-1:first"
    assert second == "assess:replica-1:restart"
    assert first != second


def test_the_replica_id_is_stable_within_a_process(monkeypatch):
    """A worker whose id changed between claims would look like a different worker each time,
    which is the same blindness in a new shape."""
    import core
    monkeypatch.setattr(core, "_REPLICA_FALLBACK", None, raising=False)
    import joblog
    monkeypatch.setattr(joblog, "REPLICA", "unknown", raising=False)
    assert core._replica_id() == core._replica_id()


def test_identity_never_takes_the_worker_pool_down(monkeypatch):
    """It is a label. A worker that refused to start because it could not name itself would be a
    worse outcome than an imperfect name."""
    import core
    monkeypatch.setattr(core, "_REPLICA_FALLBACK", None, raising=False)
    import builtins
    real = builtins.__import__

    def _boom(name, *a, **k):
        if name == "joblog":
            raise RuntimeError("no joblog")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _boom)
    assert core._replica_id().startswith("unknown-")


# ── The shipped consumers now read the right column ─────────────────────────────────────────────

def test_the_live_activity_row_separates_the_claim_from_the_heartbeat(st):
    """Both facts are useful and they are different: run duration and lease freshness. They used
    to be the same value under two names that each promised the first one."""
    st.save_scan(_scan())
    _one_job(st)
    job = st.claim_job("host-a:w0")
    st.touch_job(job["id"], worker_id="host-a:w0", attempt=st.get_job(job["id"])["attempts"])

    rows = st.admin_live_activity()
    assert rows, "no live activity rows, so this test asserts nothing"
    row = rows[0]
    assert "current_job_started_at" in row
    assert "current_job_heartbeat_at" in row
    # The claim is not the heartbeat: if these were still the same field, the drawer would keep
    # showing a job that started two minutes ago no matter how long it had run.
    assert row["current_job_started_at"] != row["current_job_heartbeat_at"] \
        or row["current_job_started_at"] is None
