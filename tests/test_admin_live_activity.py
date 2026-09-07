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
    monkeypatch.setattr(system.core, "is_admin", lambda email: False)
    monkeypatch.setattr(system, "_azure_block", lambda: None)
    response = _Response()
    assert system.admin_activity(_Request("viewer@example.org"), response) == {
        "runs": [], "workflows": [], "summary": {
            "active_runs": 0, "recent_runs": 0, "active_workflows": 0,
            "recent_workflows": 0, "active_users": 0, "waiting_users": 0}}
    assert response.headers["Cache-Control"] == "no-store"


def test_non_admin_live_activity_is_scoped_to_the_viewer(monkeypatch):
    monkeypatch.setattr(system.core, "is_admin", lambda email: False)
    monkeypatch.setattr(system, "_admin_activity_snapshot", lambda: {
        "runs": [
            {"scan_id": "mine", "owner": "viewer@example.org"},
            {"scan_id": "other", "owner": "other@example.org"},
        ],
        "workflows": [
            {"workflow_id": "mine", "owner_display_name": "viewer@example.org"},
            {"workflow_id": "other", "owner_display_name": "other@example.org"},
        ],
        "summary": {"worker_slots": 12},
    })
    body = system.admin_activity(_Request("viewer@example.org"), _Response())
    assert [row["scan_id"] for row in body["runs"]] == ["mine"]
    assert [row["workflow_id"] for row in body["workflows"]] == ["mine"]
    assert body["summary"]["worker_slots"] == 12


def test_admin_live_activity_keeps_authorized_cross_user_workflows(monkeypatch):
    """An admin still sees the whole fleet — the rows, the counts, the stages.

    This used to assert the snapshot came back as the SAME OBJECT. It no longer can: an admin now
    receives a copy with other tenants' document names removed. What the test is named for is
    unchanged and is what it asserts instead — the cross-user rows are still there.
    """
    monkeypatch.setattr(system.core, "is_admin", lambda email: True)
    snapshot = {"runs": [{"owner": "other@example.org", "stage": "assess", "running": 3}],
                "workflows": [{"owner_display_name": "other@example.org"}], "summary": {}}
    scoped = system._scope_activity_snapshot(snapshot, "admin@example.org")

    assert [row["owner"] for row in scoped["runs"]] == ["other@example.org"]
    assert scoped["workflows"] == snapshot["workflows"]
    # The operational facts survive; only the name would have gone, and this row has none.
    assert scoped["runs"][0]["stage"] == "assess"
    assert scoped["runs"][0]["running"] == 3
    # And the source snapshot is not mutated by the per-viewer copy.
    assert "file_redacted" not in snapshot["runs"][0]


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


def test_live_ops_cancel_is_admin_gated_and_stage_scoped(monkeypatch):
    calls = []
    monkeypatch.setattr(system, "_require_admin", lambda request: calls.append(("guard", request)))
    monkeypatch.setattr(system.core.store, "get_scan",
                        lambda scan_id: {"_scan_id": scan_id, "files": 4})
    monkeypatch.setattr(system.core.store, "request_stage_cancel",
                        lambda scan_id, stage, actor: {"found": True, "batch_id": "b1",
                                                       "cancelled": 3, "requested": 1,
                                                       "actor": actor})
    request = _Request("admin@example.org")
    result = system.cancel_workflow_stage("scan-1", "assess", request)
    assert calls == [("guard", request)]
    assert result == {"workflow_id": "scan-1", "stage": "assess", "found": True,
                      "batch_id": "b1", "cancelled": 3, "requested": 1,
                      "actor": "admin@example.org"}


def test_live_ops_discover_cancel_uses_the_existing_whole_scan_stop(monkeypatch):
    monkeypatch.setattr(system, "_require_admin", lambda request: None)
    monkeypatch.setattr(system.core.store, "get_scan", lambda scan_id: {"_scan_id": scan_id})
    monkeypatch.setattr(system.core.store, "cancel_scan", lambda scan_id: True)
    workflow_updates = []
    monkeypatch.setattr(system.core.store, "_update_workflow_stage",
                        lambda *args: workflow_updates.append(args))
    monkeypatch.setattr(system.core.store, "_stage_owner", lambda scan_id: "owner@example.org")
    events = []
    monkeypatch.setattr(system.core.store, "append_orchestration_event",
                        lambda **event: events.append(event))
    result = system.cancel_workflow_stage("scan-1", "discover", _Request("admin@example.org"))
    assert result["stage"] == "discover" and result["cancelled"] == 1
    assert events[0]["kind"] == "job.stage_cancelled"
    assert events[1]["detail"]["requested_by"] == "admin@example.org"
    assert workflow_updates == [("scan-1", "discover", "cancelled")]


