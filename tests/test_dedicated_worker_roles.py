import pytest
from worker import JobWorker


def test_discovery_role_routes_every_slot_away_from_content(monkeypatch, isolated_store):
    import core
    monkeypatch.setenv('ACP_WORKER_ROLE', 'discovery')
    content = isolated_store.enqueue_job('scan_file', {}, priority=0)
    discovery = isolated_store.enqueue_job('scan_discover', {}, priority=100)
    for index in range(3):
        assert core._worker_job_types(index, 3) == core.DISCOVERY_LANE_JOB_TYPES
    claimed = isolated_store.claim_job('dedicated', job_types=core._worker_job_types(2, 3))
    assert claimed['id'] == discovery
    assert isolated_store.get_job(content)['status'] == 'queued'


def test_discovery_role_also_drains_the_fan_out(monkeypatch, isolated_store):
    """The Discovery stage is two job types. `scan_discover` lists the source and fans out one
    `scan_folder` per top-level folder — those folder jobs ARE the enumeration.

    With the lane naming only the entry job, a dedicated discovery service claimed the first job,
    fanned out, and then had nothing it was allowed to claim: its own follow-on work sat in the
    processing lane behind the content backlog while the service it was isolated into went idle.
    """
    import core
    monkeypatch.setenv('ACP_WORKER_ROLE', 'discovery')
    content = isolated_store.enqueue_job('scan_file', {}, priority=0)
    folder = isolated_store.enqueue_job('scan_folder', {'folder_id': 'f1'}, priority=100)
    types = core._worker_job_types(0, 3)
    assert isolated_store.claim_job('dedicated', job_types=types)['id'] == folder
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


def test_processing_role_excludes_the_whole_discovery_stage(monkeypatch, isolated_store):
    """Excluding only the entry job leaks the isolation: a processing worker would claim the
    scan_folder jobs the discovery service just fanned out. Both halves of the stage are out."""
    import core
    monkeypatch.setenv('ACP_WORKER_ROLE', 'processing')
    folder = isolated_store.enqueue_job('scan_folder', {}, priority=0)
    content = isolated_store.enqueue_job('scan_file', {}, priority=100)
    types = core._worker_job_types(0, 3)
    for reserved in core.DISCOVERY_LANE_JOB_TYPES:
        assert reserved not in types, reserved
    # Claims the CONTENT job despite the folder job outranking it on priority.
    assert isolated_store.claim_job('processing', job_types=types)['id'] == content
    assert isolated_store.get_job(folder)['status'] == 'queued'


def test_bad_role_fails_closed(monkeypatch):
    import core
    monkeypatch.setenv('ACP_WORKER_ROLE', 'discovrey')
    with pytest.raises(ValueError, match='ACP_WORKER_ROLE'):
        core._worker_job_types(0, 3)
