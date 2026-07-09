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
# Rendered page-1 thumbnails (ADR 0015) live in their own container, keyed the same
# {owner}/{scan_id}/{filename} way — kept out of 'remediated' so a preview is never
# mistaken for a remediated artifact.
_RENDER_CONTAINER = os.environ.get("ACP_BLOB_RENDER_CONTAINER", "thumbnails")
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


# --- ADR 0015 rendered-thumbnail cache ---------------------------------------
# Same seam as the remediated store (ADR 0010 non-goals bless the reuse), a distinct
# container. Blob key: {owner}/{scan_id}/{filename}.png. Like the rest of this module,
# a no-op returning None when blob storage isn't configured — the endpoint then just
# renders on demand every time instead of caching, which is correct for local dev.

def upload_render(owner: str | None, scan_id: str, filename: str, data: bytes) -> str | None:
    """Cache a rendered page-1 PNG. Returns the blob URL, or None when blob storage isn't
    configured or the cache write fails — render caching is best-effort and must NEVER raise
    into the request path. Self-heals a missing container on first use (unlike 'remediated',
    the thumbnails container is provisioned lazily here, not by one-time deploy infra)."""
    svc = _service_client()
    if svc is None:
        return None
    from azure.storage.blob import ContentSettings
    blob = svc.get_blob_client(container=_RENDER_CONTAINER, blob=_blob_path(owner, scan_id, filename) + ".png")
    settings = ContentSettings(content_type="image/png")
    try:
        blob.upload_blob(data, overwrite=True, content_settings=settings)
        return blob.url
    except Exception:
        # Most likely the container doesn't exist yet — create it and retry once. The app's
        # managed identity (Storage Blob Data Contributor) can create containers. Any other
        # failure (transient, perms) collapses to "not cached"; the endpoint still serves the
        # freshly rendered bytes, it just re-renders next time.
        try:
            svc.create_container(_RENDER_CONTAINER)
        except Exception:
            pass  # already exists (race) or can't create — fall through to the retry
        try:
            blob.upload_blob(data, overwrite=True, content_settings=settings)
            return blob.url
        except Exception:
            return None


def download_render(owner: str | None, scan_id: str, filename: str) -> bytes | None:
    """Read a cached page-1 PNG back out. None if not configured, or not yet rendered."""
    svc = _service_client()
    if svc is None:
        return None
    blob = svc.get_blob_client(container=_RENDER_CONTAINER, blob=_blob_path(owner, scan_id, filename) + ".png")
    try:
        return blob.download_blob().readall()
    except Exception:
        return None
