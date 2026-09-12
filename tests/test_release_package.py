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
    queued = None
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

    def canonical_stage_lineage(self, sid, owner=None):
        return {"schema_version": 1, "workflow_id": "workflow-1", "workflow_revision": 3,
                "scan_id": sid, "generated_at": "volatile", "available": True,
                "stages": [], "integrity": {"ok": True, "broken_manifest_links": [],
                                              "inconsistent_stages": []}}

    def enqueue_job(self, job_type, payload, **kwargs):
        self.queued = {"type": job_type, "payload": payload, **kwargs}
        return "package-job-1"

    def get_job(self, job_id):
        if job_id != "package-job-1" or not self.queued:
            return None
        return {"id": job_id, "type": self.queued["type"], "scan_id": "scan-1",
                "status": "done", "payload": self.queued["payload"]}


def _request(owner="owner@example.com"):
    return SimpleNamespace(state=SimpleNamespace(user_email=owner))


@pytest.fixture(autouse=True)
def _legacy_finding_snapshot(monkeypatch):
    monkeypatch.setattr(scans, "_remediation_snapshot", lambda sid: {
        "run_id": None, "batch_id": None, "revision": 0,
        "finding_reconciliation": None,
    })


async def _response_body(response):
    return b"".join([chunk async for chunk in response.body_iterator])


def test_package_preserves_folders_and_includes_hash_manifest(monkeypatch):
    monkeypatch.setattr(scans.core, "store", _Store())
    monkeypatch.setattr(scans, "_remediation_snapshot", lambda sid: {
        "run_id": "run-1", "batch_id": "batch-1", "revision": 23,
        "finding_reconciliation": {
            "assessed": 3, "resolved_verified": 1, "awaiting_review": 1,
            "approved_pending_verification": 0, "unchanged_no_fix": 1, "failed": 0,
            "excluded": 0, "superseded": 0, "accounted": 3, "unaccounted": 0,
            "exact": True, "violations": [],
        }})
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
    finding = manifest["finding_reconciliation"]
    assert finding["status"] == "reconciled"
    assert finding["revision"] == 23
    assert finding["identifiers"]["workflow_id"] == "workflow-1"
    assert finding["residual_outcomes"] == {
        "awaiting_review": 1, "approved_pending_verification": 0,
        "unchanged_no_fix": 1, "failed": 0, "excluded": 0, "superseded": 0,
        "unaccounted": 0,
    }


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


def test_package_can_flatten_folders_and_omit_manifest(monkeypatch):
    monkeypatch.setattr(scans.core, "store", _Store())
    monkeypatch.setattr(scans, "_remediated_bytes", lambda owner, sid, name: b"corrected")
    response = scans.download_release_package(
        "scan-1", _request(), scans.ReleasePackageRequest(
            files=["report.pdf", "form.docx"], preserve_hierarchy=False,
            include_manifest=False))

    with zipfile.ZipFile(io.BytesIO(asyncio.run(_response_body(response)))) as archive:
        assert set(archive.namelist()) == {"report.pdf", "form.docx"}


def test_direct_download_returns_the_single_corrected_file(monkeypatch):
    monkeypatch.setattr(scans.core, "store", _Store())
    monkeypatch.setattr(scans, "_remediated_bytes", lambda owner, sid, name: b"corrected-pdf")
    response = scans.download_release_package(
        "scan-1", _request(), scans.ReleasePackageRequest(
            files=["report.pdf"], download_format="original"))

    assert response.body == b"corrected-pdf"
    assert response.media_type == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="report.pdf"'


def test_direct_download_requires_exactly_one_file(monkeypatch):
    monkeypatch.setattr(scans.core, "store", _Store())
    with pytest.raises(HTTPException) as exc:
        scans.download_release_package(
            "scan-1", _request(), scans.ReleasePackageRequest(
                files=["report.pdf", "form.docx"], download_format="original"))
    assert exc.value.status_code == 422
    assert "exactly one" in exc.value.detail


