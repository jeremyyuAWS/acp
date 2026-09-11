"""Real persistence and exact approval contracts; all document/provider I/O is isolated."""
import hashlib
import json
import pytest
import release_continuation as flow
import release_continuation_store as persistence
from test_hitl_exact_batch_selection import decision, base_decision

OWNER = 'reviewer@example.com'
SID = 's1'
FILE = 'deck.pptx'


@pytest.fixture()
def prepared(decision, monkeypatch):
    import core
    st, item_id, *_ = decision
    with st._db.cursor() as cur:
        st._db.execute(cur, 'INSERT INTO file_records(scan_id,file,engine,status,score,compliant,remediated_at,corrected_sha256) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
                       (SID, FILE, 'office', 'analysed', 80, 0, '2026-09-01', hashlib.sha256(b'A').hexdigest()))
    monkeypatch.setattr(core, 'store', st)
    monkeypatch.setattr(flow, 'source_check', lambda *args: None)
    row = flow.plan(st, SID, OWNER, [FILE], None, 'Authorized release')
    assert any(r['authorize'] for r in row['intent']['files'][FILE]['rows'])
    return st, item_id, row


def tick(st, row):
    flow.advance(st, {'intent_id': row['id'], 'owner': OWNER, 'revision': row['revision']}, {})
    return persistence.get(st, row['id'], OWNER)


def complete_application(st, row, *, success=True):
    with st.transaction():
        with st._db.cursor() as cur:
            st._db.execute(cur, "UPDATE jobs SET status=%s WHERE scan_id=%s AND type='apply_approved_values'",
                           ('done' if success else 'dead', SID))
            if success:
                st._db.execute(cur, 'UPDATE hitl_queue SET applied=1 WHERE scan_id=%s', (SID,))
                st._db.execute(cur, 'UPDATE file_records SET compliant=1,corrected_sha256=%s WHERE scan_id=%s',
                               (hashlib.sha256(b'B').hexdigest(), SID))
        if success:
            persistence.artifact(st, row['id'], OWNER, FILE, hashlib.sha256(b'B').hexdigest())


def test_exact_authorization_apply_verification_publish_and_repeated_action(prepared, monkeypatch):
    from routes import scans
    st, item_id, row = prepared
    first = flow.authorize(st, row['id'], OWNER)
    assert flow.authorize(st, row['id'], OWNER)['revision'] == first['revision']
    jobs = flow.application_jobs(st, first, FILE)
    assert len(jobs) == 1
    assert st.get_hitl_item(item_id)['status'] == 'approved'
    deliveries = []
    monkeypatch.setattr(scans, 'publish_files', lambda sid, request, body: deliveries.append(body) or {
        'published': [{'file': FILE, 'status': 'published', 'artifact_digest': 'sha256:' + hashlib.sha256(b'B').hexdigest()}]})
    waiting = tick(st, first)
    assert not deliveries and waiting['status'] == 'waiting'
    complete_application(st, waiting)
    completed = tick(st, waiting)
    assert completed['progress'][FILE]['state'] == 'published', completed
    assert deliveries[0]['expected_artifacts'][FILE] == hashlib.sha256(b'B').hexdigest()
    tick(st, waiting)  # replay of the old worker, including after process/browser restart
    flow.resume(st, row['id'], OWNER)
    assert len(deliveries) == 1


@pytest.mark.parametrize('change', ['source', 'proposal', 'artifact'])
def test_changed_preview_inputs_prevent_any_approval(prepared, change):
    st, item_id, row = prepared
    with st._db.cursor() as cur:
        if change == 'source':
            st._db.execute(cur, 'UPDATE scan_runs SET rubric_hash=%s WHERE id=%s', ('changed', SID))
        elif change == 'artifact':
            st._db.execute(cur, 'UPDATE file_records SET corrected_sha256=%s WHERE scan_id=%s', ('changed', SID))
        else:
            proposals = st.get_hitl_item(item_id)['proposals']
            proposals[0]['proposed_value'] = 'unapproved replacement'
            st._db.execute(cur, 'UPDATE hitl_queue SET proposals=%s WHERE id=%s', (json.dumps(proposals), item_id))
    with pytest.raises(ValueError, match='changed'):
        flow.authorize(st, row['id'], OWNER)
    assert st.get_hitl_item(item_id)['status'] == 'pending'
    assert persistence.get(st, row['id'], OWNER)['status'] == 'draft'