def test_live_ops_cancel_still_refuses_an_unknown_stage(monkeypatch):
    monkeypatch.setattr(system, "_require_admin", lambda request: None)
    with pytest.raises(HTTPException) as denied:
        system.cancel_workflow_stage("scan-1", "archive", _Request("admin@example.org"))
    assert denied.value.status_code == 400


def test_live_ops_resume_uses_existing_durable_remediation_hold(monkeypatch):
    monkeypatch.setattr(system, "_require_admin", lambda request: None)
    monkeypatch.setattr(system.core.store, "get_scan", lambda scan_id: {"_scan_id": scan_id})
    monkeypatch.setattr(system.core.store, "remediation_run_paused", lambda scan_id: True)
    monkeypatch.setattr(system.core.store, "_stage_owner", lambda scan_id: "owner@example.org")
    events = []
    monkeypatch.setattr(system.core.store, "append_orchestration_event",
                        lambda **event: events.append(event))
    monkeypatch.setattr(system.core.store, "resume_remediation_run",
                        lambda scan_id, actor: {"resumed_at": "now", "released": 2})
    result = system.resume_workflow_remediation("scan-1", _Request("admin@example.org"))
    assert result["paused"] is False
    assert result["released"] == 2
    assert events[0]["detail"]["requested_by"] == "admin@example.org"


def test_live_ops_resume_refuses_to_invent_a_pause(monkeypatch):
    monkeypatch.setattr(system, "_require_admin", lambda request: None)
    monkeypatch.setattr(system.core.store, "get_scan", lambda scan_id: {"_scan_id": scan_id})
    monkeypatch.setattr(system.core.store, "remediation_run_paused", lambda scan_id: False)
    with pytest.raises(HTTPException) as denied:
        system.resume_workflow_remediation("scan-1", _Request("admin@example.org"))
    assert denied.value.status_code == 409


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


def test_admin_live_activity_exposes_the_durable_remediation_hold(isolated_store):
    isolated_store.save_scan(_scan())
    isolated_store.enqueue_stage_batch(
        "scan-live-1", "remediate", "remediate_file", [{"file": "Private Report.docx"}],
        snapshot_id="remediate-1", request_fingerprint="remediate")
    isolated_store.pause_remediation_run("scan-live-1", actor="operator@example.org")
    row = isolated_store.admin_live_activity()[0]
    assert row["stage"] == "remediate"
    assert row["paused"] is True
    assert "paused_by" not in row


def test_admin_live_activity_exposes_a_running_stage_cancellation_request(isolated_store):
    isolated_store.save_scan(_scan())
    job_id = isolated_store.enqueue_job(
        "scan_assess", {"file": "Private Report.docx"}, scan_id="scan-live-1", batch_id="batch-1")
    claimed = isolated_store.claim_job("test-worker")
    assert claimed and claimed["id"] == job_id

    result = isolated_store.request_stage_cancel(
        "scan-live-1", "assess", actor="operator@example.org")
    assert result["requested"] == 1
    row = isolated_store.admin_live_activity()[0]
    assert row["cancel_requested"] is True
    assert row["cancel_requested_at"]
    assert "operator@example.org" not in str(row)


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


def test_recent_failed_stage_is_visible_to_the_workflow_contract(isolated_store):
    isolated_store.save_scan(_scan())
    isolated_store.enqueue_job("scan_file", {"file": "broken.docx"}, scan_id="scan-live-1")
    claimed = isolated_store.claim_job("test-worker")
    assert claimed
    isolated_store.fail_job(claimed["id"], "broken", worker_id="test-worker",
                            attempt=claimed["attempts"], force_dead=True)
    run = isolated_store.admin_live_activity()[0]
    assert run["failed"] == 1
    assert run["status"] == "failed"
    workflow = system._workflow_rows([run])[0]
    assert workflow["status"] == "failed"
    assert workflow["stages"][0]["failed"] == 1


