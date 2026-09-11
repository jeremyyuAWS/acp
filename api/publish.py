"""Non-destructive, hierarchy-preserving publication of approved corrected copies."""
from __future__ import annotations

import hashlib
import io
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from urllib.parse import quote

import blob as _blob
import provenance

RELEASE_ROOT = "Remediated"
RELEASE_TIMEZONES = frozenset({
    "UTC", "America/Los_Angeles", "America/Denver", "America/Chicago",
    "America/New_York", "Asia/Kolkata",
})


def user_release_timezone(store, owner: str) -> str:
    """Use the owner's saved preference, including the Settings default."""
    getter = getattr(store, "get_user_setting", None)
    return (getter(owner, "release_timezone") if callable(getter) else None) or "America/Chicago"


def release_folder_name(at: datetime | None = None, timezone_name: str = "UTC",
                        *, owner_email: str | None = None) -> str:
    """Human-facing release folder name; the underlying release instant remains UTC."""
    if timezone_name not in RELEASE_TIMEZONES:
        raise ValueError("unsupported release timezone")
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("unsupported release timezone") from exc
    moment = at or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    stamp = moment.astimezone(zone).strftime("%Y-%m-%d %H-%M %Z")
    if not owner_email:
        return stamp
    # Identity comes from the authenticated owner, never a submitted folder label.
    # Keep the complete ordinary email while replacing provider-invalid path characters.
    email = _RELEASE_NAME_INVALID.sub("_", owner_email.strip()).rstrip(". ")
    if not email:
        email = "user-" + hashlib.sha256(owner_email.encode()).hexdigest()[:10]
    limit = 100 - len(stamp) - 3
    if len(email) > limit:
        email = email[:limit - 11] + "-" + hashlib.sha256(owner_email.encode()).hexdigest()[:10]
    return f"{stamp} - {email}"
RELEASE_PROPERTY = "acpReleaseId"
IDEMPOTENCY_PROPERTY = "acpPublishKey"
_FOLDER_MIME = "application/vnd.google-apps.folder"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_INVALID = re.compile(r'[<>:"|?*]')
_RELEASE_NAME_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_EXT_MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "html": "text/html", "htm": "text/html",
}


class UnsafeReleasePath(ValueError):
    """The immutable source path cannot safely become a provider path."""


def normalize_release_name(value: str | None, *, field: str) -> str | None:
    """Validate an optional user-facing package or destination label."""
    if value is None or not value.strip():
        return None
    cleaned = value.strip()
    if not cleaned or cleaned in (".", ".."):
        raise UnsafeReleasePath(f"{field} must contain a usable name")
    if cleaned.endswith("."):
        raise UnsafeReleasePath(f"{field} cannot end with a period")
    if len(cleaned) > 100:
        raise UnsafeReleasePath(f"{field} must be 100 characters or fewer")
    if _RELEASE_NAME_INVALID.search(cleaned):
        raise UnsafeReleasePath(f"{field} contains a character that cannot be used in a file or folder name")
    return cleaned


