"""Azure Blob store for ACP Managed Content Workspace uploads (ADR 0044, PRD Phase 1).

Mirrors api/blob.py's pattern exactly — managed-identity auth via DefaultAzureCredential, a
no-op (returns None everywhere) when ACP_WORKSPACE_BLOB_ACCOUNT isn't set, so importing this
module is always safe — but is its own module with its own container, NOT an extension of
api/blob.py. That module is ADR 0010's remediated-output store and its own docstring scopes it
OUT of general use ("Scoped to remediated-output artifacts only — not a general file-storage
abstraction"); its container also holds an unrelated shape ({owner_email}/{scan_id}/{filename},
a scan's remediated output) from what this module needs ({owner_email}/{workspace_id}/
{document_id}/{kind}/{version_id}/..., a workspace's uploaded original — see ADR 0044's Blob
layout section).

Blob path: workspace/{owner_email}/{workspace_id}/{document_id}/{kind}/{version_id}/{leaf}
(ACP_WORKSPACE_BLOB_CONTAINER, default 'workspace-content'). `kind` is one of the PRD §10
sub-paths (source/remediated/previews/reports/release); only 'source' is used by anything in
this PR — the others are named now so a later PR's paths agree with this one rather than
inventing a second convention.

UNVERIFIED against a live Azure account, same caveat as every other azure-sdk-touching module
in this codebase (api/blob.py, api/routes/control.py) — this sandbox has no network access to
a real storage account, and its own azure-identity import is additionally broken by an
unrelated native _cffi_backend build issue (see CLAUDE.md). Tested the same way
tests/test_perf_blobstore.py already tests api/blob.py: fake `azure.*` modules injected into
sys.modules so this module loads without the real package, then api-shaped fakes standing in
for the SDK objects it calls.
"""
from __future__ import annotations
import base64
import logging
import os
import uuid

_ACCOUNT = os.environ.get("ACP_WORKSPACE_BLOB_ACCOUNT", "")
_CONTAINER = os.environ.get("ACP_WORKSPACE_BLOB_CONTAINER", "workspace-content")
_ENABLED = bool(_ACCOUNT)
_LOG = logging.getLogger(__name__)

# PRD §9: upload authorization "must expire quickly". 15 minutes is generous for a single
# direct-to-blob PUT (even a slow connection finishes a multi-MB block upload well inside
# this) while still being "short-lived" in the sense the requirement means.
_UPLOAD_SAS_TTL_SECONDS = 900

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


def blob_path(owner: str | None, workspace_id: str, document_id: str, version_id: str,
              *, kind: str = "source", leaf: str = "original") -> str:
    """ADR 0044's Blob layout, with owner_email standing in for {tenant_id} (see that ADR's
    tenant-boundary decision). Opaque ids throughout (PRD §10: "use opaque IDs as Blob keys") —
    the human-facing filename is protected metadata in content_workspace_document_versions.
    original_filename, never part of the path itself.

    Public (no leading underscore) so the upload-completion route can RECOMPUTE the expected
    path server-side from (owner, workspace_id, document_id, version_id) rather than trust a
    client-supplied one — a client-supplied path could otherwise point a new document_version
    row at a completely different, already-uploaded blob (including another owner's), since
    nothing else in that flow re-derives or re-checks it."""
    return f"workspace/{owner or 'demo'}/{workspace_id}/{document_id}/{kind}/{version_id}/{leaf}"


def _user_delegation_key(svc, ttl_seconds: int):
    """A short-lived key scoped to exactly this TTL, obtained via the managed identity —
    never an account key (PRD §29: "No account keys in the browser" / §9: "avoid exposing
    storage account keys"). Azure AD-backed SAS generation, the modern replacement for
    account-key SAS."""
    from datetime import datetime, timedelta, timezone
    start = datetime.now(timezone.utc)
    return svc.get_user_delegation_key(start, start + timedelta(seconds=ttl_seconds))


