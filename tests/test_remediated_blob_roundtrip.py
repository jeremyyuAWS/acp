"""Exercise corrected-output persistence through the real Blob adapter, without cloud I/O."""
from types import SimpleNamespace

import blob


def test_corrected_bytes_roundtrip_and_package_reader_stay_separate(monkeypatch, isolated_store):
    objects, reads = {}, []

    class Service:
        def get_blob_client(self, container, blob):
            key = (container, blob)

            def upload(data, **kwargs):
                objects[key] = data.read() if hasattr(data, 'read') else data

            def download(**kwargs):
                reads.append((key, kwargs))
                return SimpleNamespace(readall=lambda: objects[key])

            return SimpleNamespace(upload_blob=upload, download_blob=download,
                                   url=f'https://fixture.invalid/{container}/{blob}')

    monkeypatch.setattr(blob, '_service_client', lambda: Service())
    body = b'actual verified corrected document'
    url = blob.upload_remediated('owner', 'scan', 'one.pdf', body, 'application/pdf')
    assert url.endswith('/remediated/owner/scan/one.pdf')
    assert blob.download_remediated('owner', 'scan', 'one.pdf') == body
    assert reads[-1] == (('remediated', 'owner/scan/one.pdf'), blob._timeouts())
    assert blob.download_remediated('foreign', 'scan', 'one.pdf') is None
    import io
    blob.upload_release_package('owner', 'scan', 'package', io.BytesIO(b'zip bytes'))
    assert blob.open_release_package('owner', 'scan', 'package').readall() == b'zip bytes'
    assert blob.download_remediated('owner', 'scan', 'one.pdf') == body

    # Follow the actual adapter through Release and its durable receipt; only the
    # storage SDK is substituted, not the corrected-output reader or publisher.
    import hashlib
    import core
    from routes import scans
    from test_release_artifact_readers import seed
    seed(isolated_store, body)
    monkeypatch.setattr(core, 'store', isolated_store)
    blob.upload_remediated('reader@example.com', 'reader-scan', 'one.pdf', body, 'application/pdf')
    request = SimpleNamespace(state=SimpleNamespace(user_email='reader@example.com'), headers={})
    first = scans.publish_files('reader-scan', request, {'files': ['one.pdf']})
    assert first['published'][0]['status'] == 'published', first
    assert first['published'][0]['artifact_digest'] == 'sha256:' + hashlib.sha256(body).hexdigest()
    repeat = scans.publish_files('reader-scan', request, {'files': ['one.pdf']})
    assert repeat['batch_id'] == first['batch_id']
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur, 'SELECT content_digest FROM side_effect_receipts')
        assert isolated_store._db.fetchall(cur) == [{'content_digest': hashlib.sha256(body).hexdigest()}]


def test_unconfigured_corrected_storage_remains_unavailable(monkeypatch):
    monkeypatch.setattr(blob, '_service_client', lambda: None)
    assert blob.download_remediated('owner', 'scan', 'one.pdf') is None
