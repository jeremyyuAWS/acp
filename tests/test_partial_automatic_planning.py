import automatic_release as flow
from test_automatic_release_service import prepared, SID, OWNER, FILE


def test_failed_or_untracked_files_do_not_block_tracked_files(prepared, monkeypatch):
    monkeypatch.setattr(prepared.store, 'get_decisions', lambda *a, **kw: {})
    records = prepared.store.get_file_records(SID, owner=OWNER)
    records['failed.pdf'] = {'status': 'error', 'score': None}
    records['untracked.pdf'] = {'status': 'analysed', 'score': 90}
    monkeypatch.setattr(prepared.store, 'get_file_records', lambda *a, **kw: records)
    result = flow.planning_preview(prepared.store, SID, OWNER, [FILE, 'failed.pdf', 'untracked.pdf'])
    assert result['available']
    assert result['files'] == [FILE]
    assert {r['file'] for r in result['blocked_files']} == {'failed.pdf', 'untracked.pdf'}
    assert '2 files will be skipped' in result['reason']
    assert result['destination']['folder_id']


def test_every_untracked_file_still_blocks_publication(prepared, monkeypatch):
    monkeypatch.setattr(prepared.store, 'get_file_records', lambda *a, **kw: {FILE: {'status': 'analysed', 'score': 90}})
    result = flow.planning_preview(prepared.store, SID, OWNER, [FILE])
    assert not result['available']
    assert result['files'] == []
    assert 'identity or freshness' in result['blocked_files'][0]['reason']