def test_workflow_contract_groups_stages_under_the_scan_identity():
    rows = system._workflow_rows([
        {"scan_id": "scan-1", "owner": "owner@example.org", "source": "sharepoint",
         "stage": "assess", "status": "active", "running": 2, "queued": 1,
         "completed": 3, "total": 6, "started_at": "2026-09-05T10:05:00+00:00",
         "updated_at": "2026-09-05T10:08:00+00:00", "max_attempts_seen": 2},
        {"scan_id": "scan-1", "owner": "owner@example.org", "source": "sharepoint",
         "stage": "discover", "status": "recent", "running": 0, "queued": 0,
         "completed": 1, "total": 1, "started_at": "2026-09-05T10:00:00+00:00",
         "updated_at": "2026-09-05T10:04:00+00:00", "max_attempts_seen": 1},
    ])
    assert len(rows) == 1
    workflow = rows[0]
    assert workflow["workflow_id"] == workflow["scan_id"] == "scan-1"
    assert workflow["status"] == "running"
    assert workflow["current_stage"] == "assess"
    assert workflow["created_at"] == "2026-09-05T10:00:00+00:00"
    assert [stage["stage"] for stage in workflow["stages"]] == ["discover", "assess"]
    assert workflow["stages"][0]["status"] == "completed"
    assert workflow["stages"][1]["stage_run_id"] == "scan-1:assess"
    assert workflow["stages"][1]["attempt"] == 2


def test_workflow_contract_uses_the_durable_stage_execution_and_completion_time():
    run = {"scan_id": "scan-1", "owner": "owner@example.org", "source": "sharepoint",
           "stage": "assess", "status": "recent", "running": 0, "queued": 0,
           "completed": 2, "total": 2, "started_at": "2026-09-05T10:00:00+00:00",
           "updated_at": "2026-09-05T10:10:00+00:00", "max_attempts_seen": 1}
    events = [
        {"event_id": "start", "kind": "job.stage_started", "scan_id": "scan-1",
         "stage": "assess", "correlation_id": "batch-42",
         "occurred_at": "2026-09-05T10:01:00+00:00"},
        {"event_id": "done", "kind": "job.stage_completed", "scan_id": "scan-1",
         "stage": "assess", "correlation_id": "batch-42",
         "occurred_at": "2026-09-05T10:09:00+00:00"},
    ]

    stage = system._workflow_rows([run], events)[0]["stages"][0]
    assert stage["stage_run_id"] == "batch-42"
    assert stage["started_at"] == "2026-09-05T10:01:00+00:00"
    assert stage["completed_at"] == "2026-09-05T10:09:00+00:00"
    assert stage["completion_recorded"] is True


def test_workflow_contract_carries_only_safe_durable_stage_events():
    run = {"scan_id": "scan-1", "owner": "owner@example.org", "source": "sharepoint",
           "stage": "assess", "status": "active", "running": 1, "queued": 0,
           "completed": 0, "total": 2}
    events = [{"event_id": "start", "kind": "job.stage_started", "scan_id": "scan-1",
               "stage": "assess", "correlation_id": "batch-42",
               "occurred_at": "2026-09-05T10:01:00+00:00", "attempt": 1,
               "detail": {"documents": 2, "filename": "patient-name.docx", "secret": "no"}},
              {"event_id": "unknown", "kind": "job.internal_debug", "scan_id": "scan-1",
               "stage": "assess", "occurred_at": "2026-09-05T10:02:00+00:00"}]

    workflow = system._workflow_rows([run], events)[0]
    assert workflow["events"] == [{
        "event_id": "start", "kind": "job.stage_started", "stage": "assess",
        "occurred_at": "2026-09-05T10:01:00+00:00", "correlation_id": "batch-42",
        "attempt": 1, "error_class": None, "detail": {"documents": 2},
    }]


def test_workflow_contract_keeps_completed_stage_after_queue_tail_expires():
    events = [
        {"event_id": "start", "kind": "job.stage_started", "scan_id": "scan-old",
         "stage": "discover", "correlation_id": "batch-old", "owner_email": "a@example.org",
         "source": "sharepoint", "occurred_at": "2026-09-05T08:00:00+00:00"},
        {"event_id": "done", "kind": "job.stage_completed", "scan_id": "scan-old",
         "stage": "discover", "correlation_id": "batch-old", "owner_email": "a@example.org",
         "source": "sharepoint", "occurred_at": "2026-09-05T08:02:00+00:00",
         "attempt": 1, "detail": {"documents": 12}},
    ]

    workflow = system._workflow_rows([], events)[0]
    assert workflow["workflow_id"] == "scan-old"
    assert workflow["owner_display_name"] == "a@example.org"
    assert workflow["source"] == "sharepoint"
    assert workflow["status"] == "completed"
    assert workflow["stages"][0]["stage_run_id"] == "batch-old"
    assert workflow["stages"][0]["completed"] == 12
    assert workflow["stages"][0]["completion_recorded"] is True