def sharepoint_release_name(value: str | None, owner_email: str, *,
                            timezone_name: str = "UTC", at: datetime | None = None) -> str:
    """Bind every new SharePoint folder to time and the authenticated releasing owner.

    A name returned by preview can be submitted unchanged, even across a minute boundary.
    Persisted release roots are reused by callers before consulting this helper.
    """
    requested = normalize_release_name(value, field="Release folder name")
    generated = release_folder_name(at, timezone_name, owner_email=owner_email)
    stamp_pattern = r"^\d{4}-\d{2}-\d{2} \d{2}-\d{2} (?:UTC|PST|PDT|MST|MDT|CST|CDT|EST|EDT|IST) - "
    identity = re.sub(stamp_pattern, "", generated)
    if requested:
        candidate = re.sub(stamp_pattern, "", requested)
        if candidate != requested and (candidate == identity or candidate.startswith(identity + " - ")):
            return requested
        available = 100 - len(generated) - 3
        label = requested[:max(0, available)].rstrip(". ")
        if label:
            return f"{generated} - {label}"
    return generated


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
    rows = _drive_publication_candidates(svc, " and ".join(clauses))
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
                            folder_name: str | None = None,
                            parent_id: str | None = None,
                            return_details: bool = False):
    """Create/reuse ``Remediated/<user-local timestamp>`` for one stable release execution."""
    if not release_id:  # backwards compatibility for older callers/tests
        root, _ = _ensure_folder(svc, parent_id, RELEASE_ROOT)
        return root["id"]
    root, _ = _ensure_folder(svc, parent_id, RELEASE_ROOT)
    folder = _find_folder(svc, root["id"], release_id=release_id)
    at = (released_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    name = folder_name or release_folder_name(at)
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


def find_published_folder(svc, release_id: str, *, parent_id: str | None = None):
    """Locate a historical release without creating any new provider objects."""
    root = _find_folder(svc, parent_id, name=RELEASE_ROOT)
    folder = _find_folder(svc, root["id"], release_id=release_id) if root else None
    if not folder:
        from release_artifacts import ReleaseArtifactError
        raise ReleaseArtifactError("The earlier Google Drive release folder could not be found. Check the destination before authorizing another copy.", category="delivery_version_unresolved")
    return {"id": folder["id"], "name": folder.get("name") or RELEASE_ROOT,
            "url": folder.get("webViewLink") or f"https://drive.google.com/drive/folders/{folder['id']}"}


def ensure_relative_folders(svc, release_folder_id: str, relative_path: str | None,
                            filename: str, cache: dict | None = None, *,
                            read_only: bool = False) -> tuple[str, str]:
    folders, safe_filename = normalize_relative_path(relative_path, filename)
    cache = cache if cache is not None else {}
    parent = release_folder_id
    for segment in folders:
        key = (parent, segment.casefold())
        if key not in cache:
            if read_only:
                folder = _find_folder(svc, parent, name=segment)
                if not folder:
                    from release_artifacts import ReleaseArtifactError
                    raise ReleaseArtifactError("The earlier Google Drive destination could not be found. Check it before authorizing another copy.", category="delivery_version_unresolved")
            else:
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
                                     folder_name: str, parent_id: str | None = None) -> dict:
    """Find/create the release's durably claimed root in one Graph drive/library."""
    import scanner
    root_id = _sp_ensure_folder(token, drive_id, parent_id, RELEASE_ROOT)
    base = scanner._sp_base(drive_id)
    folder_id = _sp_ensure_folder(token, drive_id, root_id, folder_name)
    item = scanner._sp_get(token, f"{base}/items/{folder_id}?$select=id,name,webUrl")
    return {"id": folder_id, "name": item.get("name") or folder_name,
            "url": item.get("webUrl")}


def _sp_child(token: str, drive_id: str | None, folder_id: str, name: str) -> dict | None:
    import scanner
    return _sp_find_child(
        token, f"{scanner._sp_base(drive_id)}/items/{folder_id}/children?"
               "$select=id,name,file,size,webUrl&$top=200", name)


def _sp_ensure_folder(token: str, drive_id: str | None, parent_id: str | None,
                      name: str) -> str:
    """Find/create one Graph folder, following pagination and converging on a 409 race."""
    import httpx
    import scanner
    base = scanner._sp_base(drive_id)
    parent = f"{base}/items/{parent_id}" if parent_id else f"{base}/root"
    children = f"{parent}/children"
    listing = f"{children}?$select=id,name,folder&$top=200"
    found = _sp_find_child(token, listing, name, folder_only=True)
    if found:
        return found["id"]
    response = httpx.post(
        children,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"},
        timeout=30, follow_redirects=True)
    if response.status_code == 401:
        raise scanner.SharePointSessionExpired("Microsoft Graph access token expired.")
    if response.status_code == 403:
        raise PermissionError("Microsoft Graph refused to create the SharePoint release folder.")
    if response.status_code == 409:
        winner = _sp_find_child(token, listing, name, folder_only=True)
        if winner:
            return winner["id"]
    response.raise_for_status()
    return response.json()["id"]


