"""A dead delivery of older bytes must not ask users to reconnect."""
import pytest
from test_automatic_release_service import prepared, authorize, tick, SID, FILE, DIGEST


@pytest.mark.parametrize('provider', ['sharepoint', 'drive'])
def test_dead_delivery_of_changed_copy_identifies_new_plan_requirement(prepared, provider):
    row = authorize(prepared)
    admitted = tick(prepared, row)
    if provider == 'drive':
        # The coordinator's decision is provider-independent; no provider is called.
        admitted['intent']['destination']['provider'] = provider
        with prepared.store._db.cursor() as cur:
            import json
            prepared.store._db.execute(cur, 'UPDATE automatic_release_authorizations SET intent=%s WHERE id=%s',
                                      (json.dumps(admitted['intent']), admitted['id']))
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur, "UPDATE jobs SET status='dead' WHERE type='publish_file' AND scan_id=%s", (SID,))
        prepared.store._db.execute(cur, 'UPDATE file_records SET corrected_sha256=%s WHERE scan_id=%s', ('b' * 64, SID))
    blocked = tick(prepared, admitted)
    entry = blocked['progress']['files'][FILE]
    assert entry['state'] == 'blocked'
    assert entry['failure_category'] == 'admitted_copy_changed'
    assert 'new release plan' in entry['message'].lower()
    assert 'reconnect' not in entry['message'].lower()
    assert entry['artifact_digest'] == DIGEST
    assert not entry.get('requires_reconnect')
    assert len(prepared.calls) == 1
    import automatic_release as flow
    assert not flow.public(blocked, prepared.store)['can_resume']
    # Explicit/replayed ticks can still reconcile, but never create idle work.
    from test_automatic_release_service import count_jobs, OWNER
    count = count_jobs(prepared)
    for _ in range(3):
        blocked = tick(prepared, blocked)
        assert blocked['status'] == 'blocked'
        assert blocked['progress']['files'][FILE]['artifact_digest'] == DIGEST
    assert count_jobs(prepared) == count
    assert len(prepared.calls) == 1
    release = prepared.store.ensure_release_execution(
        SID, OWNER, provider, 1,
        preferred_folder_name=blocked['intent']['release_folder_name'],
        parent_folder_id=blocked['intent']['release_parent_id'])
    prepared.store.record_release_document(release['id'], OWNER,
        dict(file=FILE, status='published', artifact_digest='sha256:' + DIGEST))
    assert flow.public(blocked, prepared.store)['progress']['published'] == 1
    assert tick(prepared, blocked)['status'] == 'completed'
    assert len(prepared.calls) == 1


@pytest.mark.parametrize('other_state,category,digest', [
    ('waiting', None, None), ('publishing', None, DIGEST),
    ('blocked', 'connection_failed', DIGEST),
    ('blocked', 'admitted_copy_changed', None),
])
def test_mixed_pending_or_recoverable_copy_keeps_successors(other_state, category, digest):
    import automatic_release as flow
    row = {'intent': {'files': [FILE, 'other.docx']}, 'progress': {'files': {
        FILE: dict(state='blocked', failure_category='admitted_copy_changed', artifact_digest=DIGEST),
        'other.docx': dict(state=other_state, failure_category=category, artifact_digest=digest)}}}
    assert not flow._permanent_delivery_pause(row, ['dead'])


@pytest.mark.parametrize('job_state', ['queued', 'running', 'processing', 'retry', 'unknown'])
def test_active_or_unknown_admitted_job_keeps_receipt_polling(job_state):
    import automatic_release as flow
    row = {'intent': {'files': [FILE]}, 'progress': {'files': {
        FILE: dict(state='blocked', failure_category='admitted_copy_changed', artifact_digest=DIGEST)}}}
    assert not flow._permanent_delivery_pause(row, [job_state])


@pytest.mark.parametrize('other_state', ['published', 'failed'])
def test_permanent_changed_copy_and_settled_files_pause_successors(other_state):
    import automatic_release as flow
    row = {'intent': {'files': [FILE, 'other.docx']}, 'progress': {'files': {
        FILE: dict(state='blocked', failure_category='admitted_copy_changed', artifact_digest=DIGEST),
        'other.docx': dict(state=other_state)}}}
    assert flow._permanent_delivery_pause(row, ['done', 'dead', 'cancelled'])
