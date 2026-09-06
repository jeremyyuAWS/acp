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
             "source_relative_path": "/drives/lib/root:/Clinical", "drive_id": "lib"},
            {"file": "report.pdf", "compliant": 1, "remediated_at": "now",
             "source_relative_path": "/drives/lib/root:/Clinical", "drive_id": "lib"},
        ]}

    def release_for_scan(self, sid, owner):
        return self.status


def _request(owner="owner@example.com"):
    return SimpleNamespace(state=SimpleNamespace(user_email=owner))


def test_preview_resolves_exact_path_without_writing(monkeypatch):
    store = _Store()
    monkeypatch.setattr(scans.core, "store", store)
    result = scans.preview_release_destination(
        "scan-1", _request(),
        scans.ReleasePreviewRequest(files=["Report.pdf"],
                                    release_folder_name="Q3 Accessibility"))
    assert result["folder_name"] == "Q3 Accessibility"
    assert result["folder_state"] == "proposed"
    assert result["documents"] == [{
        "file": "Report.pdf", "provider_location": "graph:lib",
        "destination_path": "Remediated/Q3 Accessibility/Clinical/Report.pdf",
        "action": "create",
    }]
    assert result["can_release"] is True
    assert result["original_files_unchanged"] is True
    assert "not overwritten" in result["collision_policy"]


def test_preview_reuses_persisted_folder_and_published_copy(monkeypatch):
    store = _Store({"folder_name": "Existing Release", "documents": [
        {"file": "Report.pdf", "status": "published"}]})
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


def test_preview_is_owner_scoped(monkeypatch):
    monkeypatch.setattr(scans.core, "store", _Store())
    with pytest.raises(HTTPException) as exc:
        scans.preview_release_destination(
            "scan-1", _request("other@example.com"),
            scans.ReleasePreviewRequest(files=["Report.pdf"]))
    assert exc.value.status_code == 404

