"""ACP Managed Content Workspace (ADR 0044) — content_workspace_documents /
content_workspace_document_versions store-layer CRUD.

Store-layer only, no route yet (see ADR 0044: these tables are specified for "the upload PR
that populates them" — this PR builds the tables and the store methods an upload route will
call; the route itself, with a real Blob write behind it, is a later item).
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "alice@x.com"
OTHER = "bob@y.com"


@pytest.fixture()
def ws(isolated_store):
    """A real workspace to attach documents to, owned by OWNER."""
    wid = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace(wid, owner_email=OWNER, name="Test workspace")
    return wid


def test_create_and_get_a_document(isolated_store, ws):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(
        doc_id, workspace_id=ws, owner_email=OWNER, display_name="report.pdf",
        relative_path="Legal/report.pdf", status="uploading")
    doc = isolated_store.get_content_workspace_document(doc_id, owner_email=OWNER)
    assert doc["display_name"] == "report.pdf"
    assert doc["relative_path"] == "Legal/report.pdf"
    assert doc["status"] == "uploading"
    assert doc["workspace_id"] == ws


def test_a_foreign_owner_gets_none_not_the_document(isolated_store, ws):
    """Same 404-not-403 contract as get_content_workspace/get_scan — an id must not be an
    existence oracle across owners."""
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(
        doc_id, workspace_id=ws, owner_email=OWNER, display_name="private.pdf")
    assert isolated_store.get_content_workspace_document(doc_id, owner_email=OTHER) is None


def test_list_is_scoped_to_workspace_and_owner(isolated_store, ws):
    other_ws = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace(other_ws, owner_email=OWNER, name="Other workspace")
    isolated_store.create_content_workspace_document(
        uuid.uuid4().hex[:12], workspace_id=ws, owner_email=OWNER, display_name="in-scope.pdf")
    isolated_store.create_content_workspace_document(
        uuid.uuid4().hex[:12], workspace_id=other_ws, owner_email=OWNER, display_name="elsewhere.pdf")

    names = [d["display_name"] for d in isolated_store.list_content_workspace_documents(ws, owner_email=OWNER)]
    assert names == ["in-scope.pdf"]
    assert isolated_store.list_content_workspace_documents(ws, owner_email=OTHER) == []


def test_update_status(isolated_store, ws):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(
        doc_id, workspace_id=ws, owner_email=OWNER, status="uploading")
    isolated_store.update_content_workspace_document_status(doc_id, "ready")
    assert isolated_store.get_content_workspace_document(doc_id, owner_email=OWNER)["status"] == "ready"


def test_update_display_name(isolated_store, ws):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(
        doc_id, workspace_id=ws, owner_email=OWNER, display_name="report.pdf")
    isolated_store.update_content_workspace_document_display_name(doc_id, "report_v2.docx")
    assert isolated_store.get_content_workspace_document(
        doc_id, owner_email=OWNER)["display_name"] == "report_v2.docx"


def test_first_version_is_seq_1(isolated_store, ws):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc_id, workspace_id=ws, owner_email=OWNER)
    assert isolated_store.next_content_workspace_document_version_seq(doc_id) == 1


def test_version_seq_increments_past_existing_versions(isolated_store, ws):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc_id, workspace_id=ws, owner_email=OWNER)
    isolated_store.create_content_workspace_document_version(
        uuid.uuid4().hex[:12], document_id=doc_id, version_seq=1, content_hash="h1")
    assert isolated_store.next_content_workspace_document_version_seq(doc_id) == 2
    isolated_store.create_content_workspace_document_version(
        uuid.uuid4().hex[:12], document_id=doc_id, version_seq=2, content_hash="h2")
    assert isolated_store.next_content_workspace_document_version_seq(doc_id) == 3


def test_list_versions_newest_first(isolated_store, ws):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc_id, workspace_id=ws, owner_email=OWNER)
    isolated_store.create_content_workspace_document_version(
        uuid.uuid4().hex[:12], document_id=doc_id, version_seq=1, content_hash="h1")
    isolated_store.create_content_workspace_document_version(
        uuid.uuid4().hex[:12], document_id=doc_id, version_seq=2, content_hash="h2")
    versions = isolated_store.list_content_workspace_document_versions(doc_id)
    assert [v["version_seq"] for v in versions] == [2, 1]


def test_get_latest_version(isolated_store, ws):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc_id, workspace_id=ws, owner_email=OWNER)
    isolated_store.create_content_workspace_document_version(
        uuid.uuid4().hex[:12], document_id=doc_id, version_seq=1, content_hash="h1",
        original_filename="v1.pdf")
    isolated_store.create_content_workspace_document_version(
        uuid.uuid4().hex[:12], document_id=doc_id, version_seq=2, content_hash="h2",
        original_filename="v2.pdf")
    latest = isolated_store.get_latest_content_workspace_document_version(doc_id)
    assert latest["original_filename"] == "v2.pdf"


def test_get_latest_version_of_a_document_with_none_is_none(isolated_store, ws):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc_id, workspace_id=ws, owner_email=OWNER)
    assert isolated_store.get_latest_content_workspace_document_version(doc_id) is None


def test_get_version_scoped_to_its_own_document(isolated_store, ws):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc_id, workspace_id=ws, owner_email=OWNER)
    version_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document_version(
        version_id, document_id=doc_id, version_seq=1, content_hash="h1")

    found = isolated_store.get_content_workspace_document_version(version_id, document_id=doc_id)
    assert found is not None
    assert found["id"] == version_id


def test_get_version_belonging_to_a_different_document_is_none(isolated_store, ws):
    doc1 = uuid.uuid4().hex[:12]
    doc2 = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc1, workspace_id=ws, owner_email=OWNER)
    isolated_store.create_content_workspace_document(doc2, workspace_id=ws, owner_email=OWNER)
    version_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document_version(
        version_id, document_id=doc1, version_seq=1, content_hash="h1")

    assert isolated_store.get_content_workspace_document_version(
        version_id, document_id=doc2) is None


def test_a_version_carries_the_full_field_set(isolated_store, ws):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc_id, workspace_id=ws, owner_email=OWNER)
    version_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document_version(
        version_id, document_id=doc_id, version_seq=1, content_hash="h1",
        mime_type="application/pdf", size_bytes=1024, blob_path="workspace/alice/ws1/doc1/source/v1/original",
        original_filename="Report.pdf", uploaded_by=OWNER, malware_status="clean",
        lifecycle_state="ready", assessment_status="pending")
    [v] = isolated_store.list_content_workspace_document_versions(doc_id)
    assert v["id"] == version_id
    assert v["mime_type"] == "application/pdf"
    assert v["size_bytes"] == 1024
    assert v["blob_path"] == "workspace/alice/ws1/doc1/source/v1/original"
    assert v["malware_status"] == "clean"
    assert v["uploaded_by"] == OWNER


def test_duplicate_detection_finds_a_matching_hash_in_the_same_workspace(isolated_store, ws):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc_id, workspace_id=ws, owner_email=OWNER)
    isolated_store.create_content_workspace_document_version(
        uuid.uuid4().hex[:12], document_id=doc_id, version_seq=1, content_hash="dupe-hash")

    found = isolated_store.find_content_workspace_document_version_by_hash(
        ws, "dupe-hash", owner_email=OWNER)
    assert found is not None
    assert found["content_hash"] == "dupe-hash"


def test_duplicate_detection_is_scoped_to_the_workspace(isolated_store, ws):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc_id, workspace_id=ws, owner_email=OWNER)
    isolated_store.create_content_workspace_document_version(
        uuid.uuid4().hex[:12], document_id=doc_id, version_seq=1, content_hash="same-bytes")

    other_ws = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace(other_ws, owner_email=OWNER, name="Other workspace")
    assert isolated_store.find_content_workspace_document_version_by_hash(
        other_ws, "same-bytes", owner_email=OWNER) is None


def test_duplicate_detection_never_crosses_owners(isolated_store, ws):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc_id, workspace_id=ws, owner_email=OWNER)
    isolated_store.create_content_workspace_document_version(
        uuid.uuid4().hex[:12], document_id=doc_id, version_seq=1, content_hash="same-bytes")
    assert isolated_store.find_content_workspace_document_version_by_hash(
        ws, "same-bytes", owner_email=OTHER) is None


def test_no_match_returns_none(isolated_store, ws):
    assert isolated_store.find_content_workspace_document_version_by_hash(
        ws, "never-uploaded", owner_email=OWNER) is None


def test_update_version_lifecycle_state(isolated_store, ws):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc_id, workspace_id=ws, owner_email=OWNER)
    version_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document_version(
        version_id, document_id=doc_id, version_seq=1, content_hash="h1",
        lifecycle_state="duplicate")

    isolated_store.update_content_workspace_document_version_lifecycle_state(version_id, "ready")
    [v] = isolated_store.list_content_workspace_document_versions(doc_id)
    assert v["lifecycle_state"] == "ready"


def test_delete_document_removes_it_and_its_versions(isolated_store, ws):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc_id, workspace_id=ws, owner_email=OWNER)
    isolated_store.create_content_workspace_document_version(
        uuid.uuid4().hex[:12], document_id=doc_id, version_seq=1, content_hash="h1")

    deleted = isolated_store.delete_content_workspace_document(doc_id, owner_email=OWNER)
    assert deleted is True
    assert isolated_store.get_content_workspace_document(doc_id, owner_email=OWNER) is None
    assert isolated_store.list_content_workspace_document_versions(doc_id) == []


def test_delete_document_is_owner_scoped(isolated_store, ws):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc_id, workspace_id=ws, owner_email=OWNER)

    deleted = isolated_store.delete_content_workspace_document(doc_id, owner_email=OTHER)
    assert deleted is False
    assert isolated_store.get_content_workspace_document(doc_id, owner_email=OWNER) is not None


def test_delete_document_returns_false_for_a_nonexistent_document(isolated_store, ws):
    assert isolated_store.delete_content_workspace_document("does-not-exist", owner_email=OWNER) is False


def test_list_expired_versions_finds_a_past_due_retention_date(isolated_store, ws):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc_id, workspace_id=ws, owner_email=OWNER)
    version_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document_version(
        version_id, document_id=doc_id, version_seq=1, content_hash="h1",
        retention_date="2020-01-01T00:00:00+00:00")

    expired = isolated_store.list_expired_content_workspace_document_versions(
        as_of="2026-01-01T00:00:00+00:00")
    assert [v["id"] for v in expired] == [version_id]
    assert expired[0]["workspace_id"] == ws
    assert expired[0]["owner_email"] == OWNER


def test_list_expired_versions_excludes_a_future_retention_date(isolated_store, ws):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc_id, workspace_id=ws, owner_email=OWNER)
    isolated_store.create_content_workspace_document_version(
        uuid.uuid4().hex[:12], document_id=doc_id, version_seq=1, content_hash="h1",
        retention_date="2099-01-01T00:00:00+00:00")

    assert isolated_store.list_expired_content_workspace_document_versions(
        as_of="2026-01-01T00:00:00+00:00") == []


def test_list_expired_versions_excludes_a_version_with_no_retention_date(isolated_store, ws):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc_id, workspace_id=ws, owner_email=OWNER)
    isolated_store.create_content_workspace_document_version(
        uuid.uuid4().hex[:12], document_id=doc_id, version_seq=1, content_hash="h1")

    assert isolated_store.list_expired_content_workspace_document_versions() == []


def test_list_expired_versions_excludes_one_already_marked_expired(isolated_store, ws):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc_id, workspace_id=ws, owner_email=OWNER)
    version_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document_version(
        version_id, document_id=doc_id, version_seq=1, content_hash="h1",
        retention_date="2020-01-01T00:00:00+00:00", lifecycle_state="expired")

    assert isolated_store.list_expired_content_workspace_document_versions(
        as_of="2026-01-01T00:00:00+00:00") == []


def test_storage_bytes_sums_versions_across_documents(isolated_store, ws):
    doc1 = uuid.uuid4().hex[:12]
    doc2 = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc1, workspace_id=ws, owner_email=OWNER)
    isolated_store.create_content_workspace_document(doc2, workspace_id=ws, owner_email=OWNER)
    isolated_store.create_content_workspace_document_version(
        uuid.uuid4().hex[:12], document_id=doc1, version_seq=1, content_hash="h1", size_bytes=100)
    isolated_store.create_content_workspace_document_version(
        uuid.uuid4().hex[:12], document_id=doc2, version_seq=1, content_hash="h2", size_bytes=250)

    assert isolated_store.get_content_workspace_storage_bytes(ws, owner_email=OWNER) == 350


def test_storage_bytes_is_zero_for_an_empty_workspace(isolated_store, ws):
    assert isolated_store.get_content_workspace_storage_bytes(ws, owner_email=OWNER) == 0


def test_storage_bytes_excludes_expired_versions(isolated_store, ws):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc_id, workspace_id=ws, owner_email=OWNER)
    isolated_store.create_content_workspace_document_version(
        uuid.uuid4().hex[:12], document_id=doc_id, version_seq=1, content_hash="h1",
        size_bytes=500, lifecycle_state="expired")

    assert isolated_store.get_content_workspace_storage_bytes(ws, owner_email=OWNER) == 0


def test_storage_bytes_includes_quarantined_and_duplicate_versions(isolated_store, ws):
    """Those states still occupy real blob storage, whatever their Discovery-eligibility."""
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc_id, workspace_id=ws, owner_email=OWNER)
    isolated_store.create_content_workspace_document_version(
        uuid.uuid4().hex[:12], document_id=doc_id, version_seq=1, content_hash="h1",
        size_bytes=100, lifecycle_state="quarantined")
    isolated_store.create_content_workspace_document_version(
        uuid.uuid4().hex[:12], document_id=doc_id, version_seq=2, content_hash="h2",
        size_bytes=200, lifecycle_state="duplicate")

    assert isolated_store.get_content_workspace_storage_bytes(ws, owner_email=OWNER) == 300


def test_storage_bytes_is_scoped_to_the_workspace_and_owner(isolated_store, ws):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc_id, workspace_id=ws, owner_email=OWNER)
    isolated_store.create_content_workspace_document_version(
        uuid.uuid4().hex[:12], document_id=doc_id, version_seq=1, content_hash="h1", size_bytes=500)

    other_ws = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace(other_ws, owner_email=OWNER, name="Other")
    assert isolated_store.get_content_workspace_storage_bytes(other_ws, owner_email=OWNER) == 0
    assert isolated_store.get_content_workspace_storage_bytes(ws, owner_email=OTHER) == 0


def test_get_version_scan_returns_none_when_never_assessed(isolated_store, ws):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc_id, workspace_id=ws, owner_email=OWNER)
    version_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document_version(
        version_id, document_id=doc_id, version_seq=1, content_hash="h1")

    assert isolated_store.get_content_workspace_version_scan(version_id) is None


def test_get_version_scan_finds_the_linked_scan(isolated_store, ws):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc_id, workspace_id=ws, owner_email=OWNER)
    version_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document_version(
        version_id, document_id=doc_id, version_seq=1, content_hash="h1")

    scan_id, _ = isolated_store.enqueue_scan(
        uuid.uuid4().hex[:12], "workspace", OWNER, "workspace_scan_file", {},
        content_workspace_version_id=version_id)

    scan = isolated_store.get_content_workspace_version_scan(version_id)
    assert scan is not None
    assert scan["id"] == scan_id
    assert scan["status"] == "queued"


def test_get_version_scan_returns_the_most_recent_of_several(isolated_store, ws):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc_id, workspace_id=ws, owner_email=OWNER)
    version_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document_version(
        version_id, document_id=doc_id, version_seq=1, content_hash="h1")

    isolated_store.enqueue_scan(uuid.uuid4().hex[:12], "workspace", OWNER, "workspace_scan_file",
                                {}, content_workspace_version_id=version_id)
    # A second (later) scan for the same version — e.g. a re-assessment.
    scan_id2, _ = isolated_store.enqueue_scan(
        uuid.uuid4().hex[:12], "workspace", OWNER, "workspace_scan_file", {},
        content_workspace_version_id=version_id)
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur, "UPDATE scan_runs SET started_at=%s WHERE id=%s",
                                   ("2099-01-01T00:00:00+00:00", scan_id2))

    scan = isolated_store.get_content_workspace_version_scan(version_id)
    assert scan["id"] == scan_id2


def test_admin_reset_wipes_documents_and_versions(isolated_store, ws):
    doc_id = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(doc_id, workspace_id=ws, owner_email=OWNER)
    isolated_store.create_content_workspace_document_version(
        uuid.uuid4().hex[:12], document_id=doc_id, version_seq=1, content_hash="h1")

    isolated_store.reset_analytics()
    assert isolated_store.list_content_workspace_documents(ws, owner_email=OWNER) == []
    assert isolated_store.list_content_workspace_document_versions(doc_id) == []


def test_per_user_reset_wipes_only_that_users_documents_and_versions(isolated_store, ws):
    other_ws = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace(other_ws, owner_email=OTHER, name="Bob's workspace")

    alice_doc = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(alice_doc, workspace_id=ws, owner_email=OWNER)
    isolated_store.create_content_workspace_document_version(
        uuid.uuid4().hex[:12], document_id=alice_doc, version_seq=1, content_hash="h1")

    bob_doc = uuid.uuid4().hex[:12]
    isolated_store.create_content_workspace_document(bob_doc, workspace_id=other_ws, owner_email=OTHER)
    isolated_store.create_content_workspace_document_version(
        uuid.uuid4().hex[:12], document_id=bob_doc, version_seq=1, content_hash="h2")

    isolated_store.reset_user_data(OWNER)

    assert isolated_store.list_content_workspace_documents(ws, owner_email=OWNER) == []
    assert isolated_store.list_content_workspace_document_versions(alice_doc) == []
    assert [d["id"] for d in isolated_store.list_content_workspace_documents(other_ws, owner_email=OTHER)] == [bob_doc]
    assert len(isolated_store.list_content_workspace_document_versions(bob_doc)) == 1
