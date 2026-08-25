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
import logging
import os

_ACCOUNT = os.environ.get("ACP_BLOB_ACCOUNT", "")
_CONTAINER = os.environ.get("ACP_BLOB_CONTAINER", "remediated")
# Rendered page-1 thumbnails (ADR 0015) live in their own container, keyed the same
# {owner}/{scan_id}/{filename} way — kept out of 'remediated' so a preview is never
# mistaken for a remediated artifact.
_RENDER_CONTAINER = os.environ.get("ACP_BLOB_RENDER_CONTAINER", "thumbnails")
_ENABLED = bool(_ACCOUNT)
_LOG = logging.getLogger(__name__)

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
    settings = ContentSettings(content_type=content_type)
    try:
        blob.upload_blob(data, overwrite=False, content_settings=settings)
    except Exception as exc:
        if getattr(exc, "status_code", None) == 409 or getattr(exc, "error_code", "") == "BlobAlreadyExists":
            _LOG.warning("upload_remediated: overwriting existing blob scan=%s file=%s", scan_id, filename)
            blob.upload_blob(data, overwrite=True, content_settings=settings)
        else:
            raise
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


# --- ADR 0020 stage 1: source-bytes cache -------------------------------------
# Discover downloads each file once; a later Assess phase (ADR 0020 stage 3) reads the
# SAME bytes back from this cache instead of paying a second Drive/SharePoint download —
# the 'open each file once' property, kept across the phase boundary. A distinct
# container so a source original can never be mistaken for a remediated artifact or a
# thumbnail. Same discipline as the render cache: lazy container creation, best-effort,
# a no-op returning None when blob storage isn't configured (local dev re-reads the
# source instead — the ADR's stated degradation, not an error).
_SOURCES_CONTAINER = os.environ.get("ACP_BLOB_SOURCES_CONTAINER", "sources")


def upload_source(owner: str | None, scan_id: str, filename: str, data: bytes) -> str | None:
    """Cache a discovered file's original bytes. Returns the blob URL, or None when blob
    storage isn't configured or the write fails — caching is best-effort and must NEVER
    raise into the scan path. Self-heals a missing container on first use."""
    svc = _service_client()
    if svc is None:
        return None
    from azure.storage.blob import ContentSettings
    blob = svc.get_blob_client(container=_SOURCES_CONTAINER, blob=_blob_path(owner, scan_id, filename))
    settings = ContentSettings(content_type="application/octet-stream")
    try:
        blob.upload_blob(data, overwrite=True, content_settings=settings)
        return blob.url
    except Exception:
        try:
            svc.create_container(_SOURCES_CONTAINER)
        except Exception:
            pass  # already exists (race) or can't create — fall through to the retry
        try:
            blob.upload_blob(data, overwrite=True, content_settings=settings)
            return blob.url
        except Exception:
            return None


def download_source(owner: str | None, scan_id: str, filename: str) -> bytes | None:
    """Read a discovered file's cached original bytes back out. None if not configured or
    not cached (the caller falls back to a fresh source download — today's behavior)."""
    svc = _service_client()
    if svc is None:
        return None
    blob = svc.get_blob_client(container=_SOURCES_CONTAINER, blob=_blob_path(owner, scan_id, filename))
    try:
        return blob.download_blob().readall()
    except Exception:
        return None


# Every container this module writes scan-derived artifacts into. All three are DATA
# (remediated copies, cached originals, rendered previews) that a scan re-populates —
# none holds configuration — so a demo reset should wipe them alongside the DB analytics
# tables. Kept as a list so purge_all() and any future infra tooling share one source of
# truth for "what does acp store in blob".
_DATA_CONTAINERS = (_CONTAINER, _SOURCES_CONTAINER, _RENDER_CONTAINER)


def purge_all(owner: str | None = None) -> dict:
    """Delete every scan-derived blob so a demo reset is a TRUE clean slate — the DB reset
    (store.reset_analytics) drops the remediation_state / applied_fixes / … rows but leaves
    the fixed-file bytes, cached originals and previews sitting in blob storage.

    Deletes the blobs, NOT the containers: `remediated` is provisioned once by deploy infra
    and upload_remediated does not self-heal a missing container, so dropping it would break
    the next remediation. owner=None purges the whole account (matching reset_analytics, which
    is global); pass an owner to scope to one tenant's `{owner}/` prefix. Best-effort and never
    raises: returns {container: deleted_count}, with -1 for a container that errored. No-op
    ({} ) when blob storage isn't configured (local dev)."""
    svc = _service_client()
    if svc is None:
        return {}
    prefix = f"{owner}/" if owner else None
    out: dict = {}
    for cname in _DATA_CONTAINERS:
        try:
            cc = svc.get_container_client(cname)
            n = 0
            for b in cc.list_blobs(name_starts_with=prefix):
                try:
                    cc.delete_blob(b.name)
                    n += 1
                except Exception:
                    pass  # blob vanished mid-iteration or a lease — skip, keep going
            out[cname] = n
        except Exception:
            out[cname] = -1  # container missing / listing failed — surface, don't abort the rest
    return out


def purge_scan(owner: str, scan_id: str) -> dict:
    """Delete every blob that belongs to ONE scan (BAA/HIPAA right-to-erasure path).

    Blob paths follow the `{owner}/{scan_id}/{filename}` convention defined in _blob_path,
    so listing with the prefix `{owner}/{scan_id}/` finds exactly this scan's bytes across
    all three data containers. Best-effort and never raises; returns {container: deleted_count}
    with -1 for a container that errored. No-op ({}) when blob storage isn't configured.
    """
    svc = _service_client()
    if svc is None:
        return {}
    prefix = f"{owner}/{scan_id}/"
    out: dict = {}
    for cname in _DATA_CONTAINERS:
        try:
            cc = svc.get_container_client(cname)
            n = 0
            for b in cc.list_blobs(name_starts_with=prefix):
                try:
                    cc.delete_blob(b.name)
                    n += 1
                except Exception:
                    pass
            out[cname] = n
        except Exception:
            out[cname] = -1
    return out
