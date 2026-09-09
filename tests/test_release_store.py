"""Durable release execution state is owner-scoped and retry-safe."""
import os


def _scan(store, scan_id, owner):
    store.init_scan_run(scan_id, "sharepoint", 2, "2026-09-05T10:00:00Z",
                        "rubric", "hash", owner=owner, status="completed")


def test_release_identity_and_roots_stay_stable_while_total_expands(isolated_store):
    _scan(isolated_store, "scan-1", "owner@example.com")
    first = isolated_store.ensure_release_execution(
        "scan-1", "owner@example.com", "sharepoint", 2)
    again = isolated_store.ensure_release_execution(
        "scan-1", "owner@example.com", "sharepoint", 99)
    assert first["id"] == again["id"]
    assert again["documents_total"] == 99
    assert again["acp_version"] == (os.environ.get("ACP_BUILD_VERSION") or
                                    os.environ.get("ACP_VERSION") or "dev")

    isolated_store.record_release_root(
        first["id"], "owner@example.com", "sharepoint", "graph:drive-a",
        "folder-a", "2026-09-05 10-00 UTC", "https://sp/a")
    root = isolated_store.get_release_root(
        first["id"], "graph:drive-a", "owner@example.com")
    assert root["folder_id"] == "folder-a"


def test_custom_folder_name_is_saved_once_and_stays_stable_on_retry(isolated_store):
    owner = "owner@example.com"
    _scan(isolated_store, "scan-named", owner)
    first = isolated_store.ensure_release_execution(
        "scan-named", owner, "sharepoint", 2,
        preferred_folder_name="Q3 Accessibility Release")
    retry = isolated_store.ensure_release_execution(
        "scan-named", owner, "sharepoint", 2,
        preferred_folder_name="A different name")
    assert first["folder_name"].endswith(" - owner@example.com - Q3 Accessibility Release")
    assert retry["folder_name"] == first["folder_name"]


def test_custom_parent_destination_is_saved_once_and_stays_stable_on_retry(isolated_store):
    owner = "owner@example.com"
    _scan(isolated_store, "scan-parent", owner)
    first = isolated_store.ensure_release_execution(
        "scan-parent", owner, "sharepoint", 2,
        parent_folder_id="drive-a/folder-a", parent_folder_name="Finance")
    retry = isolated_store.ensure_release_execution(
        "scan-parent", owner, "sharepoint", 2,
        parent_folder_id="drive-b/folder-b", parent_folder_name="Wrong retry target")
    assert first["parent_folder_id"] == retry["parent_folder_id"] == "drive-a/folder-a"
    assert first["parent_folder_name"] == retry["parent_folder_name"] == "Finance"


def test_later_approvals_expand_and_reopen_a_completed_release(isolated_store):
    owner = "owner@example.com"
    _scan(isolated_store, "scan-expand", owner)
    release = isolated_store.ensure_release_execution("scan-expand", owner, "sharepoint", 2)
    for name in ("one.pdf", "two.pdf"):
        isolated_store.record_release_document(release["id"], owner, {
            "file": name, "status": "published", "created": True,
        })
    assert isolated_store.release_status(release["id"], owner)["status"] == "completed"

    expanded = isolated_store.ensure_release_execution("scan-expand", owner, "sharepoint", 3)
    status = isolated_store.release_status(release["id"], owner)
    assert expanded["id"] == release["id"]
    assert expanded["status"] == "running"
    assert (status["documents_total"], status["published"], status["remaining"]) == (3, 2, 1)

    stale_retry = isolated_store.ensure_release_execution("scan-expand", owner, "sharepoint", 1)
    assert stale_retry["documents_total"] == 3


def test_release_root_name_claim_survives_retries_and_separates_concurrent_releases(isolated_store):
    owner = "owner@example.com"
    _scan(isolated_store, "scan-claim-1", owner)
    _scan(isolated_store, "scan-claim-2", owner)
    first = isolated_store.ensure_release_execution("scan-claim-1", owner, "sharepoint", 1)
    second = isolated_store.ensure_release_execution("scan-claim-2", owner, "sharepoint", 1)
    timestamp = "2026-09-05 10-00 UTC"

    first_name = isolated_store.claim_release_root_name(
        first["id"], owner, "sharepoint", "graph:drive-a", timestamp)
    retry_name = isolated_store.claim_release_root_name(
        first["id"], owner, "sharepoint", "graph:drive-a", timestamp)
    second_name = isolated_store.claim_release_root_name(
        second["id"], owner, "sharepoint", "graph:drive-a", timestamp)

    assert first_name == retry_name == timestamp
    assert second_name == f"{timestamp} · {second['id'][:8]}"


