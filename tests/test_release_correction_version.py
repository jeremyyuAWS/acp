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


def test_new_release_digest_persists_without_replacing_provider_checksum(isolated_store):
    from test_release_store import _scan
    from release_artifacts import artifact_tag
    owner = 'owner@example.com'
    _scan(isolated_store, 'version-1', owner)
    _scan(isolated_store, 'version-2', owner)
    first = isolated_store.ensure_release_execution('version-1', owner, 'drive', 1)
    other = isolated_store.ensure_release_execution('version-2', owner, 'drive', 1)
    result = {'file': 'one.pdf', 'status': 'published', 'corrected_checksum': 'provider-md5',
              'artifact_digest': artifact_tag('a' * 64)}
    isolated_store.record_release_document(first['id'], owner, result)
    saved = isolated_store.get_release_document(first['id'], 'one.pdf', owner)
    assert saved['artifact_digest'] == 'sha256:' + 'a' * 64
    assert saved['corrected_checksum'] == 'provider-md5'
    assert isolated_store.get_release_document(other['id'], 'one.pdf', owner) is None
    assert isolated_store.get_release_document(first['id'], 'one.pdf', 'foreign@example.com') is None
    isolated_store.record_release_document(first['id'], 'foreign@example.com', {**result, 'artifact_digest': 'sha256:' + 'b' * 64})
    assert isolated_store.get_release_document(first['id'], 'one.pdf', owner)['artifact_digest'] == saved['artifact_digest']
    isolated_store.record_release_document(first['id'], owner, {**result, 'artifact_digest': 'sha256:' + 'b' * 64})
    assert isolated_store.get_release_document(first['id'], 'one.pdf', owner)['artifact_digest'] == 'sha256:' + 'b' * 64


def test_legacy_published_without_exact_digest_stays_unresolved_on_repeated_retry(monkeypatch):
    import core
    import publish
    from routes import scans
    store = _RouteStore('local')
    store.document = {'file': 'one.pdf', 'status': 'published', 'published_at': '2026-09-01'}
    original_save = store.record_release_document
    # Real persistence retains historical published_at when a failed request has no new timestamp.
    store.record_release_document = lambda rid, owner, result: original_save(rid, owner, {**result, 'published_at': '2026-09-01'})
    monkeypatch.setattr(core, 'store', store)
    monkeypatch.setattr(publish, 'remediated_content_digest', lambda *args: 'sha256-content')
    for _ in range(2):
        result = scans.publish_files('scan-1', _request(), {'files': ['one.pdf']})
        assert result['published'][0]['status'] == 'failed'
        assert 'no exact artifact digest' in result['published'][0]['explanation']
    assert not any(isinstance(event, tuple) and event[0] == 'receipt' for event in store.events)


def test_stale_source_and_revoked_approval_prevent_provider_effects(monkeypatch):
    import core
    import handlers
    import publish
    from routes import scans
    from types import SimpleNamespace
    store = _RouteStore('drive')
    state = {'compliant': 1, 'modified': '2026-09-02', 'revoke_on_read': False}
    original_record = store.get_file_record
    store.get_file_record = lambda *args: {**original_record(*args), 'compliant': state['compliant'], 'source_modified': '2026-09-01'}
    def metadata():
        if state['revoke_on_read']:
            state['compliant'] = 0
        return {'modifiedTime': state['modified']}
    service = SimpleNamespace(files=lambda: SimpleNamespace(get=lambda **kwargs: SimpleNamespace(execute=metadata)))
    monkeypatch.setattr(core, 'store', store)
    monkeypatch.setattr(handlers, '_drive_client', lambda token: service)
    monkeypatch.setattr(publish, 'remediated_content_digest', lambda *args: 'sha256-content')
    for revoke in (False, True):
        if revoke:
            state.update(modified='2026-09-01', revoke_on_read=True)
        result = scans.publish_files('scan-1', _request({'x-drive-token': 'fixture-token'}), {'files': ['one.pdf']})
        assert result['published'][0]['status'] == 'failed'
        assert 'Approval' in result['published'][0]['explanation'] if revoke else 'Source changed' in result['published'][0]['explanation']
    assert 'publish' not in store.events
    assert not any(isinstance(event, tuple) and event[0] in {'receipt', 'reserve'} for event in store.events)


def test_upload_reads_cannot_switch_away_from_reserved_bytes(monkeypatch):
    import publish
    import pytest
    monkeypatch.setattr(publish._blob, 'download_remediated', lambda *args: b'changed after reservation')
    monkeypatch.setattr(publish, 'ensure_relative_folders', lambda *args: pytest.fail('must not create folders'))
    monkeypatch.setattr(publish, '_sp_ensure_folder', lambda *args: pytest.fail('must not create folders'))
    digest = hashlib.sha256(b'approved bytes').hexdigest()
    with pytest.raises(ValueError, match='changed before delivery'):
        publish.archive_copy_publish(object(), 'folder', 'owner', 'scan', 'one.pdf', expected_digest=digest)
    with pytest.raises(ValueError, match='changed before delivery'):
        publish.archive_copy_publish_sharepoint('token', 'drive', 'folder', 'owner', 'release', 'scan', 'one.pdf', 'one.pdf', 'source', expected_digest=digest)


