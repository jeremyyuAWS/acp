from __future__ import annotations

from api.routes import system


def _scan(owner="admin@example.org"):
    return {
        "_scan_id": "scan-live-1", "owner": owner, "source": "drive",
        "started_at": "2026-09-03T12:00:00+00:00", "completed_at": None,
        "rubric": {"name": "wcag-aa", "hash": "h"},
        "summary": {"files": 2, "certifiable": 0, "uncertain": 0, "error": 0, "avg_score": 0},
        "files": [],
    }


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
        "worker_slots": 4, "available_slots": 0, "utilization_pct": 100,
        "pressure": "saturated", "worker_tier_alive": True,
        "scheduling_policy": "tenant_fair_least_loaded",
        "by_stage": {
            "assess": {"runs": 1, "running": 3, "queued": 8, "completed": 2, "total": 13},
            "remediate": {"runs": 1, "running": 1, "queued": 2, "completed": 4, "total": 7},
        },
    }