def _sp_content_matches(token: str, drive_id: str | None, item_id: str,
                        expected_sha256: str) -> bool:
    """Verify an existing/uploaded Graph item by reading its bytes; never trust size alone."""
    import httpx
    import scanner
    response = httpx.get(f"{scanner._sp_base(drive_id)}/items/{item_id}/content",
                         headers={"Authorization": f"Bearer {token}"}, timeout=120,
                         follow_redirects=True)
    if response.status_code == 401:
        raise scanner.SharePointSessionExpired("Microsoft Graph access token expired.")
    response.raise_for_status()
    return hashlib.sha256(response.content).hexdigest() == expected_sha256


def remediated_content_digest(owner: str, scan_id: str, filename: str) -> str | None:
    """Return the digest used to reserve a publication before any provider write."""
    data = _blob.download_remediated(owner, scan_id, filename)
    return hashlib.sha256(data).hexdigest() if data else None


def archive_copy_publish_sharepoint(token: str, drive_id: str | None, folder_id: str,
                                    owner: str, release_id: str, scan_id: str,
                                    filename: str, relative_path: str | None,
                                    source_id: str, folder_cache: dict | None = None,
                                    source_filename: str | None = None,
                                    expected_digest: str | None = None) -> dict | None:
    """Publish one Blob-backed corrected copy into a Graph drive without overwriting a source."""
    import scanner
    data = _blob.download_remediated(owner, scan_id, filename)
    if not data:
        return None
    if expected_digest and hashlib.sha256(data).hexdigest() != expected_digest:
        from release_artifacts import ReleaseArtifactError
        raise ReleaseArtifactError("Corrected content changed before delivery; review the new copy.")
    folders, safe_name = sharepoint_relative_path(relative_path, source_filename or filename)
    cache = folder_cache if folder_cache is not None else {}
    parent = folder_id
    for segment in folders:
        key = (drive_id or "me", parent, segment.casefold())
        if key not in cache:
            cache[key] = _sp_ensure_folder(token, drive_id, parent, segment)
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
                               content=data, content_type=_mime_for(target_name),
                               conflict_behavior="fail", force_session=True)
    item_id = result.get("id")
    if not item_id:
        result = _sp_child(token, drive_id, parent, target_name) or {}
        item_id = result.get("id")
    if not item_id or not _sp_content_matches(token, drive_id, item_id, sha256):
        raise IOError("SharePoint content verification failed")
    return {"id": item_id, "url": result.get("webUrl"), "checksum": sha256,
            "verified": True, "created": True, "filename": target_name}


def _drive_publication_candidates(svc, query: str) -> list[dict]:
    """Do not infer absence from a truncated or incomplete Drive search."""
    rows, token, seen = [], None, set()
    while True:
        options = {"q": query,
                   "fields": "nextPageToken,incompleteSearch,files(id,name,webViewLink,md5Checksum)",
                   "orderBy": "createdTime", "pageSize": 100}
        if token:
            options["pageToken"] = token
        page = svc.files().list(**options).execute()
        if page.get("incompleteSearch"):
            raise IOError("Google Drive could not complete the delivery lookup")
        rows.extend(page.get("files", []))
        token = page.get("nextPageToken")
        if not token:
            return rows
        if token in seen:
            raise IOError("Google Drive repeated a delivery lookup page")
        seen.add(token)


def _verify_drive_publication(svc, result: dict, data: bytes) -> None:
    """A provider identifier or missing checksum is never proof of delivered content."""
    item_id = result.get("id")
    if not item_id:
        raise IOError("Google Drive did not return a delivered document identifier")
    expected_md5 = hashlib.md5(data).hexdigest()  # nosec B324: provider integrity checksum
    if result.get("md5Checksum") and result["md5Checksum"] != expected_md5:
        raise IOError("provider checksum did not match corrected content")
    downloaded = svc.files().get_media(fileId=item_id).execute()
    if not isinstance(downloaded, bytes) or hashlib.sha256(downloaded).digest() != hashlib.sha256(data).digest():
        raise IOError("Google Drive content verification failed")