def test_release_status_counts_success_failure_and_remaining(isolated_store):
    _scan(isolated_store, "scan-2", "owner@example.com")
    release = isolated_store.ensure_release_execution(
        "scan-2", "owner@example.com", "sharepoint", 3)
    isolated_store.record_release_document(release["id"], "owner@example.com", {
        "file": "one.pdf", "provider_location": "graph:drive-a", "status": "published",
        "provider_item_id": "item-1", "url": "https://sp/one", "checksum": "abc",
        "verified": True, "created": True, "published_filename": "one.pdf",
    })
    isolated_store.record_release_document(release["id"], "owner@example.com", {
        "file": "two.pdf", "provider_location": "graph:drive-a", "status": "failed",
        "error": "permission denied",
    })
    status = isolated_store.release_status(release["id"], "owner@example.com")
    assert (status["published"], status["failed"], status["remaining"]) == (1, 1, 1)
    assert isolated_store.release_status(release["id"], "someone@example.com") is None


def test_release_history_is_owner_scoped_and_includes_durable_evidence(isolated_store):
    owner = "owner@example.com"
    _scan(isolated_store, "scan-history", owner)
    _scan(isolated_store, "scan-foreign", "someone@example.com")
    release = isolated_store.ensure_release_execution(
        "scan-history", owner, "sharepoint", 2, preferred_folder_name="Finance Release")
    isolated_store.record_release_root(
        release["id"], owner, "sharepoint", "graph:finance", "folder-1",
        "Finance Release", "https://sharepoint.example/finance")
    isolated_store.record_release_document(release["id"], owner, {
        "file": "report.pdf", "status": "published", "created": False,
        "released_relative_path": "Remediated/Finance Release/report.pdf",
        "corrected_checksum": "a" * 64, "verification": "sha256",
        "published_at": "2026-09-06T12:00:00Z",
    })
    isolated_store.ensure_release_execution(
        "scan-foreign", "someone@example.com", "sharepoint", 1)

    history = isolated_store.list_release_history(owner)

    assert [row["id"] for row in history] == [release["id"]]
    assert history[0]["folder_name"] == release["folder_name"]
    assert release["folder_name"].endswith(" - owner@example.com - Finance Release")
    assert history[0]["roots"][0]["folder_url"] == "https://sharepoint.example/finance"
    assert history[0]["documents"][0]["created_result"] == 0
    assert history[0]["documents"][0]["corrected_checksum"] == "a" * 64
    assert (history[0]["published"], history[0]["failed"], history[0]["remaining"]) == (1, 0, 1)


def test_deleting_a_scan_also_removes_its_release_records(isolated_store):
    _scan(isolated_store, "scan-delete", "owner@example.com")
    release = isolated_store.ensure_release_execution(
        "scan-delete", "owner@example.com", "sharepoint", 1)
    isolated_store.record_release_root(
        release["id"], "owner@example.com", "sharepoint", "graph:drive-a",
        "folder-a", "2026-09-05 10-00 UTC", "https://sp/a")
    isolated_store.record_release_document(release["id"], "owner@example.com", {
        "file": "one.pdf", "status": "published", "created": True,
    })

    isolated_store.delete_scan("scan-delete", "owner@example.com")

    assert isolated_store.release_status(release["id"], "owner@example.com") is None


def test_legacy_release_name_is_not_renamed_by_new_email_policy(isolated_store):
    owner = 'owner@example.com'
    _scan(isolated_store, 'legacy-folder', owner)
    original = isolated_store.ensure_release_execution('legacy-folder', owner, 'sharepoint', 1)
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur, 'UPDATE release_executions SET folder_name=%s WHERE id=%s', ('2026-09-01 10-00 UTC', original['id']))
    retry = isolated_store.ensure_release_execution('legacy-folder', owner, 'sharepoint', 2, preferred_folder_name='New label')
    assert retry['id'] == original['id']
    assert retry['folder_name'] == '2026-09-01 10-00 UTC'
