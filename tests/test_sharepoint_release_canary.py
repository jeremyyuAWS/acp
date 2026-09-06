import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from verify_sharepoint_release_canary import verify  # noqa: E402


def _write(path, value):
    if isinstance(value, bytes):
        path.write_bytes(value)
    else:
        path.write_text(json.dumps(value), encoding="utf-8")


def _bundle(tmp_path):
    original = b"original bytes"
    corrected = b"corrected bytes"
    permissions = [{"roles": ["read"], "grantedTo": "canary-group"}]
    source_item = {"id": "source-1", "name": "report.docx",
                   "parentReference": {"path": "/drives/drive-1/root:/Policies"}}
    destination_item = {"id": "copy-1", "name": "report.docx",
                        "webUrl": "https://tenant.sharepoint.example/copy-1",
                        "parentReference": {"path":
                            "/drives/drive-1/root:/Remediated/2026-09-06 01-00 UTC/Policies"}}
    for name, value in {
        "original-before.docx": original, "original-after.docx": original,
        "corrected.docx": corrected, "source-before.json": permissions,
        "source-after.json": permissions, "destination.json": permissions,
        "expected-destination.json": permissions,
        "source-item-before.json": source_item, "source-item-after.json": source_item,
        "destination-item.json": destination_item,
    }.items():
        _write(tmp_path / name, value)
    manifest = {
        "schema_version": 1, "release_id": "release-1", "scan_id": "scan-1",
        "snapshot_id": "snapshot-1", "actor": "operator@example.com",
        "source": "sharepoint", "original_files_unchanged": True,
        "status": "completed", "created_at": "2026-09-06T01:00:00+00:00",
        "updated_at": "2026-09-06T01:01:00+00:00",
        "manifest_generated_by": {"service": "acp", "release_version": "2026.9.6.1"},
        "release_folder": "2026-09-06 01-00 UTC",
        "roots": [{"provider": "sharepoint", "folder_id": "folder-1",
                   "folder_name": "2026-09-06 01-00 UTC",
                   "created_at": "2026-09-06T01:00:00+00:00",
                   "folder_url": "https://tenant.sharepoint.example/folder-1"}],
        "counts": {"total": 1, "published": 1, "failed": 0, "remaining": 0},
        "documents": [{
            "status": "published", "verification": "content verified",
            "source_document_id": "source-1", "released_document_id": "copy-1",
            "released_document_url": "https://tenant.sharepoint.example/copy-1",
            "source_relative_path": "Policies/report.docx",
            "destination_relative_path": "Policies/report.docx",
            "corrected_sha256": hashlib.sha256(corrected).hexdigest(),
        }],
    }
    digest = hashlib.sha256(json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    return {
        "manifest_response": {"manifest": manifest,
                              "content_digest": {"algorithm": "SHA-256", "value": digest}},
        "expected": {"source_relative_path": "Policies/report.docx",
                     "destination_relative_path": "Policies/report.docx",
                     "provider_destination_path":
                         "Remediated/2026-09-06 01-00 UTC/Policies/report.docx"},
        "artifacts": {"original_before": "original-before.docx",
                      "original_after": "original-after.docx", "corrected": "corrected.docx"},
        "permissions": {"source_before": "source-before.json", "source_after": "source-after.json",
                        "destination": "destination.json",
                        "expected_destination": "expected-destination.json"},
        "provider_observations": {"source_before": "source-item-before.json",
                                  "source_after": "source-item-after.json",
                                  "destination": "destination-item.json"},
    }


def test_complete_canary_evidence_passes(tmp_path):
    result = verify(_bundle(tmp_path), base=tmp_path)
    assert result["passed"] is True
    assert result["failed_checks"] == 0


def test_changed_original_fails_closed(tmp_path):
    bundle = _bundle(tmp_path)
    (tmp_path / "original-after.docx").write_bytes(b"changed")
    result = verify(bundle, base=tmp_path)
    assert result["passed"] is False
    assert next(c for c in result["checks"] if c["check"] == "original unchanged")["passed"] is False


def test_tampered_manifest_and_wrong_corrected_copy_are_both_reported(tmp_path):
    bundle = _bundle(tmp_path)
    bundle["manifest_response"]["manifest"]["actor"] = "changed@example.com"
    (tmp_path / "corrected.docx").write_bytes(b"wrong")
    result = verify(bundle, base=tmp_path)
    failed = {c["check"] for c in result["checks"] if not c["passed"]}
    assert {"manifest digest", "corrected checksum"} <= failed


def test_permission_drift_fails_closed(tmp_path):
    bundle = _bundle(tmp_path)
    _write(tmp_path / "source-after.json", [{"roles": ["write"]}])
    _write(tmp_path / "destination.json", [{"roles": ["owner"]}])
    result = verify(bundle, base=tmp_path)
    failed = {c["check"] for c in result["checks"] if not c["passed"]}
    assert {"source permissions unchanged", "destination permissions"} <= failed


def test_incomplete_audit_provenance_fails_closed(tmp_path):
    bundle = _bundle(tmp_path)
    bundle["manifest_response"]["manifest"]["manifest_generated_by"]["release_version"] = "not recorded"
    bundle["manifest_response"]["manifest"]["snapshot_id"] = None
    result = verify(bundle, base=tmp_path)
    failed = {c["check"] for c in result["checks"] if not c["passed"]}
    assert {"manifest digest", "recorded ACP version", "release provenance identities"} <= failed


def test_provider_observation_must_prove_destination_placement(tmp_path):
    bundle = _bundle(tmp_path)
    item = json.loads((tmp_path / "destination-item.json").read_text())
    item["parentReference"]["path"] = "/drives/drive-1/root:/Wrong"
    _write(tmp_path / "destination-item.json", item)
    result = verify(bundle, base=tmp_path)
    assert next(c for c in result["checks"]
                if c["check"] == "provider destination identity and placement")["passed"] is False
