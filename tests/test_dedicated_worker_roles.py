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


def test_every_registered_job_type_is_claimable_by_some_role(monkeypatch):
    """No job type may fall through every role's allow-list, or it queues forever in silence.

    THE SHAPE OF THE HAZARD, which is why this is a sweep and not an assertion about one type.
    The two role allow-lists are built from opposite halves of one literal:

        discovery   ("scan_discover",)                     — an explicit allow-list
        processing  every handler EXCEPT "scan_discover"   — the complement

    They cover the whole set only while those two definitions stay exact complements. Narrow the
    processing side by pattern rather than by that literal — excluding anything ending in
    "_discover", say, which reads like a tidy generalisation — and any OTHER discover-shaped type
    becomes claimable by neither role. Nothing raises: the jobs enqueue fine, sit 'queued', and
    the run never starts. A split-role deployment would show a workspace assessment that simply
    never begins, with a green queue and no error anywhere.

    workspace_scan_discover is exactly such a type, and it is deliberately NOT reserved-capacity
    Discovery: the reservation exists for _scan_discover's long connector walk, and this one is a
    single indexed SELECT over rows already in the database. Being claimed by the processing pool
    is the correct outcome, not an accident to be corrected — but it is only correct while the
    complement holds, which is what this test pins.
    """
    import core
    from worker import HANDLERS

    monkeypatch.setenv('ACP_WORKER_ROLE', 'discovery')
    discovery_types = set(core._worker_job_types(0, 3) or ())
    monkeypatch.setenv('ACP_WORKER_ROLE', 'processing')
    processing_types = set(core._worker_job_types(0, 3) or ())

    unclaimable = sorted(set(HANDLERS) - discovery_types - processing_types)
    assert not unclaimable, (
        f"no worker role can claim {unclaimable} — a job of that type would sit 'queued' "
        f"forever in a split-role deployment, with nothing raising and nothing to see")


def test_workspace_discovery_is_not_pinned_to_the_reserved_discovery_workers(monkeypatch,
                                                                             isolated_store):
    """The other direction. Reserved Discovery capacity exists to stop long connector walks
    starving the pool; putting a one-SELECT job behind them would make a workspace run wait on
    an estate walk it has nothing to do with."""
    import core
    import handlers  # noqa: F401 — registers the workspace handlers in HANDLERS
    monkeypatch.setenv('ACP_WORKER_ROLE', 'processing')
    types = core._worker_job_types(0, 3)
    assert 'workspace_scan_discover' in types
    assert 'workspace_scan_file' in types

    job_id = isolated_store.enqueue_job('workspace_scan_discover', {'scan_id': 's1'}, priority=100)
    claimed = isolated_store.claim_job('processing', job_types=types)
    assert claimed is not None and claimed['id'] == job_id
