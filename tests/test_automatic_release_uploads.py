"""Uploaded assessments can authorize cloud delivery or a durable download package."""
import json
import pytest
import automatic_release as flow
from test_automatic_release_service import prepared, SID, OWNER, FILE, DIGEST


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
    from test_automatic_release_routes import real_publish
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
    from test_automatic_release_routes import real_publish
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
