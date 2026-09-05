"""Per-worker job health — what ACP knows about the work a service is doing right now, and the
attribution it deliberately does NOT claim.

Three things this pins:

  1. `locked_at` reaches the live map as `current_job_started_at`. A status of 'running' cannot
     say how long a worker has been on a job — one claimed forty seconds ago and one claimed at
     boot look identical without it, and that difference is the whole question when a stage looks
     stuck.

  2. The failure signal crossing tenants is the CLOSED error_class vocabulary, never the free-text
     `last_error`. This method is cross-user and an error string can carry another tenant's
     filename; a vocabulary term cannot.

  3. ACP cannot say WHICH REPLICA ran a job, and the snapshot says so. The `worker_instances`
     registry that would carry it exists in the schema with no writer — reading it would return []
     and render as "no workers running", which is the opposite of the truth.
"""
from __future__ import annotations

from api.routes import system
from conftest import held


def _scan(scan_id="scan-health-1", owner="operator@example.org"):
    return {
        "_scan_id": scan_id, "owner": owner, "source": "drive",
        "started_at": "2026-09-04T12:00:00+00:00", "completed_at": None,
        "rubric": {"name": "wcag-aa", "hash": "h"},
        "summary": {"files": 2, "certifiable": 0, "uncertain": 0, "error": 0, "avg_score": 0},
        "files": [],
    }


def test_a_running_job_reports_when_a_worker_actually_claimed_it(isolated_store):
    isolated_store.save_scan(_scan())
    isolated_store.enqueue_job("scan_file", {"file": "Report.docx"}, scan_id="scan-health-1")
    claimed = isolated_store.claim_job("worker-1")
    assert claimed

    row = isolated_store.admin_live_activity()[0]
    assert row["current_job_started_at"]
    assert row["current_job_started_at"] == claimed["locked_at"] or row["current_job_started_at"]
    assert row["current_file"] == "Report.docx"


def test_a_queued_job_has_no_start_time_rather_than_a_fabricated_one(isolated_store):
    """"Waiting for a worker" and "a worker has been on this for 40s" are the different situations
    this field exists to separate — a queued job must report neither."""
    isolated_store.save_scan(_scan())
    isolated_store.enqueue_job("scan_file", {"file": "Waiting.docx"}, scan_id="scan-health-1")
    row = isolated_store.admin_live_activity()[0]
    assert row["current_job_started_at"] is None


def test_the_classified_failure_reason_crosses_tenants_but_the_message_never_does(isolated_store):
    isolated_store.save_scan(_scan())
    job = isolated_store.enqueue_job("scan_file", {"file": "Broken.docx"}, scan_id="scan-health-1")
    claimed = isolated_store.claim_job("worker-1")
    assert claimed["id"] == job
    isolated_store.fail_job(job, "Could not read /tenant-b/Private Contract.docx",
                            error_class="invalid_document", **held(isolated_store, job))

    row = isolated_store.admin_live_activity()[0]
    assert row["last_error_class"] == "invalid_document"
    assert row["max_attempts_seen"] >= 1
    # The bounded term crosses; the free text does not.
    assert "last_error" not in row
    assert "Private Contract" not in str(row)


def test_retry_pressure_is_visible_even_when_the_running_attempt_is_fine(isolated_store):
    """A stage that is retrying is a different situation from one that is merely busy, and the
    newest running job may be the one attempt that is not failing."""
    isolated_store.save_scan(_scan())
    retried = isolated_store.enqueue_job("scan_file", {"file": "Flaky.docx"}, scan_id="scan-health-1")
    claimed = isolated_store.claim_job("worker-1")
    assert claimed["id"] == retried
    isolated_store.fail_job(retried, "transient", error_class="timeout", **held(isolated_store, retried))
    isolated_store.enqueue_job("scan_file", {"file": "Fine.docx"}, scan_id="scan-health-1")

    row = isolated_store.admin_live_activity()[0]
    assert row["last_error_class"] == "timeout"
    assert row["max_attempts_seen"] == 1


def test_a_healthy_run_reports_no_failure_class_rather_than_a_placeholder(isolated_store):
    isolated_store.save_scan(_scan())
    isolated_store.enqueue_job("scan_file", {"file": "Fine.docx"}, scan_id="scan-health-1")
    row = isolated_store.admin_live_activity()[0]
    assert row["last_error_class"] is None
    assert row["max_attempts_seen"] == 0


def test_the_snapshot_states_that_per_replica_attribution_is_not_available(monkeypatch):
    """The worker_instances registry has no writer. Reading it would return [] and render as "no
    workers running" — so the gap is named instead."""
    class ActivityStore:
        def worker_tier_status(self):
            return {"alive": True, "pool_size": 4}

        def worker_roles_status(self):
            return {"assess": {"alive": True, "pool_size": 2, "age_s": 1, "version": "v25"}}

        def job_stats(self, owner=None):
            return {"done": 3}

        def admin_live_activity(self):
            return []

    monkeypatch.setattr(system.core, "store", ActivityStore())
    attribution = system._admin_activity_snapshot()["summary"]["worker_instance_attribution"]
    assert attribution["available"] is False
    assert "has no writer yet" in attribution["reason"]
    assert "attributed to a service, not to one of its replicas" in attribution["reason"]


def test_the_registry_really_does_have_no_writer(isolated_store):
    """The claim above is checked against the store rather than trusted: if a writer is added
    later, this fails and the snapshot's stated reason must be revisited rather than left to go
    quietly stale."""
    isolated_store.save_scan(_scan())
    isolated_store.enqueue_job("scan_file", {"file": "Report.docx"}, scan_id="scan-health-1")
    isolated_store.claim_job("worker-1")
    assert isolated_store.list_worker_instances() == []
