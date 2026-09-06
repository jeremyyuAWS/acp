"""The downloadable Release manifest is server-authored, owner-scoped and reproducible."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from routes import scans


STATUS = {
    "id": "release-1", "scan_id": "scan-1", "owner_email": "owner@example.com",
    "source": "sharepoint", "folder_name": "2026-09-06 01-00 UTC",
    "documents_total": 1, "status": "completed",
    "created_at": "2026-09-06T01:00:00+00:00", "updated_at": "2026-09-06T01:01:00+00:00",
    "acp_version": "2026.9.6.1",
    "published": 1, "failed": 0, "remaining": 0,
    "roots": [{"provider": "sharepoint", "provider_location": "graph:drive-1",
               "folder_id": "folder-1", "folder_name": "2026-09-06 01-00 UTC",
               "folder_url": "https://sharepoint.example/folder",
               "created_at": "2026-09-06T01:00:00+00:00"}],
    "documents": [{"file": "report.pdf", "source_document_id": "source-1",
                   "source_relative_path": "Clinical/report.pdf",
                   "destination_relative_path": "Remediated/2026/report.pdf",
                   "released_document_id": "released-1",
                   "released_document_url": "https://sharepoint.example/report",
                   "corrected_checksum": "a" * 64, "verification": "sha256",
                   "status": "published", "failure_category": None, "explanation": None,
                   "created_result": 1, "published_at": "2026-09-06T01:01:00+00:00"}],
}


class _Store:
    def get_scan(self, sid, owner=None):
        return {"run": {"id": sid}} if owner == "owner@example.com" else None

    def release_for_scan(self, sid, owner):
        return STATUS if sid == "scan-1" and owner == "owner@example.com" else None

    def stage_snapshot_id(self, sid):
        return "snapshot-1"


def _request(owner="owner@example.com"):
    return SimpleNamespace(state=SimpleNamespace(user_email=owner))


def test_release_manifest_comes_from_persisted_server_evidence(monkeypatch):
    monkeypatch.setattr(scans.core, "store", _Store())
    first = scans.get_release_manifest("scan-1", _request())
    second = scans.get_release_manifest("scan-1", _request())

    assert first == second
    manifest = first["manifest"]
    assert manifest["actor"] == "owner@example.com"
    assert manifest["snapshot_id"] == "snapshot-1"
    assert manifest["original_files_unchanged"] is True
    assert manifest["documents"][0]["corrected_sha256"] == "a" * 64
    assert manifest["documents"][0]["created"] is True
    assert manifest["manifest_generated_by"]["release_version"] == "2026.9.6.1"
    assert len(first["content_digest"]["value"]) == 64
    assert "not a digital signature" in first["digest_note"]


def test_release_manifest_is_owner_scoped(monkeypatch):
    monkeypatch.setattr(scans.core, "store", _Store())
    with pytest.raises(HTTPException) as exc:
        scans.get_release_manifest("scan-1", _request("someone@example.com"))
    assert exc.value.status_code == 404
