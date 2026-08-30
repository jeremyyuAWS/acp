"""ACP Managed Content Workspace (ADR 0044, PRD Phase 1) — workspace create/list/get.

Named `content_workspaces`, not `workspaces`, to stay unambiguous next to the existing,
unrelated `api/routes/workspace.py` (`GET /workspace/bootstrap` — the app-shell initial-load
optimization; nothing to do with this PRD).

Also implements PRD §9's upload flow — POST .../documents/upload-session (issue a constrained,
short-lived direct-to-Blob upload authorization via workspace_blob.generate_upload_authorization)
and POST .../documents/{document_id}/complete (verify the upload actually landed — size checked
server-side against workspace_blob.get_uploaded_blob_properties, never trusted from the client —
then create the content_workspace_document_version row). Deliberately NOT yet wired in: PRD
§13's security/quarantine pipeline (extension allow-lists, magic-byte sniffing, malware
scanning) and §12's duplicate-handling UX (reuse/new-version/cancel) — both later PRs; this PR
always creates a brand-new document per upload session.

Owner-scoped throughout: `owner_email` is the tenant boundary this whole app already uses
(ADR 0044). `GET /content-workspaces/{id}` 404s — never 403 — for a foreign id, matching
`test_foreign_scan_404.py`'s established "an id is never an existence oracle across owners"
contract.
"""
from __future__ import annotations

import json
import os
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import core
import workspace_blob

router = APIRouter()

# PRD §9: "ACP validates user, workspace, type, size, and quota" before issuing upload
# authorization. This is the "size" half only — type/quota (extension allow-lists, malware
# scanning, per-workspace quota) are PRD §13's security/quarantine pipeline, a separate,
# later PR (this session's item 20). 500 MiB is an arbitrary-but-reasonable placeholder
# ceiling for a single file, configurable per deployment.
_MAX_UPLOAD_BYTES = int(os.environ.get("ACP_WORKSPACE_MAX_UPLOAD_BYTES", str(500 * 1024 * 1024)))


def _owner(request: Request) -> str:
    """Matches api/routes/workspace.py's identical helper — the gate-verified email, or
    'demo' for the keyless/demo path."""
    return getattr(request.state, "user_email", None) or "demo"


def _serialize(ws: dict) -> dict:
    """store.py's content_workspaces rows carry permitted_file_types as a JSON-encoded TEXT
    column (same reasoning as campaign.scope) — decoded here, at the API boundary, so callers
    get a real list rather than a string they'd have to json.loads themselves."""
    out = dict(ws)
    raw = out.get("permitted_file_types")
    out["permitted_file_types"] = json.loads(raw) if raw else None
    return out


class ContentWorkspaceCreate(BaseModel):
    name: str
    purpose: str | None = None
    business_owner: str | None = None
    department: str | None = None
    wcag_standard: str | None = None
    retention_policy: str | None = None
    permitted_file_types: list[str] | None = None
    due_date: str | None = None
    project: str | None = None
    processing_region: str | None = None
    external_ai_policy: str | None = None


@router.post("/content-workspaces")
def create_content_workspace(body: ContentWorkspaceCreate, request: Request):
    if not body.name.strip():
        raise HTTPException(422, "name is required")
    owner = _owner(request)
    workspace_id = uuid.uuid4().hex[:12]
    core.store.create_content_workspace(
        workspace_id, owner_email=owner, name=body.name.strip(), purpose=body.purpose,
        business_owner=body.business_owner, department=body.department,
        wcag_standard=body.wcag_standard, retention_policy=body.retention_policy,
        permitted_file_types=body.permitted_file_types, due_date=body.due_date,
        project=body.project, processing_region=body.processing_region,
        external_ai_policy=body.external_ai_policy)
    core.store.log_decision(owner, "content_workspace.created", detail=body.name.strip())
    return get_content_workspace(workspace_id, request)


@router.get("/content-workspaces")
def list_content_workspaces(request: Request):
    rows = core.store.list_content_workspaces(_owner(request))
    return {"workspaces": [_serialize(r) for r in rows]}


@router.get("/content-workspaces/{workspace_id}")
def get_content_workspace(workspace_id: str, request: Request):
    ws = core.store.get_content_workspace(workspace_id, owner_email=_owner(request))
    if ws is None:
        raise HTTPException(404, "workspace not found")
    return _serialize(ws)


# ── Documents & upload (PRD §9) ──────────────────────────────────────────────

class UploadSessionCreate(BaseModel):
    filename: str
    relative_path: str | None = None
    size_bytes: int
    mime_type: str | None = None


class UploadComplete(BaseModel):
    version_id: str
    content_hash: str
    size_bytes: int
    mime_type: str | None = None


def _require_workspace(workspace_id: str, owner: str) -> dict:
    ws = core.store.get_content_workspace(workspace_id, owner_email=owner)
    if ws is None:
        raise HTTPException(404, "workspace not found")
    return ws


