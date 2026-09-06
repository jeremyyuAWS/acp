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
