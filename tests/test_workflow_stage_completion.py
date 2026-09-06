"""Durable, idempotent workflow-stage transitions for Live Ops."""

from __future__ import annotations


def _scan(store, sid="stage-scan", owner="owner@example.com"):
    store.init_scan_run(sid, "sharepoint", 2, "2026-09-05T12:00:00+00:00",
                        "WCAG", "rubric-1", owner=owner, status="discovered")


def _execution(store, sid="stage-scan"):
    return store.enqueue_stage_batch(
        sid, "assess", "scan_assess",
        [{"scan_id": sid, "file": "a.docx"}, {"scan_id": sid, "file": "b.docx"}],
        snapshot_id="snapshot-1", request_fingerprint="same-request")


def _hold(store, job_id, worker="worker-1", attempt=1):
    with store._db.cursor() as cur:
        store._db.execute(cur,
            "UPDATE jobs SET status='running',locked_by=%s,attempts=%s WHERE id=%s",
            (worker, attempt, job_id))
    return {"worker_id": worker, "attempt": attempt}


def test_stage_start_is_one_durable_event_for_an_idempotent_submission(isolated_store):
    _scan(isolated_store)
    first = _execution(isolated_store)
    second = _execution(isolated_store)

    assert second["batch_id"] == first["batch_id"] and second["reused"] is True
    events = isolated_store.list_orchestration_events(
        owner_email="owner@example.com", scan_id="stage-scan", kind="job.stage_started")
    assert len(events) == 1
    assert events[0]["stage"] == "assess"
    assert events[0]["correlation_id"] == first["batch_id"]
    assert events[0]["detail"]["documents"] == 2


def test_completion_lands_only_after_every_document_succeeds(isolated_store):
    _scan(isolated_store)
    execution = _execution(isolated_store)
    first, last = execution["job_ids"]

    assert isolated_store.complete_job(first, **_hold(isolated_store, first)) is True
    assert isolated_store.list_orchestration_events(
        owner_email="owner@example.com", kind="job.stage_completed") == []

    assert isolated_store.complete_job(last, **_hold(isolated_store, last)) is True
    (completed,) = isolated_store.list_orchestration_events(
        owner_email="owner@example.com", kind="job.stage_completed")
    assert completed["stage"] == "assess"
    assert completed["correlation_id"] == execution["batch_id"]
    assert completed["detail"]["documents"] == 2


def test_replayed_completion_cannot_create_a_second_stage_completion(isolated_store):
    _scan(isolated_store)
    execution = _execution(isolated_store)
    for job_id in execution["job_ids"]:
        assert isolated_store.complete_job(job_id, **_hold(isolated_store, job_id)) is True

    last = isolated_store.get_job(execution["job_ids"][-1])
    isolated_store._record_stage_completed_if_ready(last)
    isolated_store._record_stage_completed_if_ready(last)

    events = isolated_store.list_orchestration_events(
        owner_email="owner@example.com", kind="job.stage_completed")
    assert len(events) == 1


def test_failed_batch_does_not_claim_stage_completion(isolated_store):
    _scan(isolated_store)
    execution = _execution(isolated_store)
    first, second = execution["job_ids"]
    isolated_store.complete_job(first, **_hold(isolated_store, first))
    isolated_store.fail_job(second, "permanent", force_dead=True,
                            **_hold(isolated_store, second))

    assert isolated_store.list_orchestration_events(
        owner_email="owner@example.com", kind="job.stage_completed") == []


def test_release_jobs_use_the_release_stage(isolated_store):
    _scan(isolated_store)
    execution = isolated_store.enqueue_stage_batch(
        "stage-scan", "release", "publish_file", [{"file": "a.docx"}],
        snapshot_id="release-1", request_fingerprint="files-a")
    job_id = execution["job_ids"][0]
    isolated_store.complete_job(job_id, **_hold(isolated_store, job_id))

    events = isolated_store.list_orchestration_events(
        owner_email="owner@example.com", kind="job.stage_completed")
    assert len(events) == 1 and events[0]["stage"] == "release"


def test_discover_completion_projects_its_existing_finalize_once_fact(isolated_store):
    _scan(isolated_store)
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "UPDATE scan_runs SET discovered_at=%s WHERE id=%s",
            ("2026-09-05T12:03:00+00:00", "stage-scan"))

    events = isolated_store.list_workflow_stage_events()
    discover = [event for event in events if event.get("stage") == "discover"]
    assert [event["kind"] for event in discover] == ["job.stage_started", "job.stage_completed"]
    assert discover[1]["occurred_at"] == "2026-09-05T12:03:00+00:00"
    assert discover[1]["detail"] == {"documents": 2}


def test_failed_stage_is_recorded_once_after_the_whole_batch_is_terminal(isolated_store):
    _scan(isolated_store)
    execution = _execution(isolated_store)
    for job_id in execution["job_ids"]:
        isolated_store.fail_job(job_id, "timed out", force_dead=True, error_class="timeout",
                                **_hold(isolated_store, job_id))
    events = isolated_store.list_workflow_stage_events()
    failed = [event for event in events if event.get("kind") == "job.stage_failed"]
    assert len(failed) == 1
    assert failed[0]["correlation_id"] == execution["batch_id"]
    assert failed[0]["error_class"] == "timeout"
    assert failed[0]["detail"] == {"documents": 2, "completed": 0, "failed": 2,
                                    "cancelled": 0, "stage_execution_id": execution["batch_id"]}


def test_cancelled_stage_is_distinct_from_failed(isolated_store):
    _scan(isolated_store)
    execution = _execution(isolated_store)
    for job_id in execution["job_ids"]:
        isolated_store.mark_job_cancelled(job_id, **_hold(isolated_store, job_id))
    events = isolated_store.list_workflow_stage_events()
    cancelled = [event for event in events if event.get("kind") == "job.stage_cancelled"]
    assert len(cancelled) == 1
    assert cancelled[0]["error_class"] == "cancelled"