def generate_upload_authorization(owner: str | None, workspace_id: str, document_id: str,
                                  *, expires_in_seconds: int = _UPLOAD_SAS_TTL_SECONDS,
                                  kind: str = "source") -> dict | None:
    """PRD §9's "ACP issues constrained upload authorization" step. Returns
    {"version_id", "blob_path", "upload_url", "expires_at"}, or None when blob storage isn't
    configured (the caller — the future upload-session route — must not offer direct upload in
    that case; there is no server-mediated fallback for large files by design, PRD §9's whole
    point).

    The SAS this issues:
      - permits WRITE only — no read, no list, no delete (PRD §9: "permit upload but not
        container listing").
      - is scoped to ONE blob path, for a version_id minted HERE and never used before —
        "prevent overwrite of another object" (PRD §9) holds structurally, by construction,
        rather than needing an Azure-side conditional-write guarantee: there is no prior
        object at this path for the upload to collide with, and no other caller is ever handed
        this same path.
      - expires in `expires_in_seconds` (PRD §9: "expire quickly").
    """
    svc = _service_client()
    if svc is None:
        return None
    from datetime import datetime, timedelta, timezone
    from azure.storage.blob import BlobSasPermissions, generate_blob_sas

    version_id = uuid.uuid4().hex[:12]
    path = blob_path(owner, workspace_id, document_id, version_id, kind=kind)
    expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)
    udk = _user_delegation_key(svc, expires_in_seconds)
    sas = generate_blob_sas(
        account_name=_ACCOUNT, container_name=_CONTAINER, blob_name=path,
        user_delegation_key=udk,
        permission=BlobSasPermissions(write=True, create=True),
        expiry=expiry)
    return {
        "version_id": version_id,
        "blob_path": path,
        "upload_url": f"https://{_ACCOUNT}.blob.core.windows.net/{_CONTAINER}/{path}?{sas}",
        "expires_at": expiry.isoformat(),
    }


def get_uploaded_blob_properties(owner: str | None, workspace_id: str, document_id: str,
                                 version_id: str, *, kind: str = "source") -> dict | None:
    """PRD §9's "ACP verifies completion, size, hash, and ownership" step — called by the
    upload-complete route (a later PR) after the browser reports it finished. Returns
    {"size", "content_md5"} (content_md5 base64-encoded, matching the `Content-MD5` header
    convention, or None if the client didn't set one on upload), or None if the blob isn't
    configured, doesn't exist, or the read fails — any of which the caller must treat as
    'upload not verified', never as 'upload succeeded with unknown properties'."""
    svc = _service_client()
    if svc is None:
        return None
    path = blob_path(owner, workspace_id, document_id, version_id, kind=kind)
    blob = svc.get_blob_client(container=_CONTAINER, blob=path)
    try:
        props = blob.get_blob_properties()
    except Exception:
        return None
    md5 = getattr(props.content_settings, "content_md5", None) if props.content_settings else None
    return {"size": props.size, "content_md5": base64.b64encode(md5).decode() if md5 else None}


def download_document_bytes(owner: str | None, workspace_id: str, document_id: str,
                            version_id: str, *, kind: str = "source") -> bytes | None:
    """Server-mediated download (PRD's "download original") — the SAME server-streams-it-back
    shape api/blob.py's download_remediated already uses, rather than a second SAS scheme for
    reads. None if not configured or not found."""
    svc = _service_client()
    if svc is None:
        return None
    path = blob_path(owner, workspace_id, document_id, version_id, kind=kind)
    blob = svc.get_blob_client(container=_CONTAINER, blob=path)
    try:
        return blob.download_blob().readall()
    except Exception:
        return None


def download_document_prefix(owner: str | None, workspace_id: str, document_id: str,
                             version_id: str, *, kind: str = "source",
                             n: int = 8) -> bytes | None:
    """The first `n` bytes only, via an Azure ranged read — enough for magic-byte/file-
    signature sniffing (PRD §13) without downloading the whole file, which would spend exactly
    the transfer cost direct-to-blob upload (PRD §9) exists to avoid paying server-side. None
    if not configured, not found, or the blob is shorter than `n` bytes and Azure raises on the
    out-of-range request (callers already treat None as 'can't verify', the same as every
    other read in this module)."""
    svc = _service_client()
    if svc is None:
        return None
    path = blob_path(owner, workspace_id, document_id, version_id, kind=kind)
    blob = svc.get_blob_client(container=_CONTAINER, blob=path)
    try:
        return blob.download_blob(offset=0, length=n).readall()
    except Exception:
        return None


def delete_document_version(owner: str | None, workspace_id: str, document_id: str,
                            version_id: str, *, kind: str = "source") -> bool:
    """PRD §28 retention/deletion. Best-effort: returns True only on a confirmed delete, False
    for 'not configured' or 'already gone or failed' alike — the caller (a future retention
    sweep) treats both the same way ("nothing left to do"), not as distinct outcomes."""
    svc = _service_client()
    if svc is None:
        return False
    path = blob_path(owner, workspace_id, document_id, version_id, kind=kind)
    blob = svc.get_blob_client(container=_CONTAINER, blob=path)
    try:
        blob.delete_blob()
        return True
    except Exception:
        return False