def test_verification_failure_never_delivers(prepared, monkeypatch):
    from routes import scans
    st, _, row = prepared
    row = flow.authorize(st, row['id'], OWNER)
    monkeypatch.setattr(scans, 'publish_files', lambda *args: pytest.fail('must not deliver failed verification'))
    complete_application(st, row, success=False)
    result = tick(st, row)
    assert result['status'] == 'completed'
    assert result['progress'][FILE]['state'] == 'blocked'


def test_new_proposal_after_approval_cannot_be_implicitly_accepted(prepared):
    st, item_id, row = prepared
    row = flow.authorize(st, row['id'], OWNER)
    st.enqueue_proposals(SID, FILE, '2.4.4', [{'locator': 'new', 'proposed_value': 'new draft'}])
    with pytest.raises(ValueError, match='new proposals'):
        flow.check_application(st, row['id'], SID, FILE)
    assert st.get_hitl_item(item_id)['last_decision_request_id'] == f"{row['id']}:{item_id}"


def test_owner_cannot_authorize_another_owners_intent(prepared):
    st, _, row = prepared
    with pytest.raises(ValueError, match='not found'):
        flow.authorize(st, row['id'], 'foreign@example.com')


def test_failed_delivery_resumes_same_artifact_without_new_approval(prepared, monkeypatch):
    from routes import scans
    st, item_id, row = prepared
    row = flow.authorize(st, row['id'], OWNER)
    complete_application(st, row)
    monkeypatch.setattr(scans, 'publish_files', lambda *args: {'published': [{'file': FILE, 'status': 'failed', 'explanation': 'reconnect'}]})
    failed = tick(st, row)
    assert failed['progress'][FILE]['state'] == 'failed'
    request_id = st.get_hitl_item(item_id)['last_decision_request_id']
    resumed = flow.resume(st, row['id'], OWNER)
    monkeypatch.setattr(scans, 'publish_files', lambda *args: {'published': [{'file': FILE, 'status': 'published'}]})
    assert tick(st, resumed)['progress'][FILE]['state'] == 'published'
    assert st.get_hitl_item(item_id)['last_decision_request_id'] == request_id


@pytest.mark.parametrize('verified', [True, False])
def test_actual_apply_handler_records_only_its_verified_output(prepared, monkeypatch, verified):
    import sys
    import handlers
    from proposals import Verification
    from test_apply_approved_values import _Blob, _deck
    st, _, _ = prepared
    blob = _Blob(_deck('Picture 1'))
    with st._db.cursor() as cur:
        st._db.execute(cur, 'UPDATE file_records SET corrected_sha256=%s WHERE scan_id=%s',
                       (hashlib.sha256(blob.data).hexdigest(), SID))
    row = flow.plan(st, SID, OWNER, [FILE], None, 'Exact output')
    row = flow.authorize(st, row['id'], OWNER)
    job = flow.application_jobs(st, row, FILE)[0]
    payload = json.loads(job['payload']) if isinstance(job['payload'], str) else job['payload']
    monkeypatch.setitem(sys.modules, 'blob', blob)
    monkeypatch.setattr(handlers, '_verify_residual', lambda *args: Verification(True, () if verified else ('1.1.1',)))
    handlers._apply_approved_values(payload, {})
    current = persistence.get(st, row['id'], OWNER)
    if verified:
        assert current['artifacts'][FILE] == hashlib.sha256(blob.data).hexdigest()
        assert st.get_file_record(SID, FILE)['corrected_sha256'] == current['artifacts'][FILE]
        assert st.get_file_record(SID, FILE)['compliant'] == 1
    else:
        assert current['artifacts'] == {}
        assert not st.get_file_record(SID, FILE)['compliant']


