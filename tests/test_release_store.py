"""Durable release execution state is owner-scoped and retry-safe."""


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

    isolated_store.record_release_root(
        first["id"], "owner@example.com", "sharepoint", "graph:drive-a",
        "folder-a", "2026-09-05 10-00 UTC", "https://sp/a")
    root = isolated_store.get_release_root(
        first["id"], "graph:drive-a", "owner@example.com")
    assert root["folder_id"] == "folder-a"


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
