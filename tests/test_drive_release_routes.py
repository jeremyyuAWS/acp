"""Drive submits resumable delivery work; the HTTP request never uploads a file."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from test_sharepoint_release_worker import FakeStore, OWNER, SID, FILE, DIGEST


class DriveStore(FakeStore):
    def get_scan(self, sid, owner=None):
        scan = super().get_scan(sid, owner)
        scan['run']['source'] = 'drive'
        return scan

    def enqueue_manual_drive_release(self, sid, payloads, *, owner, **kwargs):
        assert owner == OWNER
        return self.enqueue_stage_batch(sid, 'release', 'publish_file', payloads, **kwargs)

    def ensure_synchronous_stage_execution(self, **kwargs):
        raise AssertionError('Drive must not create job-less Release work')


@pytest.fixture
def setup(monkeypatch):
    import core
    import handlers
    import publish
    store = DriveStore()
    registered = []
    monkeypatch.setattr(core, 'store', store)
    monkeypatch.setattr(core, 'register_scan_tokens', lambda *a, **kw: registered.append((a, kw)))
    monkeypatch.setattr(handlers, '_drive_client', lambda token: object())
    monkeypatch.setattr(publish, 'archive_copy_publish', lambda *a, **kw: pytest.fail('request uploaded bytes'))
    return store, registered


def test_drive_submission_is_durable_and_credentials_are_not_in_payload(setup):
    from routes.scans import publish_files
    store, registered = setup
    response = publish_files(SID, SimpleNamespace(state=SimpleNamespace(user_email=OWNER),
        headers={'x-drive-token': 'private-grant'}), {'files': [FILE]})
    assert response['queued'] == 1 and response['batch_id'] == 'batch-1'
    assert store.jobs[:2] == ('release', 'publish_file')
    assert store.jobs[2][0]['artifact_digest'] == f'sha256:{DIGEST}'
    assert 'private-grant' not in repr(store.jobs)
    assert registered == [((SID,), {'drive': 'private-grant', 'require_shared': True})]


def test_drive_without_write_grant_does_not_queue(setup):
    from routes.scans import publish_files
    store, _ = setup
    with pytest.raises(HTTPException) as error:
        publish_files(SID, SimpleNamespace(state=SimpleNamespace(user_email=OWNER), headers={}), {'files': [FILE]})
    assert error.value.status_code == 403
    assert store.jobs is None


def test_shared_credential_failure_does_not_queue(setup, monkeypatch):
    import core
    from routes.scans import publish_files
    store, _ = setup
    def unavailable(*a, **kw):
        raise core.SharedTokenStoreUnavailable('offline')
    monkeypatch.setattr(core, 'register_scan_tokens', unavailable)
    with pytest.raises(HTTPException) as error:
        publish_files(SID, SimpleNamespace(state=SimpleNamespace(user_email=OWNER),
            headers={'x-drive-token': 'private-grant'}), {'files': [FILE]})
    assert error.value.status_code == 503
    assert store.jobs is None


def test_automatic_resume_requires_release_publish_capability():
    from workspace_capability_map import ROUTE_CAPABILITIES
    assert ROUTE_CAPABILITIES[('POST', '/scans/{sid}/release/automatic/{authorization_id}/resume')] == {'release.publish'}


def test_resume_rejects_wrong_scan_before_registering_credentials(monkeypatch):
    from fastapi import Response
    from routes import automatic_release as route
    monkeypatch.setattr(route, 'owner_scan', lambda *a: (OWNER, {}))
    monkeypatch.setattr(route.persistence, 'get', lambda *a: {'scan_id': 'other-scan'})
    monkeypatch.setattr(route, 'credentials', lambda *a: pytest.fail('foreign credentials admitted'))
    with pytest.raises(HTTPException) as error:
        route.resume(SID, 'auth-1', SimpleNamespace(headers={}), Response())
    assert error.value.status_code == 404


def test_resume_preserves_saved_authorization_and_registers_current_credentials(monkeypatch):
    from fastapi import Response
    from routes import automatic_release as route
    calls = []
    monkeypatch.setattr(route, 'owner_scan', lambda *a: (OWNER, {}))
    monkeypatch.setattr(route.persistence, 'get', lambda *a: {'scan_id': SID})
    monkeypatch.setattr(route, 'credentials', lambda *a: calls.append('credentials'))
    monkeypatch.setattr(route.service, 'resume', lambda store, identifier, owner, sid:
                        calls.append((identifier, owner)) or {'id': identifier}, raising=False)
    monkeypatch.setattr(route.service, 'public', lambda row, store: row)
    response = Response()
    assert route.resume(SID, 'auth-1', SimpleNamespace(headers={}), response) == {'id': 'auth-1'}
    assert calls == ['credentials', ('auth-1', OWNER)]
    assert response.headers['cache-control'] == 'no-store'


def test_manual_release_missing_drive_token_exposes_reconnect(monkeypatch):
    import core
    from routes.release_continuation import public_state
    monkeypatch.setattr(core, 'get_scan_tokens', lambda sid: {})
    row = {'scan_id': SID, 'intent': {'source': 'drive', 'files': {}},
           'progress': {FILE: {'state': 'failed'}}}
    assert public_state(row)['requires_reconnect'] is True
    row['progress'][FILE]['state'] = 'published'
    assert public_state(row)['requires_reconnect'] is False


def test_manual_release_missing_token_is_retryable_without_new_approval(monkeypatch):
    import core
    from release_continuation import source_check
    monkeypatch.setattr(core, 'get_scan_tokens', lambda sid: {})
    with pytest.raises(PermissionError, match='Reconnect Google Drive'):
        source_check({'scan_id': SID, 'intent': {'source': 'drive'}}, {})
