"""Uploaded assessments can authorize cloud delivery or a durable download package."""
import json
import pytest
import automatic_release as flow
from test_automatic_release_service import prepared, SID, OWNER, FILE, DIGEST
from test_automatic_release_routes import real_publish


def upload(prepared):
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur, "UPDATE scan_runs SET source='local' WHERE id=%s", (SID,))
        prepared.store._db.execute(cur, 'UPDATE scan_inventory SET drive_file_id=NULL,drive_id=NULL,source_modified=NULL WHERE scan_id=%s', (SID,))
        prepared.store._db.execute(cur, 'UPDATE file_records SET drive_file_id=NULL,source_modified=NULL WHERE scan_id=%s', (SID,))
    revision = prepared.store.remediation_source_revision(SID)
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur, 'UPDATE stage_executions SET input_snapshot_id=%s WHERE execution_id=%s', (revision, prepared.run))


def test_upload_defaults_to_download_without_review_or_provider_identity(prepared):
    upload(prepared)
    plan = flow.planning_preview(prepared.store, SID, OWNER, [FILE])
    assert plan['available'], plan
    assert plan['destination']['provider'] == 'local'
    row = flow.authorize(prepared.store, SID, OWNER, prepared.run, [FILE], plan['destination'], 'uploaded', allow_remaining_issues=True, include_reports=True)
    assert flow.ready(prepared.store, row, FILE)['corrected_sha256'] == DIGEST


@pytest.mark.parametrize('provider,folder', [('drive', 'folder'), ('sharepoint', 'library/folder')])
def test_upload_uses_remembered_cloud_destination(prepared, provider, folder):
    upload(prepared)
    destination = dict(provider=provider, folder_id=folder, folder_name='Team documents')
    prepared.store.set_user_setting(OWNER, 'release_destination', json.dumps(destination))
    plan = flow.planning_preview(prepared.store, SID, OWNER, [FILE])
    assert plan['available'], plan
    assert plan['destination'] == destination
    row = flow.authorize(prepared.store, SID, OWNER, prepared.run, [FILE], destination, 'cloud-upload', allow_remaining_issues=True)
    assert row['intent']['source'] == 'local'
    assert row['intent']['destination']['provider'] == provider
    assert flow.ready(prepared.store, row, FILE)['corrected_sha256'] == DIGEST


def test_upload_admission_queues_real_cloud_delivery_to_chosen_provider(prepared, monkeypatch):
    from types import SimpleNamespace
    from routes import scans
    import core
    upload(prepared)
    destination = dict(provider='sharepoint', folder_id='target-library/folder', folder_name='Team')
    row = flow.authorize(prepared.store, SID, OWNER, prepared.run, [FILE], destination, 'cloud', allow_remaining_issues=True)
    flow.publish_admission(prepared.store, row['id'], OWNER, SID, FILE, DIGEST)
    monkeypatch.setattr(scans, '_preflight_release_destination', lambda *a: {'ready': True})
    monkeypatch.setattr(core, 'register_scan_tokens', lambda *a, **kw: None)
    result = real_publish(SID, SimpleNamespace(state=SimpleNamespace(user_email=OWNER), headers={'x-sp-token':'fixture'}), dict(files=[FILE], destination=destination, automatic_release_id=row['id'], release_folder_name=row['intent']['release_folder_name'], expected_artifacts={FILE:DIGEST}, allow_remaining_issues=True, expected_destination=destination))
    assert result['queued'] == 1
    release = prepared.store.release_for_scan(SID, OWNER)
    assert release['source'] == 'sharepoint' and release['parent_folder_id'] == 'target-library/folder'


def test_local_completion_prepares_one_frozen_package_and_reports(prepared, monkeypatch):
    import blob
    from types import SimpleNamespace
    from routes import scans
    from test_automatic_release_service import tick
    upload(prepared)
    monkeypatch.setattr(blob, 'enabled', lambda: True)
    monkeypatch.setattr(scans, '_preflight_release_destination', lambda *a: {'ready':True})
    import publish
    monkeypatch.setattr(publish, 'remediated_content_digest', lambda *a: DIGEST)
    monkeypatch.setattr(scans, 'publish_files', real_publish)
    monkeypatch.setattr(flow, 'request_for', lambda *a: SimpleNamespace(state=SimpleNamespace(user_email=OWNER), headers={}))
    plan = flow.planning_preview(prepared.store, SID, OWNER, [FILE])
    row = flow.authorize(prepared.store, SID, OWNER, prepared.run, [FILE], plan['destination'], 'package', allow_remaining_issues=True, include_reports=True)
    row = tick(prepared, row)
    assert row['status'] == 'completed', row['progress']
    job_id = row['progress']['_package_job_id']
    job = prepared.store.get_job(job_id)
    assert job['payload']['expected_artifacts'] == {FILE:DIGEST}
    assert job['payload']['report_bundle_id']
    assert flow.public(row, prepared.store)['status'] == 'publishing'
    tick(prepared, row)
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur, "SELECT COUNT(*) AS n FROM jobs WHERE scan_id=%s AND type='prepare_release_package'", (SID,))
        assert prepared.store._db.fetchone(cur)['n'] == 1
        prepared.store._db.execute(cur, "UPDATE jobs SET status='done' WHERE id=%s", (job_id,))
    assert flow.public(row, prepared.store)['status'] == 'completed'


