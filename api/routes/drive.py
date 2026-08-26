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
    # Prefer the access-gate-verified identity for the ownership signal (it is set for BOTH
    # Google and Microsoft sign-ins), falling back to the Drive-reported email. is_scope_owner
    # tells the SPA whether this user may edit the scan scope — the same owner-only gate PUT
    # /settings enforces — so the scope editor can be hidden for non-owners POST-auth.
    verified = getattr(request.state, "user_email", None) or u.get("emailAddress")
    return {"email": u.get("emailAddress"), "name": u.get("displayName"), "photo": u.get("photoLink"),
            "is_scope_owner": core.is_scope_owner(verified),
            "is_admin": core.is_admin(verified)}


@router.get("/sources")
def sources(request: Request):
    from scanner import _DRIVE_MIME_Q
    token = request.headers.get("x-drive-token")
    # No Google Drive token in GIS mode = the user is authenticated some other way (a Microsoft /
    # SharePoint sign-in never has one) or simply hasn't connected Drive. That is NOT an error:
    # core.drive_service would raise 401 "sign in with Google", and the SPA reads any 401 as an
    # expired session — so an otherwise-signed-in Microsoft user gets bounced off the app, and the
    # bounce clears their token, cascading a 401 onto the next call (/scans/active). Their sources
    # come from /sharepoint/sites instead; Drive sources are simply absent here. Return an empty
    # list so the load call succeeds and the app stays put. (Demo/ADC mode — no GOOGLE_CLIENT_ID —
    # still falls through to the Google path below and lists the demo corpus.)
    if not token and core.GOOGLE_CLIENT_ID:
        return []
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


def describe_drive_readiness(request: Request, roots: list[str] | None) -> dict:
    """Preflight readiness for a Drive source + the SPECIFIC roots a user selected — the piece
    `/readyz` cannot answer, since it has no scan_id yet and no idea which folder was picked.

    Deliberately ONE Drive call per root (`files().get`, metadata only — never `.list()`), so
    this never approaches the full BFS walk it exists to run ahead of. A successful `get` proves
    both "the token is valid" and "it can read this root" in the same round trip — cheaper and
    more precise than a separate tokeninfo scope check, since a scope check cannot tell you
    whether THIS folder is actually reachable (shared-drive membership, trashed, wrong account).
    `roots=None`/empty means a whole-Drive scan, checked via the synthetic 'root' id.
    """
    try:
        svc = core.drive_service(request)
    except HTTPException as e:
        return {"ready": False, "credential_valid": False, "reason": str(e.detail), "roots": []}
    checked = roots or ["root"]
    root_results = []
    for r in checked:
        try:
            info = svc.files().get(fileId=r, fields="id,name,trashed").execute()
            root_results.append({"id": r, "name": info.get("name"), "exists": True,
                                 "trashed": bool(info.get("trashed"))})
        except Exception as e:
            he = _drive_error(e)
            root_results.append({"id": r, "exists": False, "error": he.detail})
    bad = [r for r in root_results if not r["exists"] or r.get("trashed")]
    return {"ready": not bad, "credential_valid": True, "roots": root_results,
           "reason": None if not bad else f"{len(bad)} of {len(checked)} selected folder(s) unreachable"}


def _tokeninfo_scopes(token: str) -> list[str]:
    """Ask Google what scopes an access token actually carries.

    The seam the diagnostic below is tested through, and the only authoritative source: the
    scopes on the credential object are what the CLIENT asked for, which for a user ADC is not
    what was granted. Takes the token as an argument and returns only scope names — the value
    never enters the response or a log.
    """
    import json as _json
    import urllib.request as _ur
    with _ur.urlopen(
        "https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=" + token, timeout=8,
    ) as r:
        return (_json.load(r).get("scope") or "").split()


@router.get("/drive/adc-scopes")
def adc_scopes(request: Request):
    """What Drive scopes the SERVER-SIDE (ADC) credential was actually granted. Owner-only.

    The scheduled sweep runs on ADC, not on any user's token, and asks Drive for a
    `corpora=allDrives` listing — which needs a broad Drive scope. When that scope is missing
    Google answers `403 "Request had insufficient authentication scopes."` and the sweep saves
    nothing, every five minutes, for as long as the credential stands.

    Reading the code does NOT tell you whether the scope is there.
    `scanner._drive_service(None)` passes `scopes=SCOPES` to `google.auth.default()`, but
    `default()` deliberately withholds scopes from the credential loader and then relies on
    `with_scopes_if_required`, which is a no-op for an `authorized_user` credential — the kind
    `gcloud auth application-default login` writes and `deploy/public/deploy.sh` ships by default.
    A user credential's scopes are fixed at consent; the client cannot widen them.
    (tests/test_drive_adc_scopes.py pins both halves of that.)

    So the only authoritative answer comes from Google. This mints the ADC access token and asks
    the tokeninfo endpoint what it carries. Returns scope NAMES and the credential TYPE — never
    the token, the refresh token, or the client secret.

    Fixing a missing scope is an OPS action, not a deploy: the account behind the ADC must
    re-consent (`gcloud auth application-default login --scopes=...`), or the deployment must move
    to a service account, which does honour `scopes=`.
    """
    from .system import _require_owner
    _require_owner(request)   # reports on the deployment's server-side credential — owner-only, not a tenant's business

    import google.auth
    import google.auth.transport.requests as _gart

    needed = list(core.DRIVE_SCOPES)
    try:
        creds, project = google.auth.default(scopes=needed)
    except Exception as e:
        return {"available": False, "reason": "no_adc", "detail": str(e)[:300],
                "scopes_requested": needed}

    cred_type = type(creds).__name__
    # `requires_scopes` False + `scopes` None is the exact signature of the silent-drop case.
    scopes_applied_locally = list(creds.scopes) if creds.scopes else []

    granted: list[str] | None = None
    error = None
    try:
        creds.refresh(_gart.Request())
        granted = _tokeninfo_scopes(str(creds.token))
    except Exception as e:
        # A refresh that fails because the scopes were never granted is itself the answer.
        error = str(e)[:300]

    missing = [s for s in needed if granted is not None and s not in granted]
    return {
        "available": True,
        "credential_type": cred_type,
        "is_user_credential": cred_type == "Credentials",   # google.oauth2.credentials
        "project": project,
        "scopes_requested": needed,
        "scopes_applied_to_credential": scopes_applied_locally,
        "scopes_granted": granted,
        "missing_scopes": missing,
        "sufficient_for_all_drives_listing": bool(granted) and not missing,
        "error": error,
        "remediation": (
            None if (granted and not missing) else
            "The ADC credential lacks the Drive scope the sweep needs. This cannot be fixed by "
            "config or a redeploy: re-consent as the account that owns the ADC "
            "(gcloud auth application-default login --scopes=openid,"
            "https://www.googleapis.com/auth/cloud-platform,"
            "https://www.googleapis.com/auth/drive.readonly) and re-set ACP_GOOGLE_ADC, or move "
            "the deployment to a service account with Drive access to the folders in scope."
        ),
    }


