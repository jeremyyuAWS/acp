"""A scan is the first revision of one durable Discover → Assess → Remediate workflow."""

OWNER = "owner@example.org"


def test_scan_acceptance_creates_a_first_class_workflow_atomically(isolated_store):
    sid, _ = isolated_store.enqueue_scan(
        "scan-workflow-1", "sharepoint", OWNER, "scan_discover",
        {"scan_id": "scan-workflow-1"},
        inputs={"source": "sharepoint", "folder_ids": ["site-a"]},
    )

    workflow = isolated_store.workflow_for_scan(sid, OWNER)
    assert workflow == {
        **workflow,
        "id": sid,
        "scan_id": sid,
        "owner_email": OWNER,
        "source": "sharepoint",
        "revision": 1,
        "state": "waiting",
        "current_stage": "discover",
    }
    scan = isolated_store.get_scan(sid, owner=OWNER)["run"]
    assert scan["workflow_id"] == sid
    assert scan["workflow_revision"] == 1


def test_workflow_exposes_the_frozen_lifecycle_policy_ledger(isolated_store):
    rules = [
        {"policy_id": "archive-old", "version": 3, "condition": {"age_days": 365}},
        {"policy_id": "delete-temp", "version": 2, "condition": {"path": "Temp/"}},
    ]
    sid, _ = isolated_store.enqueue_scan(
        "scan-workflow-policy", "sharepoint", OWNER, "scan_discover", {},
        inputs={"source": "sharepoint", "lifecycle_rules": rules})

    workflow = isolated_store.workflow_for_scan(sid, OWNER)
    assert workflow["lifecycle_policy_count"] == 2
    assert workflow["lifecycle_policy_versions"] == [
        {"policy_id": "archive-old", "version": 3},
        {"policy_id": "delete-temp", "version": 2},
    ]
    assert len(workflow["lifecycle_policy_digest"]) == 64

    [active] = isolated_store.active_workflows(OWNER)
    assert active["lifecycle_policy_digest"] == workflow["lifecycle_policy_digest"]
    assert active["lifecycle_policy_versions"] == workflow["lifecycle_policy_versions"]


def test_stage_snapshot_is_bound_to_the_frozen_lifecycle_rules(isolated_store):
    sid, _ = isolated_store.enqueue_scan(
        "scan-workflow-snapshot", "sharepoint", OWNER, "scan_discover", {},
        inputs={"source": "sharepoint", "lifecycle_rules": [
            {"policy_id": "archive-old", "version": 1}]})
    first = isolated_store.stage_snapshot_id(sid)

    # scan_inputs is immutable through the product API. This direct corruption demonstrates the
    # identity is cryptographically sensitive to the policy snapshot rather than ignoring it.
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(
            cur, "UPDATE scan_inputs SET lifecycle_rules=%s WHERE scan_id=%s",
            ('[{"policy_id":"archive-old","version":2}]', sid))

    assert isolated_store.stage_snapshot_id(sid) != first


def test_workflow_stage_projection_advances_with_durable_stage_events(isolated_store):
    sid, _ = isolated_store.enqueue_scan(
        "scan-workflow-2", "sharepoint", OWNER, "scan_discover",
        {"scan_id": "scan-workflow-2"}, inputs={"source": "sharepoint"})
    execution = isolated_store.enqueue_stage_batch(
        sid, "assess", "scan_assess", [{"scan_id": sid}],
        snapshot_id="snapshot-1", request_fingerprint="scope-1")

    workflow = isolated_store.workflow_for_scan(sid, OWNER)
    assert (workflow["current_stage"], workflow["state"]) == ("assess", "running")

    job = isolated_store.claim_job("worker-1", job_types=("scan_assess",))
    assert job["id"] == execution["job_ids"][0]
    isolated_store.complete_job(job["id"], worker_id="worker-1", attempt=job["attempts"])
    workflow = isolated_store.workflow_for_scan(sid, OWNER)
    assert (workflow["current_stage"], workflow["state"]) == ("assess", "completed")


def test_active_workflow_contract_exposes_identity_and_revision(isolated_store):
    sid, _ = isolated_store.enqueue_scan(
        "scan-workflow-3", "drive", OWNER, "scan_discover",
        {"scan_id": "scan-workflow-3"}, inputs={"source": "drive"})

    [active] = isolated_store.active_workflows(OWNER)
    assert active["scan_id"] == sid
    assert active["workflow_id"] == sid
    assert active["workflow_revision"] == 1


def test_pre_v24_scan_has_a_compatible_workflow_identity(isolated_store):
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "INSERT INTO scan_runs(id,source,status,owner_email,started_at) "
            "VALUES(%s,%s,%s,%s,%s)",
            ("legacy-scan", "drive", "done", OWNER, isolated_store._now()))

    workflow = isolated_store.workflow_for_scan("legacy-scan", OWNER)
    assert workflow["id"] == "legacy-scan"
    assert workflow["revision"] == 1
    assert workflow["legacy"] is True
