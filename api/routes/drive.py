"""Google Drive endpoints: identity, source listing, folder picker, write-back."""
from __future__ import annotations
import os

from fastapi import APIRouter, HTTPException, Request

import core
import provenance

router = APIRouter()


def _drive_error(e: Exception) -> HTTPException:
    """Translate a Google API error into a clear, actionable HTTPException so the
    UI shows *why* Drive failed instead of a bare status code."""
    status = getattr(getattr(e, "resp", None), "status", None)
    msg = ""
    try:
        import json as _json
        msg = (_json.loads(getattr(e, "content", b"") or b"{}")
               .get("error", {}).get("message", "")) or ""
    except Exception:
        msg = str(getattr(e, "reason", "") or "")
    low = msg.lower()
    if status == 403:
        if "has not been used" in low or "is disabled" in low or "accessnotconfigured" in low:
            return HTTPException(403, "Google Drive API is not enabled for this app's "
                                 "Google Cloud project. Enable it in Console → APIs & Services → Library.")
        if "insufficient" in low or "scope" in low:
            return HTTPException(403, "Your Google sign-in didn't grant Drive access. "
                                 "Sign out and sign in again, and approve the Drive permission.")
        return HTTPException(403, f"Google denied Drive access: {msg or 'permission denied'}")
    return HTTPException(status or 502, f"Drive error: {msg or e}")


@router.get("/me")
def me(request: Request):
    """Signed-in identity = the connected Google account (real, via the Drive API)."""
    try:
        u = core.drive_service(request).about().get(fields="user").execute().get("user", {})
    except HTTPException:
        raise
    except Exception as e:
        raise _drive_error(e)
    return {"email": u.get("emailAddress"), "name": u.get("displayName"), "photo": u.get("photoLink")}


@router.get("/sources")
def sources(request: Request):
    from scanner import _DRIVE_MIME_Q
    token = request.headers.get("x-drive-token")
    name = "My Drive" if token else "acp-demo-corpus"
    try:
        svc = core.drive_service(request)
        about = svc.about().get(fields="user/displayName").execute()
        if token:
            # Paginate to get an accurate count (mirrors _search_drive in scanner.py)
            n = 0
            page_token = None
            while True:
                resp = svc.files().list(
                    q=f"({_DRIVE_MIME_Q}) and trashed=false",
                    fields="files(id)", pageSize=1000, pageToken=page_token,
                ).execute()
                n += len(resp.get("files", []))
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break
            source_id = "root"
        else:
            demo_folder = os.environ.get("ACP_DRIVE_FOLDER") or "1W27ULZsstP7gYGzgKKBId0qEfNxeKn0_"
            n = len(svc.files().list(q=f"'{demo_folder}' in parents and trashed=false",
                                     fields="files(id)", pageSize=200).execute().get("files", []))
            source_id = demo_folder
        return [{"type": "google_drive", "name": name, "id": source_id,
                 "files": n, "access": "read-only",
                 "user": about.get("user", {}).get("displayName")}]
    except HTTPException:
        raise
    except Exception as e:
        raise _drive_error(e)


@router.get("/folders")
def folders(request: Request, parent: str = "root"):
    """List immediate subfolders of a Drive folder — drives the frontend folder picker."""
    try:
        svc = core.drive_service(request)
        items = svc.files().list(
            q=f"'{parent}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
            fields="files(id,name)",
            pageSize=100,
            orderBy="name",
        ).execute().get("files", [])
        parent_name = "My Drive" if parent == "root" else svc.files().get(
            fileId=parent, fields="name").execute().get("name", "")
        return {"parent": parent, "name": parent_name,
                "folders": [{"id": f["id"], "name": f["name"]} for f in items]}
    except HTTPException:
        raise
    except Exception as e:
        raise _drive_error(e)


@router.post("/drive/upload")
async def drive_upload(request: Request):
    """Upload a remediated file to Google Drive → Remediated/ folder.
    Body: multipart/form-data with fields: scan_id, file (filename), blob (file bytes)."""
    from fastapi import UploadFile
    import io
    from googleapiclient.http import MediaIoBaseUpload

    form = await request.form()
    scan_id = form.get("scan_id", "")
    filename = form.get("file", "")
    upload_file: UploadFile = form.get("blob")
    if not upload_file:
        raise HTTPException(400, "missing blob field")

    token = request.headers.get("x-drive-token")
    if not token:
        raise HTTPException(401, "No Drive token — connect Google Drive in Settings → Integrations")

    content = await upload_file.read()
    content_type = upload_file.content_type or "application/octet-stream"

    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        creds = Credentials(token=token, scopes=["https://www.googleapis.com/auth/drive.file"])
        svc = build("drive", "v3", credentials=creds, cache_discovery=False)

        # Find or create the Remediated/ folder
        q = "name='Remediated' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        folders = svc.files().list(q=q, fields="files(id)", pageSize=1).execute().get("files", [])
        if folders:
            folder_id = folders[0]["id"]
        else:
            folder_id = svc.files().create(
                body={"name": "Remediated", "mimeType": "application/vnd.google-apps.folder"},
                fields="id"
            ).execute()["id"]

        media = MediaIoBaseUpload(io.BytesIO(content), mimetype=content_type, resumable=False)
        result = svc.files().create(
            body={"name": filename, "parents": [folder_id],
                  "properties": provenance.stamp(filename)},
            media_body=media, fields="id,webViewLink"
        ).execute()
        web_url = result.get("webViewLink", "")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Drive upload failed: {e}")

    if scan_id and filename:
        core.store.record_remediation(scan_id, filename, drive_write_url=web_url)
        core.emit_remediation_span(scan_id, filename, drive_write_url=web_url)

    return {"url": web_url, "file_id": result.get("id", "")}