def test_workflow_contract_keeps_a_durable_failed_stage_after_queue_tail_expires():
    events = [{"event_id": "failed", "kind": "job.stage_failed", "scan_id": "scan-failed",
               "stage": "assess", "correlation_id": "batch-failed",
               "owner_email": "a@example.org", "source": "sharepoint", "error_class": "timeout",
               "occurred_at": "2026-09-05T08:02:00+00:00", "attempt": 5,
               "detail": {"documents": 12, "completed": 9, "failed": 3}}]
    stage = system._workflow_rows([], events)[0]["stages"][0]
    assert stage["status"] == "failed"
    assert stage["terminal_outcome"] == "failed"
    assert stage["error_class"] == "timeout"
    assert stage["completion_recorded"] is False


def test_workflow_contract_keeps_a_manual_stop_distinct_after_queue_tail_expires():
    events = [{"event_id": "stopped", "kind": "job.stage_cancelled", "scan_id": "scan-stop",
               "stage": "assess", "correlation_id": "batch-stop",
               "owner_email": "a@example.org", "source": "sharepoint",
               "occurred_at": "2026-09-05T08:02:00+00:00", "attempt": 1,
               "detail": {"documents": 12, "completed": 9, "cancelled": 3}}]
    stage = system._workflow_rows([], events)[0]["stages"][0]
    assert stage["status"] == "cancelled"
    assert stage["terminal_outcome"] == "cancelled"
    assert stage["error_class"] is None


def test_workflow_contract_flags_a_running_stage_with_a_stale_worker_heartbeat():
    run = {"scan_id": "scan-stalled", "stage": "assess", "owner": "a@example.org",
           "source": "sharepoint", "running": 1, "queued": 0, "completed": 3, "total": 12,
           "started_at": "2020-01-01T00:00:00+00:00", "updated_at": "2020-01-01T00:01:00+00:00",
           "current_job_heartbeat_at": "2020-01-01T00:01:00+00:00"}
    stage = system._workflow_rows([run])[0]["stages"][0]
    assert stage["stalled"] is True
    assert stage["waiting_reason"] == "worker_heartbeat_stale"


def test_workflow_contract_carries_the_stop_request_into_the_stage():
    run = {"scan_id": "scan-stopping", "stage": "assess", "owner": "a@example.org",
           "source": "drive", "running": 1, "queued": 0, "completed": 3, "total": 12,
           "cancel_requested": True, "cancel_requested_at": "2026-09-05T10:03:00+00:00"}
    stage = system._workflow_rows([run])[0]["stages"][0]
    assert stage["cancel_requested"] is True
    assert stage["cancel_requested_at"] == "2026-09-05T10:03:00+00:00"

    workflow = system._workflow_rows([run])[0]
    assert workflow["status"] == "stopping"


