from __future__ import annotations

import pytest
from fastapi import HTTPException

from api.routes import system


def _scan(owner="admin@example.org"):
    return {
        "_scan_id": "scan-live-1", "owner": owner, "source": "drive",
        "started_at": "2026-09-03T12:00:00+00:00", "completed_at": None,
        "rubric": {"name": "wcag-aa", "hash": "h"},
        "summary": {"files": 2, "certifiable": 0, "uncertain": 0, "error": 0, "avg_score": 0},
        "files": [],
    }


class _Request:
    def __init__(self, email):
        self.state = type("State", (), {"user_email": email})()


class _Response:
    def __init__(self):
        self.headers = {}


def test_live_activity_read_is_available_to_any_signed_in_user(monkeypatch):
    monkeypatch.setattr(system, "_admin_activity_snapshot", lambda: {"runs": [], "summary": {}})
    monkeypatch.setattr(system, "_azure_block", lambda: None)
    response = _Response()
    assert system.admin_activity(_Request("viewer@example.org"), response) == {
        "runs": [], "summary": {}}
    assert response.headers["Cache-Control"] == "no-store"


def test_the_first_read_carries_the_azure_block_so_the_page_is_not_blank(monkeypatch):
    """A tab that has just loaded should have the infrastructure reading immediately rather than
    waiting for the stream's next Azure frame, which is up to a TTL away."""
    monkeypatch.setattr(system, "_admin_activity_snapshot", lambda: {"runs": [], "summary": {}})
    monkeypatch.setattr(system, "_azure_block", lambda: {"configured": True, "measured_at": "t0"})
    body = system.admin_activity(_Request("viewer@example.org"), _Response())
    assert body["azure"] == {"configured": True, "measured_at": "t0"}


def test_an_azure_read_that_fails_leaves_the_topology_intact(monkeypatch):
    """None means "no Azure block", never an empty one: replacing a real reading with zeroes is
    the failure this whole surface is built to avoid."""
    monkeypatch.setattr(system, "_admin_activity_snapshot", lambda: {"runs": [], "summary": {}})
    monkeypatch.setattr(system, "_azure_block", lambda: None)
    assert "azure" not in system.admin_activity(_Request("viewer@example.org"), _Response())


def test_the_azure_block_never_takes_the_live_map_down(monkeypatch):
    """_azure_block swallows an unimportable control module, a branch without the cache, and a
    read that raises — all three degrade to None rather than propagating."""
    import routes.control as control_module
    monkeypatch.setattr(control_module, "cached_capacity",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("azure is down")))
    assert system._azure_block() is None


def test_live_activity_read_still_rejects_anonymous_users():
    with pytest.raises(HTTPException) as denied:
        system.admin_activity(_Request(""), _Response())
    assert denied.value.status_code == 401


def test_admin_live_activity_groups_active_stage_without_exposing_payload(isolated_store):
    isolated_store.save_scan(_scan())
    isolated_store.enqueue_job("scan_file", {"file": "Private Report.docx", "secret": "never-return"},
                               scan_id="scan-live-1")
    rows = isolated_store.admin_live_activity()
    assert len(rows) == 1
    assert rows[0]["stage"] == "assess"
    assert rows[0]["owner"] == "admin@example.org"
    assert rows[0]["queued"] == 1
    assert rows[0]["queue_position"] == 1
    assert rows[0]["oldest_queued_at"]
    assert rows[0]["started_at"]
    assert "payload" not in rows[0]
    assert "secret" not in str(rows[0])


def test_admin_live_activity_exposes_only_safe_running_context(isolated_store):
    isolated_store.save_scan(_scan())
    isolated_store.enqueue_job(
        "remediate_file",
        {"file": "Private Report.docx", "rule_id": "1.1.1", "secret": "never-return"},
        scan_id="scan-live-1",
    )
    claimed = isolated_store.claim_job("test-worker")
    assert claimed
    row = isolated_store.admin_live_activity()[0]
    assert row["current_file"] == "Private Report.docx"
    assert row["current_rule_id"] == "1.1.1"
    assert row["current_job_type"] == "remediate_file"
    assert "secret" not in str(row)


def test_admin_live_activity_carries_bounded_sanitized_remediation_events(isolated_store):
    isolated_store.save_scan(_scan())
    isolated_store.enqueue_job(
        "remediate_file", {"file": "Private Report.docx"}, scan_id="scan-live-1")
    for i in range(15):
        isolated_store.append_scan_event(
            "scan-live-1", "remediate.fix_applied", owner_email="admin@example.org",
            detail={"file": f"private-{i}.docx", "fixes": i, "secret": "never-return"},
        )

    row = isolated_store.admin_live_activity()[0]
    events = row["recent_events"]
    assert len(events) == 12
    assert [event["seq"] for event in events] == list(range(4, 16))
    assert events[-1]["detail"] == {"fixes": 14}
    assert "private" not in str(events)
    assert "secret" not in str(events)


