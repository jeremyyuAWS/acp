import pytest
from worker import JobWorker


def test_discovery_role_routes_every_slot_away_from_content(monkeypatch, isolated_store):
    import core
    monkeypatch.setenv('ACP_WORKER_ROLE', 'discovery')
    content = isolated_store.enqueue_job('scan_file', {}, priority=0)
    discovery = isolated_store.enqueue_job('scan_discover', {}, priority=100)
    for index in range(3):
        assert core._worker_job_types(index, 3) == ('scan_discover',)
    claimed = isolated_store.claim_job('dedicated', job_types=core._worker_job_types(2, 3))
    assert claimed['id'] == discovery
    assert isolated_store.get_job(content)['status'] == 'queued'


def test_processing_role_never_claims_discovery(monkeypatch, isolated_store):
    import core
    import handlers
    monkeypatch.setenv('ACP_WORKER_ROLE', 'processing')
    discovery = isolated_store.enqueue_job('scan_discover', {}, priority=0)
    content = isolated_store.enqueue_job('scan_file', {}, priority=100)
    types = core._worker_job_types(0, 3)
    assert 'scan_file' in types
    assert 'scan_discover' not in types
    assert isolated_store.claim_job('processing', job_types=types)['id'] == content
    assert isolated_store.get_job(discovery)['status'] == 'queued'


def test_bad_role_fails_closed(monkeypatch):
    import core
    monkeypatch.setenv('ACP_WORKER_ROLE', 'discovrey')
    with pytest.raises(ValueError, match='ACP_WORKER_ROLE'):
        core._worker_job_types(0, 3)
