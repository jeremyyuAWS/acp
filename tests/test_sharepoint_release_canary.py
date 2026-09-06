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
    for name, value in {
        "original-before.docx": original, "original-after.docx": original,
        "corrected.docx": corrected, "source-before.json": permissions,
        "source-after.json": permissions, "destination.json": permissions,
        "expected-destination.json": permissions,
    }.items():
        _write(tmp_path / name, value)
    manifest = {
        "source": "sharepoint", "original_files_unchanged": True,
        "release_folder": "2026-09-06 01-00 UTC",
        "roots": [{"folder_id": "folder-1", "folder_name": "2026-09-06 01-00 UTC",
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
