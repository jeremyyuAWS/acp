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


def test_drive_transport_uses_saved_folder_and_verifies_downloaded_bytes(monkeypatch):
    from types import SimpleNamespace
    import handlers
    import publish
    calls = []
    downloaded = [b'follow-up checklist']
    def get_media(*, fileId):
        calls.append(('get_media', fileId))
        return SimpleNamespace(execute=lambda: downloaded[0])
    service = SimpleNamespace(files=lambda: SimpleNamespace(get_media=get_media))
    def make_service(source, tokens):
        assert source == 'drive' and tokens == {'drive': 'fixture-token'}
        return service
    monkeypatch.setattr(handlers, '_make_svc', make_service)
    def upload(svc, folder_id, filename, data, **options):
        assert svc is service
        calls.append(('upload', folder_id, filename, data, options))
        return dict(id='report-drive-item', url='https://drive.google.com/report', verified=True)
    monkeypatch.setattr(publish, 'upload_published', upload)
    root = dict(provider='drive', provider_location='drive', folder_id='existing-release-folder')
    asset = dict(name='follow-up.html', content='follow-up checklist', content_type='text/html')
    result = delivery._upload(root, asset, {'drive': 'fixture-token'}, 'bundle:asset-key')
    assert result['url'] == 'https://drive.google.com/report'
    assert calls == [('upload', 'existing-release-folder', 'follow-up.html', b'follow-up checklist',
                      {'idempotency_key': 'bundle:asset-key', 'return_details': True}),
                     ('get_media', 'report-drive-item')]
    downloaded[0] = b'different bytes'
    with pytest.raises(ValueError, match='could not be verified'):
        delivery._upload(root, asset, {'drive': 'fixture-token'}, 'bundle:asset-key')
    before = len(calls)
    with pytest.raises(ValueError, match='connection is unavailable'):
        delivery._upload(root, asset, {}, 'bundle:asset-key')
    assert len(calls) == before


def test_late_failed_worker_does_not_regress_completed_bundle(setup, monkeypatch):
    store, release = setup
    bundle = delivery.queue_release_reports(store, SID, OWNER, release['id'])
    def another_worker_completed_then_this_upload_failed(*args):
        with store._db.cursor() as cur:
            store._db.execute(cur, "UPDATE release_report_bundles SET status='completed',error=NULL WHERE id=%s", (bundle['bundle_id'],))
        raise RuntimeError('Late duplicate upload failure')
    monkeypatch.setattr(delivery, '_upload', another_worker_completed_then_this_upload_failed)
    result = delivery.process_release_reports(store, bundle['bundle_id'], OWNER)
    assert result['status'] == 'completed'
    assert result['error'] is None


def test_pdf_bytes_survive_frozen_storage_and_download(setup, monkeypatch):
    import release_reports
    store, release = setup
    content = b'%PDF-1.7\n\xff\x00binary fixture'
    monkeypatch.setattr(release_reports, 'build_release_reports', lambda *a: [dict(name='scan-summary.pdf', content=content, content_type='application/pdf')])
    bundle = delivery.queue_release_reports(store, SID, OWNER, release['id'])
    frozen = delivery._get(store, bundle['bundle_id'], OWNER)['assets'][0]
    assert frozen['encoding'] == 'base64'
    assert delivery._asset_bytes(frozen) == content
    assert delivery.get_release_report_asset(store, SID, OWNER, bundle['bundle_id'], 0)['content'] == content


def test_completed_legacy_bundle_can_generate_new_pdf_without_rescanning(setup, monkeypatch):
    import release_reports
    store, release = setup
    old = delivery.queue_release_reports(store, SID, OWNER, release['id'])
    monkeypatch.setattr(delivery, '_upload', lambda *args: dict(id='saved', url='https://example.com/report'))
    delivery.process_release_reports(store, old['bundle_id'], OWNER)
    # A legacy bundle predates the versioned PDF fingerprint.
    with store._db.cursor() as cur:
        store._db.execute(cur, 'UPDATE release_report_bundles SET id=%s WHERE id=%s', ('legacy-bundle', old['bundle_id']))
    content = b'%PDF-1.7\nrefreshed'
    monkeypatch.setattr(release_reports, 'build_release_reports', lambda *a: [dict(name='scan-summary.pdf', content=content, content_type='application/pdf')])
    refreshed = delivery.retry_release_reports(store, SID, OWNER)
    assert refreshed['bundle_id'] != 'legacy-bundle'
    assert refreshed['reports'][0]['content_type'] == 'application/pdf'
    assert store.release_status(release['id'], OWNER)['published'] == 1
    assert delivery.get_release_report_asset(store, SID, OWNER, 'legacy-bundle', 0)['content'].startswith(b'<a')