def upload_published(svc, folder_id: str, filename: str, data: bytes, *,
                     idempotency_key: str | None = None, return_details: bool = False,
                     target_file_id: str | None = None, reconcile_only: bool = False):
    """Create or reuse a corrected document, verifying provider checksum when available."""
    from googleapiclient.http import MediaIoBaseUpload
    digest = hashlib.md5(data).hexdigest()  # nosec B324: provider integrity checksum
    clauses = [f"'{_q(folder_id)}' in parents", "trashed=false"]
    if idempotency_key:
        clauses.append(f"properties has {{ key='{IDEMPOTENCY_PROPERTY}' and value='{_q(idempotency_key)}' }}")
    else:
        clauses.append(f"name='{_q(filename)}'")
    if target_file_id:
        try:
            existing = svc.files().get(
                fileId=target_file_id,
                fields="id,name,webViewLink,md5Checksum,parents,properties,trashed").execute()
        except Exception as exc:
            if getattr(getattr(exc, "resp", None), "status", None) != 404:
                raise
            existing = None
        if existing and (existing.get("trashed") or folder_id not in existing.get("parents", [])
                         or (existing.get("properties") or {}).get(IDEMPOTENCY_PROPERTY) != idempotency_key):
            raise IOError("Reserved Google Drive document identity no longer matches this delivery")
        rows = [existing] if existing else []
    else:
        rows = _drive_publication_candidates(svc, " and ".join(clauses))
    if not rows and reconcile_only:
        from release_artifacts import ReleaseArtifactError
        raise ReleaseArtifactError(
            "The earlier Google Drive delivery could not be confirmed. Check the destination before authorizing another copy.",
            category="delivery_version_unresolved")
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
        body = {"name": upload_name, "parents": [folder_id], "properties": props}
        if target_file_id:
            body["id"] = target_file_id
        try:
            result = svc.files().create(
                body=body, media_body=media, fields="id,name,webViewLink,md5Checksum").execute()
        except Exception as exc:
            if not target_file_id or getattr(getattr(exc, "resp", None), "status", None) != 409:
                raise
            # A prior attempt can commit between exact-ID lookup and create. Re-enter the
            # read-only verification path; never replace a different provider revision.
            return upload_published(svc, folder_id, filename, data,
                                    idempotency_key=idempotency_key, return_details=return_details,
                                    target_file_id=target_file_id, reconcile_only=True)
        created = True
        if idempotency_key and not target_file_id:
            winner = _drive_publication_candidates(
                svc, f"'{_q(folder_id)}' in parents and trashed=false and properties has "
                     f"{{ key='{IDEMPOTENCY_PROPERTY}' and value='{_q(idempotency_key)}' }}")
            if winner:
                created = winner[0].get("id") == result.get("id")
                result = winner[0]
    _verify_drive_publication(svc, result, data)
    details = {"id": result.get("id"), "url": result.get("webViewLink", ""),
               "checksum": digest, "verified": True, "created": created,
               "filename": result.get("name") or filename}
    return details if return_details else details["url"]


def archive_copy_publish(svc, folder_id: str | None, owner: str | None,
                         scan_id: str, filename: str, *, relative_path: str | None = None,
                         source_id: str | None = None, folder_cache: dict | None = None,
                         return_details: bool = False, expected_digest: str | None = None,
                         target_file_id: str | None = None, reconcile_only: bool = False):
    if svc is None or folder_id is None:
        return None
    data = _blob.download_remediated(owner, scan_id, filename)
    if not data:
        return None
    if expected_digest and hashlib.sha256(data).hexdigest() != expected_digest:
        from release_artifacts import ReleaseArtifactError
        raise ReleaseArtifactError("Corrected content changed before delivery; review the new copy.")
    destination, safe_name = ensure_relative_folders(
        svc, folder_id, relative_path, filename, folder_cache, read_only=reconcile_only)
    key = publication_key(scan_id, source_id or filename, hashlib.sha256(data).hexdigest())
    return upload_published(svc, destination, safe_name, data,
                            idempotency_key=key, return_details=return_details,
                            target_file_id=target_file_id, reconcile_only=reconcile_only)
