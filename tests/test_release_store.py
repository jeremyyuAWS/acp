"""Durable release execution state is owner-scoped and retry-safe."""
import os


def _scan(store, scan_id, owner):
    store.init_scan_run(scan_id, "sharepoint", 2, "2026-09-05T10:00:00Z",
                        "rubric", "hash", owner=owner, status="completed")


def test_release_execution_and_roots_are_stable_across_retries(isolated_store):
    _scan(isolated_store, "scan-1", "owner@example.com")
    first = isolated_store.ensure_release_execution(
        "scan-1", "owner@example.com", "sharepoint", 2)
    again = isolated_store.ensure_release_execution(
        "scan-1", "owner@example.com", "sharepoint", 99)
    assert first["id"] == again["id"]
    assert again["documents_total"] == 2
    assert again["acp_version"] == (os.environ.get("ACP_BUILD_VERSION") or
                                    os.environ.get("ACP_VERSION") or "dev")

    isolated_store.record_release_root(
        first["id"], "owner@example.com", "sharepoint", "graph:drive-a",
        "folder-a", "2026-09-05 10-00 UTC", "https://sp/a")
    root = isolated_store.get_release_root(
        first["id"], "graph:drive-a", "owner@example.com")
    assert root["folder_id"] == "folder-a"


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
