"""Exact corrected-artifact identity at the Release write boundary.

Provider checksums remain provider-specific (Drive MD5, SharePoint SHA-256).
Release identity is separately tagged SHA-256, never inferred from a filename.
"""
from __future__ import annotations


class ReleaseArtifactError(ValueError):
    def __init__(self, message, *, category="release_evidence_changed"):
        super().__init__(message)
        self.category = category


def artifact_tag(digest: str) -> str:
    return f"sha256:{digest}"


def reuse_state(saved: dict | None, digest: str) -> str:
    if not saved:
        return "new"
    previous = saved.get("artifact_digest")
    if not previous and (saved.get("status") == "published" or saved.get("published_at")
                         or saved.get("released_document_id")
                         or saved.get("failure_category") == "delivery_version_unresolved"):
        return "unresolved"
    if saved.get("status") == "published" and previous == artifact_tag(digest):
        return "reuse"
    return "new"


def require_current_record(store, scan_id: str, filename: str, digest: str,
                           remediated_at: str | None, *, owner: str) -> dict:
    from assessment_policy import selected_documents
    selected = selected_documents(store.get_decisions(scan_id, owner=owner))
    if selected is not None and filename not in selected:
        raise ReleaseArtifactError("Document is no longer in the Remediate selection.")
    record = store.get_file_record(scan_id, filename)
    if not record or not record.get("compliant") or not record.get("remediated_at"):
        raise ReleaseArtifactError("Approval or corrected-copy readiness changed. Review and verify again.")
    if record.get("remediated_at") != remediated_at:
        raise ReleaseArtifactError("The corrected copy changed while preparing Release. Review the new copy.")
    if record.get("corrected_sha256") and record["corrected_sha256"] != digest:
        raise ReleaseArtifactError("Corrected bytes do not match the verified artifact. Verify this copy again.")
    return record


def require_current_source(source: str, record: dict, *, drive_service=None, sp_token=None):
    """Recheck tracked source metadata; absence of a baseline remains untracked, not unchanged."""
    baseline, item_id = record.get("source_modified"), record.get("drive_file_id")
    if not baseline or not item_id or source not in {"drive", "sharepoint"}:
        return
    from source_staleness import compare_state
    if source == "drive":
        if drive_service is None:
            raise ReleaseArtifactError("Source freshness could not be verified. Reconnect Google Drive.")
        current = drive_service.files().get(fileId=item_id, fields="modifiedTime",
                                            supportsAllDrives=True).execute().get("modifiedTime")
    else:
        import httpx
        import scanner
        response = httpx.get(f"{scanner._sp_base(record.get('drive_id'))}/items/{item_id}",
                             headers={"Authorization": f"Bearer {sp_token}"},
                             params={"$select": "lastModifiedDateTime"}, timeout=30)
        response.raise_for_status()
        current = response.json().get("lastModifiedDateTime")
    state = compare_state(baseline, current)
    if state != "unchanged":
        raise ReleaseArtifactError("Source changed. Rescan and verify before Release." if state == "stale"
                                   else "Source freshness could not be verified. Check access and retry.")
