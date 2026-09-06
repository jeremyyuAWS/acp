"""Selected corrected copies download as one owner-scoped, hierarchy-preserving ZIP."""
import hashlib
import io
import json
import zipfile
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from routes import scans


class _Store:
    def get_scan(self, sid, owner=None):
        if sid != "scan-1" or owner != "owner@example.com":
            return None
        return {
            "run": {"id": sid, "source": "sharepoint"},
            "files": [
                {"file": "report.pdf", "source_relative_path": "/drive/root:/Clinical/2026"},
                {"file": "form.docx", "source_relative_path": "/drive/root:/Intake"},
            ],
        }

    def release_for_scan(self, sid, owner):
        return None

    def stage_snapshot_id(self, sid):
        return "snapshot-1"


def _request(owner="owner@example.com"):
    return SimpleNamespace(state=SimpleNamespace(user_email=owner))


async def _response_body(response):
    return b"".join([chunk async for chunk in response.body_iterator])


def test_package_preserves_folders_and_includes_hash_manifest(monkeypatch):
    monkeypatch.setattr(scans.core, "store", _Store())
    payloads = {"report.pdf": b"corrected-pdf", "form.docx": b"corrected-docx"}
    monkeypatch.setattr(scans, "_remediated_bytes", lambda owner, sid, name: payloads[name])

    response = scans.download_release_package(
        "scan-1", _request(), scans.ReleasePackageRequest(files=["report.pdf", "form.docx"]))

    assert response.media_type == "application/zip"
    assert response.headers["content-disposition"] == 'attachment; filename="acp-release-scan-1.zip"'
    assert response.headers["cache-control"] == "private, no-store"
    with zipfile.ZipFile(io.BytesIO(asyncio.run(_response_body(response)))) as archive:
        assert set(archive.namelist()) == {
            "release-manifest.json",
            "Remediated/Clinical/2026/report.pdf",
            "Remediated/Intake/form.docx",
        }
        assert archive.read("Remediated/Clinical/2026/report.pdf") == b"corrected-pdf"
        manifest = json.loads(archive.read("release-manifest.json"))
    assert manifest["actor"] == "owner@example.com"
    assert manifest["snapshot_id"] == "snapshot-1"
    assert manifest["original_files_unchanged"] is True
    assert manifest["documents"][0]["corrected_sha256"] == hashlib.sha256(b"corrected-pdf").hexdigest()


def test_package_is_owner_scoped(monkeypatch):
    monkeypatch.setattr(scans.core, "store", _Store())
    with pytest.raises(HTTPException) as exc:
        scans.download_release_package(
            "scan-1", _request("other@example.com"),
            scans.ReleasePackageRequest(files=["report.pdf"]))
    assert exc.value.status_code == 404


def test_package_fails_whole_request_when_a_copy_is_unavailable(monkeypatch):
    monkeypatch.setattr(scans.core, "store", _Store())
    monkeypatch.setattr(
        scans, "_remediated_bytes",
        lambda owner, sid, name: b"corrected" if name == "report.pdf" else None)
    with pytest.raises(HTTPException) as exc:
        scans.download_release_package(
            "scan-1", _request(),
            scans.ReleasePackageRequest(files=["report.pdf", "form.docx"]))
    assert exc.value.status_code == 409
    assert "form.docx" in exc.value.detail


def test_package_uses_a_valid_custom_name_in_header_and_manifest(monkeypatch):
    monkeypatch.setattr(scans.core, "store", _Store())
    monkeypatch.setattr(scans, "_remediated_bytes", lambda owner, sid, name: b"corrected")
    response = scans.download_release_package(
        "scan-1", _request(),
        scans.ReleasePackageRequest(files=["report.pdf"], package_name="Q3 Accessible Files.zip"))
    assert 'filename="Q3 Accessible Files.zip"' in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(asyncio.run(_response_body(response)))) as archive:
        manifest = json.loads(archive.read("release-manifest.json"))
    assert manifest["package_name"] == "Q3 Accessible Files"


def test_package_rejects_an_unsafe_custom_name(monkeypatch):
    monkeypatch.setattr(scans.core, "store", _Store())
    with pytest.raises(HTTPException) as exc:
        scans.download_release_package(
            "scan-1", _request(),
            scans.ReleasePackageRequest(files=["report.pdf"], package_name="Q3/exports"))
    assert exc.value.status_code == 422
    assert "ZIP filename" in exc.value.detail
