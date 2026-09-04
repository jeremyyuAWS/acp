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


@router.get("/sharepoint/folders")
def sp_folders(request: Request, drive_id: str = "", parent: str = "root", site: str = ""):
    """Immediate subfolders of a driveItem — the Graph counterpart of drive.py's /folders.

    Without this, "SharePoint" could only ever be scoped to a WHOLE SITE and OneDrive could not
    be scoped at all: the site picker was the only narrowing surface, and OneDrive has no site to
    pick. A user with one relevant folder in a large OneDrive had to scan all of it.

    `drive_id` may be omitted, in which case it resolves to the site's default document library
    or — with no site either — the signed-in user's OneDrive, so the picker can open at a sensible
    root without the caller first making two lookups of its own.

    The returned ids are `<driveId>/<itemId>` PAIRS, which is the form `?folders=` expects: a
    Graph item id is unique only within its drive, so a bare id does not identify a folder.
    Handing back the bare id and re-attaching the drive at the call site is exactly how the
    download path once ended up fetching the signed-in user's file of that id (see _sp_list).
    """
    token = _token(request)
    try:
        # `parent` comes back to us in the SAME `<driveId>/<itemId>` form this endpoint mints
        # below — the picker sends the id of the folder you clicked, and that id is a pair. It was
        # passed through whole, so drilling into any folder built
        # `/drives/{d}/items/{d}/{item}/children` and Graph answered 400 Bad Request, with the
        # drive id visibly twice in the URL. The ROOT listing worked ("root" has no "/"), which is
        # why this survived review: the picker opened fine and failed on the first click.
        #
        # The rule it broke: the ids an endpoint hands out must be valid inputs to that same
        # endpoint. Split on the first "/" exactly as scanner's root parser does (scanner.py's
        # `partition("/")`) — neither a Graph drive id nor an item id contains one.
        parent_drive, _, parent_item = parent.partition("/") if "/" in parent else ("", "", parent)
        # The drive embedded in `parent` wins: it is the drive that item actually lives in, so a
        # stale or absent `drive_id` query param cannot send the lookup at the wrong library.
        did = parent_drive or drive_id or scanner._sp_default_drive(token, site or None)
        if not did:
            raise HTTPException(status_code=404,
                                detail="no document library found for that site or user")
        return {"drive_id": did, "parent": parent,
                "folders": [{**f, "id": f"{did}/{f['id']}", "item_id": f["id"]}
                            for f in scanner._sp_folders(token, did, parent_item)]}
    except HTTPException:
        raise
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Microsoft Graph error: {e}") from e


def describe_sharepoint_readiness(request: Request, roots: list[str] | None) -> dict:
    """Preflight readiness for a SharePoint/OneDrive source + the SPECIFIC roots selected.

    Mirrors drive.describe_drive_readiness: one Graph metadata call per root
    (scanner._sp_item_exists), never a /children listing, so this stays bounded regardless of
    folder size. `roots` are `<driveId>/<itemId>` pairs — the same form /sharepoint/folders hands
    out and start_scan's `folders` param expects — split the same way sp_folders splits `parent`.
    An empty/None roots means the signed-in user's whole OneDrive, checked via its default drive.

    A root with NO "/" is a SITE id, and is checked as one (its libraries listed) rather than as
    an item — see the branch below for what the item path did with a site id before this.
    """
    token = request.headers.get("x-sp-token")
    if not token:
        return {"ready": False, "credential_valid": False,
               "reason": "sign in with Microsoft to scan SharePoint/OneDrive", "roots": []}
    checked = roots or [None]
    root_results = []
    for r in checked:
        if r and "/" not in r:
            # A BARE root is a SITE id, not an item id — the same split scanner._sp_locations
            # makes, and the reason this branch exists at all. Without it the id fell through to
            # the item path below, which resolves a missing drive to the signed-in user's
            # OneDrive and then asks it for an item whose id is a site: Graph answers 404, and a
            # perfectly readable site was reported "unreachable" by a check that had looked in
            # somebody's OneDrive for it. Every multi-site scan starts with roots of exactly this
            # shape, so the wrong answer would have been the ordinary case.
            #
            # Readiness for a site is "can this token list its libraries" — one Graph call, the
            # same bounded cost as an item lookup, and the same call the scan itself makes first.
            try:
                libs = scanner._sp_drives(token, r)
            except PermissionError as e:
                # WHOSE PROBLEM, alongside the message. The message is already the diagnosis
                # (scanner._sp_get calls sp_readiness); `owner` is the same verdict in a form the
                # preflight UI can group by, so an operator selecting thirty sites sees "two need
                # the site owner, one needs your admin" rather than thirty sentences to read.
                import sp_readiness
                root_results.append({"id": r, "kind": "site", "exists": False, "error": str(e),
                                     "owner": sp_readiness.diagnose_refusal(
                                         403, token=token, on_site=True)["owner"]})
                continue
            except Exception as e:  # noqa: BLE001 — a transport failure is not a missing site
                root_results.append({"id": r, "kind": "site", "exists": False,
                                     "error": f"Microsoft Graph error: {e}"})
                continue
            # A site with NO visible library scans to zero. Reporting it ready would hand the
            # operator an empty run and no way to tell the site from the product — the same
            # judgement SitePicker makes when it says so before the scan starts.
            root_results.append({"id": r, "kind": "site", "exists": bool(libs),
                                 "name": scanner._sp_site_name(token, r),
                                 "libraries": len(libs),
                                 **({} if libs else
                                    {"error": "no document libraries visible on this site"})})
            continue
        if r:
            drive_id, _, item_id = r.partition("/")
        else:
            drive_id, item_id = scanner._sp_default_drive(token) or "", "root"
        if not drive_id:
            root_results.append({"id": r or "root", "exists": False,
                                 "error": "no document library found for that site or user"})
            continue
        info = scanner._sp_item_exists(token, drive_id, item_id)
        root_results.append({"id": r or "root", **info})
    bad = [r for r in root_results if not r.get("exists")]
    return {"ready": not bad, "credential_valid": True, "roots": root_results,
           "reason": None if not bad else f"{len(bad)} of {len(checked)} selected folder(s) unreachable"}


