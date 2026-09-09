"""Large Release scopes read the queue once, without relaxing frozen authorization."""
import json

import release_continuation as flow
from routes.release_continuation import public_state
from test_release_store import _scan


def test_177_file_plan_batches_queue_and_identity_reads(isolated_store, monkeypatch):
    store = isolated_store
    owner, sid = 'owner@example.com', 'large-release'
    _scan(store, sid, owner)
    files = [f'deck-{i}.pptx' for i in range(177)]
    for file in files:
        with store._db.cursor() as cur:
            store._db.execute(cur, 'INSERT INTO file_records(scan_id,file,engine,status,score,compliant,'
                              'remediated_at,corrected_sha256) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
                              (sid, file, 'office', 'analysed', 80, 0, '2026-09-01', 'a' * 64))
        store.enqueue_proposals(sid, file, '1.1.1', [{'locator': 'shape:1',
            'proposed_value': 'A legacy description without a frozen proposal version. ' * 100}])
    queue_read, record_read = store.list_hitl_queue, store.get_file_records
    calls = {'queue': 0, 'records': 0}

    def queue(**kwargs):
        calls['queue'] += 1
        assert kwargs['owner'] == owner and kwargs['scan_id'] == sid
        return queue_read(**kwargs)

    def records(scan_id, **kwargs):
        calls['records'] += 1
        assert kwargs['owner'] == owner and scan_id == sid
        return record_read(scan_id, **kwargs)

    monkeypatch.setattr(store, 'list_hitl_queue', queue)
    monkeypatch.setattr(store, 'get_file_records', records)
    monkeypatch.setattr(store, 'get_file_record', lambda *args: (_ for _ in ()).throw(
        AssertionError('per-file read reintroduced')))
    planned = flow.plan(store, sid, owner, files, None, 'Exact release')
    assert calls == {'queue': 1, 'records': 1}
    assert len(planned['intent']['files']) == 177
    assert all(entry['rows'] and not any(r['authorize'] for r in entry['rows'])
               for entry in planned['intent']['files'].values())
    displayed = public_state(planned)
    assert len(json.dumps(displayed)) < len(json.dumps(planned)) / 5
    assert all(not entry['rows'] and entry['blockers'] for entry in displayed['intent']['files'].values())
    # Display filtering never erases the server's exact identity/evidence.
    assert all(entry['rows'][0]['proposals'] for entry in planned['intent']['files'].values())


def test_batch_identity_reader_preserves_single_file_shape_and_owner_scope(isolated_store):
    from test_release_artifact_readers import seed
    seed(isolated_store, b'corrected')
    row = isolated_store.get_file_record('reader-scan', 'one.pdf')
    assert isolated_store.get_file_records('reader-scan', owner='reader@example.com') == {'one.pdf': row}
    assert isolated_store.get_file_records('reader-scan', owner='foreign@example.com') == {}
    assert isolated_store.get_file_records('reader-scan', files=[]) == {}


def test_public_projection_keeps_every_eligible_proposal_without_mutating_frozen_inputs():
    eligible = {'id': 'eligible', 'authorize': True, 'proposals': [{'proposed_value': 'Exact text'}]}
    old = {'id': 'old', 'authorize': False, 'proposals': [{'proposed_value': 'Already applied'}]}
    row = {'id': 'intent', 'intent': {'files': {'one.docx': {'rows': [eligible, old], 'blockers': ['Manual']}}}}
    result = public_state(row)
    assert result['id'] == row['id']
    assert result['intent']['files']['one.docx']['rows'] == [eligible]
    assert row['intent']['files']['one.docx']['rows'] == [eligible, old]
    assert public_state(None) is None