def test_package_preview_reports_paths_size_coverage_and_recommendation(monkeypatch):
    store = _Store()
    original = store.get_scan

    def scan_with_sizes(sid, owner=None):
        result = original(sid, owner)
        if result:
            result["files"][0]["size"] = 120
            result["files"][1]["size"] = 80
        return result

    store.get_scan = scan_with_sizes
    monkeypatch.setattr(scans.core, "store", store)
    preview = scans.preview_release_package(
        "scan-1", _request(), scans.ReleasePackagePreviewRequest(
            files=["report.pdf"], preserve_hierarchy=False, include_manifest=False))

    assert preview["paths"] == ["report.pdf"]
    assert preview["estimated_bytes"] == 120
    assert preview["estimate_complete"] is True
    assert preview["recommended_format"] == "original"
    assert preview["include_manifest"] is False
    assert preview["can_download"] is True


def test_large_package_can_be_queued_and_downloaded_after_navigation(monkeypatch):
    import blob
    store = _Store()
    monkeypatch.setattr(scans.core, "store", store)
    monkeypatch.setattr(blob, "enabled", lambda: True)
    queued = scans.prepare_release_package(
        "scan-1", _request(), scans.ReleasePackageRequest(
            files=["report.pdf", "form.docx"], package_name="Board files"))
    assert queued == {"job_id": "package-job-1", "scan_id": "scan-1", "status": "queued", "files": 2}
    assert store.queued["type"] == "prepare_release_package"
    assert store.queued["payload"]["owner"] == "owner@example.com"

    class _Download:
        def chunks(self):
            yield b"prepared-"
            yield b"zip"
    monkeypatch.setattr(blob, "open_release_package", lambda owner, sid, job_id: _Download())
    response = scans.download_prepared_release_package(
        "scan-1", "package-job-1", _request())
    assert asyncio.run(_response_body(response)) == b"prepared-zip"
    assert response.headers["content-disposition"] == 'attachment; filename="Board files.zip"'


def test_prepared_package_download_is_owner_scoped(monkeypatch):
    store = _Store()
    store.queued = {"type": "prepare_release_package", "payload": {
        "owner": "owner@example.com", "package_name": "Board files"}}
    monkeypatch.setattr(scans.core, "store", store)
    with pytest.raises(HTTPException) as exc:
        scans.download_prepared_release_package(
            "scan-1", "package-job-1", _request("other@example.com"))
    assert exc.value.status_code == 404


def test_automatic_package_contains_exact_corrected_bytes_and_follow_up_reports(monkeypatch):
    import release_artifacts
    store = _Store()
    scan = store.get_scan('scan-1', owner='owner@example.com')
    rows = {r['file']:r for r in scan['files']}
    data = b'current-corrected-copy'
    digest = hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(scans.core, 'store', store)
    monkeypatch.setattr(scans, '_remediated_bytes', lambda *a:data)
    checked = []
    monkeypatch.setattr(release_artifacts, 'require_current_record', lambda *a,**kw:checked.append((a,kw)))
    output, size, filename = scans._build_release_zip('scan-1', 'owner@example.com', scan, ['report.pdf'], rows, package_name='', preserve_hierarchy=True, include_manifest=True, expected_artifacts={'report.pdf':digest}, report_assets=[{'name':'follow-up.html','content':'Remaining work','encoding':'utf-8'}])
    with output, zipfile.ZipFile(output) as archive:
        assert archive.read('Remediated/Clinical/2026/report.pdf') == data
        assert archive.read('Reports/follow-up.html') == b'Remaining work'
        assert 'release-manifest.json' in archive.namelist()
    assert checked[0][1]['allow_remaining_issues'] is True
    with pytest.raises(HTTPException, match='corrected copy changed'):
        scans._build_release_zip('scan-1', 'owner@example.com', scan, ['report.pdf'], rows, package_name='', preserve_hierarchy=True, include_manifest=True, expected_artifacts={'report.pdf':'f'*64})


@pytest.fixture(autouse=True)
def _candidate_assessment_for_delivery_fixture(monkeypatch):
    # These delivery fixtures use sentinel bytes, not Office/PDF documents. Real
    # saved-byte scanner gates are exercised in test_release_candidate_assessment.
    import release_candidate_assessment
    monkeypatch.setattr(release_candidate_assessment, 'assess_candidate',
                        lambda *args, **kwargs: {'fixture_assessment': True})