@router.get("/sharepoint/readiness")
def sharepoint_readiness(request: Request, site: str = "", probe: bool = True):
    """TENANT ONBOARDING: what this tenant will and will not answer, before a scan is committed.

    The two questions a first run against a customer tenant fails on, asked up front instead of
    discovered at the end:

    1. **Which permissions does this sign-in actually carry?** Read from the token's own claims
       (sp_readiness.token_scopes) — no Graph call, and the difference between "the grant is
       missing" and "the grant is there and this account is not a member of that site" is the
       difference between a task for the tenant admin and a task for the site owner. Before this,
       every refusal was reported as the former.
    2. **Which SharePoint-native metadata will arrive?** The walk asks for the wide `$select` and
       the `listItem` expansion and silently falls back when a tenant refuses them, so a refused
       tenant produces a complete estate with every content type unread — and says so only per
       document, only after the scan. Three bounded requests settle it in advance.

    `site` names a site to probe; omitted, the signed-in user's own OneDrive is used. `probe=false`
    reports the token facts alone and issues NO Graph call, which is what a caller wants when the
    question is "am I signed in with the right scopes" rather than "will this tenant answer".

    DELIBERATELY NOT A GATE. Nothing here refuses a scan: a tenant that answers only tier 2 can
    still be scanned, and should be — it produces a real estate with less metadata. This endpoint
    exists so that outcome is a decision somebody made rather than one they discover afterwards.
    """
    import sp_readiness
    token = _token(request)
    granted, why_not = sp_readiness.token_scopes(token)
    report: dict = {
        "scopes": sorted(granted) if granted else None,
        "scopes_unreadable": why_not,
        "has_sites_scope": sp_readiness._has(granted, sp_readiness.SITES_SCOPE)
                           if granted else None,
        "site": site or None,
        "libraries": None,
        "metadata": None,
        "problems": [],
    }
    # A token with no Sites.Read.All is not an error and is not refused here — a OneDrive-only
    # deployment is a legitimate configuration. It is reported, because the operator selecting a
    # SITE with this token is about to get a 403 and this is where that becomes predictable.
    if granted is not None and not report["has_sites_scope"]:
        report["problems"].append({
            "owner": sp_readiness.TENANT_ADMIN,
            "missing_scope": sp_readiness.SITES_SCOPE,
            "message": (f"This sign-in does not carry {sp_readiness.SITES_SCOPE}, so SharePoint "
                        f"SITES will be refused; the signed-in user's own OneDrive still works. "
                        f"A tenant admin grants it on the Azure app registration."),
        })
    if not probe:
        return report

    drive_id = None
    if site:
        try:
            libs = scanner._sp_drives(token, site)
        except PermissionError as e:
            # The diagnosis _sp_get already made, carried through rather than re-derived: one
            # place decides whose problem a refusal is, and a second opinion here could disagree
            # with the message the scan itself will print.
            report["problems"].append({"owner": sp_readiness.UNKNOWN_OWNER, "message": str(e)})
            return report
        except Exception as e:  # noqa: BLE001 — a transport failure is not a permissions verdict
            report["problems"].append({"owner": sp_readiness.UNKNOWN_OWNER,
                                       "message": f"Microsoft Graph error: {e}"})
            return report
        report["libraries"] = [{"id": d["id"], "name": d.get("name")} for d in libs]
        if not libs:
            report["problems"].append({
                "owner": sp_readiness.SITE_OWNER,
                "message": "No document libraries are visible on this site, so a scan of it "
                           "would return nothing.",
            })
            return report
        drive_id = libs[0]["id"]

    try:
        report["metadata"] = sp_readiness.probe_metadata_tiers(token, drive_id)
    except PermissionError as e:
        report["problems"].append({"owner": sp_readiness.UNKNOWN_OWNER, "message": str(e)})
        return report
    except Exception as e:  # noqa: BLE001
        report["problems"].append({"owner": sp_readiness.UNKNOWN_OWNER,
                                   "message": f"Microsoft Graph error: {e}"})
        return report
    if (report["metadata"] or {}).get("refused"):
        report["problems"].append({
            "owner": sp_readiness.TENANT_ADMIN,
            "message": (f"This tenant refuses part of what the walk asks for, so a scan will "
                        f"record {report['metadata']['reads']}. Fields it cannot read are "
                        f"reported as 'unavailable' per document rather than as 'not "
                        f"configured' — they are not missing from the tenant, they were not "
                        f"handed over."),
        })
    return report


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
