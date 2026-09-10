import json
import pytest
import release_report_delivery as delivery

OWNER = 'reports@example.com'
SID = 'report-delivery'


@pytest.fixture
def setup(isolated_store, monkeypatch):
    import core
    import release_reports
    import release_continuation
    store = isolated_store
    monkeypatch.setattr(core, 'store', store)
    monkeypatch.setattr(core, 'get_scan_tokens', lambda sid: {'sp': 'secret-fixture'})
    monkeypatch.setattr(release_continuation, 'require_grants', lambda *a, **k: None)
    with store._db.cursor() as cur:
        store._db.execute(cur, "INSERT INTO scan_runs(id,owner_email,source,status) VALUES(%s,%s,'sharepoint','done')", (SID, OWNER))
    release = store.ensure_release_execution(SID, OWNER, 'sharepoint', 1)
    store.record_release_root(release['id'], OWNER, 'sharepoint', 'graph:library', 'saved-folder', 'Release', 'https://example.com/folder')
    store.record_release_document(release['id'], OWNER, dict(file='doc.pdf', status='published', artifact_digest='sha256:' + 'a'*64))
    monkeypatch.setattr(release_reports, 'build_release_reports', lambda *a: [dict(name='scan-summary.html', content=b'<a href="checklist.html">Checklist</a>', content_type='text/html'), dict(name='checklist.html', content=b'Unresolved issue', content_type='text/html')])
    return store, release


def test_frozen_owner_scoped_reports_and_single_queue(setup):
    store, release = setup
    first = delivery.queue_release_reports(store, SID, OWNER, release['id'])
    assert first == delivery.queue_release_reports(store, SID, OWNER, release['id'])
    assert first['status'] == 'queued'
    asset = delivery.get_release_report_asset(store, SID, OWNER, first['bundle_id'], 0)
    assert first['reports'][1]['name'].encode() in asset['content']
    with pytest.raises(KeyError):
        delivery.get_release_report_asset(store, SID, 'other', first['bundle_id'], 0)
    assert delivery.get_latest_release_reports(store, SID, 'other')['status'] == 'not_started'
    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT payload FROM jobs WHERE type='publish_release_reports'")
        jobs = store._db.fetchall(cur)
    assert len(jobs) == 1
    assert set(json.loads(jobs[0]['payload'])) == {'bundle_id', 'owner'}


def test_delivery_same_folder_and_retry_reuses_receipts(setup, monkeypatch):
    store, release = setup
    bundle = delivery.queue_release_reports(store, SID, OWNER, release['id'])
    calls = []
    def upload(root, asset, tokens, key):
        assert root['folder_id'] == 'saved-folder'
        calls.append(asset['name'])
        if len(calls) == 2:
            raise RuntimeError('secret-fixture provider error')
        return dict(id=key, url='https://example.com/' + asset['name'])
    monkeypatch.setattr(delivery, '_upload', upload)
    failed = delivery.process_release_reports(store, bundle['bundle_id'], OWNER)
    assert failed['status'] == 'failed'
    assert 'secret-fixture' not in failed['error']
    assert store.release_status(release['id'], OWNER)['published'] == 1
    delivery.retry_release_reports(store, SID, OWNER)
    done = delivery.process_release_reports(store, bundle['bundle_id'], OWNER)
    assert done['status'] == 'completed'
    assert len(calls) == 3 and calls[1] == calls[2]
    assert all(r['url'] for r in done['reports'])
    delivery.process_release_reports(store, bundle['bundle_id'], OWNER)
    assert len(calls) == 3


def test_local_reports_downloadable_and_settled_guard(setup):
    store, release = setup
    with store._db.cursor() as cur:
        store._db.execute(cur, 'DELETE FROM release_roots WHERE release_id=%s', (release['id'],))
        store._db.execute(cur, 'UPDATE release_executions SET documents_total=2 WHERE id=%s', (release['id'],))
    assert delivery.queue_if_release_settled(store, SID, OWNER) is None
    store.record_release_document(release['id'], OWNER, dict(file='other.pdf', status='failed'))
    bundle = delivery.queue_if_release_settled(store, SID, OWNER)
    done = delivery.process_release_reports(store, bundle['bundle_id'], OWNER)
    assert done['status'] == 'completed'
    assert all(r['url'] is None and r['download_url'] for r in done['reports'])


def test_sharepoint_transport_uses_existing_folder_and_reads_back(monkeypatch):
    import publish
    import scanner
    calls = []
    monkeypatch.setattr(publish, '_sp_child', lambda *a: None)
    monkeypatch.setattr(publish, '_sp_content_matches', lambda *a: a[1] == 'library' and a[2] == 'report-id')
    monkeypatch.setattr(scanner, '_sp_write', lambda token, **kw: calls.append(kw) or dict(id='report-id', webUrl='https://example.com/report'))
    result = delivery._upload(dict(provider='sharepoint', provider_location='graph:library', folder_id='saved-folder'), dict(name='report.html', content='checklist', content_type='text/html'), {'sp': 'fixture'}, 'key')
    assert result['id'] == 'report-id'
    assert '/items/saved-folder:/report.html:/content' in calls[0]['put_url']
    assert calls[0]['conflict_behavior'] == 'fail'
    assert calls[0]['content'] == b'checklist'