def test_new_correction_retry_reuses_completed_effect_after_persistence_failure(monkeypatch):
    import core
    import handlers
    import publish
    from routes import scans
    store = _RouteStore('drive')
    artifact = {'bytes': b'A'}
    digest = lambda: hashlib.sha256(artifact['bytes']).hexdigest()
    record = store.get_file_record
    store.get_file_record = lambda *args: {**record(*args), 'corrected_sha256': digest()}
    store.root = {'folder_id': 'folder', 'folder_name': 'Release', 'folder_url': 'https://example.test/folder'}
    store.get_release_root = lambda *args: store.root
    effects = {}
    uploads = []
    def reserve(**kwargs):
        key = kwargs['content_digest']
        if key in effects:
            return {'reused': True, 'status': 'completed', 'receipt': effects[key]}
        return {'acquired': True, 'effect_id': key, 'reservation_token': key}
    store.reserve_side_effect = reserve
    store.finalize_side_effect = lambda effect, token, receipt: effects.update({effect: receipt})
    original_save = store.record_release_document
    fail = {'once': False}
    def save(rid, owner, result):
        if result['status'] == 'published' and fail['once']:
            fail['once'] = False
            raise RuntimeError('persistence interruption')
        original_save(rid, owner, result)
    store.record_release_document = save
    monkeypatch.setattr(core, 'store', store)
    monkeypatch.setattr(handlers, '_drive_client', lambda token: object())
    monkeypatch.setattr(publish, 'remediated_content_digest', lambda *args: digest())
    def upload(*args, **kwargs):
        assert kwargs['expected_digest'] == digest()
        uploads.append(artifact['bytes'])
        return {'id': digest(), 'url': 'https://example.test/copy', 'checksum': 'provider-md5', 'created': True}
    monkeypatch.setattr(publish, 'archive_copy_publish', upload)
    request = _request({'x-drive-token': 'fixture'})
    scans.publish_files('scan-1', request, {'files': ['one.pdf']})
    scans.publish_files('scan-1', request, {'files': ['one.pdf']})
    assert uploads == [b'A']
    artifact['bytes'] = b'B'; fail['once'] = True
    result = scans.publish_files('scan-1', request, {'files': ['one.pdf']})
    assert result['published'][0]['status'] == 'queued'  # preserve uncertain-outcome recovery
    assert uploads == [b'A', b'B']
    scans.publish_files('scan-1', request, {'files': ['one.pdf']})
    scans.publish_files('scan-1', request, {'files': ['one.pdf']})
    assert uploads == [b'A', b'B']
    assert store.document['artifact_digest'] == 'sha256:' + digest()


def test_sharepoint_versions_queue_separately_and_stale_job_cannot_clobber_new_receipt(monkeypatch):
    import core
    import handlers
    import publish
    import pytest
    from handlers import FatalJobError
    from routes import scans
    from test_sharepoint_release_worker import FakeStore, OWNER, SID, FILE
    store = FakeStore()
    artifact = {'bytes': b'A', 'at': '2026-09-01'}
    original = store.get_file_record
    store.get_file_record = lambda *args: {**original(*args), 'remediated_at': artifact['at'],
                                          'corrected_sha256': hashlib.sha256(artifact['bytes']).hexdigest()}
    monkeypatch.setattr(core, 'store', store)
    monkeypatch.setattr(core, 'register_scan_tokens', lambda *args, **kwargs: None)
    monkeypatch.setattr(core, 'get_scan_tokens', lambda sid: {'sp': 'fixture'})
    monkeypatch.setattr(publish._blob, 'download_remediated', lambda *args: artifact['bytes'])
    monkeypatch.setattr(publish, 'ensure_sharepoint_release_folder', lambda *args, **kwargs: {'id': 'root', 'name': 'Release'})
    uploads = []
    def upload(*args, **kwargs):
        assert kwargs['expected_digest'] == hashlib.sha256(artifact['bytes']).hexdigest()
        uploads.append(artifact['bytes'])
        return {'id': str(len(uploads)), 'url': 'https://example.test/copy', 'checksum': kwargs['expected_digest'], 'created': True}
    monkeypatch.setattr(publish, 'archive_copy_publish_sharepoint', upload)
    request = _request({'x-sp-token': 'fixture'})
    first = scans.publish_files(SID, request, {'files': [FILE]})
    assert first['queued'] == 1
    job_a = dict(store.jobs[2][0]); fingerprint_a = store.jobs[3]['request_fingerprint']
    handlers._publish_file(job_a, {})
    assert scans.publish_files(SID, request, {'files': [FILE]})['queued'] == 0
    artifact.update(bytes=b'B', at='2026-09-02')
    second = scans.publish_files(SID, request, {'files': [FILE]})
    assert second['queued'] == 1
    assert store.jobs[3]['request_fingerprint'] != fingerprint_a
    handlers._publish_file(store.jobs[2][0], {})
    assert scans.publish_files(SID, request, {'files': [FILE]})['queued'] == 0
    assert uploads == [b'A', b'B']
    with pytest.raises(FatalJobError, match='changed after'):
        handlers._publish_file(job_a, {})
    assert store.documents[FILE]['status'] == 'published'
    assert store.documents[FILE]['artifact_digest'] == 'sha256:' + hashlib.sha256(b'B').hexdigest()