def test_page_evidence_format_invalidates_previous_bundle(setup, monkeypatch):
    store, release = setup
    current = delivery.REPORT_FORMAT
    monkeypatch.setattr(delivery, 'REPORT_FORMAT', 'pdf-v3-release-page-evidence')
    old = delivery.queue_release_reports(store, SID, OWNER, release['id'])
    monkeypatch.setattr(delivery, 'REPORT_FORMAT', current)
    new = delivery.queue_release_reports(store, SID, OWNER, release['id'])
    assert new['bundle_id'] != old['bundle_id']
    assert delivery.queue_release_reports(store, SID, OWNER, release['id'])['bundle_id'] == new['bundle_id']


def test_release_changed_during_render_is_not_frozen(setup, monkeypatch):
    import release_reports
    store, release = setup
    def changed(*args):
        store.record_release_document(release['id'], OWNER, {'file': 'changed.pdf', 'status': 'failed'})
        return []
    monkeypatch.setattr(release_reports, 'build_release_reports', changed)
    with pytest.raises(ValueError, match='Release changed'):
        delivery.queue_release_reports(store, SID, OWNER, release['id'])


def test_optional_render_precedes_local_release_transaction(setup, monkeypatch):
    import release_reports
    from contextlib import contextmanager
    store, release = setup
    original = store.transaction
    depth = []
    @contextmanager
    def transaction():
        depth.append(True)
        try:
            with original():
                yield
        finally:
            depth.pop()
    monkeypatch.setattr(store, 'transaction', transaction)
    build = release_reports.build_release_reports
    def render(*args):
        assert not depth
        return build(*args)
    monkeypatch.setattr(release_reports, 'build_release_reports', render)
    delivery.queue_release_reports(store, SID, OWNER, release['id'])


def test_report_identity_metadata_survives_frozen_bundle(setup, monkeypatch):
    import release_reports
    store, release = setup
    digest = 'sha256:' + 'a' * 64
    monkeypatch.setattr(release_reports, 'build_release_reports', lambda *a: [
        dict(name='scan-summary.pdf', content=b'summary', content_type='application/pdf', report_kind='scan_summary'),
        dict(name='changes-doc.pdf', content=b'changes', content_type='application/pdf', report_kind='changes', file='doc.pdf', artifact_digest=digest)])
    bundle = delivery.queue_release_reports(store, SID, OWNER, release['id'])
    current = delivery.get_latest_release_reports(store, SID, OWNER)
    assert current == bundle
    assert current['scan_id'] == SID
    assert current['release_id'] == release['id']
    assert current['reports'][1]['file'] == 'doc.pdf'
    assert current['reports'][1]['artifact_digest'] == digest
    assert current['reports'][0]['report_kind'] == 'scan_summary'


def test_legacy_identity_recovery_requires_exact_frozen_release(setup, monkeypatch):
    import release_reports
    import hashlib
    store, release = setup
    file_hash = hashlib.sha256(b'doc.pdf').hexdigest()[:10]
    monkeypatch.setattr(release_reports, 'build_release_reports', lambda *a: [dict(
        name=f'checklist-doc.pdf-{file_hash}.pdf', content=b'legacy', content_type='application/pdf')])
    bundle = delivery.queue_release_reports(store, SID, OWNER, release['id'])
    assert bundle['reports'][0]['file'] == 'doc.pdf'
    assert bundle['reports'][0]['report_kind'] == 'checklist'
    assert bundle['reports'][0]['artifact_digest'] == 'sha256:' + 'a' * 64
    store.record_release_document(release['id'], OWNER, dict(file='doc.pdf', status='published', artifact_digest='sha256:' + 'b'*64))
    refreshed = delivery.get_latest_release_reports(store, SID, OWNER)
    assert refreshed['reports'][0]['file'] is None
    assert refreshed['reports'][0]['artifact_digest'] is None