def test_admin_live_activity_omits_inactive_runs(isolated_store):
    isolated_store.save_scan(_scan())
    job_id = isolated_store.enqueue_job("scan_file", {"file": "done.docx"}, scan_id="scan-live-1")
    claimed = isolated_store.claim_job("test-worker")
    assert claimed and claimed["id"] == job_id
    isolated_store.complete_job(job_id, worker_id="test-worker", attempt=claimed["attempts"])
    recent = isolated_store.admin_live_activity()
    assert len(recent) == 1
    assert recent[0]["status"] == "recent"
    assert recent[0]["completed"] == 1
    assert isolated_store.admin_live_activity(recent_seconds=0) == []


def test_admin_activity_summary_reports_capacity_stage_load_and_waiting_users(monkeypatch):
    class ActivityStore:
        def worker_tier_status(self):
            return {"alive": True, "pool_size": 4}

        def worker_roles_status(self):
            return {
                "discovery": {"alive": True, "pool_size": 3, "age_s": 1, "version": "v10"},
                "assess": {"alive": True, "pool_size": 2, "age_s": 2, "version": "v10"},
                "remediate": {"alive": True, "pool_size": 2, "age_s": 3, "version": "v10"},
                "processing": {"alive": False, "pool_size": 4, "age_s": 999, "version": "v9"},
            }

        def job_stats(self, owner=None):
            assert owner is None
            return {"done": 12}

        def admin_live_activity(self):
            return [
                {"owner": "a@example.org", "stage": "assess", "status": "active", "running": 3, "queued": 8,
                 "completed": 2, "total": 13},
                {"owner": "b@example.org", "stage": "remediate", "status": "recent", "running": 1, "queued": 2,
                 "completed": 4, "total": 7},
            ]

    monkeypatch.setattr(system.core, "store", ActivityStore())
    snapshot = system._admin_activity_snapshot()
    assert snapshot["summary"] == {
        "active_runs": 1, "recent_runs": 1, "active_users": 2, "waiting_users": 2,
        "queued": 10, "running": 4, "completed_jobs": 12,
        "worker_slots": 7, "available_slots": 3, "utilization_pct": None,
        "pressure": "busy", "worker_tier_alive": True,
        "scheduling_policy": "tenant_fair_least_loaded",
        "worker_roles": {
            "discovery": {"alive": True, "pool_size": 3, "age_s": 1, "version": "v10"},
            "assess": {"alive": True, "pool_size": 2, "age_s": 2, "version": "v10"},
            "remediate": {"alive": True, "pool_size": 2, "age_s": 3, "version": "v10"},
            "processing": {"alive": False, "pool_size": 4, "age_s": 999, "version": "v9"},
        },
        "worker_capacity_by_role": {},
        "by_stage": {
            # `findings` is None, not 0: this stub reports no findings count, and "no findings yet"
            # is a different fact from "findings were not counted for this stage".
            "assess": {"runs": 1, "running": 3, "queued": 8, "completed": 2, "total": 13,
                       "findings": None},
            "remediate": {"runs": 1, "running": 1, "queued": 2, "completed": 4, "total": 7,
                          "findings": None},
        },
        # Off unless a connection string is set — see api/telemetry.py. Reported rather than
        # omitted so the drawer can say why a trace drill-down is unavailable instead of offering
        # a link to traces that do not exist.
        "tracing": {"enabled": False, "reason": "not configured", "sampling_ratio": None,
                    "correlation": "off", "configured_at": None},
        # Stated, not omitted: ACP records which SERVICE ran a job, never which replica, because
        # the worker_instances registry that would carry that has no writer yet. Reading the empty
        # table instead would render as "no workers running".
        "worker_instance_attribution": {
            "available": False,
            "reason": "Per-replica capacity is not yet reporting. Jobs in flight are available, but slot utilization cannot be calculated honestly.",
        },
    }


def test_instance_capacity_uses_busy_slots_not_running_rows(monkeypatch):
    class ActivityStore:
        def worker_tier_status(self): return {"alive": True, "pool_size": 2}
        def worker_roles_status(self): return {"assess": {"alive": True, "pool_size": 2}}
        def job_stats(self, owner=None): return {"done": 0}
        def admin_live_activity(self):
            return [{"stage": "assess", "status": "active", "running": 40, "queued": 0,
                     "completed": 0, "total": 40}]
        def list_worker_instances(self):
            now = system.datetime.now(system.timezone.utc).isoformat()
            return [{"worker_id": f"assess:r{i}:p{i}", "replica_id": f"r{i}",
                     "last_heartbeat_at": now, "state": "busy", "concurrency_limit": 2,
                     "active_job_count": 2, "revision_name": "v1"} for i in range(10)]

    monkeypatch.setattr(system.core, "store", ActivityStore())
    summary = system._admin_activity_snapshot()["summary"]
    assess = summary["worker_capacity_by_role"]["assess"]
    assert assess["healthy_replicas"] == 10
    assert assess["worker_slots"] == 20
    assert assess["busy_slots"] == 20
    assert assess["jobs_in_flight"] == 40
    assert assess["unattributed_running"] == 20
    assert assess["utilization_pct"] == 100
    assert [alert["code"] for alert in assess["alerts"]] == ["unattributed_running"]
    assert summary["utilization_pct"] == 100


