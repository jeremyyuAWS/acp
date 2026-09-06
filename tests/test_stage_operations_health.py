from __future__ import annotations

from api.routes import system


def _execution(store):
    sid = "operations-health"
    store.enqueue_scan(sid, "sharepoint", "owner@example.org", "scan_discover",
                       {"scan_id": sid}, inputs={"source": "sharepoint"})
    return store.enqueue_stage_batch(
        sid, "remediate", "remediate_file", [{"file": "a.docx"}],
        snapshot_id="snapshot", request_fingerprint="fingerprint")


def test_cancellation_health_counts_attempts_and_overdue_deadlines(isolated_store):
    execution = _execution(isolated_store)
    job = isolated_store.claim_job("worker-1", job_types=("remediate_file",))
    current = isolated_store.get_stage_execution(execution["batch_id"])
    isolated_store.control_stage_execution(
        execution["batch_id"], "cancel", expected_revision=current["revision"])
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "UPDATE stage_attempts SET cancel_deadline_at='2000-01-01T00:00:00+00:00' "
            "WHERE job_id=%s", (job["id"],))

    overdue = isolated_store.stage_cancellation_health(owner="owner@example.org")
    assert overdue == {"awaiting_acknowledgement": 1, "overdue": 1, "escalated": 0,
                       "acknowledged": 0, "next_deadline_at": "2000-01-01T00:00:00+00:00",
                       "status": "overdue"}
    assert len(isolated_store.escalate_overdue_stage_cancellations()) == 1
    assert isolated_store.stage_cancellation_health()["status"] == "escalated"

    isolated_store.mark_job_cancelled(
        job["id"], worker_id="worker-1", attempt=job["attempts"])
    clear = isolated_store.stage_cancellation_health()
    assert clear["awaiting_acknowledgement"] == 0
    assert clear["acknowledged"] == 1
    assert clear["status"] == "clear"


def test_admin_snapshot_exposes_health_without_fabricating_missing_values(monkeypatch):
    class ActivityStore:
        def worker_tier_status(self): return {"alive": True, "pool_size": 1}
        def worker_roles_status(self): return {}
        def job_stats(self, owner=None): return {"done": 0}
        def admin_live_activity(self): return []
        def stage_outbox_health(self):
            return {"pending": 2, "claimed": 1, "retrying": 3, "delivered": 8,
                    "dead_lettered": 1, "oldest_undelivered_age_s": 42}
        def stage_cancellation_health(self):
            return {"awaiting_acknowledgement": 2, "overdue": 1, "escalated": 1,
                    "acknowledged": 4, "status": "escalated"}

    monkeypatch.setattr(system.core, "store", ActivityStore())
    summary = system._admin_activity_snapshot()["summary"]
    assert summary["canonical_delivery"]["dead_lettered"] == 1
    assert summary["cancellation_acknowledgements"]["overdue"] == 1

    monkeypatch.setattr(ActivityStore, "stage_outbox_health",
                        lambda self: (_ for _ in ()).throw(RuntimeError("old schema")))
    assert "canonical_delivery" not in system._admin_activity_snapshot()["summary"]