def test_worker_rejects_release_from_another_scan_before_mutation(monkeypatch):
    import core
    import handlers
    import pytest
    from handlers import FatalJobError
    from test_sharepoint_release_worker import FakeStore, OWNER, SID, FILE
    store = FakeStore()
    status = store.release_status
    store.release_status = lambda *args: {**status(*args), 'scan_id': 'foreign-scan'}
    monkeypatch.setattr(core, 'store', store)
    original_record = store.get_file_record
    for compliant in (1, 0):
        store.get_file_record = lambda *args: {**original_record(*args), 'compliant': compliant}
        with pytest.raises(FatalJobError, match='does not belong'):
            handlers._publish_file({'scan_id': SID, 'file': FILE, 'release_id': 'foreign-release', 'owner': OWNER}, {})
    assert store.documents == {}
    assert store.published is None


def test_worker_rechecks_document_selection_before_delivery(monkeypatch):
    import core
    import handlers
    import publish
    import pytest
    from handlers import FatalJobError
    from test_sharepoint_release_worker import FakeStore, OWNER, SID, FILE, DIGEST
    store = FakeStore()
    store.get_decisions = lambda *args, **kwargs: {FILE: {'triage': 'defer'}, 'other.pdf': {'triage': 'inscope'}}
    monkeypatch.setattr(core, 'store', store)
    monkeypatch.setattr(core, 'get_scan_tokens', lambda sid: {'sp': 'fixture'})
    monkeypatch.setattr(publish, 'remediated_content_digest', lambda *args: DIGEST)
    with pytest.raises(FatalJobError, match='no longer in'):
        handlers._publish_file({'scan_id': SID, 'file': FILE, 'release_id': 'release-1', 'owner': OWNER}, {})
    assert store.published is None
    assert store.documents[FILE]['status'] == 'failed'


def test_partial_release_retries_only_requested_failed_file(monkeypatch):
    import core
    import publish
    from routes import scans
    store = _RouteStore('local')
    documents = {}
    ready = {'one.pdf': True, 'two.pdf': False}
    original = store.get_file_record
    store.get_file_record = lambda sid, name: {**original(sid, name), 'compliant': ready[name]}
    store.get_release_document = lambda release, name, owner: documents.get(name)
    store.record_release_document = lambda release, owner, result: documents.update({result['file']: dict(result)})
    store.release_status = lambda *args: {'roots': [], 'documents_total': 2, 'published': sum(d['status'] == 'published' for d in documents.values())}
    monkeypatch.setattr(core, 'store', store)
    monkeypatch.setattr(publish, 'remediated_content_digest', lambda *args: 'sha256-content')
    result = scans.publish_files('scan-1', _request(), {'files': ['one.pdf', 'two.pdf']})
    assert [r['status'] for r in result['published']] == ['published', 'failed']
    first = dict(documents['one.pdf'])
    ready['two.pdf'] = True
    result = scans.publish_files('scan-1', _request(), {'files': ['two.pdf']})
    assert [r['file'] for r in result['published']] == ['two.pdf']
    assert result['published'][0]['status'] == 'published'
    assert documents['one.pdf'] == first


def test_unresolved_legacy_marker_survives_without_timestamp_or_provider_id():
    from release_artifacts import reuse_state
    saved = {'status': 'failed', 'failure_category': 'delivery_version_unresolved'}
    assert reuse_state(saved, 'a' * 64) == 'unresolved'


def test_sharepoint_reuse_rechecks_approval_after_source_read(monkeypatch):
    import core
    import publish
    import release_artifacts
    from routes import scans
    from test_sharepoint_release_worker import FakeStore, SID, FILE
    store = FakeStore()
    state = {"compliant": 1}
    digest = hashlib.sha256(b"A").hexdigest()
    original = store.get_file_record
    store.get_file_record = lambda *args: {
        **original(*args), "corrected_sha256": digest, "compliant": state["compliant"]}
    store.documents[FILE] = {"file": FILE, "status": "published", "artifact_digest": "sha256:" + digest}
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(core, "register_scan_tokens", lambda *args, **kwargs: None)
    monkeypatch.setattr(publish._blob, "download_remediated", lambda *args: b"A")
    monkeypatch.setattr(release_artifacts, "require_current_source",
                        lambda *args, **kwargs: state.update(compliant=0))
    result = scans.publish_files(SID, _request({"x-sp-token": "fixture"}), {"files": [FILE]})
    assert result["published"][0]["status"] == "failed"
    assert "Approval" in result["published"][0]["explanation"]
