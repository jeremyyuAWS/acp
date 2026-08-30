"""ACP Managed Content Workspace (ADR 0044, PRD Phase 1) — workspace create/list/get.

Named `content_workspaces`, not `workspaces`, to stay unambiguous next to the existing,
unrelated `api/routes/workspace.py` (`GET /workspace/bootstrap` — the app-shell initial-load
optimization; nothing to do with this PRD).

Also implements PRD §9's upload flow — POST .../documents/upload-session (issue a constrained,
short-lived direct-to-Blob upload authorization via workspace_blob.generate_upload_authorization)
and POST .../documents/{document_id}/complete (verify the upload actually landed — size checked
server-side against workspace_blob.get_uploaded_blob_properties, never trusted from the client —
then create the content_workspace_document_version row).

Also implements the part of PRD §13's security/quarantine pipeline that's decidable without a
real malware scanner: an extension allow-list at session-creation time (reusing
scanner.OFFICE/HTML_EXTS — the exact set PRD §8 already commits to supporting, not a second
list to keep in sync) and a magic-byte signature check at completion time, via
workspace_blob.download_document_prefix's ranged read. A signature mismatch does not fail the
request — PRD §8 lists "Quarantined" alongside "Ready for Discovery" as a normal terminal
upload state, not an error condition — it creates the version row with lifecycle_state
"quarantined" and leaves the document there for a human/later workflow to resolve, rather than
enqueueing Discovery. `malware_status` is stamped "not_scanned" on every version: there is no
real AV integration behind it (yet), and claiming "clean" without one would be worse than
omitting the field. Deeper archive-structure inspection, encrypted-file detection, and ZIP
path-traversal prevention are explicitly OUT of scope here — later work, once a real scanning
dependency is chosen.

Also implements the detectable half of PRD §12's duplicate handling: `complete_upload` checks
the freshly-uploaded content_hash against every other document already in the workspace (via
store.find_content_workspace_document_version_by_hash) and, on a match, marks the new version
"duplicate" instead of "ready" — again a normal terminal state (PRD §8 lists "Duplicate"
alongside "Quarantined"), not a request error, and skipped entirely when the upload was already
quarantined (a quarantined file's dedup status isn't useful). `POST
.../documents/{document_id}/resolve-duplicate` then lets the caller pick one of PRD §12's four
paths for a flagged document: `keep_as_new` (clear the flag, treat it as an ordinary new
document), `reuse_existing` or `cancel` (both delete this document/version and its blob — the
former because the existing document already has the content, the latter because the upload
was a mistake; they differ only in which decision gets logged). The fourth path, "attach as a
new version of the existing document", needs a document-scoped upload-session variant that
does not exist yet (`create_upload_session` always mints a brand-new document) — explicitly
deferred rather than half-built here.

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
import scanner
import workspace_blob

router = APIRouter()

# PRD §9: "ACP validates user, workspace, type, size, and quota" before issuing upload
# authorization. Quota (per-workspace limits) remains out of scope. 500 MiB is an
# arbitrary-but-reasonable placeholder ceiling for a single file, configurable per deployment.
_MAX_UPLOAD_BYTES = int(os.environ.get("ACP_WORKSPACE_MAX_UPLOAD_BYTES", str(500 * 1024 * 1024)))

# PRD §8's supported-format list, reusing scanner.py's own constants rather than a second list
# that could drift from what the scan engines actually accept.
_ALLOWED_EXTENSIONS = scanner.OFFICE + (".pdf",) + scanner.HTML_EXTS

# PRD §13: magic-byte / file-signature verification at completion time. HTML has no reliable
# leading signature (it can start with whitespace, a doctype in any case, a BOM, ...), so it is
# in the allow-list above but deliberately absent here — every other supported extension has an
# unambiguous magic number and IS enforced.
_SIGNATURES: dict[str, bytes] = {
    ".pdf": b"%PDF-",
    ".docx": b"PK\x03\x04",
    ".pptx": b"PK\x03\x04",
    ".xlsx": b"PK\x03\x04",
}


def _extension(filename: str) -> str:
    return "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


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
    if _extension(body.filename.strip()) not in _ALLOWED_EXTENSIONS:
        raise HTTPException(422, f"unsupported file type — accepted types are "
                             f"{', '.join(_ALLOWED_EXTENSIONS)}")
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

    # PRD §13: verify the bytes that actually landed match what the extension claims, via a
    # cheap ranged read (workspace_blob.download_document_prefix) rather than downloading the
    # whole file server-side. A mismatch is a normal terminal state (PRD §8's "Quarantined"),
    # not a request error — the version row is still created so the upload isn't silently
    # dropped, just routed away from Discovery for a human/later workflow to resolve.
    ext = _extension(doc.get("display_name") or "")
    expected_sig = _SIGNATURES.get(ext)
    quarantined = False
    if expected_sig is not None:
        prefix = workspace_blob.download_document_prefix(owner, workspace_id, document_id,
                                                          body.version_id, n=len(expected_sig))
        quarantined = prefix is None or not prefix.startswith(expected_sig)

    # PRD §12: is this exact content already uploaded elsewhere in the workspace? A match
    # against THIS SAME document is a normal re-upload/new-version, not a duplicate — only a
    # match against a DIFFERENT document is flagged. Skipped once already quarantined: a
    # security hold takes precedence, and dedup status on a file that isn't going to Discovery
    # anyway isn't useful.
    duplicate_of = None
    if not quarantined:
        dup = core.store.find_content_workspace_document_version_by_hash(
            workspace_id, body.content_hash, owner_email=owner)
        if dup is not None and dup["document_id"] != document_id:
            duplicate_of = {"document_id": dup["document_id"], "version_id": dup["id"]}

    version_seq = core.store.next_content_workspace_document_version_seq(document_id)
    path = workspace_blob.blob_path(owner, workspace_id, document_id, body.version_id)
    if quarantined:
        lifecycle_state = "quarantined"
    elif duplicate_of is not None:
        lifecycle_state = "duplicate"
    else:
        lifecycle_state = "ready"
    core.store.create_content_workspace_document_version(
        body.version_id, document_id=document_id, version_seq=version_seq,
        content_hash=body.content_hash, mime_type=body.mime_type, size_bytes=body.size_bytes,
        blob_path=path, original_filename=doc.get("display_name"), uploaded_by=owner,
        lifecycle_state=lifecycle_state, malware_status="not_scanned")
    core.store.update_content_workspace_document_status(document_id, lifecycle_state)
    core.store.log_decision(
        owner, f"content_workspace.upload_{lifecycle_state}"
        if lifecycle_state != "ready" else "content_workspace.upload_completed",
        detail=f"{workspace_id}/{document_id}/{body.version_id}")
    result = get_content_workspace_document(workspace_id, document_id, request)
    if duplicate_of is not None:
        result = {**result, "duplicate_of": duplicate_of}
    return result


class DuplicateResolution(BaseModel):
    action: str  # "keep_as_new" | "reuse_existing" | "cancel"


@router.post("/content-workspaces/{workspace_id}/documents/{document_id}/resolve-duplicate")
def resolve_duplicate(workspace_id: str, document_id: str, body: DuplicateResolution,
                      request: Request):
    """PRD §12: the caller's decision once complete_upload has flagged a document
    lifecycle_state="duplicate". `keep_as_new` clears the flag (the user confirms this really
    is a separate, wanted document despite the identical content). `reuse_existing` and
    `cancel` both discard this document/version and its blob — they differ only in the reason
    recorded, since from the store's point of view an unwanted duplicate and an abandoned
    upload end the same way. See this module's docstring for why the fourth PRD §12 path
    ("attach as a new version of the existing document") isn't implemented here."""
    if body.action not in ("keep_as_new", "reuse_existing", "cancel"):
        raise HTTPException(422, "action must be one of: keep_as_new, reuse_existing, cancel")
    owner = _owner(request)
    _require_workspace(workspace_id, owner)
    doc = core.store.get_content_workspace_document(document_id, owner_email=owner)
    if doc is None or doc["workspace_id"] != workspace_id:
        raise HTTPException(404, "document not found")
    if doc["status"] != "duplicate":
        raise HTTPException(409, "document is not flagged as a duplicate")

    if body.action == "keep_as_new":
        latest = core.store.get_latest_content_workspace_document_version(document_id)
        if latest is not None:
            core.store.update_content_workspace_document_version_lifecycle_state(
                latest["id"], "ready")
        core.store.update_content_workspace_document_status(document_id, "ready")
        core.store.log_decision(owner, "content_workspace.duplicate_kept_as_new",
                                detail=f"{workspace_id}/{document_id}")
        return get_content_workspace_document(workspace_id, document_id, request)

    latest = core.store.get_latest_content_workspace_document_version(document_id)
    if latest is not None:
        workspace_blob.delete_document_version(owner, workspace_id, document_id, latest["id"])
    core.store.delete_content_workspace_document(document_id, owner_email=owner)
    core.store.log_decision(
        owner, f"content_workspace.duplicate_{body.action}", detail=f"{workspace_id}/{document_id}")
    return {"document_id": document_id, "status": "deleted", "action": body.action}


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