_LOCATIONS_KEY = "scan_locations"


@router.get("/sources/locations")
def get_scan_locations(request: Request):
    """The folders each source is scoped to, as chosen on the Sources tab.

    Mounted under /sources rather than a new top-level path — historical caution from when
    core.py's gate was a manually-maintained prefix allowlist, DEFAULT-OPEN for anything not
    listed (how /campaigns and /disposition, then five more route groups, shipped unauthenticated
    over five weeks). The gate is fail-closed now (2026-08-22): any REGISTERED route requires auth
    by default, so a new top-level router would no longer create that specific risk. Left mounted
    here anyway — a working, already-tested placement with no reason to move it.

    A location set is a property of the CONNECTION, not of one scan. That is the whole reason
    this is persisted rather than passed per scan: "which folders do we scan" is a thing an
    operator decides once about a source, and re-asking on every scan is what made the existing
    Drive picker (Discover tab) feel like a per-scan detour instead of configuration.

    Empty / absent means the whole source, which is the pre-existing behaviour and the safe
    reading: a MISSING selection must never be interpreted as "scan nothing".
    """
    import json
    raw = core.store.get_setting(_LOCATIONS_KEY) or "{}"
    try:
        return {"locations": json.loads(raw)}
    except (ValueError, TypeError):
        # A corrupt value must not take the Sources tab down; it means "no narrowing", which is
        # the same as never having chosen — and is visibly wrong on screen rather than silently
        # narrowing a scan to something nobody picked.
        return {"locations": {}}


@router.put("/sources/locations")
async def put_scan_locations(request: Request):
    """Replace the chosen locations for one source. Body: {source, folders:[{id,name}]}."""
    import json
    body = await request.json()
    source = (body.get("source") or "").strip()
    if source not in ("drive", "sharepoint"):
        raise HTTPException(400, "source must be 'drive' or 'sharepoint'")
    folders = body.get("folders") or []
    exclude = body.get("exclude") or []
    if not isinstance(folders, list) or not isinstance(exclude, list):
        raise HTTPException(400, "folders and exclude must be lists")

    def _clean(rows):
        return [{"id": str(f.get("id")), "name": str(f.get("name") or f.get("id"))}
                for f in rows if isinstance(f, dict) and f.get("id")]

    clean = _clean(folders)
    # Exclusions are only meaningful beneath an inclusion, so they are dropped with the
    # inclusions rather than kept as orphans. A stored exclusion with nothing to carve out of
    # would silently re-arm the moment somebody picked a folder that happened to contain it —
    # a narrowing nobody chose, from a decision made about a different scope.
    clean_excl = _clean(exclude) if clean else []
    try:
        current = json.loads(core.store.get_setting(_LOCATIONS_KEY) or "{}")
    except (ValueError, TypeError):
        current = {}
    current[source] = clean
    excl_map = current.get("_exclude") if isinstance(current.get("_exclude"), dict) else {}
    excl_map[source] = clean_excl
    current["_exclude"] = excl_map
    core.store.set_setting(_LOCATIONS_KEY, json.dumps(current))
    return {"ok": True, "source": source, "folders": clean, "exclude": clean_excl}


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
    """Upload a remediated file to the configured Drive mirror folder.
    Body: multipart/form-data with fields: scan_id, file (filename), blob (file bytes)."""
    from fastapi import UploadFile
    import io
    import handlers
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

        # The folder name is admin-configurable (settings.drive_mirror_folder). This route used
        # to hardcode 'Remediated', so an operator who renamed the mirror got their per-file
        # uploads scattered into a folder the rest of the system does not read. Reuse the one
        # find-or-create: it honours the setting, escapes quotes in the name, and picks the
        # OLDEST folder when legacy duplicates exist rather than an arbitrary one.
        folder_id = handlers.ensure_remediated_folder(svc)

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