def test_remaining_issues_permission_does_not_publish_approved_but_unwritten_changes(prepared):
    upload(prepared)
    plan = flow.planning_preview(prepared.store, SID, OWNER, [FILE])
    row = flow.authorize(prepared.store, SID, OWNER, prepared.run, [FILE],
        plan['destination'], 'unwritten-approved', allow_remaining_issues=True)
    item = prepared.store.enqueue_proposals(SID, FILE, '1.1.1', [
        {'locator': 'ppt/slides/slide1.xml#Picture 1', 'proposed_value': 'Approved description', 'source': 'fixture'}])
    prepared.store.update_hitl_item(item, 'approved')
    prepared.store.approve_proposal_values(item, [])
    # Reproduce a historical apply job that returned done before actually writing
    # the approved content. A different, older corrected copy still exists.
    job = prepared.store.enqueue_job('apply_approved_values',
        {'owner': OWNER, 'scan_id': SID, 'file': FILE}, scan_id=SID)
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur, "UPDATE jobs SET status='done' WHERE id=%s", (job,))
    assert prepared.store.count_unapplied_approved_values(SID, FILE) == 1
    with pytest.raises(ValueError, match='Approved changes still need'):
        flow.ready(prepared.store, row, FILE)
    prepared.store.mark_row_applied(item)
    assert flow.ready(prepared.store, row, FILE)['corrected_sha256'] == DIGEST


def test_automatic_run_recovers_exact_approved_writes_once_and_stops_on_unwritten_failure(prepared):
    upload(prepared)
    plan = flow.planning_preview(prepared.store, SID, OWNER, [FILE])
    row = flow.authorize(prepared.store, SID, OWNER, prepared.run, [FILE],
        plan['destination'], 'recover-approved', allow_remaining_issues=True)
    item = prepared.store.enqueue_proposals(SID, FILE, '1.1.1', [
        {'locator': 'ppt/slides/slide1.xml#Picture 1', 'proposed_value': 'Exact saved approval', 'source': 'fixture'}])
    prepared.store.update_hitl_item(item, 'approved')
    prepared.store.approve_proposal_values(item, [])
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur, 'UPDATE hitl_queue SET approved_source_revision=%s WHERE id=%s',
            (row['intent']['source_revision'], item))
    assert flow.recover_approved_writes(prepared.store, row, FILE)
    assert flow.recover_approved_writes(prepared.store, row, FILE)
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur, "SELECT id,payload FROM jobs WHERE type='apply_approved_values' AND scan_id=%s", (SID,))
        jobs = prepared.store._db.fetchall(cur)
        assert len(jobs) == 1
        assert json.loads(jobs[0]['payload'])['automatic_release_recovery_id'] == row['id']
        prepared.store._db.execute(cur, "UPDATE jobs SET status='done' WHERE id=%s", (jobs[0]['id'],))
    with pytest.raises(ValueError, match='recovery finished without applying'):
        flow.recover_approved_writes(prepared.store, row, FILE)
    prepared.store.mark_row_applied(item)
    assert flow.recover_approved_writes(prepared.store, row, FILE) is False


def test_recovery_rejects_stale_or_unlocated_approved_values(prepared):
    upload(prepared)
    plan = flow.planning_preview(prepared.store, SID, OWNER, [FILE])
    row = flow.authorize(prepared.store, SID, OWNER, prepared.run, [FILE],
        plan['destination'], 'stale-approved', allow_remaining_issues=True)
    item = prepared.store.enqueue_proposals(SID, FILE, '1.1.1', [
        {'locator': 'ppt/slides/slide1.xml#Picture 1', 'proposed_value': 'Approval', 'source': 'fixture'}])
    prepared.store.update_hitl_item(item, 'approved')
    prepared.store.approve_proposal_values(item, [])
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur, "UPDATE hitl_queue SET approved_source_revision='different-source' WHERE id=%s", (item,))
    with pytest.raises(ValueError, match='current-source'):
        flow.recover_approved_writes(prepared.store, row, FILE)
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur, "SELECT COUNT(*) AS n FROM jobs WHERE type='apply_approved_values' AND scan_id=%s", (SID,))
        assert prepared.store._db.fetchone(cur)['n'] == 0


def test_partial_publish_accepts_saved_applied_changes_even_when_not_verified(prepared):
    upload(prepared)
    plan = flow.planning_preview(prepared.store, SID, OWNER, [FILE])
    row = flow.authorize(prepared.store, SID, OWNER, prepared.run, [FILE],
        plan['destination'], 'saved-unverified', allow_remaining_issues=True)
    item = prepared.store.enqueue_proposals(SID, FILE, '1.1.1', [
        {'locator': 'ppt/slides/slide1.xml#Picture 1', 'proposed_value': 'Written approval', 'source': 'fixture'}])
    prepared.store.update_hitl_item(item, 'approved')
    prepared.store.approve_proposal_values(item, [])
    prepared.store.mark_row_applied(item)
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur, 'UPDATE file_records SET compliant=0 WHERE scan_id=%s', (SID,))
    assert flow.recover_approved_writes(prepared.store, row, FILE) is False
    assert flow.ready(prepared.store, row, FILE)['corrected_sha256'] == DIGEST