def test_recovery_summary_matches_only_requested_stage_cancellations():
    events = [
        {"kind": "workflow.stage_cancel_requested", "scan_id": "s1", "stage": "assess",
         "correlation_id": "b1", "occurred_at": "2026-09-05T10:00:00+00:00"},
        {"kind": "job.stage_cancelled", "scan_id": "s1", "stage": "assess",
         "correlation_id": "b1", "occurred_at": "2026-09-05T10:01:00+00:00"},
        {"kind": "job.stage_cancelled", "scan_id": "s2", "stage": "discover",
         "correlation_id": "unrequested", "occurred_at": "2026-09-05T10:02:00+00:00"},
        {"kind": "workflow.stage_resumed", "scan_id": "s3", "stage": "remediate",
         "correlation_id": "r1", "occurred_at": "2026-09-05T10:03:00+00:00"},
    ]
    assert system._recovery_summary(events) == {
        "window_hours": 24, "cancel_requests": 1, "cancel_resolved": 1,
        "cancel_pending": 0, "resumes": 1,
        "cancel_success_pct": 100, "median_cancel_seconds": 60,
        "latest_action_at": "2026-09-05T10:03:00+00:00",
    }


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
        "active_workflows": 0,
        "recent_workflows": 0,
        "workflow_correlation": {"attributed_stage_runs": 2,
                                 "unlinked_active_jobs": None, "complete": None},
        "recovery": {"window_hours": 24, "cancel_requests": 0, "cancel_resolved": 0,
                     "cancel_pending": 0, "cancel_success_pct": None,
                     "median_cancel_seconds": None, "resumes": 0, "latest_action_at": None},
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
        # Stated, not omitted: a store that has not reported per-replica CAPACITY says so, rather
        # than rendering as "no workers running" from an empty read.
        "worker_instance_attribution": {
            "available": False,
            "reason": "Per-replica capacity is not yet reporting. Jobs in flight are available, but slot utilization cannot be calculated honestly.",
        },
        # Per-replica JOB PLACEMENT is a separate question with a separate answer — `locked_by`
        # carries the Container Apps replica name, so it needs no Azure call. This stub is an
        # older store shape without the method, which reads as unavailable rather than as an idle
        # fleet. See tests/test_replica_job_attribution.py.
        "job_attribution": {
            "available": False, "replicas": [], "attributed": None, "unattributed": None,
            "reason": "This deployment's job store does not report per-replica attribution.",
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


def test_activity_signature_includes_durable_workflow_changes():
    base = {"runs": [], "summary": {"running": 0}, "workflows": [
        {"scan_id": "s1", "stages": [{"stage": "assess", "status": "active"}]},
    ]}
    changed = {**base, "workflows": [
        {"scan_id": "s1", "stages": [{"stage": "assess", "status": "completed"}]},
    ]}
    assert system._activity_signature(base) != system._activity_signature(changed)


def test_workflow_rows_use_canonical_counts_and_manual_stop_state():
    run = {"scan_id": "s1", "stage": "assess", "owner": "a@example.org", "source": "drive",
           "status": "active", "running": 9, "queued": 8, "failed": 7, "completed": 6,
           "total": 30, "started_at": "2026-09-06T00:00:00+00:00",
           "updated_at": "2026-09-06T00:01:00+00:00"}
    canonical = {"s1": {"available": True, "workflow_revision": 2, "stages": [{
        "stage": "assess", "execution_id": "execution-1", "workflow_revision": 2,
        "revision": 4, "state": "cancelled", "last_durable_update_at": "2026-09-06T00:02:00+00:00",
        "counts": {"work_items": {"unit": "work items", "total": 5, "completed": 2,
                   "processing": 0, "queued": 0, "failed": 0, "cancelled": 2, "skipped": 1}},
        "control": {"cancel_requested": True, "cancel_requested_at": "2026-09-06T00:01:30+00:00"},
        "reconciliation": {"exact": True}, "integrity": {"ok": True},
    }]}}
    workflow = system._workflow_rows([run], canonical_lineages=canonical)[0]
    stage = workflow["stages"][0]
    assert (stage["total"], stage["completed"], stage["cancelled"], stage["skipped"]) == (5, 2, 2, 1)
    assert stage["status"] == "cancelled"
    assert stage["terminal_outcome"] == "cancelled"
    assert stage["stage_run_id"] == "execution-1"
    assert stage["canonical"]["revision"] == 4
    assert workflow["status"] == "stopped"


def test_liveops_canonical_lineage_read_is_safe_during_rolling_deploy(monkeypatch):
    class Store:
        def canonical_stage_lineage(self, scan_id):
            if scan_id == "bad":
                raise RuntimeError("old replica")
            return {"available": True, "scan_id": scan_id, "stages": []}

    monkeypatch.setattr(system.core, "store", Store())
    assert system._liveops_canonical_lineages(
        [{"scan_id": "good"}, {"scan_id": "bad"}], [{"scan_id": "event-only"}]) == {
            "event-only": {"available": True, "scan_id": "event-only", "stages": []},
            "good": {"available": True, "scan_id": "good", "stages": []},
        }


def test_liveops_projects_remediation_finding_units_from_one_durable_snapshot(monkeypatch):
    class Store:
        def canonical_stage_lineage(self, scan_id):
            return {"available": True, "scan_id": scan_id,
                    "stages": [{"stage": "remediate", "execution_id": "e1"}]}

        def remediation_run_facts(self, scan_id):
            return {"scan_id": scan_id, "batch_id": "b1", "total_findings": 7,
                    "finding_reconciliation": {"assessed": 7, "resolved_verified": 4,
                        "awaiting_review": 3, "approved_pending_verification": 0,
                        "unchanged_no_fix": 0, "failed": 0, "excluded": 0,
                        "superseded": 0, "accounted": 7, "unaccounted": 0,
                        "exact": True},
                    "review_findings": 3, "review_items": 1, "jobs": [],
                    "fixes_applied": 9, "fixes_verified": 8}

    monkeypatch.setattr(system.core, "store", Store())
    remediate = system._liveops_canonical_lineages([{"scan_id": "s1"}])["s1"]["stages"][0]
    accounting = remediate["finding_accounting"]
    assert accounting["finding_reconciliation"]["assessed"] == 7
    assert accounting["finding_reconciliation"]["accounted"] == 7
    assert accounting["review"] == {"documents": 0, "items": 1, "findings": 3}
    assert accounting["fixes"]["verified"] == 8
