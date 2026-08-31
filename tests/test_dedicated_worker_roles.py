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
    import handlers  # noqa: F401 — registers every handler in HANDLERS
    from worker import HANDLERS

    covered = set()
    for role in ('discovery', 'assess', 'remediate', 'processing'):
        monkeypatch.setenv('ACP_WORKER_ROLE', role)
        covered |= set(core._worker_job_types(0, 3) or ())

    unclaimable = sorted(set(HANDLERS) - covered)
    assert not unclaimable, (
        f"no worker role can claim {unclaimable} — a job of that type would sit 'queued' "
        f"forever in a split-role deployment, with nothing raising and nothing to see")


def test_the_stage_lanes_alone_cover_every_job_type(monkeypatch):
    """The stronger claim, and the one that actually bites. `processing` is the catch-all — it is
    every handler minus the Discovery lane — so any type nobody placed deliberately still gets
    claimed, and the sweep above passes. The lane tuples' own comment says that service is to be
    RETIRED. On that day the catch-all disappears and only the three stage lanes remain, so a type
    in none of them becomes unclaimable, silently, in a deployment change that touches no code.

    That is not hypothetical: when #1133 introduced these lanes it placed workspace_scan_file in
    ASSESS_LANE_JOB_TYPES and could not place workspace_scan_discover, which existed only on this
    branch. Checked by running it, the fully-lane-split union left exactly that one type
    uncovered. It is an Assess-lane job — see the comment on those tuples for why a
    discovery-shaped name belongs in the Assess lane — and this test is what keeps the next new
    job type from repeating it."""
    import core
    import handlers  # noqa: F401
    from worker import HANDLERS

    lanes = (core.DISCOVERY_LANE_JOB_TYPES + core.ASSESS_LANE_JOB_TYPES
             + core.REMEDIATE_LANE_JOB_TYPES)
    unplaced = sorted(set(HANDLERS) - set(lanes))
    assert not unplaced, (
        f"{unplaced} belong to no stage lane. Today the generic 'processing' role still claims "
        f"them; when it is retired they will queue forever. Add each to the lane that owns its "
        f"work.")

    # Disjoint, as those tuples claim to be: a type in two lanes is claimed by two services, and
    # the isolation the split exists for is gone for that type.
    assert len(lanes) == len(set(lanes)), (
        f"a job type appears in more than one stage lane: "
        f"{sorted(t for t in set(lanes) if lanes.count(t) > 1)}")


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
