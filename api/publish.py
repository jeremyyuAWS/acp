"""Non-destructive, hierarchy-preserving publication of approved corrected copies."""
from __future__ import annotations

import hashlib
import io
import re
from datetime import datetime, timezone
from urllib.parse import quote

import blob as _blob
import provenance

RELEASE_ROOT = "Remediated"
RELEASE_PROPERTY = "acpReleaseId"
IDEMPOTENCY_PROPERTY = "acpPublishKey"
_FOLDER_MIME = "application/vnd.google-apps.folder"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_INVALID = re.compile(r'[<>:"|?*]')
_EXT_MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "html": "text/html", "htm": "text/html",
}


class UnsafeReleasePath(ValueError):
    """The immutable source path cannot safely become a provider path."""


def _mime_for(filename: str) -> str:
    return _EXT_MIME.get(filename.rsplit(".", 1)[-1].lower(), "application/octet-stream")


def _q(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def normalize_relative_path(path: str | None, filename: str) -> tuple[list[str], str]:
    """Return safe folder segments and filename from an immutable source-relative path."""
    raw = (path or filename).replace("\\", "/")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:/", raw):
        raise UnsafeReleasePath("absolute source paths cannot be released")
    parts = raw.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise UnsafeReleasePath("source path contains an empty or traversal segment")
    safe: list[str] = []
    for part in parts:
        if _CONTROL.search(part):
            raise UnsafeReleasePath("source path contains control characters")
        cleaned = _INVALID.sub("_", part).rstrip(". ").strip()
        if not cleaned:
            raise UnsafeReleasePath("source path contains an invalid provider name")
        safe.append(cleaned[:255])
    if safe[-1].casefold() != filename.casefold():
        leaf = _INVALID.sub("_", filename).rstrip(". ").strip()[:255]
        if not leaf:
            raise UnsafeReleasePath("filename is invalid for the provider")
        safe.append(leaf)
    return safe[:-1], safe[-1]


def sharepoint_relative_path(path: str | None, filename: str) -> tuple[list[str], str]:
    """Normalize Graph's ``/drives/.../root:/Folder`` parentReference into a relative path."""
    raw = (path or "").replace("\\", "/")
    if ":" in raw:
        raw = raw.split(":", 1)[1]
    raw = raw.strip("/")
    return normalize_relative_path(f"{raw}/{filename}" if raw else filename, filename)


def _find_folder(svc, parent_id: str | None, *, name: str | None = None,
                 release_id: str | None = None) -> dict | None:
    clauses = [f"mimeType='{_FOLDER_MIME}'", "trashed=false"]
    if parent_id:
        clauses.append(f"'{_q(parent_id)}' in parents")
    if name:
        clauses.append(f"name='{_q(name)}'")
    if release_id:
        clauses.append(f"properties has {{ key='{RELEASE_PROPERTY}' and value='{_q(release_id)}' }}")
    rows = svc.files().list(q=" and ".join(clauses),
                            fields="files(id,name,webViewLink,createdTime)",
                            orderBy="createdTime,id", pageSize=10).execute().get("files", [])
    return rows[0] if rows else None


def _ensure_folder(svc, parent_id: str | None, name: str, *,
                   properties: dict | None = None) -> tuple[dict, bool]:
    found = _find_folder(svc, parent_id, name=name)
    if found:
        return found, False
    body = {"name": name, "mimeType": _FOLDER_MIME}
    if parent_id:
        body["parents"] = [parent_id]
    if properties:
        body["properties"] = properties
    created = svc.files().create(body=body, fields="id,name,webViewLink,createdTime").execute()
    winner = _find_folder(svc, parent_id, name=name) or created
    return winner, winner.get("id") == created.get("id")


def ensure_published_folder(svc, release_id: str | None = None, *,
                            released_at: datetime | None = None,
                            return_details: bool = False):
    """Create/reuse ``Remediated/<UTC timestamp>`` for one stable release execution."""
    if not release_id:  # backwards compatibility for older callers/tests
        root, _ = _ensure_folder(svc, None, RELEASE_ROOT)
        return root["id"]
    root, _ = _ensure_folder(svc, None, RELEASE_ROOT)
    folder = _find_folder(svc, root["id"], release_id=release_id)
    at = (released_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    name = at.strftime("%Y-%m-%d %H-%M UTC")
    if not folder:
        created = svc.files().create(
            body={"name": name, "mimeType": _FOLDER_MIME, "parents": [root["id"]],
                  "properties": {RELEASE_PROPERTY: release_id}},
            fields="id,name,webViewLink,createdTime").execute()
        # Query by the stable release property, not merely the timestamp name: two distinct
        # executions may start in the same minute and must never share a destination.
        folder = _find_folder(svc, root["id"], release_id=release_id) or created
    details = {"id": folder["id"], "name": folder.get("name") or name,
               "url": folder.get("webViewLink") or
                      f"https://drive.google.com/drive/folders/{folder['id']}"}
    return details if return_details else details["id"]


def ensure_relative_folders(svc, release_folder_id: str, relative_path: str | None,
                            filename: str, cache: dict | None = None) -> tuple[str, str]:
    folders, safe_filename = normalize_relative_path(relative_path, filename)
    cache = cache if cache is not None else {}
    parent = release_folder_id
    for segment in folders:
        key = (parent, segment.casefold())
        if key not in cache:
            folder, _ = _ensure_folder(svc, parent, segment)
            cache[key] = folder["id"]
        parent = cache[key]
    return parent, safe_filename


def publication_key(release_id: str, source_id: str, corrected_checksum: str) -> str:
    return hashlib.sha256(f"{release_id}\0{source_id}\0{corrected_checksum}".encode()).hexdigest()


def _sp_find_child(token: str, url: str, name: str, *, folder_only: bool = False) -> dict | None:
    """Find an exact Graph child across every page, stopping safely on a repeated nextLink."""
    import scanner
    seen: set[str] = set()
    while url and url not in seen:
        seen.add(url)
        page = scanner._sp_get(token, url)
        for item in page.get("value", []):
            if item.get("name") == name and (not folder_only or item.get("folder") is not None):
                return item
        url = page.get("@odata.nextLink")
    return None


def ensure_sharepoint_release_folder(token: str, drive_id: str | None, release_id: str,
                                     folder_name: str) -> dict:
    """Create a distinct ``Remediated/<timestamp>`` root in one Graph drive/library."""
    import scanner
    root_id = scanner._sp_folder_id(token, drive_id, RELEASE_ROOT)
    base = scanner._sp_base(drive_id)
    children_url = f"{base}/items/{root_id}/children?$select=id,name,folder,webUrl&$top=200"
    collision = _sp_find_child(token, children_url, folder_name, folder_only=True)
    # Graph enforces sibling-name uniqueness. Preserve the clean timestamp normally and add a
    # stable release suffix only when another execution began in the same minute.
    actual_name = folder_name if collision is None else f"{folder_name} · {release_id[:8]}"
    folder_id = scanner._sp_folder_id(token, drive_id, actual_name, parent_id=root_id)
    item = scanner._sp_get(token, f"{base}/items/{folder_id}?$select=id,name,webUrl")
    return {"id": folder_id, "name": item.get("name") or actual_name,
            "url": item.get("webUrl")}


def _sp_child(token: str, drive_id: str | None, folder_id: str, name: str) -> dict | None:
    import scanner
    return _sp_find_child(
        token, f"{scanner._sp_base(drive_id)}/items/{folder_id}/children?"
               "$select=id,name,file,size,webUrl&$top=200", name)


def _sp_content_matches(token: str, drive_id: str | None, item_id: str,
                        expected_sha256: str) -> bool:
    """Verify an existing/uploaded Graph item by reading its bytes; never trust size alone."""
    import httpx
    import scanner
    response = httpx.get(f"{scanner._sp_base(drive_id)}/items/{item_id}/content",
                         headers={"Authorization": f"Bearer {token}"}, timeout=120,
                         follow_redirects=True)
    response.raise_for_status()
    return hashlib.sha256(response.content).hexdigest() == expected_sha256


def archive_copy_publish_sharepoint(token: str, drive_id: str | None, folder_id: str,
                                    owner: str, release_id: str, scan_id: str,
                                    filename: str, relative_path: str | None,
                                    source_id: str, folder_cache: dict | None = None) -> dict | None:
    """Publish one Blob-backed corrected copy into a Graph drive without overwriting a source."""
    import scanner
    data = _blob.download_remediated(owner, scan_id, filename)
    if not data:
        return None
    folders, safe_name = sharepoint_relative_path(relative_path, filename)
    cache = folder_cache if folder_cache is not None else {}
    parent = folder_id
    for segment in folders:
        key = (drive_id or "me", parent, segment.casefold())
        if key not in cache:
            cache[key] = scanner._sp_folder_id(token, drive_id, segment, parent_id=parent)
        parent = cache[key]
    sha256 = hashlib.sha256(data).hexdigest()
    key = publication_key(release_id, source_id, sha256)
    target_name = safe_name
    existing = _sp_child(token, drive_id, parent, target_name)
    if existing:
        if _sp_content_matches(token, drive_id, existing["id"], sha256):
            return {"id": existing["id"], "url": existing.get("webUrl"),
                    "checksum": sha256, "verified": True, "created": False,
                    "filename": target_name}
        stem, dot, ext = safe_name.rpartition(".")
        stem, dot, ext = (stem, dot, ext) if dot else (safe_name, "", "")
        target_name = f"{stem} ({key[:8]}){dot}{ext}"
        existing = _sp_child(token, drive_id, parent, target_name)
        if existing and _sp_content_matches(token, drive_id, existing["id"], sha256):
            return {"id": existing["id"], "url": existing.get("webUrl"),
                    "checksum": sha256, "verified": True, "created": False,
                    "filename": target_name}
    # Graph's path-addressing form requires the leaf to be URL encoded.  Keep slash encoded
    # too: this segment is a filename, never another hierarchy level.
    encoded_name = quote(target_name, safe="")
    base = f"{scanner._sp_base(drive_id)}/items/{parent}:/{encoded_name}:"
    result = scanner._sp_write(token, put_url=f"{base}/content",
                               session_url=f"{base}/createUploadSession",
                               content=data, content_type=_mime_for(target_name))
    item_id = result.get("id")
    if not item_id:
        result = _sp_child(token, drive_id, parent, target_name) or {}
        item_id = result.get("id")
    if not item_id or not _sp_content_matches(token, drive_id, item_id, sha256):
        raise IOError("SharePoint content verification failed")
    return {"id": item_id, "url": result.get("webUrl"), "checksum": sha256,
            "verified": True, "created": True, "filename": target_name}


def upload_published(svc, folder_id: str, filename: str, data: bytes, *,
                     idempotency_key: str | None = None, return_details: bool = False):
    """Create or reuse a corrected document, verifying provider checksum when available."""
    from googleapiclient.http import MediaIoBaseUpload
    digest = hashlib.md5(data).hexdigest()  # nosec B324: provider integrity checksum
    clauses = [f"'{_q(folder_id)}' in parents", "trashed=false"]
    if idempotency_key:
        clauses.append(f"properties has {{ key='{IDEMPOTENCY_PROPERTY}' and value='{_q(idempotency_key)}' }}")
    else:
        clauses.append(f"name='{_q(filename)}'")
    rows = svc.files().list(q=" and ".join(clauses),
                            fields="files(id,name,webViewLink,md5Checksum)",
                            orderBy="createdTime,id", pageSize=10).execute().get("files", [])
    if rows and idempotency_key:
        result, created = rows[0], False
    elif rows:
        props = provenance.stamp(filename)
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=_mime_for(filename), resumable=False)
        result = svc.files().update(fileId=rows[0]["id"], body={"properties": props},
                                    media_body=media,
                                    fields="id,name,webViewLink,md5Checksum").execute()
        created = False
    else:
        upload_name = filename
        if idempotency_key:
            collisions = svc.files().list(
                q=f"name='{_q(filename)}' and '{_q(folder_id)}' in parents and trashed=false",
                fields="files(id)", pageSize=1).execute().get("files", [])
            if collisions:
                stem, dot, ext = filename.rpartition(".")
                stem, dot, ext = (stem, dot, ext) if dot else (filename, "", "")
                upload_name = f"{stem} ({idempotency_key[:8]}){dot}{ext}"
        props = provenance.stamp(filename)
        if idempotency_key:
            props[IDEMPOTENCY_PROPERTY] = idempotency_key
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=_mime_for(filename), resumable=False)
        result = svc.files().create(
            body={"name": upload_name, "parents": [folder_id], "properties": props},
            media_body=media, fields="id,name,webViewLink,md5Checksum").execute()
        created = True
        if idempotency_key:
            winner = svc.files().list(
                q=(f"'{_q(folder_id)}' in parents and trashed=false and properties has "
                   f"{{ key='{IDEMPOTENCY_PROPERTY}' and value='{_q(idempotency_key)}' }}"),
                fields="files(id,name,webViewLink,md5Checksum)",
                orderBy="createdTime,id", pageSize=10).execute().get("files", [])
            if winner:
                created = winner[0].get("id") == result.get("id")
                result = winner[0]
    provider_digest = result.get("md5Checksum")
    if provider_digest and provider_digest != digest:
        raise IOError("provider checksum did not match corrected content")
    details = {"id": result.get("id"), "url": result.get("webViewLink", ""),
               "checksum": digest, "verified": True, "created": created}
    return details if return_details else details["url"]


def archive_copy_publish(svc, folder_id: str | None, owner: str | None,
                         scan_id: str, filename: str, *, relative_path: str | None = None,
                         source_id: str | None = None, folder_cache: dict | None = None,
                         return_details: bool = False):
    if svc is None or folder_id is None:
        return None
    data = _blob.download_remediated(owner, scan_id, filename)
    if not data:
        return None
    destination, safe_name = ensure_relative_folders(
        svc, folder_id, relative_path, filename, folder_cache)
    key = publication_key(scan_id, source_id or filename, hashlib.sha256(data).hexdigest())
    return upload_published(svc, destination, safe_name, data,
                            idempotency_key=key, return_details=return_details)