def test_ready_subset_is_delivered_while_manual_file_finishes_blocked(isolated_store, monkeypatch):
    import core
    from routes import scans
    from test_release_artifact_readers import seed
    st = isolated_store
    seed(st, b'A')
    with st._db.cursor() as cur:
        st._db.execute(cur, 'INSERT INTO file_records(scan_id,file,engine,status,score,compliant) VALUES(%s,%s,%s,%s,%s,%s)',
                       ('reader-scan', 'manual.pdf', 'pdf', 'analysed', 50, 0))
    monkeypatch.setattr(core, 'store', st)
    monkeypatch.setattr(flow, 'source_check', lambda *args: None)
    row = flow.plan(st, 'reader-scan', 'reader@example.com', ['one.pdf', 'manual.pdf'], None, '')
    row = flow.authorize(st, row['id'], 'reader@example.com')
    called = []
    monkeypatch.setattr(scans, 'publish_files', lambda sid, request, body: called.extend(body['files']) or {'published': [{'file': 'one.pdf', 'status': 'published'}]})
    flow.advance(st, {'intent_id': row['id'], 'owner': row['owner_email'], 'revision': row['revision']}, {})
    result = persistence.get(st, row['id'], row['owner_email'])
    assert called == ['one.pdf']
    assert result['status'] == 'completed'
    assert result['progress']['manual.pdf']['state'] == 'blocked'


def test_authorize_route_cannot_cross_scan_or_owner(prepared):
    from test_hitl_owner_isolation import _client
    st, _, row = prepared
    assert _client('foreign@example.com').post(f'/scans/{SID}/release/continuation/{row["id"]}/authorize').status_code == 404
    assert _client(OWNER).post(f'/scans/other/release/continuation/{row["id"]}/authorize').status_code == 404
    assert persistence.get(st, row['id'], OWNER)['status'] == 'draft'


def test_existing_destination_is_resolved_and_a_later_change_requires_confirmation(prepared):
    st, item_id, row = prepared
    st.ensure_release_execution(SID, OWNER, 'drive', 0, preferred_folder_name='Other release',
                                parent_folder_id='other-folder', parent_folder_name='Other folder')
    with pytest.raises(ValueError, match='destination changed'):
        flow.authorize(st, row['id'], OWNER)
    assert st.get_hitl_item(item_id)['status'] == 'pending'
    refreshed = flow.plan(st, SID, OWNER, [FILE], None, '')
    assert refreshed['intent']['destination']['folder_id'] == 'other-folder'
    assert refreshed['intent']['release_folder_name'] == 'Other release'


def test_publish_permission_does_not_also_grant_batch_approval(prepared, monkeypatch):
    import workspace_roles
    import workspace_rollout
    st, item_id, row = prepared
    monkeypatch.setattr(workspace_rollout, 'enforcement_active', lambda: True)
    monkeypatch.setattr(workspace_roles, 'access_for_email', lambda *args, **kwargs: {'capabilities': ['release.publish']})
    with pytest.raises(ValueError, match='permission changed'):
        flow.authorize(st, row['id'], OWNER)
    assert st.get_hitl_item(item_id)['status'] == 'pending'


def test_permission_revocation_stops_continuation_before_delivery(prepared, monkeypatch):
    import workspace_roles
    import workspace_rollout
    from routes import scans
    st, _, row = prepared
    row = flow.authorize(st, row['id'], OWNER)
    complete_application(st, row)
    monkeypatch.setattr(workspace_rollout, 'enforcement_active', lambda: True)
    monkeypatch.setattr(workspace_roles, 'access_for_email', lambda *args, **kwargs: {'capabilities': []})
    monkeypatch.setattr(scans, 'publish_files', lambda *args: pytest.fail('revoked permission cannot publish'))
    assert tick(st, row)['progress'][FILE]['state'] == 'needs_confirmation'


def test_composite_route_requires_both_capabilities_but_shared_reads_remain_any_of():
    import workspace_capability_map as caps
    path = '/scans/{sid}/release/continuation/{intent_id}/authorize'
    assert not caps.allows('POST', path, {'release.publish'})
    assert not caps.allows('POST', path, {'remediate.review'})
    assert caps.allows('POST', path, {'release.publish', 'remediate.review'})
    assert caps.allows('GET', '/scans/{sid}', {'release.view'})


def test_owner_reset_purges_the_continuation_without_touching_other_owner(isolated_store):
    from test_release_store import _scan
    st = isolated_store
    _scan(st, 'mine', OWNER); _scan(st, 'other', 'other@example.com')
    mine = persistence.create(st, OWNER, 'mine', {'files': {}})
    other = persistence.create(st, 'other@example.com', 'other', {'files': {}})
    st.reset_user_data(OWNER)
    assert persistence.get(st, mine['id'], OWNER) is None
    assert persistence.get(st, other['id'], 'other@example.com') is not None


