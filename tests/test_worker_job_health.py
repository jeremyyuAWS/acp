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
    """A store that reports no worker instances says so, rather than rendering as "no workers".

    The registry DOES have a writer now (worker_telemetry.WorkerInstanceReporter, started from
    both entry points), so this is about a store that has not reported YET — a fresh deployment,
    a mixed-version rollout, or a fake store like the one below — not about a permanently empty
    table. Per-replica JOB placement is a separate question with a separate answer; see
    `job_attribution` and tests/test_replica_job_attribution.py."""
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
    assert "not yet reporting" in attribution["reason"]
    assert "cannot be calculated honestly" in attribution["reason"]


def test_claiming_a_job_does_not_fabricate_process_telemetry(isolated_store):
    """Only a process heartbeat may register capacity; a durable claim is not one."""
    isolated_store.save_scan(_scan())
    isolated_store.enqueue_job("scan_file", {"file": "Report.docx"}, scan_id="scan-health-1")
    isolated_store.claim_job("worker-1")
    assert isolated_store.list_worker_instances() == []


def test_running_jobs_by_type_counts_durable_rows_without_payloads(isolated_store):
    isolated_store.enqueue_job("scan_assess", {"file": "Private.docx"})
    isolated_store.enqueue_job("scan_assess", {"file": "Other.docx"})
    isolated_store.enqueue_job("remediate_file", {"file": "Third.docx"})
    isolated_store.claim_job("w1", job_types=("scan_assess",))
    isolated_store.claim_job("w2", job_types=("scan_assess",))
    isolated_store.claim_job("w3", job_types=("remediate_file",))
    assert isolated_store.running_jobs_by_type() == {"scan_assess": 2, "remediate_file": 1}


def test_every_in_flight_job_is_reported_with_its_phase(isolated_store):
    """`current_file` names whichever running row came back first.

    A stage with several jobs in flight therefore named ONE document, and Live Operations read as
    though a saturated service were barely working. `in_flight` carries them all, each with the
    phase the handler writes as it works — a column this query did not select at all.
    """
    isolated_store.save_scan(_scan())
    ids = []
    for name in ("Handbook.docx", "Policy.pdf", "Notes.pptx"):
        ids.append(isolated_store.enqueue_job("scan_file", {"file": name}, scan_id="scan-health-1"))
    for i, job_id in enumerate(ids):
        assert isolated_store.claim_job(f"assess:rep-a:proc:w{i}") is not None
    isolated_store.set_job_phase(ids[0], "remediating")
    isolated_store.set_job_phase(ids[1], "verifying")

    row = [r for r in isolated_store.admin_live_activity() if r["stage"] == "assess"][0]
    in_flight = {job["file"]: job for job in row["in_flight"]}

    assert set(in_flight) == {"Handbook.docx", "Policy.pdf", "Notes.pptx"}
    assert in_flight["Handbook.docx"]["phase"] == "remediating"
    assert in_flight["Policy.pdf"]["phase"] == "verifying"
    # None, not a phase guessed from the job type: a handler that has written nothing has not
    # reported, and inventing "processing" would be a guess dressed as a measurement.
    assert in_flight["Notes.pptx"]["phase"] is None
    # Claim instant, never locked_at — touch_job rewrites locked_at on every heartbeat.
    assert all(job["started_at"] for job in row["in_flight"])
    assert all(job["job_id"] for job in row["in_flight"])

    # current_* is unchanged, so every existing reader of this shape behaves exactly as before.
    assert row["current_file"] in in_flight
    assert row["current_job_type"] == "scan_file"


def test_the_in_flight_list_is_bounded(isolated_store):
    """A live panel refreshed every two seconds is not the place for an unbounded list."""
    from api.store import _IN_FLIGHT_LIMIT

    isolated_store.save_scan(_scan())
    for i in range(_IN_FLIGHT_LIMIT + 5):
        job_id = isolated_store.enqueue_job("scan_file", {"file": f"Doc{i}.docx"},
                                            scan_id="scan-health-1")
        assert isolated_store.claim_job(f"assess:rep-a:proc:w{i}") is not None

    row = [r for r in isolated_store.admin_live_activity() if r["stage"] == "assess"][0]
    assert len(row["in_flight"]) == _IN_FLIGHT_LIMIT
    # The stage's own running count is NOT capped — the bound is on what is listed, not on what
    # is counted, or the panel would understate the service's load.
    assert row["running"] == _IN_FLIGHT_LIMIT + 5
