"""Archive-copy publish (ADR 0010 follow-on).

Publishing an approved document is **non-destructive**: the original source file is
never overwritten. Instead the re-validated fixed copy — durable in Blob since
ADR 0010 — is placed into a distinct Drive *"Published (Accessible)"* folder as the
official document-of-record, kept separate from the working *"Remediated"* mirror the
remediation step writes. We return the Drive webViewLink so the UI can point the user
straight at the published artifact.

Graceful by contract: when Drive write isn't available (no token / read-only grant /
Blob miss) the caller still records the publish — Blob remains the durable copy — so
publishing never hard-fails. This mirrors the remediation Drive-mirror contract.
"""
from __future__ import annotations

import io

import blob as _blob

# A dedicated, human-legible folder distinct from the 'Remediated' working mirror, so
# an auditor sees exactly which documents are officially published & accessible.
PUBLISHED_FOLDER = "ACP — Published (Accessible)"

_EXT_MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "html": "text/html",
    "htm": "text/html",
}


def _mime_for(filename: str) -> str:
    return _EXT_MIME.get(filename.rsplit(".", 1)[-1].lower(), "application/octet-stream")


def ensure_published_folder(svc) -> str:
    """Find-or-create the 'Published (Accessible)' Drive folder; oldest wins if legacy
    duplicates exist (deterministic). Call ONCE per publish batch and pass the id in,
    so concurrent files don't each create their own folder."""
    safe = PUBLISHED_FOLDER.replace("\\", "\\\\").replace("'", "\\'")
    q = (f"name='{safe}' and mimeType='application/vnd.google-apps.folder' "
         f"and trashed=false")
    folders = svc.files().list(q=q, fields="files(id)", orderBy="createdTime",
                               pageSize=1).execute().get("files", [])
    if folders:
        return folders[0]["id"]
    return svc.files().create(
        body={"name": PUBLISHED_FOLDER, "mimeType": "application/vnd.google-apps.folder"},
        fields="id").execute()["id"]


def upload_published(svc, folder_id: str, filename: str, data: bytes) -> str:
    """Upsert the fixed copy into the published folder (update an existing same-named
    copy rather than piling up duplicates on re-publish). Returns the webViewLink."""
    from googleapiclient.http import MediaIoBaseUpload
    mimetype = _mime_for(filename)
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mimetype, resumable=False)
    safe = filename.replace("\\", "\\\\").replace("'", "\\'")
    existing = svc.files().list(
        q=f"name='{safe}' and '{folder_id}' in parents and trashed=false",
        fields="files(id)", pageSize=1).execute().get("files", [])
    if existing:
        res = svc.files().update(fileId=existing[0]["id"], media_body=media,
                                 fields="id,webViewLink").execute()
    else:
        res = svc.files().create(body={"name": filename, "parents": [folder_id]},
                                 media_body=media, fields="id,webViewLink").execute()
    return res.get("webViewLink", "")


def archive_copy_publish(svc, folder_id: str | None, owner: str | None,
                         scan_id: str, filename: str) -> str | None:
    """Publish one file by archive-copy: read its fixed bytes from Blob and place them
    in the published folder. Returns the Drive URL, or None when there's nothing to
    publish to Drive (no Blob copy, or no Drive service) — the caller records the
    publish regardless, since Blob is the durable document-of-record."""
    if svc is None or folder_id is None:
        return None
    data = _blob.download_remediated(owner, scan_id, filename)
    if not data:
        return None
    try:
        return upload_published(svc, folder_id, filename, data)
    except Exception:
        return None
