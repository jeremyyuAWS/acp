"""An isolated reproduction: filename reuse must not skip a newer corrected artifact."""
import hashlib
from test_synchronous_release_stage import _RouteStore, _request


def test_release_new_correction_after_published_filename(monkeypatch):
    import core
    import publish
    from routes import scans

    store = _RouteStore('local')
    artifact = {'bytes': b'corrected version A', 'at': '2026-09-01T00:00:00Z'}
    original_record = store.get_file_record
    store.get_file_record = lambda sid, filename: {
        **original_record(sid, filename),
        'remediated_at': artifact['at'],
        'corrected_sha256': hashlib.sha256(artifact['bytes']).hexdigest(),
    }
    monkeypatch.setattr(core, 'store', store)
    monkeypatch.setattr(publish, 'remediated_content_digest',
                        lambda *args: hashlib.sha256(artifact['bytes']).hexdigest())
    first = scans.publish_files('scan-1', _request(), {'files': ['one.pdf']})
    assert first['published'][0]['status'] == 'published'
    receipts = lambda: [event[1] for event in store.events if isinstance(event, tuple) and event[0] == 'receipt']
    digest_a = hashlib.sha256(artifact['bytes']).hexdigest()
    assert receipts()[-1]['content_digest'] == digest_a
    # Exact replay is idempotent and should not record another effect.
    scans.publish_files('scan-1', _request(), {'files': ['one.pdf']})
    assert len(receipts()) == 1
    artifact.update(bytes=b'corrected version B', at='2026-09-06T00:00:00Z')
    second = scans.publish_files('scan-1', _request(), {'files': ['one.pdf']})
    assert second['published'][0]['status'] == 'published'
    digest_b = hashlib.sha256(artifact['bytes']).hexdigest()
    assert receipts()[-1]['content_digest'] == digest_b, (
        'Release returned published for B but the latest durable receipt still attests to A')
