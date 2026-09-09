"""Release destination preview is owner-scoped, read-only, and collision-aware."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from routes import scans


class _Store:
    def __init__(self, status=None):
        self.status = status

    def get_scan(self, sid, owner=None):
        if sid != "scan-1" or owner != "owner@example.com":
            return None
        return {"run": {"source": "sharepoint"}, "files": [
            {"file": "Report.pdf", "compliant": 1, "remediated_at": "now",
             "corrected_sha256": "a" * 64, "source_relative_path": "/drives/lib/root:/Clinical", "drive_id": "lib"},
            {"file": "report.pdf", "compliant": 1, "remediated_at": "now",
             "corrected_sha256": "a" * 64, "source_relative_path": "/drives/lib/root:/Clinical", "drive_id": "lib"},
        ]}

    def release_for_scan(self, sid, owner):
        return self.status


def _request(owner="owner@example.com", headers=None):
    return SimpleNamespace(state=SimpleNamespace(user_email=owner), headers=headers or {})


def test_preview_resolves_exact_path_without_writing(monkeypatch):
    store = _Store()
    monkeypatch.setattr(scans.core, "store", store)
    result = scans.preview_release_destination(
        "scan-1", _request(),
        scans.ReleasePreviewRequest(files=["Report.pdf"],
                                    release_folder_name="Q3 Accessibility"))
    assert result["folder_name"].endswith(" - owner@example.com - Q3 Accessibility")
    assert result["folder_state"] == "proposed"
    assert result["documents"] == [{
        "file": "Report.pdf", "provider_location": "graph:lib",
        "destination_path": f"Remediated/{result['folder_name']}/Clinical/Report.pdf",
        "action": "create",
    }]
    assert result["can_release"] is True
    assert result["original_files_unchanged"] is True
    assert "not overwritten" in result["collision_policy"]


def test_preview_reuses_persisted_folder_and_published_copy(monkeypatch):
    store = _Store({"folder_name": "Existing Release", "documents": [
        {"file": "Report.pdf", "status": "published", "artifact_digest": "sha256:" + "a" * 64}]})
    monkeypatch.setattr(scans.core, "store", store)
    result = scans.preview_release_destination(
        "scan-1", _request(), scans.ReleasePreviewRequest(
            files=["Report.pdf"], release_folder_name="Ignored new name"))
    assert result["folder_name"] == "Existing Release"
    assert result["folder_state"] == "existing"
    assert result["documents"][0]["action"] == "reuse"


def test_preview_blocks_case_insensitive_destination_collision(monkeypatch):
    monkeypatch.setattr(scans.core, "store", _Store())
    result = scans.preview_release_destination(
        "scan-1", _request(),
        scans.ReleasePreviewRequest(files=["Report.pdf", "report.pdf"],
                                    release_folder_name="Release"))
    assert result["can_release"] is False
    assert result["blockers"][0]["file"] == "report.pdf"


def test_preview_can_flatten_the_source_hierarchy(monkeypatch):
    monkeypatch.setattr(scans.core, "store", _Store())
    result = scans.preview_release_destination(
        "scan-1", _request(), scans.ReleasePreviewRequest(
            files=["Report.pdf"], release_folder_name="Release",
            preserve_hierarchy=False))
    assert result["documents"][0]["destination_path"] == f"Remediated/{result['folder_name']}/Report.pdf"
    assert result["preserve_hierarchy"] is False


def test_preview_is_owner_scoped(monkeypatch):
    monkeypatch.setattr(scans.core, "store", _Store())
    with pytest.raises(HTTPException) as exc:
        scans.preview_release_destination(
            "scan-1", _request("other@example.com"),
            scans.ReleasePreviewRequest(files=["Report.pdf"]))
    assert exc.value.status_code == 404


def test_preview_uses_selected_sharepoint_parent_and_requires_preflight(monkeypatch):
    monkeypatch.setattr(scans.core, "store", _Store())
    monkeypatch.setattr(scans, "_preflight_release_destination", lambda request, destination: {
        "ready": True, "folder_reachable": True, "write_permission": True})
    result = scans.preview_release_destination(
        "scan-1", _request(), scans.ReleasePreviewRequest(
            files=["Report.pdf"], release_folder_name="Release",
            destination={"provider": "sharepoint", "folder_id": "target-drive/target-folder",
                         "folder_name": "Board packets"}))
    assert result["destination"]["folder_id"] == "target-drive/target-folder"
    assert result["documents"][0]["provider_location"] == "graph:target-drive"
    assert result["documents"][0]["destination_path"] == (
        f"Board packets/Remediated/{result['folder_name']}/Clinical/Report.pdf")
    assert result["can_release"] is True


def test_preview_blocks_an_unready_selected_destination(monkeypatch):
    monkeypatch.setattr(scans.core, "store", _Store())
    monkeypatch.setattr(scans, "_preflight_release_destination", lambda request, destination: {
        "ready": False, "folder_reachable": True, "write_permission": False,
        "message": "Write access is required."})
    result = scans.preview_release_destination(
        "scan-1", _request(), scans.ReleasePreviewRequest(
            files=["Report.pdf"], destination={
                "provider": "sharepoint", "folder_id": "target-drive/target-folder",
                "folder_name": "Board packets"}))
    assert result["can_release"] is False
    assert result["preflight"]["message"] == "Write access is required."


def test_drive_preflight_uses_provider_can_add_children_capability(monkeypatch):
    class Files:
        def get(self, **kwargs):
            assert kwargs["fileId"] == "finance"
            return self
        def execute(self):
            return {"id": "finance", "name": "Finance", "trashed": False,
                    "capabilities": {"canAddChildren": False}}
    monkeypatch.setattr(scans.core, "drive_service",
                        lambda request: SimpleNamespace(files=lambda: Files()))
    result = scans._preflight_release_destination(_request(), {
        "provider": "drive", "folder_id": "finance", "folder_name": "Finance"})
    assert result["folder_reachable"] is True
    assert result["write_permission"] is False
    assert result["ready"] is False


def test_partial_preview_requires_opt_in_and_exact_corrected_artifact(monkeypatch):
    store = _Store()
    scan = store.get_scan("scan-1", "owner@example.com")
    scan["files"][0].update(compliant=0, issues=[{"wcag": "SC_1_1_1"}])
    monkeypatch.setattr(store, "get_scan", lambda *a, **kw: scan)
    monkeypatch.setattr(scans.core, "store", store)
    def preview(**kw):
        return scans.preview_release_destination("scan-1", _request(), scans.ReleasePreviewRequest(files=["Report.pdf"], **kw))
    assert not preview()["can_release"]
    assert not preview(allow_remaining_issues=True)["can_release"]
    result = preview(allow_remaining_issues=True, expected_artifacts={"Report.pdf": "a" * 64})
    assert result["can_release"]
    assert result["documents"][0]["release_review"]["remaining_issue_count"] == 1
    scan["files"][0]["corrected_sha256"] = None
    assert not preview(allow_remaining_issues=True)["can_release"]