@router.post("/content-workspaces/{workspace_id}/documents/upload-session")
def create_upload_session(workspace_id: str, body: UploadSessionCreate, request: Request):
    """PRD §9: browser requests a session → ACP validates → issues constrained upload
    authorization → browser uploads directly to Blob. Always creates a NEW document (see this
    module's docstring: duplicate-handling/reuse is a later PR, item 21)."""
    owner = _owner(request)
    _require_workspace(workspace_id, owner)
    if not body.filename.strip():
        raise HTTPException(422, "filename is required")
    if body.size_bytes <= 0:
        raise HTTPException(422, "size_bytes must be positive")
    if body.size_bytes > _MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"file exceeds the {_MAX_UPLOAD_BYTES}-byte workspace upload limit")
    if not workspace_blob.enabled():
        raise HTTPException(503, "workspace uploads are not configured on this deployment")

    document_id = uuid.uuid4().hex[:12]
    core.store.create_content_workspace_document(
        document_id, workspace_id=workspace_id, owner_email=owner,
        display_name=body.filename.strip(), relative_path=body.relative_path, status="uploading")

    auth = workspace_blob.generate_upload_authorization(owner, workspace_id, document_id)
    if auth is None:
        # enabled() was true a moment ago but the actual SAS issuance failed (e.g. a transient
        # Azure error) — don't leave an orphan "uploading" row with nothing to upload to.
        core.store.update_content_workspace_document_status(document_id, "failed")
        raise HTTPException(503, "could not obtain an upload authorization")

    core.store.log_decision(owner, "content_workspace.upload_session_created",
                            detail=f"{workspace_id}/{document_id}: {body.filename.strip()}")
    return {"document_id": document_id, **auth}


@router.post("/content-workspaces/{workspace_id}/documents/{document_id}/complete")
def complete_upload(workspace_id: str, document_id: str, body: UploadComplete, request: Request):
    """PRD §9: 'ACP verifies completion, size, hash, and ownership' — the blob's ACTUAL size
    (read from Azure via workspace_blob, never the client's own claim about itself) must match
    what the client now reports; a mismatch means the upload is incomplete, was tampered with
    in transit, or targets the wrong blob, and the version row is never created. The blob path
    itself is RECOMPUTED here (workspace_blob.blob_path), never accepted from the client — see
    that function's own docstring for why trusting a client-supplied path would be unsafe.
    `content_hash` is recorded as reported (used by a later PR's duplicate detection, item 21)
    rather than independently re-verified — Azure's own Content-MD5 validation (enforced at
    PUT time by the browser's own upload, if it sets that header) is the integrity check that
    actually matters for 'did the right bytes arrive'; this endpoint's job is size + ownership +
    that a blob genuinely exists at the expected path."""
    owner = _owner(request)
    _require_workspace(workspace_id, owner)
    doc = core.store.get_content_workspace_document(document_id, owner_email=owner)
    if doc is None or doc["workspace_id"] != workspace_id:
        raise HTTPException(404, "document not found")

    props = workspace_blob.get_uploaded_blob_properties(owner, workspace_id, document_id,
                                                        body.version_id)
    if props is None:
        raise HTTPException(409, "upload not found — the browser may not have finished uploading")
    if props["size"] != body.size_bytes:
        raise HTTPException(422, f"declared size {body.size_bytes} does not match the "
                             f"uploaded blob's actual size {props['size']}")

    version_seq = core.store.next_content_workspace_document_version_seq(document_id)
    path = workspace_blob.blob_path(owner, workspace_id, document_id, body.version_id)
    core.store.create_content_workspace_document_version(
        body.version_id, document_id=document_id, version_seq=version_seq,
        content_hash=body.content_hash, mime_type=body.mime_type, size_bytes=body.size_bytes,
        blob_path=path, original_filename=doc.get("display_name"), uploaded_by=owner,
        lifecycle_state="ready")
    core.store.update_content_workspace_document_status(document_id, "ready")
    core.store.log_decision(owner, "content_workspace.upload_completed",
                            detail=f"{workspace_id}/{document_id}/{body.version_id}")
    return get_content_workspace_document(workspace_id, document_id, request)


@router.get("/content-workspaces/{workspace_id}/documents")
def list_content_workspace_documents(workspace_id: str, request: Request):
    owner = _owner(request)
    _require_workspace(workspace_id, owner)
    docs = core.store.list_content_workspace_documents(workspace_id, owner_email=owner)
    return {"documents": docs}


@router.get("/content-workspaces/{workspace_id}/documents/{document_id}")
def get_content_workspace_document(workspace_id: str, document_id: str, request: Request):
    owner = _owner(request)
    _require_workspace(workspace_id, owner)
    doc = core.store.get_content_workspace_document(document_id, owner_email=owner)
    if doc is None or doc["workspace_id"] != workspace_id:
        raise HTTPException(404, "document not found")
    versions = core.store.list_content_workspace_document_versions(document_id)
    return {**doc, "versions": versions}
