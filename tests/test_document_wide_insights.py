import json
from document_wide_insights import read_document_wide


def event(store, event_id, *, owner='owner', run='run', file='a.pdf', action='generated', **detail):
    with store._db.cursor() as cur:
        store._db.execute(cur, '''INSERT INTO decision_log(id,ts,actor,scan_id,file,action,detail)
            VALUES(%s,%s,'system','scan',%s,%s,%s)''',
            (event_id, event_id, file, 'document_wide.' + action, json.dumps({'owner_id': owner, 'run_id': run, **detail})))


def test_exact_run_owner_and_separate_suggestion_units(isolated_store):
    s = isolated_store
    event(s, '1', owner='other', proposals={'4.1.2': [{}, {}]})
    event(s, '2', run='old', proposals={'4.1.2': [{}, {}]})
    event(s, '3', proposals={'4.1.2': [{}, {}]}, unresolved=[{'finding_id': 'f', 'reason': 'ambiguous_locator'}])
    result = read_document_wide(s, 'owner', 'scan', 'run', enabled=True)
    assert result['unit'] == 'suggestions'
    assert len(result['files']) == 1
    assert result['files'][0]['suggestions'] == 2
    assert result['files'][0]['reasons'] == ['ambiguous_locator']
    assert read_document_wide(s, 'owner', 'scan', 'run') is None


def test_request_replay_not_added_and_later_deferred_does_not_hide_generated(isolated_store):
    s = isolated_store
    event(s, '1', request_id='old', proposals={'4.1.2': [{}, {}, {}]})
    event(s, '2', request_id='current', proposals={'4.1.2': [{}]})
    event(s, '3', request_id='current', action='deferred', reason='An existing review decision was preserved.')
    row = read_document_wide(s, 'owner', 'scan', 'run', enabled=True)['files'][0]
    assert row['suggestions'] == 1
    assert row['status'] == 'generated'
    assert row['reasons'] == ['An existing review decision was preserved.']


def test_extraction_and_omission_explanations(isolated_store):
    event(isolated_store, '1', action='deferred', reason='No supported targets.',
          extraction_issues=[{'kind': 'insufficient_visual_evidence'}], omitted_finding_ids=['a'])
    row = read_document_wide(isolated_store, 'owner', 'scan', 'run', enabled=True)['files'][0]
    assert row['suggestions'] == 0
    assert row['reasons'] == ['No supported targets.', 'insufficient_visual_evidence', 'findings_omitted']
