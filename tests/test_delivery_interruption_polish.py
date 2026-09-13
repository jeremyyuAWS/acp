"""Repeated browser/worker recovery preserves exact provider delivery evidence."""
import automatic_release as flow
import automatic_release_store as persistence
from test_automatic_release_service import prepared, OWNER, SID, FILE, DIGEST, tick
from test_automatic_sharepoint_recovery import interrupted
from test_automatic_drive_recovery import drive, admitted, queue


def test_sharepoint_repeated_resume_after_lost_response_keeps_one_job_and_receipt(prepared):
    row, batch = interrupted(prepared)
    original = prepared.store.get_job(batch['job_ids'][0])
    for _ in range(3):
        row = flow.resume(prepared.store, row['id'], OWNER, SID)
        row = tick(prepared, row)
        job = prepared.store.get_job(batch['job_ids'][0])
        assert job['payload'] == original['payload']
        assert job['batch_id'] == original['batch_id']
        assert row['intent'] == persistence.get(prepared.store, row['id'], OWNER)['intent']
    release = prepared.store.ensure_release_execution(SID, OWNER, 'sharepoint', 1,
        preferred_folder_name=row['intent']['release_folder_name'],
        parent_folder_id=row['intent']['release_parent_id'])
    prepared.store.record_release_document(release['id'], OWNER,
        dict(file=FILE, status='published', artifact_digest='sha256:' + DIGEST))
    for _ in range(3):
        row = tick(prepared, persistence.get(prepared.store, row['id'], OWNER))
        assert row['status'] == 'completed'
    assert not prepared.calls


def test_drive_worker_restart_then_late_receipt_finishes_without_another_upload(drive):
    row, release = admitted(drive)
    original_intent = row['intent']
    batch = queue(drive, row, release)
    before = drive.store.get_job(batch['job_ids'][0])
    with drive.store._db.cursor() as cur:
        drive.store._db.execute(cur, "UPDATE jobs SET status='dead' WHERE id=%s", (before['id'],))
    row = flow.resume(drive.store, row['id'], OWNER, SID)
    recovered = queue(drive, row, release)
    assert recovered['job_ids'] == batch['job_ids']
    assert drive.store.get_job(before['id'])['payload'] == before['payload']
    drive.store.record_release_document(release['id'], OWNER,
        dict(file=FILE, status='published', artifact_digest='sha256:' + DIGEST))
    for _ in range(3):
        row = tick(drive, persistence.get(drive.store, row['id'], OWNER))
        assert row['status'] == 'completed'
        assert row['intent'] == original_intent
    assert not drive.calls
