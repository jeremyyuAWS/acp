"""SharePoint site discovery — the list an operator picks a scan target from.

The counterpart to routes/drive.py's /sources. Until this existed the SharePoint path could only
ever reach the signed-in user's OneDrive: `_sp_list` hardcoded /me/drive, so a team site's
document libraries — which is what "SharePoint" means to a customer — were unreachable, and
there was no surface to choose one from either.

WHY THE SERVER ENUMERATES RATHER THAN THE BROWSER. The SPA already talks to Graph directly for
its own file browser, so this could have been another fetch from there. It is here because the
SCAN runs server-side: the site id the operator picks has to reach `_sp_list` through the same
token the worker will use, and a site the browser can see with one set of scopes is not proof
the scan token can read it. Discovering through the same path the scan takes is what makes the
picker's list honest.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

import core
import scanner

router = APIRouter()


def _token(request: Request) -> str:
    """The SharePoint access token, from the same header the scan path reads."""
    token = request.headers.get("x-sp-token")
    if not token:
        raise HTTPException(
            status_code=400,
            detail="No SharePoint token. Sign in to Microsoft in the app first — this endpoint "
                   "reads the same x-sp-token the scan uses, deliberately, so the sites listed "
                   "are the ones a scan could actually read.")
    return token


@router.get("/sharepoint/sites")
def sites(request: Request, q: str = ""):
    """Sites the token can see. `q` is a Graph search term; empty means everything visible.

    A PermissionError from the Graph helper is a missing scope, not a server fault, so it is
    surfaced as 403 with the consent that would fix it rather than a 500 that reads as a bug in
    ACP. That distinction is the whole reason the helper translates it.
    """
    try:
        return {"sites": scanner._sp_sites(_token(request), q)}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001 — Graph/httpx failures are the caller's problem to see
        raise HTTPException(status_code=502, detail=f"Microsoft Graph error: {e}") from e


@router.get("/sharepoint/sites/{site_id:path}/drives")
def drives(site_id: str, request: Request):
    """The document libraries on one site.

    `:path` because a Graph site id is itself compound — `contoso.sharepoint.com,<guid>,<guid>` —
    and the default converter stops at the first separator, which would silently truncate every
    id to its hostname and 404 for reasons no one could see from the URL.
    """
    try:
        return {"drives": scanner._sp_drives(_token(request), site_id)}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Microsoft Graph error: {e}") from e


@router.post("/sharepoint/upload")
async def sharepoint_upload(request: Request):
    """Write one remediated file back to SharePoint.

    The counterpart of /drive/upload, and deliberately the same shape: multipart with scan_id,
    file and blob, and the same `record_remediation` call at the end so a SharePoint write shows
    up in the compliance record exactly like a Drive one.

    `drive_id` is REQUIRED and comes from the scan, not from the browser's idea of where the file
    lives. Graph item ids are unique only within a drive, so writing to the wrong one is not an
    error you would see — it succeeds, into somebody else's library.

    TWO MODES, chosen by whether `item_id` is present.

    Without it, the file is written into the mirror folder — the SAME setting Drive uses
    (core.store.get_drive_mirror_folder), so renaming the mirror renames it for both sources
    rather than leaving SharePoint writing to a name only this route knows.

    With it, the remediated bytes REPLACE that item in place. The item keeps its URL, its
    sharing links and its version history, which is the whole point: everyone who already has a
    link to the document gets the remediated one, instead of a corrected copy sitting in a folder
    they will never open. The original is archived first and a failed archive ABORTS the write.

    The in-place path also removes a re-ingestion problem rather than adding one: a mirror write
    leaves two copies of the same document in the library, and SharePoint's defence against
    re-scanning its own output is folder-scoped and admits to being the weaker of the two
    (see scanner._sp_list). Replacing leaves exactly one file, at the path it always had.
    """
    from datetime import date

    from fastapi import UploadFile

    form = await request.form()
    scan_id = form.get("scan_id", "")
    filename = form.get("file", "")
    drive_id = form.get("drive_id", "")
    item_id = form.get("item_id", "")
    score = form.get("score", "")
    upload_file: UploadFile = form.get("blob")
    if not upload_file:
        raise HTTPException(400, "missing blob field")
    if not drive_id and not item_id:
        # Required for a MIRROR write, and only there. That write has to find-or-create a folder
        # and drop a new file in it, so an unnamed drive means guessing which library to create
        # it in — and guessing wrong succeeds, into somebody else's.
        #
        # A REPLACE names an existing item instead, and an item listed from OneDrive carries no
        # driveId at all (scanner._sp_list). Demanding one would break every OneDrive write-back
        # while reading like a safety check; absent, scanner._sp_base resolves /me/drive, exactly
        # as the download path has always done for the same items.
        raise HTTPException(
            400,
            "missing drive_id. A SharePoint item id is only unique within its drive, so the "
            "write target has to be named explicitly — the scan records it on every item it "
            "lists from a site.")

    token = _token(request)
    content = await upload_file.read()
    content_type = upload_file.content_type or "application/octet-stream"

    if item_id:
        try:
            # Archive, THEN write. Ordered, and not wrapped in its own try: an archive failure
            # must propagate as a refusal to write, never be logged past.
            scanner._sp_archive_original(token, drive_id, item_id, date.today().isoformat())
            item = scanner._sp_replace(token, drive_id, item_id, content, content_type)
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"SharePoint replace failed: {e}") from e
        stamped = f"Remediated for WCAG 2.1 AA by mova.io · {date.today().isoformat()}"
        if score:
            stamped += f" · Score: {score}/100"
        scanner._sp_describe(token, drive_id, item_id, stamped)
        web_url = item.get("webUrl", "")
        if scan_id and filename:
            core.store.record_remediation(scan_id, filename, drive_write_url=web_url)
        return {"ok": True, "url": web_url, "replaced": True,
                "archivedTo": scanner.SP_ARCHIVE_FOLDER, "driveId": drive_id}

    folder = core.store.get_drive_mirror_folder()
    try:
        item = scanner._sp_upload(token, drive_id, folder, filename, content, content_type)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"SharePoint upload failed: {e}") from e

    web_url = item.get("webUrl", "")
    if scan_id and filename:
        core.store.record_remediation(scan_id, filename, drive_write_url=web_url)
    return {"ok": True, "url": web_url, "replaced": False, "folder": folder, "driveId": drive_id}
