"""Real Store/API reader contract for exact Release artifacts; no provider calls."""
import hashlib
from types import SimpleNamespace


def seed(store, data):
    store.init_scan_run('reader-scan', 'local', 1, '2026-09-01T00:00:00Z', 'rubric', 'hash', owner='reader@example.com', status='completed')
    with store._db.cursor() as cur:
        store._db.execute(cur, 'INSERT INTO file_records(scan_id,file,engine,status,score,compliant,remediated_at,corrected_sha256,source_modified) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                          ('reader-scan', 'one.pdf', 'pdf', 'analysed', 100, 1, '2026-09-01T01:00:00Z', hashlib.sha256(data).hexdigest(), '2026-09-01T00:00:00Z'))


def test_real_store_release_readers_supply_artifact_and_source_evidence(isolated_store):
    seed(isolated_store, b'A')
    file = isolated_store.get_file_record('reader-scan', 'one.pdf')
    assert file.get('corrected_sha256') == hashlib.sha256(b'A').hexdigest()
    assert file.get('source_modified') == '2026-09-01T00:00:00Z'
    scan = isolated_store.get_scan('reader-scan', owner='reader@example.com')
    assert scan['files'][0].get('corrected_sha256') == file['corrected_sha256']


def test_real_store_release_execution_distinguishes_new_bytes_at_same_timestamp(isolated_store, monkeypatch):
    import core
    import publish
    from routes import scans
    seed(isolated_store, b'A')
    current = {'bytes': b'A'}
    monkeypatch.setattr(core, 'store', isolated_store)
    monkeypatch.setattr(publish._blob, 'download_remediated', lambda *args: current['bytes'])
    request = SimpleNamespace(state=SimpleNamespace(user_email='reader@example.com'), headers={})
    first = scans.publish_files('reader-scan', request, {'files': ['one.pdf']})
    assert first['published'][0]['status'] == 'published'
    repeat_a = scans.publish_files('reader-scan', request, {'files': ['one.pdf']})
    assert repeat_a['batch_id'] == first['batch_id']
    current['bytes'] = b'B'
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur, 'UPDATE file_records SET corrected_sha256=%s WHERE scan_id=%s AND file=%s', (hashlib.sha256(b'B').hexdigest(), 'reader-scan', 'one.pdf'))
    second = scans.publish_files('reader-scan', request, {'files': ['one.pdf']})
    assert second['published'][0]['status'] == 'published', second
    assert second['batch_id'] != first['batch_id']
    assert second['published'][0]['artifact_digest'] == 'sha256:' + hashlib.sha256(b'B').hexdigest()
    repeat_b = scans.publish_files('reader-scan', request, {'files': ['one.pdf']})
    assert repeat_b['batch_id'] == second['batch_id']
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur, 'SELECT COUNT(*) AS n FROM side_effect_receipts')
        assert isolated_store._db.fetchone(cur)['n'] == 2