def test_normal_publish_refuses_a_changed_frozen_destination_or_artifact(isolated_store, monkeypatch):
    import core
    from fastapi import HTTPException
    from types import SimpleNamespace
    from routes import scans
    from test_release_artifact_readers import seed
    st = isolated_store
    seed(st, b'A')
    monkeypatch.setattr(core, 'store', st)
    request = SimpleNamespace(state=SimpleNamespace(user_email='reader@example.com'), headers={})
    with pytest.raises(HTTPException) as changed:
        scans.publish_files('reader-scan', request, {'files': ['one.pdf'], 'expected_artifacts': {'one.pdf': hashlib.sha256(b'B').hexdigest()}})
    assert changed.value.status_code == 409
    st.ensure_release_execution('reader-scan', 'reader@example.com', 'local', 0,
                                parent_folder_id='prior-parent', parent_folder_name='Prior parent')
    with pytest.raises(HTTPException) as destination:
        scans.publish_files('reader-scan', request, {'files': ['one.pdf'], 'expected_destination': None})
    assert destination.value.status_code == 409
    assert st.get_file_record('reader-scan', 'one.pdf')['published_at'] is None


@pytest.mark.parametrize('saved_parent,requested_parent', [
    ('lib/frozen', None),
    (None, 'lib/stale'),
])
def test_publish_reports_frozen_destination_when_release_starts_after_status_read(
        isolated_store, monkeypatch, saved_parent, requested_parent):
    """A worker may freeze a destination after the browser loaded Release."""
    import core
    from fastapi import HTTPException
    from types import SimpleNamespace
    from routes import scans
    from test_release_artifact_readers import seed
    st = isolated_store
    seed(st, b'A')
    with st._db.cursor() as cur:
        st._db.execute(cur, 'UPDATE scan_runs SET source=%s WHERE id=%s',
                       ('sharepoint', 'reader-scan'))
    monkeypatch.setattr(core, 'store', st)
    monkeypatch.setattr(scans, '_preflight_release_destination', lambda *args: {'ready': True})
    provider_calls = []
    monkeypatch.setattr(scans, '_register_scan_tokens', lambda *args, **kwargs: provider_calls.append(kwargs))
    request = SimpleNamespace(state=SimpleNamespace(user_email='reader@example.com'),
                              headers={'x-sp-token': 'test-token'})
    assert scans.get_release_status('reader-scan', request)['release_id'] is None
    frozen = st.ensure_release_execution(
        'reader-scan', 'reader@example.com', 'sharepoint', 1,
        preferred_folder_name='2026-09-10 01-04 UTC - reader@example.com',
        parent_folder_id=saved_parent, parent_folder_name='Frozen parent' if saved_parent else None)
    requested = ({'provider': 'sharepoint', 'folder_id': requested_parent,
                  'folder_name': 'Stale parent'} if requested_parent else None)
    with pytest.raises(HTTPException) as conflict:
        scans.publish_files('reader-scan', request, {
            'files': ['one.pdf'], 'destination': requested, 'expected_destination': requested})
    assert conflict.value.status_code == 409
    detail = conflict.value.detail
    assert detail['code'] == 'release_destination_changed'
    assert detail['release_id'] == frozen['id']
    assert detail['release_folder_name'] == frozen['folder_name']
    assert detail['destination'] == (
        {'provider': 'sharepoint', 'folder_id': saved_parent, 'folder_name': 'Frozen parent'}
        if saved_parent else None)
    assert 'confirm' in detail['message'].lower()
    assert provider_calls == []
    assert st.get_file_record('reader-scan', 'one.pdf')['published_at'] is None
    assert st.release_for_scan('reader-scan', 'reader@example.com')['documents'] == []


def test_continuation_folder_uses_owner_timezone(prepared, monkeypatch):
    import publish
    from datetime import datetime, timezone
    st, _, _ = prepared
    real_name = publish.release_folder_name
    monkeypatch.setattr(publish, 'release_folder_name', lambda at=None, timezone_name='UTC', **kw:
        real_name(datetime(2026, 1, 11, 1, 35, tzinfo=timezone.utc), timezone_name, **kw))
    st.set_user_setting(OWNER, 'release_timezone', 'America/New_York')
    row = flow.plan(st, SID, OWNER, [FILE], None, None)
    assert row['intent']['release_folder_name'] == '2026-01-10 20-35 EST - ' + OWNER
