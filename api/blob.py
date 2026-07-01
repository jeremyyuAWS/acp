"""Azure Blob remediated-output store (ADR 0010).

The PRIMARY store for a remediated file's fixed copy — Drive write-back
(api/handlers.py's _remediate_file) is now a best-effort mirror, not the
source of truth. Managed-identity auth via DefaultAzureCredential: no storage
key to provision, rotate, or leak. A no-op (returns None everywhere) when
ACP_BLOB_ACCOUNT isn't set — e.g. local dev without the Azure infra — so
importing this module is always safe.

Blob path: {owner_email}/{scan_id}/{filename} (ACP_BLOB_CONTAINER, default
'remediated'). Scoped to remediated-output artifacts only — not a general
file-storage abstraction (ADR 0010's own non-goals).
"""
from __future__ import annotations
import os

_ACCOUNT = os.environ.get("ACP_BLOB_ACCOUNT", "")
_CONTAINER = os.environ.get("ACP_BLOB_CONTAINER", "remediated")
_ENABLED = bool(_ACCOUNT)

_client = None


def enabled() -> bool:
    return _ENABLED


def _service_client():
    global _client
    if not _ENABLED:
        return None
    if _client is None:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient
        _client = BlobServiceClient(
            account_url=f"https://{_ACCOUNT}.blob.core.windows.net",
            credential=DefaultAzureCredential())
    return _client


def _blob_path(owner: str | None, scan_id: str, filename: str) -> str:
    return f"{owner or 'demo'}/{scan_id}/{filename}"


def upload_remediated(owner: str | None, scan_id: str, filename: str, data: bytes,
                      content_type: str) -> str | None:
    """Upload a remediated file's fixed bytes. Returns the blob's URL, or None when
    blob storage isn't configured (caller falls back to Drive-only, the pre-ADR-0010
    behavior) — never raises for that case, since local/dev environments legitimately
    don't have this infra."""
    svc = _service_client()
    if svc is None:
        return None
    from azure.storage.blob import ContentSettings
    blob = svc.get_blob_client(container=_CONTAINER, blob=_blob_path(owner, scan_id, filename))
    blob.upload_blob(data, overwrite=True, content_settings=ContentSettings(content_type=content_type))
    return blob.url


def download_remediated(owner: str | None, scan_id: str, filename: str) -> bytes | None:
    """Stream a remediated file's bytes back out. None if not configured, or not found
    (e.g. a pre-ADR-0010 remediation that only ever wrote to Drive)."""
    svc = _service_client()
    if svc is None:
        return None
    blob = svc.get_blob_client(container=_CONTAINER, blob=_blob_path(owner, scan_id, filename))
    try:
        return blob.download_blob().readall()
    except Exception:
        return None
