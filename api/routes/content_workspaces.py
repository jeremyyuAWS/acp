"""ACP Managed Content Workspace (ADR 0044, PRD Phase 1) — workspace create/list/get.

Named `content_workspaces`, not `workspaces`, to stay unambiguous next to the existing,
unrelated `api/routes/workspace.py` (`GET /workspace/bootstrap` — the app-shell initial-load
optimization; nothing to do with this PRD).

Also implements PRD §9's upload flow — POST .../documents/upload-session (issue a constrained,
short-lived direct-to-Blob upload authorization via workspace_blob.generate_upload_authorization,
AND reserve a PENDING content_workspace_document_version row keyed on the version_id the SAS was
minted for — see create_pending_content_workspace_document_version) and POST .../documents/
{document_id}/complete (verify the upload actually landed and resolve that pending row —
server-computed size AND content_hash, never the client's own claims about either; see
complete_upload's own docstring for why, and for why completion is idempotent on retry).

Also implements the part of PRD §13's security/quarantine pipeline that's decidable without a
real malware scanner: an extension allow-list at session-creation time (reusing
scanner.OFFICE/HTML_EXTS — the exact set PRD §8 already commits to supporting, not a second
list to keep in sync) and a magic-byte signature check at completion time, against the full
downloaded bytes (the same read the server-side hash verification above already pays for — one
download doing both jobs, not two separate blob reads). A signature mismatch does not fail the
request — PRD §8 lists "Quarantined" alongside "Ready for Discovery" as a normal terminal
upload state, not an error condition — it resolves the version row to lifecycle_state
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
new version of the existing document", needs to MOVE the already-uploaded blob from the
duplicate document over to the existing one (not merely issue a fresh upload-session — see this
module's later docstring on the document-scoped upload-session variant, which is a different
operation) — explicitly deferred rather than half-built here.

Also implements PRD's "download original": `GET .../documents/{document_id}/versions/
{version_id}/download` streams the version's bytes back through the server (the SAME
server-mediated shape api/blob.py's download_remediated route already uses for remediated
output — no second SAS scheme for reads), via workspace_blob.download_document_bytes.

Also implements the "quota" half of PRD §9's "ACP validates user, workspace, type, size, and
quota": `create_upload_session` checks the workspace's current storage usage
(store.get_content_workspace_storage_bytes) plus this upload's declared size against
_WORKSPACE_QUOTA_BYTES before issuing an authorization, the same way it already checks a
single file against _MAX_UPLOAD_BYTES.

Also implements the document-scoped upload-session variant named as deferred by every prior PR
in this series: `POST .../documents/{document_id}/versions/upload-session` adds a new version
to an EXISTING document (unlike `create_upload_session`, which always mints a brand-new one).
Shares all the same validation (`_validate_new_upload`) and reserves its own pending version
row exactly as `create_upload_session` does — filename/extension live on THAT row, not on a
write to the document's mutable `display_name` (an earlier version of this endpoint did exactly
that, and it was a real bug: two sessions for the same document in flight at once could race
and cross-contaminate which extension got verified against which upload; see
`create_pending_content_workspace_document_version`'s docstring). This is general
document-versioning UX, not specific to duplicate resolution — PRD §12's fourth
duplicate-resolution path ("attach this content as a new version of the OTHER, already-existing
document it duplicates") still isn't implemented: that needs moving/copying an already-uploaded
blob between documents, a different operation from this one, which is always a fresh
client-driven upload.

Also connects a stored upload to ACP's existing scan/assess engine: `POST .../documents/
{document_id}/versions/{version_id}/assess` enqueues a real, durable scan (via
store.enqueue_scan + a new "workspace_scan_file" job — api/handlers.py) against that ONE
version, and `GET .../assessment` reports its current status. This is deliberately the ONLY new
code — the per-file analysis itself is the exact engine every Drive/SharePoint scan already
uses (_analyse_and_persist_one), reached via `_download`'s existing item["path"] local-read
branch rather than a new "workspace" source kind bolted onto the connector-shaped scan/discover
state machine. In particular this needs no Drive/SharePoint-style connector session: the
worker reads the file with its OWN managed identity (workspace_blob), the same one it already
writes with, so a slow queue or a worker restart cannot orphan the job the way an expired
per-user connector token can. Remediation (turning an assessment into a corrected downloadable
version) is not implemented yet — a later PR, since api/handlers.py's `_remediate_file` is
tightly coupled to a Drive file id/token unlike the assess path and needs its own review before
reuse.

Owner-scoped throughout: `owner_email` is the tenant boundary this whole app already uses
(ADR 0044). `GET /content-workspaces/{id}` 404s — never 403 — for a foreign id, matching
`test_foreign_scan_404.py`'s established "an id is never an existence oracle across owners"
contract.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

import core
import scanner
import workspace_blob

router = APIRouter()

# PRD's "download original": fall back to this when a version's own stored mime_type is
# missing (e.g. the client never sent one at upload-completion time) — the same map
# api/routes/scans.py's download_remediated route already uses for the equivalent case.
_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".html": "text/html",
    ".htm": "text/html",
}

# PRD §9: "ACP validates user, workspace, type, size, and quota" before issuing upload
# authorization. 500 MiB is an arbitrary-but-reasonable placeholder ceiling for a single file,
# configurable per deployment.
_MAX_UPLOAD_BYTES = int(os.environ.get("ACP_WORKSPACE_MAX_UPLOAD_BYTES", str(500 * 1024 * 1024)))

# The "quota" half of the same PRD §9 requirement: a per-WORKSPACE ceiling on total bytes
# already occupying blob storage (store.get_content_workspace_storage_bytes), checked against
# BEFORE issuing an authorization for one more file. 5 GiB is an arbitrary-but-reasonable
# placeholder, the same way _MAX_UPLOAD_BYTES's 500 MiB is — configurable per deployment, not a
# PRD-specified number (the PRD names "quota" as a thing to validate, not a value).
_WORKSPACE_QUOTA_BYTES = int(os.environ.get("ACP_WORKSPACE_QUOTA_BYTES", str(5 * 1024 * 1024 * 1024)))

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


def _safe_disposition_filename(filename: str) -> str:
    """`filename` is the ORIGINAL uploaded name (user-controlled, stored verbatim at session
    creation) — unlike scans.py's Content-Disposition uses, which are all server-generated
    ids. Strip control characters (CR/LF header-injection) and quotes (which would otherwise
    terminate the quoted-string early) before it goes anywhere near a response header."""
    cleaned = "".join(c for c in filename if c.isprintable()).replace('"', "'")
    return cleaned or "download"


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


def _require_document(workspace_id: str, document_id: str, owner: str) -> dict:
    doc = core.store.get_content_workspace_document(document_id, owner_email=owner)
    if doc is None or doc["workspace_id"] != workspace_id:
        raise HTTPException(404, "document not found")
    return doc


def _validate_new_upload(workspace_id: str, owner: str, filename: str, size_bytes: int) -> None:
    """Shared by both upload-session routes (new document, new version of an existing one):
    PRD §9's "ACP validates ... type, size, and quota" — everything except the "user" and
    "workspace" halves, which differ by caller (a brand-new document has no owning document to
    check; a new version does) and so stay in each route itself."""
    if not filename.strip():
        raise HTTPException(422, "filename is required")
    if _extension(filename.strip()) not in _ALLOWED_EXTENSIONS:
        raise HTTPException(422, f"unsupported file type — accepted types are "
                             f"{', '.join(_ALLOWED_EXTENSIONS)}")
    if size_bytes <= 0:
        raise HTTPException(422, "size_bytes must be positive")
    if size_bytes > _MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"file exceeds the {_MAX_UPLOAD_BYTES}-byte workspace upload limit")
    used = core.store.get_content_workspace_storage_bytes(workspace_id, owner_email=owner)
    if used + size_bytes > _WORKSPACE_QUOTA_BYTES:
        raise HTTPException(413, f"this upload would exceed the workspace's "
                             f"{_WORKSPACE_QUOTA_BYTES}-byte storage quota "
                             f"({used} bytes already used)")
    if not workspace_blob.enabled():
        raise HTTPException(503, "workspace uploads are not configured on this deployment")


@router.post("/content-workspaces/{workspace_id}/documents/upload-session")
def create_upload_session(workspace_id: str, body: UploadSessionCreate, request: Request):
    """PRD §9: browser requests a session → ACP validates → issues constrained upload
    authorization → browser uploads directly to Blob. Always creates a NEW document — for
    adding a version to an EXISTING one, see create_new_version_upload_session below."""
    owner = _owner(request)
    _require_workspace(workspace_id, owner)
    _validate_new_upload(workspace_id, owner, body.filename, body.size_bytes)

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

    # Reserve the version row NOW, pending, keyed on the version_id the SAS was just minted
    # for — see create_pending_content_workspace_document_version's own docstring for why this
    # (not a later write to the mutable document row) is what fixes the completion-time race.
    version_seq = core.store.next_content_workspace_document_version_seq(document_id)
    core.store.create_pending_content_workspace_document_version(
        auth["version_id"], document_id=document_id, version_seq=version_seq,
        original_filename=body.filename.strip(), uploaded_by=owner)

    core.store.log_decision(owner, "content_workspace.upload_session_created",
                            detail=f"{workspace_id}/{document_id}: {body.filename.strip()}")
    return {"document_id": document_id, **auth}


class NewVersionUploadSessionCreate(BaseModel):
    filename: str
    size_bytes: int
    mime_type: str | None = None


@router.post("/content-workspaces/{workspace_id}/documents/{document_id}/versions/upload-session")
def create_new_version_upload_session(workspace_id: str, document_id: str,
                                      body: NewVersionUploadSessionCreate, request: Request):
    """The document-scoped upload-session variant every prior PR in this series (#1010's
    module docstring, #1015's duplicate-resolution docstring) named as deferred: adds a new
    version to an EXISTING document rather than minting a new one. Same validation as
    create_upload_session (_validate_new_upload) plus checking the document itself exists and
    is owned by this caller. No `relative_path` field — that's the document's own location,
    unchanged by uploading a new version of it, not a per-version property."""
    owner = _owner(request)
    _require_workspace(workspace_id, owner)
    _require_document(workspace_id, document_id, owner)
    _validate_new_upload(workspace_id, owner, body.filename, body.size_bytes)

    auth = workspace_blob.generate_upload_authorization(owner, workspace_id, document_id)
    if auth is None:
        raise HTTPException(503, "could not obtain an upload authorization")

    # Reserve the version row NOW, pending, exactly as create_upload_session does for a
    # brand-new document. This is also what fixes the race the old design had: filename is
    # per-version data on THIS row, not a write to the document's own mutable display_name, so
    # two sessions for the same document in flight at once (retry, double-click) can never
    # cross-contaminate which extension gets verified against which upload.
    version_seq = core.store.next_content_workspace_document_version_seq(document_id)
    core.store.create_pending_content_workspace_document_version(
        auth["version_id"], document_id=document_id, version_seq=version_seq,
        original_filename=body.filename.strip(), uploaded_by=owner)
    core.store.update_content_workspace_document_status(document_id, "uploading")
    core.store.log_decision(owner, "content_workspace.new_version_upload_session_created",
                            detail=f"{workspace_id}/{document_id}: {body.filename.strip()}")
    return {"document_id": document_id, **auth}


def _duplicate_of_for_response(workspace_id: str, document_id: str, owner: str,
                               content_hash: str) -> dict | None:
    if not content_hash:
        return None
    dup = core.store.find_content_workspace_document_version_by_hash(
        workspace_id, content_hash, owner_email=owner)
    if dup is not None and dup["document_id"] != document_id:
        return {"document_id": dup["document_id"], "version_id": dup["id"]}
    return None


@router.post("/content-workspaces/{workspace_id}/documents/{document_id}/complete")
def complete_upload(workspace_id: str, document_id: str, body: UploadComplete, request: Request):
    """PRD §9: 'ACP verifies completion, size, hash, and ownership'.

    Requires a PENDING version row already reserved by upload-session
    (create_pending_content_workspace_document_version) — body.version_id must name one, never
    trusted as a bare client-supplied identifier that could point at an arbitrary blob path.
    Idempotent on retry: if the row is no longer 'pending' (a previous call already resolved
    it — network blip, duplicate submit, a lost response the client is now re-sending), this
    reconciles to the existing result rather than re-verifying, re-writing, or erroring — "the
    same upload session produces one document version, with no duplicate records or generic
    server error on replay."

    Size is checked against the blob's ACTUAL size (workspace_blob.get_uploaded_blob_properties,
    never the client's own claim). content_hash is INDEPENDENTLY COMPUTED server-side from the
    downloaded bytes (hashlib.sha256) and checked against the client's claim — a mismatch is
    rejected (422), since duplicate detection is keyed on this hash and a browser-supplied
    value alone is not authoritative evidence of what was actually uploaded. The same download
    also serves the magic-byte signature check (PRD §13), one full read doing both jobs rather
    than two separate blob reads. The blob path itself is RECOMPUTED here (workspace_blob.
    blob_path), never accepted from the client — see that function's own docstring for why
    trusting a client-supplied path would be unsafe."""
    owner = _owner(request)
    _require_workspace(workspace_id, owner)
    doc = core.store.get_content_workspace_document(document_id, owner_email=owner)
    if doc is None or doc["workspace_id"] != workspace_id:
        raise HTTPException(404, "document not found")
    version = core.store.get_content_workspace_document_version(body.version_id,
                                                                 document_id=document_id)
    if version is None:
        raise HTTPException(404, "upload session not found — call the upload-session endpoint "
                             "first, and complete against the version_id it returned")

    if version.get("lifecycle_state") != "pending":
        # Already resolved by an earlier call. Reconcile, don't re-verify or error.
        result = get_content_workspace_document(workspace_id, document_id, request)
        if version.get("lifecycle_state") == "duplicate":
            dup = _duplicate_of_for_response(workspace_id, document_id, owner,
                                             version.get("content_hash") or "")
            if dup is not None:
                result = {**result, "duplicate_of": dup}
        return result

    props = workspace_blob.get_uploaded_blob_properties(owner, workspace_id, document_id,
                                                        body.version_id)
    if props is None:
        raise HTTPException(409, "upload not found — the browser may not have finished uploading")
    if props["size"] != body.size_bytes:
        raise HTTPException(422, f"declared size {body.size_bytes} does not match the "
                             f"uploaded blob's actual size {props['size']}")

    data = workspace_blob.download_document_bytes(owner, workspace_id, document_id, body.version_id)
    if data is None:
        raise HTTPException(409, "upload not found — the browser may not have finished uploading")
    if len(data) != body.size_bytes:
        raise HTTPException(422, f"declared size {body.size_bytes} does not match the "
                             f"downloaded content ({len(data)} bytes)")
    computed_hash = hashlib.sha256(data).hexdigest()
    if computed_hash != body.content_hash:
        raise HTTPException(422, "content_hash does not match the uploaded bytes — a "
                             "browser-reported hash alone is not authoritative")

    # PRD §13: verify the bytes that actually landed match what the extension claims. HTML has
    # no reliable leading signature and is never checked (see _SIGNATURES). A mismatch is a
    # normal terminal state (PRD §8's "Quarantined"), not a request error — the version row is
    # still resolved so the upload isn't silently dropped, just routed away from Discovery for
    # a human/later workflow to resolve.
    ext = _extension(version.get("original_filename") or "")
    expected_sig = _SIGNATURES.get(ext)
    quarantined = expected_sig is not None and not data.startswith(expected_sig)

    # PRD §12: is this exact content already uploaded elsewhere in the workspace? A match
    # against THIS SAME document is a normal re-upload/new-version, not a duplicate — only a
    # match against a DIFFERENT document is flagged. Skipped once already quarantined: a
    # security hold takes precedence, and dedup status on a file that isn't going to Discovery
    # anyway isn't useful.
    duplicate_of = None if quarantined else _duplicate_of_for_response(
        workspace_id, document_id, owner, computed_hash)

    path = workspace_blob.blob_path(owner, workspace_id, document_id, body.version_id)
    if quarantined:
        lifecycle_state = "quarantined"
    elif duplicate_of is not None:
        lifecycle_state = "duplicate"
    else:
        lifecycle_state = "ready"
    resolved = core.store.complete_content_workspace_document_version(
        body.version_id, document_id=document_id, content_hash=computed_hash,
        mime_type=body.mime_type, size_bytes=body.size_bytes, blob_path=path,
        uploaded_by=owner, lifecycle_state=lifecycle_state, malware_status="not_scanned")
    if not resolved:
        # Lost a race to a concurrent completion of the SAME pending row between our lookup
        # above and this write — reconcile to whatever the winner actually wrote, exactly like
        # the already-resolved branch at the top of this function.
        result = get_content_workspace_document(workspace_id, document_id, request)
        if duplicate_of is not None:
            result = {**result, "duplicate_of": duplicate_of}
        return result

    core.store.update_content_workspace_document_status(document_id, lifecycle_state)
    core.store.update_content_workspace_document_display_name(
        document_id, version.get("original_filename") or doc.get("display_name"))
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


@router.get("/content-workspaces/{workspace_id}/documents/{document_id}/versions/{version_id}/download")
def download_content_workspace_document_version(workspace_id: str, document_id: str,
                                                 version_id: str, request: Request):
    """PRD's 'download original': stream the version's bytes back through the server, the same
    shape api/routes/scans.py's download_remediated route already uses. A quarantined version
    is still downloadable — quarantine blocks Discovery, not a user retrieving their own
    upload — but this is a deliberate choice, not PRD-mandated; a deployment that wants to
    withhold quarantined bytes entirely can add that check here without touching anything else
    in this module."""
    owner = _owner(request)
    _require_workspace(workspace_id, owner)
    doc = core.store.get_content_workspace_document(document_id, owner_email=owner)
    if doc is None or doc["workspace_id"] != workspace_id:
        raise HTTPException(404, "document not found")
    version = core.store.get_content_workspace_document_version(version_id, document_id=document_id)
    if version is None:
        raise HTTPException(404, "version not found")

    data = workspace_blob.download_document_bytes(owner, workspace_id, document_id, version_id)
    if data is None:
        raise HTTPException(404, "the original file is not retrievable "
                             "(blob storage not configured, or the object is gone)")

    filename = version.get("original_filename") or doc.get("display_name") or "download"
    media_type = version.get("mime_type") or _MIME_TYPES.get(_extension(filename),
                                                              "application/octet-stream")
    safe_filename = _safe_disposition_filename(filename)
    return Response(data, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'})


# ── Assess (connects a stored upload to the existing scan/assess engine) ────────

@router.post("/content-workspaces/{workspace_id}/assess")
def assess_content_workspace(workspace_id: str, request: Request):
    """Assess EVERY eligible document in the workspace as ONE run — the Discover step of the
    upload-first flow (ADR 0044).

    The per-version endpoint below assesses one stored version and is the right call after a
    single re-upload. This is the customer-facing one: upload a folder, then assess what was
    uploaded, as a single run with a single total and a single completion.

    Enumeration happens in the WORKER, not here. This route creates the run and one
    workspace_scan_discover job; that handler lists the workspace and fans out. The listing is
    therefore re-derived on every attempt from the authoritative table rather than frozen into a
    payload at request time — so a document uploaded between this call and the worker claiming
    the job is included, and a reclaimed job resumes the fan-out instead of repeating it.

    The response deliberately reports the eligible/excluded split as it stands RIGHT NOW, as a
    preview: it is what the caller needs to see to know the request did something, and it is
    explicitly not a promise, because the authoritative count is the one the worker computes.
    Marked as such in the payload rather than left to be mistaken for the final answer."""
    owner = _owner(request)
    _require_workspace(workspace_id, owner)
    if not workspace_blob.enabled():
        raise HTTPException(503, "workspace uploads are not configured on this deployment")

    # Imported inside the function, the way every other route in this package reaches handlers
    # (drive.py, disposition.py, scans.py all do). api/handlers.py imports the whole engine at
    # module scope; pulling that in at import time here would put the route package on the wrong
    # side of that dependency.
    import handlers
    eligible, excluded = handlers._workspace_scan_population(workspace_id, owner)
    if not eligible:
        # 409 rather than an empty 200: a run over nothing would finalize instantly at 0 of 0 and
        # read as a successful assessment of the workspace. The reasons are returned so the
        # caller can see WHY — "3 documents, all quarantined" is actionable; "nothing to do" is
        # not.
        raise HTTPException(409, {"error": "no documents are ready to assess",
                                  "excluded": [{"file": f, "reason": r} for f, r in excluded]})

    scan_id = uuid.uuid4().hex[:12]
    scan_id, job_id = core.store.enqueue_scan(
        scan_id, "workspace", owner, "workspace_scan_discover",
        {"scan_id": scan_id, "workspace_id": workspace_id, "user": owner},
        inputs={"source": "workspace", "workspace_id": workspace_id, "actor": owner})
    core.store.log_decision(owner, "content_workspace.workspace_assess_enqueued",
                            scan_id=scan_id,
                            detail=f"{workspace_id}: {len(eligible)} eligible, "
                                   f"{len(excluded)} excluded")
    return {"scan_id": scan_id, "job_id": job_id, "status": "queued",
            "preview": {"eligible": len(eligible), "excluded": len(excluded),
                        "excluded_documents": [{"file": f, "reason": r} for f, r in excluded]}}


@router.post("/content-workspaces/{workspace_id}/documents/{document_id}/versions/{version_id}/assess")
def assess_content_workspace_document_version(workspace_id: str, document_id: str,
                                               version_id: str, request: Request):
    """Enqueues a real scan (durable, worker-processed) against this ONE stored version,
    reusing the existing engine end to end via workspace_scan_file (api/handlers.py) — no
    separate 'workspace assessment' logic. Deliberately a user-triggered action, not automatic
    on upload completion: a batch upload of many files should not silently fan out N scans the
    moment each one lands.

    Requires lifecycle_state="ready" — a quarantined or flagged-duplicate upload is not a
    supported scan input; the caller resolves that first (POST .../resolve-duplicate, or this
    stays quarantined for a human to review)."""
    owner = _owner(request)
    _require_workspace(workspace_id, owner)
    doc = core.store.get_content_workspace_document(document_id, owner_email=owner)
    if doc is None or doc["workspace_id"] != workspace_id:
        raise HTTPException(404, "document not found")
    version = core.store.get_content_workspace_document_version(version_id, document_id=document_id)
    if version is None:
        raise HTTPException(404, "version not found")
    if version.get("lifecycle_state") != "ready":
        raise HTTPException(409, f"version is not ready for assessment "
                             f"(lifecycle_state={version.get('lifecycle_state')!r})")
    if not workspace_blob.enabled():
        raise HTTPException(503, "workspace uploads are not configured on this deployment")

    scan_id = uuid.uuid4().hex[:12]
    filename = version.get("original_filename") or doc.get("display_name") or "document"
    scan_id, job_id = core.store.enqueue_scan(
        scan_id, "workspace", owner, "workspace_scan_file",
        {"scan_id": scan_id, "workspace_id": workspace_id, "document_id": document_id,
         "version_id": version_id, "file": filename, "checksum": version.get("content_hash"),
         "user": owner},
        inputs={"source": "workspace", "workspace_id": workspace_id, "document_id": document_id,
                "version_id": version_id, "actor": owner},
        content_workspace_version_id=version_id)
    core.store.log_decision(owner, "content_workspace.assess_enqueued",
                            detail=f"{workspace_id}/{document_id}/{version_id}: scan {scan_id}")
    return {"scan_id": scan_id, "job_id": job_id, "status": "queued"}


@router.get("/content-workspaces/{workspace_id}/documents/{document_id}/versions/{version_id}/assessment")
def get_content_workspace_document_version_assessment(workspace_id: str, document_id: str,
                                                       version_id: str, request: Request):
    """The current (most recent) assessment scan for this version, or 404 if none has ever
    been triggered — distinct from a 200 with an in-progress/queued status, which means one
    HAS been triggered and the caller should keep polling."""
    owner = _owner(request)
    _require_workspace(workspace_id, owner)
    doc = core.store.get_content_workspace_document(document_id, owner_email=owner)
    if doc is None or doc["workspace_id"] != workspace_id:
        raise HTTPException(404, "document not found")
    version = core.store.get_content_workspace_document_version(version_id, document_id=document_id)
    if version is None:
        raise HTTPException(404, "version not found")
    scan = core.store.get_content_workspace_version_scan(version_id)
    if scan is None:
        raise HTTPException(404, "no assessment has been run for this version")
    return scan