def test_multiple_processes_on_one_replica_count_as_one_replica(monkeypatch):
    class ActivityStore:
        def worker_tier_status(self): return {"alive": True, "pool_size": 2}
        def worker_roles_status(self): return {"assess": {"alive": True, "pool_size": 2}}
        def job_stats(self, owner=None): return {"done": 0}
        def admin_live_activity(self):
            return [{"stage": "assess", "status": "active", "running": 3, "queued": 0,
                     "completed": 0, "total": 3}]
        def list_worker_instances(self):
            now = system.datetime.now(system.timezone.utc).isoformat()
            return [
                {"worker_id": "assess:replica-a:p1", "replica_id": "replica-a",
                 "last_heartbeat_at": now, "state": "busy", "concurrency_limit": 2,
                 "active_job_count": 2, "revision_name": "v1"},
                {"worker_id": "assess:replica-a:p2", "replica_id": "replica-a",
                 "last_heartbeat_at": now, "state": "busy", "concurrency_limit": 2,
                 "active_job_count": 1, "revision_name": "v1"},
            ]

    monkeypatch.setattr(system.core, "store", ActivityStore())
    assess = system._admin_activity_snapshot()["summary"]["worker_capacity_by_role"]["assess"]
    assert assess["healthy_replicas"] == 1
    assert assess["worker_slots"] == 4
    assert assess["busy_slots"] == 3
    assert assess["utilization_pct"] == 75
    assert len(assess["instances"]) == 1
    assert assess["instances"][0]["replica_id"] == "replica-a"
    assert assess["instances"][0]["process_count"] == 2


def test_one_stale_process_does_not_make_its_live_replica_stale():
    now = system.datetime.now(system.timezone.utc)
    rows = system._replica_capacity([
        {"worker_id": "assess:r1:old", "replica_id": "r1", "state": "busy",
         "last_heartbeat_at": "2020-01-01T00:00:00+00:00", "concurrency_limit": 9,
         "active_job_count": 9},
        {"worker_id": "assess:r1:live", "replica_id": "r1", "state": "ready",
         "last_heartbeat_at": now.isoformat(), "concurrency_limit": 2,
         "active_job_count": 0},
    ], now=now)
    assess = rows["assess"]
    assert assess["healthy_replicas"] == 1
    assert assess["stale_replicas"] == 0
    assert assess["worker_slots"] == 2
    assert assess["instances"][0]["process_count"] == 2


def test_stale_instances_remain_visible_but_add_no_capacity(monkeypatch):
    class ActivityStore:
        def worker_tier_status(self): return {"alive": False, "pool_size": None}
        def worker_roles_status(self): return {}
        def job_stats(self, owner=None): return {"done": 0}
        def admin_live_activity(self): return []
        def list_worker_instances(self):
            return [{"worker_id": "assess:old:p1", "replica_id": "old", "state": "busy",
                     "last_heartbeat_at": "2020-01-01T00:00:00+00:00",
                     "concurrency_limit": 50, "active_job_count": 50}]

    monkeypatch.setattr(system.core, "store", ActivityStore())
    assess = system._admin_activity_snapshot()["summary"]["worker_capacity_by_role"]["assess"]
    assert assess["stale_replicas"] == 1
    assert assess["healthy_replicas"] == 0
    assert assess["worker_slots"] == 0
    assert assess["busy_slots"] == 0
    assert assess["status"] == "stale"
    assert assess["instances"][0]["fresh"] is False
    assert assess["alerts"][0]["code"] == "stale_replicas"


def test_capacity_uses_the_central_freshness_threshold(monkeypatch):
    from datetime import timedelta
    monkeypatch.setattr(system.core, "WORKER_INSTANCE_FRESHNESS_SECONDS", 90)
    now = system.datetime.now(system.timezone.utc)
    heartbeat = (now - timedelta(seconds=45)).isoformat()
    rows = system._replica_capacity([{"worker_id": "assess:r:p", "replica_id": "r",
        "state": "ready", "last_heartbeat_at": heartbeat, "concurrency_limit": 2,
        "active_job_count": 0}], now=now)
    assert rows["assess"]["healthy_replicas"] == 1
    assert rows["assess"]["freshness_threshold_seconds"] == 90
