"""A draining replica's running jobs are busy slots, not nothing.

WHY THIS EXISTS. On 2026-09-06 the Live Operations capacity gauge read "Idle -- capacity
available, 0 of 20 slots (0%)" directly above "8 documents in flight". Both numbers were
computed from the same fresh heartbeats.

`_replica_capacity` counted a process only when its state was `ready` or `busy`. A worker
draining after a deploy is neither: it keeps heartbeating for the whole bounded shutdown --
ACP_SHUTDOWN_DRAIN_SECONDS is 540 on every worker lane (deploy/public/redeploy.sh:57) -- while
its handlers finish. So for up to NINE MINUTES after each worker rollout, real work on real
slots contributed neither capacity nor utilisation, and the jobs surfaced as
`unattributed_running` instead.

THE INTENT WAS ALREADY IN THE CODE AND WAS DEFEATED ONE LAYER UP.
`worker_telemetry.WorkerInstanceReporter.draining()` exists to keep the heartbeat alive through
the drain, and its docstring says why: "Stopping this reporter before that wait made genuinely
running jobs lose their process attribution after 30 seconds." The reporter held up its end.

THE SHAPE OF THE FIX MATTERS AS MUCH AS THE FIX. A draining process must not contribute its
free slots -- it will never claim them, and counting them would invent availability on a
container that is going away. It contributes exactly the work it still holds, so it reads as
fully utilised and offers nothing. `unhealthy` is the same case: the jobs are real whatever the
process thinks of itself.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from routes.system import _replica_capacity  # noqa: E402


NOW = datetime(2026, 9, 6, 21, 0, 0, tzinfo=timezone.utc)


def instance(worker_id, replica_id, state, *, slots, active, age_s=5, anchor=None):
    """`anchor` defaults to this module's frozen NOW. The snapshot tests below pass the REAL
    clock instead: `_admin_activity_snapshot` calls `datetime.now()` itself, so a fixture
    anchored to 2026-09-06 would arrive stale and every state would read the same."""
    moment = anchor or NOW
    return {"worker_id": worker_id, "replica_id": replica_id, "state": state,
            "concurrency_limit": slots, "active_job_count": active,
            "revision_name": f"rev-of-{replica_id}",
            "last_heartbeat_at": (moment - timedelta(seconds=age_s)).isoformat()}


def capacity(instances):
    return _replica_capacity(instances, now=NOW, freshness_seconds=30)


def test_a_draining_replicas_running_jobs_are_counted_as_busy():
    """The production reading, reproduced: a rollout mid-drain beside a fresh replica."""
    row = capacity([
        instance("assess:old:p1", "old", "draining", slots=12, active=8),
        instance("assess:new:p1", "new", "ready", slots=20, active=0),
    ])["assess"]
    assert row["busy_slots"] == 8, (
        "a draining replica's running jobs vanished from utilisation; this is the "
        "'0 of 20 slots (0%)' beside '8 documents in flight' defect"
    )
    assert row["worker_slots"] == 28


def test_a_draining_replica_offers_no_free_capacity():
    """Its four idle slots are not availability -- it will never claim them."""
    row = capacity([instance("assess:old:p1", "old", "draining", slots=12, active=8)])["assess"]
    assert row["worker_slots"] == 8, (
        "a draining replica advertised free slots it can never fill"
    )
    assert row["busy_slots"] == 8


def test_an_unhealthy_process_still_holds_its_jobs():
    row = capacity([instance("assess:sick:p1", "sick", "unhealthy", slots=10, active=3)])["assess"]
    assert (row["worker_slots"], row["busy_slots"]) == (3, 3)


def test_a_draining_replica_is_neither_healthy_nor_stale():
    """It takes no new work, so it is not healthy; it is reporting, so it is not stale.

    Counting it as either would put the wrong alert on the drawer -- `stale_replicas` drives a
    warning about heartbeats that have stopped, and this replica's have not.
    """
    row = capacity([
        instance("assess:old:p1", "old", "draining", slots=12, active=8),
        instance("assess:new:p1", "new", "ready", slots=20, active=0),
    ])["assess"]
    assert row["healthy_replicas"] == 1
    assert row["stale_replicas"] == 0
    assert row["occupied_replicas"] == 1


def test_a_stale_draining_replica_still_drops_out():
    """Freshness is the gate for every state. A drain that stopped reporting is gone, and its
    jobs are the sweeper's problem, not capacity's."""
    row = capacity([
        instance("assess:old:p1", "old", "draining", slots=12, active=8, age_s=600),
        instance("assess:new:p1", "new", "ready", slots=20, active=0),
    ])["assess"]
    assert (row["worker_slots"], row["busy_slots"]) == (20, 0)
    assert row["stale_replicas"] == 1
    assert row["occupied_replicas"] == 0


def test_one_replica_running_both_a_draining_and_a_ready_process():
    """A container can run several worker processes. The two contributions accumulate on the
    same replica_id rather than one state deciding for the whole box."""
    row = capacity([
        instance("assess:box:p1", "box", "draining", slots=6, active=4),
        instance("assess:box:p2", "box", "ready", slots=6, active=1),
    ])["assess"]
    assert (row["worker_slots"], row["busy_slots"]) == (10, 5)
    assert row["healthy_replicas"] == 1


def test_offline_and_starting_processes_contribute_nothing():
    """`offline` is a process that has stopped; `starting` has not registered its pool yet.
    Neither holds work, so neither is in the occupied set."""
    row = capacity([
        instance("assess:a:p1", "a", "offline", slots=12, active=0),
        instance("assess:b:p1", "b", "starting", slots=12, active=0),
    ])["assess"]
    assert (row["worker_slots"], row["busy_slots"]) == (0, 0)
    assert row["occupied_replicas"] == 0


# --- The alert this fix would otherwise have retired -------------------------------------------

def _snapshot_with(monkeypatch, instances, *, queued):
    """Drive the real `_admin_activity_snapshot` over a stub store.

    Stubbed at the store, not at `_replica_capacity`, because the thing under test here is what
    the ALERT does with the capacity numbers -- patching the function that produces them would
    test nothing.
    """
    from routes import system as sys_mod

    class _Store:
        def worker_tier_status(self):
            return {"alive": True, "pool_size": 0}

        def worker_roles_status(self):
            return {}

        def job_stats(self, owner=None):
            return {"running_by_type": {}}

        def admin_live_activity(self):
            return [{"stage": "assess", "queued": queued, "running": 0}]

        def list_worker_instances(self):
            return instances

        def recent_orchestration_events(self, **_kwargs):
            return []

    monkeypatch.setattr(sys_mod.core, "store", _Store())
    monkeypatch.setattr(sys_mod.core, "WORKER_INSTANCE_FRESHNESS_SECONDS", 30)
    return sys_mod._admin_activity_snapshot()


def _alert_codes(snapshot, role):
    row = snapshot["summary"]["worker_capacity_by_role"].get(role) or {}
    return {alert["code"] for alert in row.get("alerts", ())}


def test_a_queue_with_only_a_draining_replica_still_raises_no_capacity(monkeypatch):
    """The regression this fix nearly introduced.

    A draining replica now contributes slots, so `worker_slots` is no longer zero for a lane that
    cannot accept a single queued job. Keying the alert on slots would have silenced it during
    precisely the rollout window it exists for; it is keyed on `healthy_replicas` instead.
    """
    snapshot = _snapshot_with(
        monkeypatch,
        [instance("assess:old:p1", "old", "draining", slots=12, active=8,
                  anchor=datetime.now(timezone.utc))],
        queued=40,
    )
    assert "no_capacity_with_queue" in _alert_codes(snapshot, "assess")


def test_a_queue_with_a_ready_replica_raises_nothing(monkeypatch):
    snapshot = _snapshot_with(
        monkeypatch,
        [instance("assess:new:p1", "new", "ready", slots=20, active=0,
                  anchor=datetime.now(timezone.utc))],
        queued=40,
    )
    assert "no_capacity_with_queue" not in _alert_codes(snapshot, "assess")
