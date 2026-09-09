from test_scan_history_route import client, _seed


def test_recent_read_is_bounded_chronological_and_does_not_walk_oldest_events(client, isolated_store):
    _seed(isolated_store, 'recent')
    for i in range(70):
        isolated_store.append_scan_event('recent', 'remediate.document_completed', detail={'file': f'{i}.pdf'})
    body = client.get('/scans/recent/remediation/activity').json()
    assert body['available'] is True
    assert len(body['events']) == 50
    assert [row['seq'] for row in body['events']] == list(range(21, 71))
    assert body['events'][-1]['detail']['file'] == '69.pdf'


def test_owner_gate_and_empty_are_distinct(client, isolated_store):
    _seed(isolated_store, 'foreign', owner='someone@example.com')
    assert client.get('/scans/foreign/remediation/activity').json()['available'] is False
    _seed(isolated_store, 'empty')
    assert client.get('/scans/empty/remediation/activity').json() == {'available': True, 'scan_id': 'empty', 'events': []}


def test_history_uses_stream_privacy_projection(client, isolated_store, monkeypatch):
    from routes.scans import _project_event
    _seed(isolated_store, 'private')
    isolated_store.append_scan_event('private', 'remediate.document_completed', detail={'file': 'private.pdf'})
    privacy = isolated_store.remediation_filename_privacy('private')
    expected = _project_event(isolated_store.list_scan_events('private')[0], 'private', privacy)
    body = client.get('/scans/private/remediation/activity').json()
    assert body['events'] == [expected]


def test_query_failure_reports_unavailable(client, isolated_store, monkeypatch):
    import remediation_activity_history as history
    _seed(isolated_store, 'broken')
    monkeypatch.setattr(isolated_store, 'remediation_filename_privacy', lambda sid: (_ for _ in ()).throw(RuntimeError('unavailable')))
    assert history.read_recent_activity(isolated_store, 'broken', 'demo')['available'] is False


def test_suppression_withholds_saved_names(client, isolated_store):
    import json
    _seed(isolated_store, 'suppressed')
    isolated_store.append_scan_event('suppressed', 'remediate.document_completed', document='secret.pdf', detail={'file': 'secret.pdf'})
    isolated_store.set_setting('remediation_filename_privacy', 'suppressed')
    body = client.get('/scans/suppressed/remediation/activity').json()
    assert body['available'] is True
    assert 'secret.pdf' not in json.dumps(body)
    assert body['events'][0]['document_suppressed'] is True
