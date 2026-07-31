"""Reusable scan core: source -> engines -> rubric -> report dict.

Emits progress via a callback (phase / files_found / files_done / current) so the
control plane can stream live activity. Ephemeral working copies are deleted when the
scan finishes (the "documents never retained" guarantee).
"""
from __future__ import annotations
import concurrent.futures as _cf
import io, json, os, re, shutil, signal, subprocess, sys, tempfile, time, uuid, zipfile
from datetime import datetime, timezone
from pathlib import Path
import lf as _lf_mod
import provenance

# Per-file analysis is CPU/IO bound and independent; run it across a small thread
# pool. pikepdf/lxml release the GIL and each analyser is built fresh per call.
_SCAN_WORKERS = min(8, (os.cpu_count() or 2) * 2)

ACP = Path(__file__).resolve().parent.parent
# Engine + corpus locations default to the local dev layout but are env-overridable
# so the same code runs inside the deploy container (paths set in the Dockerfile).
# The PDF analyser is VENDORED into this repo (ADR 0029), the way ADR 0012 vendored the Office
# analysers. The previous default pointed at a checkout outside the tree
# (~/projects/_review-digital-accessibility/worker-python) which existed on exactly one laptop —
# so every other host, CI included, fell back to a path that was not there and skipped or errored
# every PDF. Defaulting into the repo means a fresh clone can assess a PDF.
WP = Path(os.environ.get("ACP_PDF_ENGINE") or (ACP / "engine" / "pdf-analyser"))
# Resolve dotnet the same way the test capability gates do (tests/engines.py): explicit
# override, then PATH, then the dev-machine install location. PATH matters wherever the
# SDK is installed by a package manager or CI action rather than the dotnet-install
# script — Homebrew puts it in /opt/homebrew/bin, actions/setup-dotnet on PATH — and
# neither creates ~/.dotnet/dotnet. Without the PATH lookup those environments resolved
# to a nonexistent path and every Office scan died with FileNotFoundError, while the
# gates (which DO check PATH) had already decided the engine was available.
DOTNET = (os.environ.get("ACP_DOTNET") or shutil.which("dotnet")
          or os.path.expanduser("~/.dotnet/dotnet"))
CLI_DLL = Path(os.environ.get("ACP_OFFICE_CLI")
               or (ACP / "spike/dotnet/AcpScan.Cli/bin/Release/net10.0/AcpScan.Cli.dll"))
# Demo corpus folder (ADC / keyless mode). Overridden by ACP_DRIVE_FOLDER env var.
# In per-user token mode (GIS), the scanner searches the user's whole Drive.
_DEMO_FOLDER = os.environ.get("ACP_DRIVE_FOLDER") or "1W27ULZsstP7gYGzgKKBId0qEfNxeKn0_"
# Fan-out discovery cap (ADR 0007): each file is its own durable job, so the
# whole estate need not fit one box — bound only against a runaway listing.
FANOUT_MAX_FILES = int(os.environ.get("ACP_FANOUT_MAX_FILES", "50000"))
# ADR 0008 — batch fan-out. Files per scan_batch job (capped ≤200 so job payloads stay
# bounded); estates with ≥ THRESHOLD files auto-use the batch path. Both env-tunable.
SCAN_BATCH_SIZE = max(1, min(200, int(os.environ.get("ACP_SCAN_BATCH_SIZE", "50"))))
SCAN_BATCH_THRESHOLD = int(os.environ.get("ACP_SCAN_BATCH_THRESHOLD", "2000"))
# No more SCAN_TRACE_SPAN_CAP — file-centric tracing (lf.file_trace) gives every file its
# own trace, so there's no single big trace whose span count could make the Langfuse OSS
# detail view un-openable (the problem that constant used to guard against).
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

sys.path.insert(0, str(ACP / "scripts"))
from rubric import Rubric

OFFICE = (".docx", ".pptx", ".xlsx")
HTML_EXTS = (".html", ".htm")

# Google Workspace native types → (export MIME, file extension)
EXPORT_MAP = {
    "application/vnd.google-apps.document":     ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",  ".docx"),
    "application/vnd.google-apps.spreadsheet":  ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",        ".xlsx"),
    "application/vnd.google-apps.presentation": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
}

# All MIME types we can scan (uploaded files + Google Workspace natives)
_SCANNABLE_MIME = list(EXPORT_MAP.keys()) + [
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/html",
]

_DRIVE_MIME_Q = " or ".join(f"mimeType='{m}'" for m in _SCANNABLE_MIME)


def _noop(_):
    pass


def _safe_name(name: str) -> str:
    """Strip chars that are invalid on most filesystems."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)


def _drive_service(drive_token: str | None = None):
    """Drive client for THIS scan. A per-user token (from GIS 'Sign in with Google')
    scans that user's Drive; with no token it falls back to ADC (the demo identity)."""
    from googleapiclient.discovery import build
    if drive_token:
        from google.oauth2.credentials import Credentials
        # GIS tokens are short-lived and carry no refresh_token, so leave `expiry` None: a
        # credential without an expiry reports `expired` False and google-auth never tries to
        # refresh it. Drive returns 401 on its own if the token really expired.
        #
        # Setting `expiry = now + 1h` did the opposite of what its comment claimed. The hour is
        # measured from when this client is BUILT, not from when Google issued the token, so a
        # scan queued behind a backlog crossed it, google-auth called refresh(), and the job
        # died on "credentials do not contain the necessary fields need to refresh the access
        # token" — five retries deep. See worker.drive_session_expired.
        creds = Credentials(token=drive_token, scopes=SCOPES)
    else:
        import google.auth
        creds, _ = google.auth.default(scopes=SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _normalize(files: list[dict]) -> list[dict]:
    """Convert raw Drive API file objects to scan items.

    Uploaded files keep their name. Google Workspace files get the export
    extension appended so the Office/PDF engine sees the right format.
    """
    result = []
    seen: set[str] = set()
    seen_ids: set[str] = set()
    skipped = 0
    relisted = 0
    for f in files:
        # IDENTITY dedup comes first. Drive can hand the SAME file back more than once in a
        # single discovery: a file may have several parents (so a subtree BFS meets it twice),
        # corpora="allDrives" can surface it from My Drive and a Shared Drive, and paged
        # listings can overlap. Without this, the name-dedup below renames the second sighting
        # to "Report (1).pptx" — a phantom document that the UI then shows as "x2 copies",
        # inflates the file count, and gets downloaded and scanned a second time.
        # A Drive file id IS the document's identity; two parents do not make two documents.
        fid = f.get("id")
        if fid is not None:
            if fid in seen_ids:
                relisted += 1
                continue
            seen_ids.add(fid)
        mime = f.get("mimeType", "")
        raw_name = f["name"]
        if mime in EXPORT_MAP:
            export_ext = EXPORT_MAP[mime][1]
            name = _safe_name(raw_name) + export_ext
        else:
            ext = Path(raw_name).suffix.lower()
            # Accept the same set the local path + scan loop handle, including HTML
            # (was dropping .html/.htm uploaded to Drive as real text/html).
            if ext not in OFFICE + (".pdf",) + HTML_EXTS:
                skipped += 1
                continue
            name = _safe_name(raw_name)
        # Disambiguate GENUINELY DISTINCT files that share a name (Drive allows two different
        # file ids named the same; a filesystem wouldn't). Reaching here means the id is new,
        # so a " (N)" suffix always denotes a real second document — never a re-listing.
        unique = name
        n = 1
        while unique in seen:
            stem = Path(name).stem
            suffix = Path(name).suffix
            unique = f"{stem} ({n}){suffix}"
            n += 1
        seen.add(unique)
        # md5Checksum is absent for native Google Workspace files (Docs/Sheets/Slides
        # have no fixed byte representation — exported on each request) so it's only
        # ever present for real binary uploads, which is exactly the case checksum
        # dedup cares about.
        result.append({"name": unique, "id": f["id"], "checksum": f.get("md5Checksum"),
                       **({"mime": mime} if mime in EXPORT_MAP else {})})
    if skipped:
        # Not silent anymore: unsupported types (images, .txt/.csv, legacy .doc/.ppt/.xls,
        # video, …) are out of accessibility scope — say how many so 'scan complete' isn't
        # mistaken for 'everything was covered'.
        print(f"[scan] {skipped} file(s) skipped as unsupported for accessibility scanning "
              f"(only pdf/docx/pptx/xlsx/html are analysed)", flush=True)
    if relisted:
        print(f"[scan] {relisted} duplicate listing(s) of the same Drive file id collapsed "
              f"(multi-parent / shared-drive / paging overlap) — not extra documents", flush=True)
    return result


def _find_remediated_folder_id(svc) -> str | None:
    """Look up the configured Drive mirror folder (default 'Remediated') WITHOUT
    creating it (unlike handlers.ensure_remediated_folder) — a discovery-time
    exclusion check shouldn't spuriously create the folder for a user who's never
    remediated anything. Returns None if it doesn't exist yet."""
    import core
    name = core.store.get_drive_mirror_folder()
    safe = name.replace("\\", "\\\\").replace("'", "\\'")
    q = f"name='{safe}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    folders = svc.files().list(q=q, fields="files(id)", orderBy="createdTime",
                               pageSize=1, includeItemsFromAllDrives=True,
                               supportsAllDrives=True).execute(num_retries=5).get("files", [])
    return folders[0]["id"] if folders else None


def _list_drive_page_all(svc, q: str, max_files: int) -> tuple[list[dict], bool]:
    """One full paginated listing for `q`. Returns (raw files, hit_cap)."""
    files: list[dict] = []
    page_token = None
    while len(files) < max_files:
        resp = svc.files().list(
            q=q,
            fields=f"nextPageToken,files({provenance.DRIVE_FIELDS})",
            pageSize=200,
            # Newest first: when a large Drive exceeds the raw cap, the files a user most likely
            # just uploaded are the ones we most want to have listed before the cap bites.
            orderBy="modifiedTime desc",
            pageToken=page_token,
            corpora="allDrives",             # span My Drive + every Shared Drive
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
        ).execute(num_retries=5)             # backoff on 429/5xx instead of failing the file
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return files, bool(page_token)


def _flag_on(name: str) -> bool:
    """Is this env flag on? `"0"` and `"false"` mean OFF.

    `os.environ.get(name)` is a non-empty STRING for `ACP_DRIVE_DISCOVERY_DEBUG=0`, and every
    non-empty string is truthy — so setting the flag to 0 to turn the diagnostic OFF left it on.
    Found 2026-07-29: the live container had the flag at "0" and was still emitting
    `[scan] discovery DEBUG:` on every sweep, including the extra unfiltered Drive listing the
    gate exists to avoid. Matches the on/off vocabulary core.py already uses for ACP_REVIEW_MEMORY.
    """
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _debug_dump_account(svc, max_files: int = 60) -> None:
    """Log EVERY file Drive returns for this account, filtered only by trashed=false — so a file
    the scan missed because its MIME type isn't scannable (a legacy .doc, an .odt, an image),
    or because it belongs to another owner (shared-with-me), is visible in the log instead of
    silently absent. Gated behind ACP_DRIVE_DISCOVERY_DEBUG because it is an extra unfiltered
    listing; turn it on to answer 'why did the scan only see N files?' and off again after.
    A best-effort diagnostic: it must never break a scan."""
    try:
        scannable = set(_SCANNABLE_MIME) | {"application/vnd.google-apps.folder"}
        resp = svc.files().list(
            q="trashed=false", pageSize=max_files, orderBy="modifiedTime desc",
            fields="files(id,name,mimeType,owners(emailAddress))",
            corpora="allDrives", includeItemsFromAllDrives=True, supportsAllDrives=True,
        ).execute(num_retries=3)
        rows = resp.get("files", [])
        print(f"[scan] discovery DEBUG: account holds {len(rows)} recent non-trashed item(s) "
              f"(unfiltered, newest first):", flush=True)
        for f in rows:
            owner = (f.get("owners") or [{}])[0].get("emailAddress", "?")
            mark = "scannable" if f.get("mimeType") in scannable else "SKIPPED (type not scanned)"
            print(f"[scan] discovery DEBUG:   {f.get('name')!r} · {f.get('mimeType')} · "
                  f"owner={owner} · {mark}", flush=True)
    except Exception as e:  # noqa: BLE001 — a diagnostic must never fail the scan
        print(f"[scan] discovery DEBUG: unfiltered listing failed: {e}", flush=True)


def _is_scannable_mime(f: dict) -> bool:
    """Does this Drive file have a type we can assess? Applied in Python, deliberately."""
    return f.get("mimeType") in _SCANNABLE_MIME


def _search_drive(svc, max_files: int = 500, exclude_remediated: bool = False,
                  scope_out: dict | None = None) -> list[dict]:
    """Whole-Drive discovery — returns all scannable files regardless of folder.

    `scope_out`, when given, is filled in with WHAT THIS LISTING COVERED — see `_list`. The
    counts already printed below went only to stdout, so the file count was the one number that
    escaped to the UI and it arrived with no statement of its boundary.

    The type filter is applied HERE, in Python, not in the Drive query — and that is the whole
    point. A `mimeType='…'` clause is served by Drive's SEARCH INDEX, which lags badly behind a
    plain listing for freshly-uploaded files: proven live, an unfiltered `trashed=false` listing
    returned 60 documents while the same query with a mimeType filter returned 2, in the same
    second. A settle-retry cannot fix that — both passes hit the same stale index. So we ask
    Drive only for `trashed=false` (read from the live file store, so a just-uploaded file
    appears at once) and keep the scannable types ourselves.

    The remediated-folder exclusion clause is dropped for the same reason (`… in parents` is also
    index-served); provenance (is_acp_generated, a client-side check on file properties) already
    skips ACP's own output wherever it sits.

    The settle-retry (ACP_DRIVE_SETTLE_SECS>0) is kept as a small belt-and-suspenders for the
    residual lag in even the plain listing, re-listing and unioning by id until a pass adds
    nothing new.
    """
    if _flag_on("ACP_DRIVE_DISCOVERY_DEBUG"):
        _debug_dump_account(svc)

    q = "trashed=false"
    # Raw ceiling: we now page over ALL files, not just scannable ones, so on a large Drive the
    # scannable documents could sit behind many non-scannable items. Page generously past
    # max_files so scannable coverage holds, but stay bounded so a huge Drive can't run away.
    raw_cap = max(max_files * 5, 2500)
    settle_secs = float(os.environ.get("ACP_DRIVE_SETTLE_SECS", "0") or 0)
    settle_passes = int(os.environ.get("ACP_DRIVE_SETTLE_PASSES", "2") or 0)
    by_id: dict[str, dict] = {}      # union across settle passes, keyed by Drive file id
    raw_seen = 0
    hit_cap = False
    extra = 0
    while True:
        batch, cap = _list_drive_page_all(svc, q, raw_cap)
        hit_cap = cap
        raw_seen = max(raw_seen, len(batch))
        before = len(by_id)
        for f in batch:
            if _is_scannable_mime(f):     # the filter Drive's index was too stale to do
                by_id.setdefault(f["id"], f)
        added = len(by_id) - before
        # Stop: settle disabled, budget spent, or a follow-up pass found nothing new.
        if settle_secs <= 0 or extra >= settle_passes or (extra > 0 and added == 0):
            break
        extra += 1
        time.sleep(settle_secs)
    if extra:
        print(f"[scan] discovery settle: {extra} extra pass(es) over ~{extra * settle_secs:.0f}s "
              f"to let Drive's live listing settle", flush=True)

    listed = len(by_id)              # distinct SCANNABLE items, before provenance filtering
    files = list(by_id.values())
    skipped_acp = 0
    if exclude_remediated:
        # Provenance beats location: skip anything ACP itself wrote, wherever it sits.
        kept = [f for f in files if not provenance.is_acp_generated(f)]
        skipped_acp = len(files) - len(kept)
        files = kept
    if hit_cap:
        print(f"[scan] whole-Drive listing hit the {raw_cap}-item raw cap — not all files were "
              f"listed; raise ACP_FANOUT_MAX_FILES to cover the full estate", flush=True)
    result = _normalize(files[:max_files])
    if scope_out is not None:
        scope_out.update({"kind": "drive", "raw": raw_seen, "scannable": listed,
                          "skipped_acp": skipped_acp, "kept": len(result),
                          "truncated": bool(hit_cap or len(files) > max_files),
                          "cap": raw_cap})
    # An audit trail of what this scan chose to ingest, and what it refused. Without it the
    # only place a file count exists is the UI, and "why 2 files?" can't be answered offline.
    print(f"[scan] discovery (whole-Drive): {raw_seen} raw · {listed} scannable · "
          f"{skipped_acp} skipped as ACP-generated output · {len(result)} kept", flush=True)
    for it in result:
        print(f"[scan] discovery:   kept {it['name']!r}", flush=True)
    return result


def _search_folder(svc, folder_id: str, max_files: int = 1000, exclude_remediated: bool = False,
                   scope_out: dict | None = None) -> list[dict]:
    """BFS over a folder subtree — returns all scannable files in the folder AND
    every nested subfolder. Bounded by max_files (newest folders may be skipped
    once the cap is hit) and a cycle guard, so a huge tree can't run unbounded.

    exclude_remediated: don't recurse into the configured Drive mirror folder
    (default 'Remediated', admin-configurable) — cheaper than tracking each file's
    parent-folder lineage, and sufficient since ACP only ever writes remediated
    output to that one well-known folder (handlers.ensure_remediated_folder).

    `scope_out`, when given, is filled in with WHAT THIS LISTING COVERED — see `_list`. This is
    the path that reported "1 document" on 2026-07-30 while the estate the user had in mind held
    eight: the folder held exactly one file, the listing was right, and NOTHING said the other
    seven were in a part of the Drive this scan never looked at."""
    remediated_folder_name = None
    if exclude_remediated:
        import core
        remediated_folder_name = core.store.get_drive_mirror_folder()
    queue = [folder_id]
    seen_folders: set[str] = set()
    raw: list[dict] = []
    listed = 0            # raw non-folder items Drive returned
    skipped_acp = 0       # ACP's own output, skipped by provenance
    skipped_mirror = 0    # subfolders skipped by name (pre-provenance copies live here)
    while queue and len(raw) < max_files:
        fid = queue.pop(0)
        if fid in seen_folders:
            continue
        seen_folders.add(fid)
        page_token = None
        while True:
            resp = svc.files().list(
                q=f"'{fid}' in parents and trashed=false",
                fields=f"nextPageToken,files({provenance.DRIVE_FIELDS})",
                pageSize=200,
                # Newest first, matching _list_drive_page_all. Without it Drive returns its own
                # default order, so when the max_files cap bites the files dropped are arbitrary
                # — and a file uploaded five minutes ago is as likely to be cut as one from last
                # year. That is the "I added files and the rescan didn't see them" symptom, and
                # it only appears on subtrees big enough to hit the cap, which is exactly where
                # nobody notices it. Discovery itself never caches; this is the other way a new
                # upload can go missing.
                orderBy="modifiedTime desc",
                pageToken=page_token,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
            ).execute(num_retries=5)
            for f in resp.get("files", []):
                if f["mimeType"] == "application/vnd.google-apps.folder":
                    # Folder-name exclusion is RETAINED, not replaced: copies written before
                    # the provenance stamp shipped carry no stamp, and this still skips them.
                    if exclude_remediated and f["name"] == remediated_folder_name:
                        skipped_mirror += 1
                        continue
                    queue.append(f["id"])
                    continue
                listed += 1
                if exclude_remediated and provenance.is_acp_generated(f):
                    skipped_acp += 1  # ACP's own output — never a source document
                else:
                    raw.append(f)
            page_token = resp.get("nextPageToken")
            if not page_token or len(raw) >= max_files:
                break
    truncated = bool(len(raw) >= max_files and (queue or page_token))
    if truncated:
        print(f"[scan] folder listing hit the {max_files}-file cap — not all files were "
              f"scanned; raise ACP_FANOUT_MAX_FILES to cover the full subtree", flush=True)
    result = _normalize(raw[:max_files])
    if scope_out is not None:
        scope_out.update({"kind": "folder", "folder_id": folder_id,
                          "folders_walked": len(seen_folders), "listed": listed,
                          "skipped_acp": skipped_acp, "skipped_mirror": skipped_mirror,
                          "kept": len(result), "truncated": truncated, "cap": max_files})
    print(f"[scan] discovery (folder subtree): {len(seen_folders)} folder(s) walked · "
          f"{listed} listed · {skipped_acp} skipped as ACP-generated output · "
          f"{skipped_mirror} mirror folder(s) skipped · {len(result)} scannable", flush=True)
    return result


def _sp_list(token: str, max_files: int = 200) -> list[dict]:
    """List scannable files from OneDrive personal via MS Graph search.

    Identity dedup, same rule as _normalize's for Drive: a drive-item id IS the document,
    and Graph's paged /search can return the same item on more than one page. Without this,
    _dedupe_names (which every source funnels through) would rename the repeat to
    "Deck (1).pptx" — a phantom document that inflates the file count, gets downloaded and
    analysed a second time, and surfaces in the UI as "x2 copies". Each source is responsible
    for yielding unique IDENTITIES; _dedupe_names only disambiguates genuine NAME collisions
    between different items."""
    import httpx
    exts = {".docx", ".pptx", ".xlsx", ".pdf", ".html", ".htm"}
    hdrs = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    files: list[dict] = []
    seen_ids: set[str] = set()
    relisted = 0
    url = "https://graph.microsoft.com/v1.0/me/drive/root/search(q='')?$select=id,name,file&$top=200"
    while url and len(files) < max_files:
        r = httpx.get(url, headers=hdrs, timeout=30, follow_redirects=True)
        r.raise_for_status()
        data = r.json()
        for item in data.get("value", []):
            if "file" not in item:
                continue
            item_id = item.get("id")
            if item_id is not None:
                if item_id in seen_ids:
                    relisted += 1
                    continue
                seen_ids.add(item_id)
            name = item.get("name", "")
            if Path(name).suffix.lower() in exts:
                files.append({"name": _safe_name(name), "id": item_id, "sp": True})
        url = data.get("@odata.nextLink")
    if relisted:
        print(f"[scan] {relisted} duplicate listing(s) of the same OneDrive item id collapsed "
              f"(paged /search overlap) — not extra documents", flush=True)
    return files[:max_files]


def _sp_download(token: str, item: dict, dest: Path) -> None:
    """Download a file from OneDrive via MS Graph /content redirect."""
    import httpx
    hdrs = {"Authorization": f"Bearer {token}"}
    url = f"https://graph.microsoft.com/v1.0/me/drive/items/{item['id']}/content"
    r = httpx.get(url, headers=hdrs, timeout=120, follow_redirects=True)
    r.raise_for_status()
    (dest / item["name"]).write_bytes(r.content)


def _dedupe_names(items: list[dict]) -> list[dict]:
    """Disambiguate same-named items from one listing — e.g. two Drive files literally
    named "Clinical-Proposal-92.pptx" with different file ids (Drive allows this; a
    filesystem wouldn't). Every downstream consumer keys off item["name"] alone
    (_download's local temp path, the in-memory per-file dict, and file_records'
    PRIMARY KEY (scan_id, file)), so without this, the second same-named item silently
    clobbers the first at each of those layers — one of the two is never analysed,
    scored, or stored, with no error or trace. Appends " (N)" before the extension on
    the 2nd+ occurrence, mirroring Drive's own web-UI convention on a manual duplicate
    upload — the frontend's "Group duplicate uploads" toggle already strips exactly
    this pattern back off for display, so it composes for free."""
    seen: dict[str, int] = {}
    out = []
    for it in items:
        name = it["name"]
        n = seen.get(name, 0)
        seen[name] = n + 1
        if n == 0:
            out.append(it)
        else:
            stem, dot, ext = name.rpartition(".")
            disambiguated = f"{stem or name} ({n}){dot}{ext}" if dot else f"{name} ({n})"
            out.append({**it, "name": disambiguated})
    return out


def _list(source: str, svc=None, folder: str | None = None, sp_token: str | None = None,
          max_files: int | None = None, exclude_remediated: bool = False,
          scope_out: dict | None = None) -> list[dict]:
    """List the source. `scope_out`, when given, is filled in with WHAT WAS COVERED.

    A file count on its own is not a fact about an estate — it is a fact about a boundary the
    caller chose, and the two are only the same number when the boundary is "everything". On
    2026-07-30 a folder-scoped scan of a one-file folder reported "1 document" six seconds after
    a whole-Drive scan of the SAME account reported 8, and the product presented both as the
    size of the estate. Neither listing was wrong; the screen was, because it printed the
    number and dropped the boundary.

    So discovery now hands its boundary out with the count, `scope_out` is persisted on the scan
    (store.init_scan_run / save_scan), and the UI renders one from the other. Shape:

      {"kind": "folder"|"drive"|"local"|"sharepoint", "kept": int, "truncated": bool, ...}

    `truncated` is the strictly different claim "we hit a cap and there are files we did not
    list" — a folder scan that covered its folder completely is NOT truncated, however small the
    answer. `folder_name` is resolved here (one metadata read) so the UI can say which folder
    rather than showing a Drive id nobody recognises.
    """
    # The monolithic scan keeps conservative caps (one box's disk holds every file);
    # the fan-out path (ADR 0007) passes a high cap since each file is its own job.
    if source == "local":
        # ACP_LOCAL_CORPUS: point local scans at a different directory — the test
        # suite uses it to scan the frozen oracle corpus (test-corpus/oracle/)
        # instead of the demo estate, which changes with the demo's needs.
        corpus = Path(os.environ.get("ACP_LOCAL_CORPUS") or (ACP / "test-corpus/files"))
        result = [{"name": p.name, "path": str(p)} for p in sorted(corpus.glob("*"))
                   if p.suffix.lower() in OFFICE + (".pdf",) + HTML_EXTS]
        if scope_out is not None:
            scope_out.update({"kind": "local", "path": str(corpus), "kept": len(result),
                              "truncated": False})
    elif source == "sharepoint":
        result = _sp_list(sp_token, max_files or 200)
        if scope_out is not None:
            scope_out.update({"kind": "sharepoint", "kept": len(result),
                              "truncated": len(result) >= (max_files or 200)})
    elif folder and folder != "root":
        # Specific folder: recursive BFS
        result = _search_folder(svc, folder, max_files or 1000,
                                exclude_remediated=exclude_remediated, scope_out=scope_out)
        if scope_out is not None:
            scope_out["folder_name"] = _folder_name(svc, folder)
    elif folder == "root" or folder is None:
        # No specific folder chosen: search the whole Drive
        result = _search_drive(svc, max_files or 500, exclude_remediated=exclude_remediated,
                               scope_out=scope_out)
    else:
        # ADC/demo mode with a pinned folder. Requests provenance.DRIVE_FIELDS and honours
        # exclude_remediated like the two GIS paths above: this branch asked for a narrower
        # field set, so `properties` never came back and `is_acp_generated` was structurally
        # incapable of firing — ACP's own output would be re-ingested as a source document.
        resp = svc.files().list(q=f"'{_DEMO_FOLDER}' in parents and trashed=false",
                                fields=f"files({provenance.DRIVE_FIELDS})", pageSize=200,
                                orderBy="name", includeItemsFromAllDrives=True,
                                supportsAllDrives=True).execute(num_retries=5)
        batch = resp.get("files", [])
        if exclude_remediated:
            batch = [f for f in batch if not provenance.is_acp_generated(f)]
        result = _normalize(batch)
        if scope_out is not None:
            scope_out.update({"kind": "folder", "folder_id": _DEMO_FOLDER,
                              "folder_name": _folder_name(svc, _DEMO_FOLDER),
                              "folders_walked": 1, "listed": len(batch), "kept": len(result),
                              "truncated": False})
    # `kept` is set by each branch above, BEFORE this pass, and stays correct because
    # _dedupe_names renames colliding names without ever dropping an item — so the count the UI
    # states beside the scope is the number of rows the UI will show. That is an invariant of
    # _dedupe_names rather than an obvious truth, so it is pinned by test
    # (test_discovery_scope_reported.py::test_kept_counts_rows_the_ui_will_show_…) instead of
    # re-derived here.
    return _dedupe_names(result)


def _folder_name(svc, folder_id: str) -> str | None:
    """The folder's display name, or None. Best-effort and deliberately non-fatal: this exists
    only so the UI can name the boundary, and a scan must never fail because a label lookup
    did."""
    try:
        meta = svc.files().get(fileId=folder_id, fields="name",
                               supportsAllDrives=True).execute(num_retries=3)
        return meta.get("name") or None
    except Exception:
        return None


def cache_source_bytes(tmp: Path, name: str, scan_id: str, user: str | None) -> None:
    """ADR 0020 stage 1: stash a just-downloaded file's original bytes in the blob source
    cache ({owner}/{scan_id}/{filename} in the 'sources' container) so a later Assess phase
    can re-read them without a second Drive/SharePoint download — the 'open each file once'
    property, kept across the phase boundary. Strictly best-effort and non-blocking: a cache
    failure (or no blob configured) must never fail or slow a scan, and NOTHING reads from
    the cache yet — this stage only proves the bytes round-trip before anything depends on
    them (ADR 0020 rollout §1)."""
    try:
        import blob
        if not blob.enabled():
            return
        blob.upload_source(user, scan_id, name, (tmp / name).read_bytes())
    except Exception:
        pass


def _download(item: dict, dest: Path, svc=None, sp_token: str | None = None) -> None:
    out = dest / item["name"]
    if "path" in item:
        out.write_bytes(Path(item["path"]).read_bytes())
        return
    if item.get("sp"):
        _sp_download(sp_token, item, dest)
        return
    from googleapiclient.http import MediaIoBaseDownload
    from googleapiclient.errors import HttpError
    buf = io.BytesIO()
    # Per-file memory guard: workers hold the whole file in RAM (+a copy) on a 1GiB
    # container, so a few large files in parallel can OOM the worker. Abort early past
    # the cap and let the file bucket as an error instead of taking the process down.
    max_bytes = int(os.environ.get("ACP_MAX_DOWNLOAD_MB", "150")) * 1024 * 1024
    if "mime" in item:
        # Google Workspace native — export as OOXML
        export_mime = EXPORT_MAP[item["mime"]][0]
        req = svc.files().export_media(fileId=item["id"], mimeType=export_mime)
    else:
        req = svc.files().get_media(fileId=item["id"], supportsAllDrives=True)
    dl = MediaIoBaseDownload(buf, req)
    done = False
    try:
        while not done:
            _, done = dl.next_chunk(num_retries=5)
            if buf.tell() > max_bytes:
                raise ValueError(f"file exceeds the {max_bytes // (1024 * 1024)}MB download "
                                 f"cap — skipped to protect worker memory (raise ACP_MAX_DOWNLOAD_MB)")
    except HttpError as e:
        # Google-native exports are capped at 10MB by Drive; surface it clearly rather
        # than as an opaque 403 so the file records a meaningful error.
        if getattr(e, "resp", None) is not None and e.resp.status == 403 and "exportSizeLimit" in str(e):
            raise ValueError("Google Doc/Sheet/Slide exceeds Drive's 10MB export limit — "
                             "can't export to Office format for analysis") from e
        raise
    out.write_bytes(buf.getvalue())


def _loc_fields(loc) -> tuple[int | None, str | None]:
    """Normalise an engine IssueLocation (pydantic model, PDF path) or the .NET CLI's JSON
    dict (Office path) into (page, location_text).

    page — the 1-based page OR slide the finding sits on; to a reviewer they're the same
    idea ("go here"). None when the analyser could not attribute one: we never invent a page.
    location_text — the analyser's structured hint for the object ('pptx:slide:0', an XPath).
    """
    if not loc:
        return None, None
    if isinstance(loc, dict):
        page = loc.get("pageNumber") or loc.get("slideNumber")
        text = loc.get("description") or loc.get("xPath")
    else:
        page = getattr(loc, "page_number", None) or getattr(loc, "slide_number", None)
        text = getattr(loc, "description", None) or getattr(loc, "x_path", None)
    return (page if isinstance(page, int) and page > 0 else None), (text or None)


def _issue_with_loc(base: dict, loc) -> dict:
    """Attach page/location to a finding only when the analyser actually reported them —
    absent keys mean 'unknown', never a fabricated page-1 default."""
    page, text = _loc_fields(loc)
    if page is not None:
        base["page"] = page
    if text:
        base["location"] = text
    return base


def _analyse_pdf(path: Path) -> dict:
    import asyncio
    sys.path.insert(0, str(WP))
    try:
        from analysers.pdf_analyser import PdfAnalyser
        from models.manifest import AnalysisJob, FileType
    except ModuleNotFoundError as exc:
        # worker-python is not vendored — it is loaded at runtime from ACP_PDF_ENGINE. Bare, this
        # import raised mid-scan, and the resulting ModuleNotFoundError read as "the scan broke on
        # this file" when the real state is "a required engine was never installed on this host".
        # Every PDF in the estate then failed one at a time with the same opaque error.
        #
        # This does NOT invent a result: the file is reported as errored and un-analysed, exactly
        # as any other engine failure would be, so nothing is scored as passing. What changes is
        # that the message names the cause and where to fix it, and /readyz reports the same
        # condition BEFORE a scan starts. Vendoring the engine the way ADR 0012 vendored the
        # Office analysers is what actually closes this.
        return {"succeeded": False, "issues": [], "errors": [{
            "message": (f"PDF engine unavailable: {exc}. worker-python is loaded at runtime from "
                        f"ACP_PDF_ENGINE (currently {WP}); this host has no importable analyser "
                        f"there, so no PDF can be assessed. See /readyz."),
            "rule": None}]}
    job = AnalysisJob(job_id=uuid.uuid4(), batch_run_id=uuid.uuid4(), file_id=uuid.uuid4(),
                      file_path=str(path), file_type=FileType.PDF, queue="pdf",
                      enqueued_at=datetime.now(timezone.utc), department_id=uuid.uuid4(), disabled_rule_ids=[])
    try:
        r = asyncio.run(PdfAnalyser().analyse(path, job))
        issues = [_issue_with_loc({"ruleId": i.rule_id, "wcag": i.wcag_criterion.name,
                                   "severity": i.severity.name}, getattr(i, "location", None))
                  for i in r.issues]
        issues = _pdf_correct_title(path, issues)
        return {"succeeded": r.succeeded,
                "issues": issues,
                "errors": [{"message": e.message, "rule": e.rule_id} for e in r.errors]}
    except Exception as e:
        return {"succeeded": False, "issues": [], "errors": [{"message": f"{type(e).__name__}: {e}", "rule": None}]}


def _pdf_correct_title(path: Path, issues: list[dict]) -> list[dict]:
    """The pdf.document-title rule (WCAG 2.4.2) reads /Title via pikepdf, whose docinfo
    READS are nondeterministic once libxml2 is loaded in a long-lived worker (office/HTML
    remediation use lxml) — so it can false-flag a PDF that actually declares a title.
    Re-read the title with pypdf (pure-Python, reliable) and drop the false finding.
    Mirror of why remediate_pdf writes metadata with pypdf."""
    if not any(i.get("ruleId") == "pdf.document-title" for i in issues):
        return issues
    try:
        from pypdf import PdfReader
        title = str((PdfReader(str(path)).metadata or {}).get("/Title") or "").strip()
    except Exception:
        return issues
    if title:
        return [i for i in issues if i.get("ruleId") != "pdf.document-title"]
    return issues


def _office_err(e: dict) -> dict:
    code = e.get("Code", "") if isinstance(e, dict) else ""
    rule = code[len("RULE_EXECUTION_ERROR_"):] if code.startswith("RULE_EXECUTION_ERROR_") else None
    msg = (e.get("message") or e.get("Message") or str(e)) if isinstance(e, dict) else str(e)
    return {"message": msg, "rule": rule}


def _cli_exit_reason(returncode: int) -> str:
    """Readable cause for a non-zero CLI exit. A NEGATIVE code is a signal, not a status."""
    if returncode < 0:
        try:
            name = signal.Signals(-returncode).name
        except ValueError:
            name = f"signal {-returncode}"
        return f"was killed by {name}"
    return f"exited with status {returncode}"


def _clip_diag(text: str, head: int = 800, tail: int = 400) -> str:
    """Keep BOTH ends of a diagnostic, because the two ends say different things.

    This used to be `stderr[-400:]`, and that single decision is why this crash went two
    flaggings without a diagnosis. A .NET failure writes the part you need FIRST —

        Unhandled exception. System.ArgumentException: <the actual cause> (Parameter 'name')
           at DocumentFormat.OpenXml.<...>
           at AcpScan.Analysers.XlsxAnalyser.AnalyseAsync(...)
           ... 30+ more frames

    — so a tail-only window is guaranteed to hold nothing but stack frames once the trace is
    longer than the window, which it always is. Production's log line read

        [scan] office CLI exited -6: ne)

    where `ne)` is the last three characters of something like `(Parameter 'name')`: the
    exception TYPE and MESSAGE, the only fields that identify the bug, fell off the front.
    Eight such lines were captured over 12h across both analysers and both container apps,
    and every one of them was unactionable for the same reason.

    The head is the larger window because that is where the answer is; the tail is kept
    because for a SIGABRT the runtime's own last words (a glibc `free(): invalid pointer`,
    an `Aborted`) arrive after the managed trace, and those identify a native fault that no
    managed exception header would mention.
    """
    text = (text or "").strip()
    if len(text) <= head + tail:
        return text
    return f"{text[:head]}\n  … {len(text) - head - tail} chars elided …\n{text[-tail:]}"


def _analyse_office(dest: Path) -> dict:
    out = dest / "_o.json"
    # DOTNET_ROOT only when that install actually exists, and never clobbering one the
    # environment already set (actions/setup-dotnet and the Docker image both set it
    # correctly). Forcing ~/.dotnet unconditionally pointed the muxer at a missing root
    # anywhere the SDK came from a package manager or CI action.
    _root = os.path.expanduser("~/.dotnet")
    env = {**os.environ, "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1"}
    if "DOTNET_ROOT" not in env and os.path.isdir(_root):
        env["DOTNET_ROOT"] = _root
    # Bounded: a hung dotnet process would otherwise stall the worker thread forever —
    # and since the fan-out scan finalizes only when every file reports in, one hang
    # froze the whole scan.
    #
    # An abnormal exit does NOT mean res stays {}. This comment used to claim it did, and
    # that assumption is what let a crash certify a document: AcpScan.Cli writes its JSON
    # in ONE File.WriteAllText after the whole loop (Program.cs), so a CLI that finishes
    # the sweep, writes complete output and THEN aborts during runtime shutdown leaves a
    # perfectly parseable file behind. Production hit exactly that on 2026-07-30 — both
    # .xlsx files logged `office CLI exited -6` (SIGABRT) and still scored 90-odd and
    # certified, because the only trace of the abort was this print.
    #
    # The "EMPTY stderr" this comment used to report was wrong, and wrong in a way worth
    # keeping a note about: stderr was NOT empty. A later sweep of ContainerAppConsoleLogs_CL
    # found 8 stack traces in 12h, on BOTH analysers (XlsxAnalyser 5, DocxAnalyser 3) and BOTH
    # container apps — so this is neither xlsx-specific nor one bad file. What made stderr
    # look empty was the old `[-400:]` tail clip eating the whole line; see _clip_diag.
    #
    # So the exit status is now part of the result. Three outcomes, all honest:
    #   * abnormal exit + parseable output -> every file the CLI reported gains a
    #     process-level error, which the rubric turns into `uncertain`: findings kept,
    #     score marked an upper bound, `compliant` forced False (scripts/rubric.py).
    #   * output missing or unparseable    -> res stays {} and the files bucket as
    #     engine-error (unanalysable) via the caller's "no engine result" substitution.
    #   * clean exit                       -> unchanged.
    timeout_s = int(os.environ.get("ACP_OFFICE_CLI_TIMEOUT", "180"))
    aborted: str | None = None
    try:
        proc = subprocess.run([DOTNET, str(CLI_DLL), str(dest), str(out)],
                              capture_output=True, text=True, env=env, timeout=timeout_s)
        if proc.returncode != 0:
            aborted = _cli_exit_reason(proc.returncode)
            # stdout as well as stderr, and both clipped from BOTH ends. A signal death is not
            # a managed exception exit, so there is no promise about which stream carries the
            # cause: .NET writes an unhandled exception to stderr, but the runtime's own
            # shutdown-time aborts and `Fatal error.` lines have been seen on stdout, and a
            # glibc abort writes straight to fd 2 underneath both. #109 recorded EMPTY stderr
            # for this same crash — if that was accurate rather than an artefact of the old
            # tail-only clip, whatever the process did say went to stdout and was never read.
            # Printing an empty stream would just be noise, so each is included only if present.
            streams = [(n, _clip_diag(s)) for n, s in (("stderr", proc.stderr),
                                                       ("stdout", proc.stdout)) if (s or "").strip()]
            detail = "\n".join(f"  {n}: {s}" for n, s in streams) or "  <both streams empty>"
            print(f"[scan] office CLI {aborted} ({proc.returncode}) on {dest}:\n{detail}",
                  flush=True)
    except subprocess.TimeoutExpired:
        # A timeout is not automatically engine-error either, for the same reason: the CLI may
        # have written its output and then hung on the way out. Whichever it did, the outcome is
        # logged below once we know, rather than guessed at here.
        aborted = f"timed out after {timeout_s}s"
        print(f"[scan] office CLI timed out after {timeout_s}s on {dest}", flush=True)
    res = {}
    if out.exists():
        # A truncated write is the other half of the same crash, and json.loads raises on it.
        # That exception used to escape _analyse_office uncaught: run_scan wraps its body in a
        # bare `finally`, so one aborted CLI failed the ENTIRE scan rather than the files it
        # analysed. Unparseable output is missing output — bucket it as engine-error.
        try:
            items = json.loads(out.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
            print(f"[scan] office CLI output at {out} is unreadable ({type(e).__name__}: {e}) — "
                  f"files will be recorded as engine-error", flush=True)
            return {}
        for item in items:
            res[item["file"]] = {
                "succeeded": item["succeeded"],
                # Keep the engine's human-readable per-finding title as `detail` — it's
                # the only evidence of WHY a finding fired ("Slide is missing a title",
                # "Reading order may not match visual order"). Dropping it left the UI
                # and traces showing a bare rule id with no explanation.
                "issues": [_issue_with_loc({"ruleId": i["ruleId"], "wcag": i["wcag"],
                                            "severity": i["severity"],
                                            **({"detail": i["title"]} if i.get("title") else {})},
                                           i.get("location"))
                           for i in item.get("issues", [])],
                "errors": [_office_err(e) for e in item.get("errors", [])],
            }
    if aborted:
        # `rule: None` deliberately — a process-level abort is not attributable to one rule, and
        # store.py's per-rule attribution already skips errors without a rule id. It still counts
        # toward skipped_rules, which is what makes the score read as an upper bound in the UI.
        #
        # succeeded is left as the CLI reported it: flipping it to False would score these files
        # `error` / "n/a (could not analyse)", throwing away findings that ARE real (production's
        # two files carried 2 and 5) and describing a run that produced findings as one that
        # produced nothing. `uncertain` is the truthful reading — we have findings, we cannot
        # claim they are the complete set — and it blocks certification just as firmly.
        for entry in res.values():
            entry["errors"] = [*entry["errors"],
                               {"message": f"office analyser {aborted} before exiting cleanly; "
                                           f"findings may be an incomplete set", "rule": None}]
        # Say what the abort actually cost, rather than predicting it before parsing: files the
        # CLI reported go uncertain, everything else in this batch falls to engine-error.
        print(f"[scan] office CLI {aborted} — {len(res)} reported file(s) recorded as uncertain "
              f"(score is an upper bound, not certifiable)", flush=True)
    return res


_VAGUE_LINK_TEXT = frozenset({"click here", "here", "read more", "more", "link", "this", "click", "learn more", "details"})

# ── 1.3.1 — text visually styled as a heading but left as body text ───────────
# The html mirror of office_structure's DOCX_PSEUDO_HEADING, filed under the SAME criterion.
# A <p>/<div> set large and bold but never marked up as a heading announces "this starts a
# section" through presentation alone, so it is absent from the outline assistive tech
# navigates by — that is 1.3.1 Info and Relationships.
#
# It is NOT 2.4.6, which is where frontend/src/rules/wcag-2-4-6.js used to file it: 2.4.6
# asks whether headings that EXIST describe their topic, and this element is not a heading
# at all yet. html and docx disagreed on the taxonomy for the one identical signal; filing
# both under 1.3.1 is what makes a cross-format report add up.
#
# The predicate is SHARED with the remediator (api/remediate.py imports it) so the fix
# promotes exactly what this flags and the re-scan verifiably clears — the same lock-step
# requirement office_structure documents, for the same reason: the fix auto-applies, so a
# false positive silently restyles real body text as a heading.
_PSEUDO_HEADING_MIN_PX = 18
_PSEUDO_HEADING_MAX_CHARS = 50
_FONT_SIZE_PX = re.compile(r"font-size:\s*(\d+(?:\.\d+)?)\s*px", re.I)
_FONT_WEIGHT_BOLD = re.compile(r"font-weight:\s*(?:bold|[6-9]00)\b", re.I)


def html_pseudo_headings(root) -> list:
    """<p>/<div> elements that read as a heading but are not marked up as one.

    Detection is the frontend module's original heuristic — a childless <p>/<div> whose
    inline style is at least 18px AND bold, holding short non-sentence text. Deliberately
    unchanged in sensitivity: refiling the criterion is one question, and how eagerly to
    promote body text is another, so this move does not quietly loosen the trigger.

    The one addition is office_structure.looks_like_heading_furniture, which the docx and
    PDF heading scans already share. "Big and bold" describes a cover-page wordmark, a
    headline figure and a pull quote just as well as a section title, and the fix writes
    without review — so html now rejects the same furniture the other formats do instead of
    promoting "$4.2B" to an <h2>.
    """
    try:
        import office_structure as _off_mod
        _furniture = _off_mod.looks_like_heading_furniture
    except Exception:                       # office deps absent — fall back to no filter
        _furniture = lambda _t: False       # noqa: E731
    out = []
    for el in root.iter("p", "div"):
        if len(el):                         # leaf text only, as the frontend module had it
            continue
        text = (el.text_content() or "").strip()
        if not text or len(text) > _PSEUDO_HEADING_MAX_CHARS or text[-1] in ".?!":
            continue
        style = el.get("style") or ""
        size = _FONT_SIZE_PX.search(style)
        if not size or float(size.group(1)) < _PSEUDO_HEADING_MIN_PX:
            continue
        if not _FONT_WEIGHT_BOLD.search(style):
            continue
        if _furniture(text):
            continue
        out.append(el)
    return out

# Phase 1 HTML-check helpers — patterns mirror frontend/src/rules/ modules.
_INPUT_PURPOSE = re.compile(
    r"e-?mail|(^|[\s_-])(tel|phone|mobile)([\s_-]|$)|(first|given)[-_ ]?name|(last|family|sur)[-_ ]?name"
    r"|full[-_ ]?name|(^|[\s_-])(zip|postal)([-_ ]?code)?([\s_-]|$)|(^|[\s_-])country([\s_-]|$)"
    r"|(^|[\s_-])(city|town)([\s_-]|$)|street|address|(^|[\s_-])(org|organization|company)([\s_-]|$)"
    r"|birth[-_ ]?(date|day)|(^|[\s_-])dob([\s_-]|$)", re.I)
_ORIENTATION_LOCK = re.compile(
    r"@media[^{]*\(\s*orientation\s*:\s*(?:portrait|landscape)\s*\)[^{]*\{[^@]*?display\s*:\s*none", re.I)
_INLINE_COLOR = re.compile(r"(?:^|[^-])color:\s*#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")


def _luma(h: str) -> float:
    """Relative luma of a hex color (0..1); >0.45 ≈ fails the 7:1 enhanced ratio on white."""
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def _analyse_html(path: Path) -> dict:
    try:
        from lxml import html as lx
        root = lx.fromstring(path.read_bytes(), base_url=str(path))
    except Exception as e:
        return {"succeeded": False, "issues": [], "errors": [{"message": f"{type(e).__name__}: {e}", "rule": None}]}

    issues: list[dict] = []

    # 2.4.2 Page Titled — missing or empty <title>
    titles = root.findall(".//title")
    if not titles or not (titles[0].text or "").strip():
        issues.append({"ruleId": "HTML_MISSING_TITLE", "wcag": "2.4.2 Page Titled", "severity": "SERIOUS"})

    # 3.1.1 Language of Page — missing lang on <html>
    # lxml.html.fromstring returns the root element (html or body depending on fragment)
    html_el = root if root.tag == "html" else root.find(".//html") or root
    lang = html_el.get("lang") or html_el.get("{http://www.w3.org/XML/1998/namespace}lang")
    if not lang:
        issues.append({"ruleId": "HTML_MISSING_LANG", "wcag": "3.1.1 Language of Page", "severity": "SERIOUS"})

    # 1.1.1 Non-text Content — <img> without alt attribute (decorative: role=presentation is ok)
    for img in root.iter("img"):
        if img.get("alt") is None and img.get("role", "") not in ("presentation", "none"):
            issues.append({"ruleId": "HTML_IMG_MISSING_ALT", "wcag": "1.1.1 Non-text Content", "severity": "CRITICAL"})

    # 2.4.4 Link Purpose (In Context) — empty or vague <a> text
    for a in root.iter("a"):
        text = (a.text_content() or "").strip()
        aria = (a.get("aria-label") or a.get("title") or "").strip()
        if not text and not aria:
            issues.append({"ruleId": "HTML_EMPTY_LINK", "wcag": "2.4.4 Link Purpose (In Context)", "severity": "SERIOUS"})
        elif text.lower() in _VAGUE_LINK_TEXT and not aria:
            issues.append({"ruleId": "HTML_VAGUE_LINK", "wcag": "2.4.4 Link Purpose (In Context)", "severity": "MODERATE"})

    # 2.4.9 Link Purpose (Link Only) — text alone must convey purpose, with no
    # credit for surrounding context. Its genuine failure case: identical link
    # text pointing at different real destinations (2.4.4 tolerates this — context
    # sorts it out — 2.4.9 doesn't). href="#" is excluded — a common JS-hook
    # placeholder, not a real distinct destination. Vague text (2.4.4's list)
    # fails "text alone" regardless of context, so it's flagged here too.
    link_groups: dict[str, set[str]] = {}
    for a in root.iter("a"):
        href = a.get("href")
        n = (a.get("aria-label") or a.text_content() or "").strip().lower()
        if not href or href == "#" or not n:
            continue
        link_groups.setdefault(n, set()).add(href)
    ambiguous_hrefs = {h for hrefs in link_groups.values() if len(hrefs) > 1 for h in hrefs}
    for a in root.iter("a"):
        href = a.get("href")
        text = (a.text_content() or "").strip()
        aria = (a.get("aria-label") or "").strip()
        vague = text.lower() in _VAGUE_LINK_TEXT and not aria
        duplicated = bool(href) and href != "#" and href in ambiguous_hrefs
        if vague or duplicated:
            issues.append({"ruleId": "HTML_LINK_PURPOSE_AMBIGUOUS", "wcag": "2.4.9 Link Purpose (Link Only)", "severity": "MODERATE"})

    # 2.4.6 Headings and Labels — skipped heading levels (e.g. h1 → h3). EVERY gap is reported,
    # not just the first: _fix_heading_skip closes them all in one pass, so stopping at the first
    # understated the work and left a page looking one edit away from clean when it was several.
    # `prev_level` advances to the level actually in the document (not the clamped prev+1), which
    # is what keeps h1→h3→h4 a single finding — the outline has one gap there, and the h3→h4 step
    # is well-formed. Mirrors office_structure.docx_checks' DOCX_HEADING_SKIP.
    HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
    prev_level = 0
    ordinal = 0
    for el in root.iter():
        if el.tag in HEADING_TAGS:
            level = int(el.tag[1])
            ordinal += 1
            if prev_level > 0 and level > prev_level + 1:
                # The ordinal keeps two identical gaps (two separate h1→h3s) distinguishable.
                issues.append({"ruleId": "HTML_HEADING_SKIP", "wcag": "2.4.6 Headings and Labels",
                               "severity": "MODERATE",
                               "detail": f"Heading {ordinal}: level jumps from h{prev_level} to h{level} "
                                         f"(should step to h{prev_level + 1})"})
            prev_level = level

    # 1.3.2 Meaningful Sequence — CSS that visually reorders content away from source order
    # (flex 'order', reversed flex direction/flow), or an image-replacement technique (a large
    # negative text-indent hiding real text behind a background image). A screen reader follows
    # source order, so any of these can make the spoken order differ from the visual one.
    _style_blob = " ".join(
        [el.get("style", "") for el in root.iter() if el.get("style")]
        + [s.text_content() for s in root.iter("style") if s.text_content()]
    ).lower()
    if re.search(r"order\s*:\s*-?[1-9]", _style_blob) or re.search(r"flex-(?:direction|flow)\s*:[^;]*reverse", _style_blob):
        issues.append({"ruleId": "HTML_VISUAL_REORDER", "wcag": "1.3.2 Meaningful Sequence", "severity": "MODERATE"})

    # 1.4.5 Images of Text — an <img> whose file name signals it carries text, or a CSS
    # image-replacement technique (large negative text-indent). Conservative: only these
    # unambiguous signals fire, so an ordinary photo/diagram is never mistaken for text.
    _TEXT_IMG_NAME = re.compile(
        r"\b(heading|headline|banner|title|quote|wordmark|slogan|tagline|typography|text)\b", re.I)
    _imgtext = any(_TEXT_IMG_NAME.search((img.get("src") or "").rsplit("/", 1)[-1]) for img in root.iter("img"))
    if not _imgtext and re.search(r"text-indent\s*:\s*-\s*(?:9{3,}|\d{4,})", _style_blob):
        _imgtext = True
    if _imgtext:
        issues.append({"ruleId": "HTML_IMAGE_OF_TEXT", "wcag": "1.4.5 Images of Text", "severity": "MODERATE"})

    # 4.1.2 Name, Role, Value — <input> without an associated label
    labelled_ids: set[str] = set()
    for label in root.iter("label"):
        for_attr = label.get("for")
        if for_attr:
            labelled_ids.add(for_attr)
    SKIP_INPUT_TYPES = {"hidden", "submit", "button", "image", "reset"}
    for inp in root.iter("input"):
        if (inp.get("type") or "text").lower() in SKIP_INPUT_TYPES:
            continue
        if not (inp.get("aria-label") or inp.get("aria-labelledby") or inp.get("title")):
            if inp.get("id", "") not in labelled_ids:
                issues.append({"ruleId": "HTML_INPUT_NO_LABEL", "wcag": "4.1.2 Name, Role, Value", "severity": "CRITICAL"})

    # ── Phase 1 additions — predicates mirror frontend/src/rules/wcag-*.js so a
    # file remediated client-side re-scans clean here.

    # 1.4.2 Audio Control — autoplaying media with no way to stop it
    for m in root.iter("audio", "video"):
        if m.get("autoplay") is not None and m.get("controls") is None:
            issues.append({"ruleId": "HTML_AUTOPLAY_MEDIA", "wcag": "1.4.2 Audio Control", "severity": "SERIOUS"})

    # 1.3.5 Identify Input Purpose — recognizable personal-data inputs without autocomplete
    for inp in root.iter("input"):
        if inp.get("autocomplete"):
            continue
        hint = f'{inp.get("name") or ""} {inp.get("id") or ""} {inp.get("placeholder") or ""}'
        if (inp.get("type") or "").lower() in ("email", "tel") or _INPUT_PURPOSE.search(hint):
            issues.append({"ruleId": "HTML_INPUT_NO_AUTOCOMPLETE", "wcag": "1.3.5 Identify Input Purpose", "severity": "MODERATE"})

    # 2.5.3 Label in Name — accessible name omits the visible label text
    for el in list(root.iter("a")) + list(root.iter("button")):
        aria = re.sub(r"\s+", " ", el.get("aria-label") or "").strip().lower()
        if not aria:
            continue
        visible = re.sub(r"\s+", " ", el.text_content() or "").strip().lower()[:80]
        if visible and visible not in aria:
            issues.append({"ruleId": "HTML_LABEL_NOT_IN_NAME", "wcag": "2.5.3 Label in Name", "severity": "SERIOUS"})

    # 2.4.1 Bypass Blocks — repeated chrome (nav/header) with no skip mechanism
    roles = {el.get("role") for el in root.iter() if callable(getattr(el, "get", None)) and el.get("role")}
    has_chrome = (root.find(".//nav") is not None or root.find(".//header") is not None
                  or roles & {"navigation", "banner"})
    if has_chrome:
        has_main = root.find(".//main") is not None or "main" in roles
        ids = {el.get("id") for el in root.iter() if callable(getattr(el, "get", None)) and el.get("id")}
        has_skip = any((a.get("href") or "").startswith("#") and (a.get("href") or "")[1:] in ids
                       for a in root.iter("a"))
        if not (has_main or has_skip):
            issues.append({"ruleId": "HTML_NO_SKIP_LINK", "wcag": "2.4.1 Bypass Blocks", "severity": "MODERATE"})

    # 3.3.2 Labels or Instructions — required field with no guidance at all
    for tag in ("input", "select", "textarea"):
        for inp in root.iter(tag):
            if inp.get("required") is None:
                continue
            if (inp.get("aria-label") or inp.get("aria-labelledby") or inp.get("aria-describedby")
                    or inp.get("title") or inp.get("placeholder")):
                continue
            if next(inp.iterancestors("label"), None) is not None or inp.get("id", "") in labelled_ids:
                continue
            issues.append({"ruleId": "HTML_REQUIRED_NO_GUIDANCE", "wcag": "3.3.2 Labels or Instructions", "severity": "SERIOUS"})

    # 1.3.4 Orientation — content hidden in one orientation ("rotate your device" lock)
    for st in root.iter("style"):
        if _ORIENTATION_LOCK.search(st.text_content() or ""):
            issues.append({"ruleId": "HTML_ORIENTATION_LOCK", "wcag": "1.3.4 Orientation", "severity": "MODERATE"})

    # 1.4.6 Contrast (Enhanced, AAA) — inline colors that pass 4.5:1 but miss 7:1
    for el in root.iter():
        style = el.get("style") if callable(getattr(el, "get", None)) else None
        if not style:
            continue
        m = _INLINE_COLOR.search(style)
        if m and _luma(m.group(1)) > 0.45:
            issues.append({"ruleId": "HTML_LOW_CONTRAST_AAA", "wcag": "1.4.6 Contrast (Enhanced)", "severity": "MODERATE"})

    # ── Phase 2 — media alternatives + target size (detect + route to HITL) ──

    # 1.2.2 Captions — <video> with no captions/subtitles track
    # 1.2.3 Audio Description — <video> with no descriptions track and no transcript
    for v in root.iter("video"):
        kinds = {(t.get("kind") or "").lower() for t in v.iter("track")}
        if not (kinds & {"captions", "subtitles"}):
            issues.append({"ruleId": "HTML_VIDEO_NO_CAPTIONS", "wcag": "1.2.2 Captions (Prerecorded)", "severity": "SERIOUS"})
        if "descriptions" not in kinds and not v.get("aria-describedby"):
            issues.append({"ruleId": "HTML_VIDEO_NO_DESCRIPTION", "wcag": "1.2.3 Audio Description or Media Alternative", "severity": "SERIOUS"})

    # 1.2.1 Audio-only — <audio> with no linked/naming transcript
    for a in root.iter("audio"):
        if not (a.get("aria-describedby") or re.search(r"transcript", a.get("aria-label") or "", re.I)):
            issues.append({"ruleId": "HTML_AUDIO_NO_TRANSCRIPT", "wcag": "1.2.1 Audio-only & Video-only (Prerecorded)", "severity": "SERIOUS"})

    # 2.5.8 Target Size — interactive element with an inline px dimension < 24
    for el in root.iter():
        tag = el.tag if isinstance(el.tag, str) else ""
        role = (el.get("role") or "") if callable(getattr(el, "get", None)) else ""
        interactive = (tag in ("a", "button", "input", "select", "textarea")
                       or role == "button" or el.get("onclick") is not None)
        if not interactive:
            continue
        if tag == "a" and not el.get("href"):
            continue
        style = el.get("style") or ""
        dims = [float(m) for m in re.findall(r"(?:^|;)\s*(?:width|height)\s*:\s*([\d.]+)px", style, re.I)]
        if any(d < 24 for d in dims):
            issues.append({"ruleId": "HTML_TARGET_TOO_SMALL", "wcag": "2.5.8 Target Size (Minimum)", "severity": "SERIOUS"})

    # ── Phase 4 — legacy rule modules with no prior backend mirror ──
    # These SCs have a frontend rule module (used for the client-side remediation
    # preview) and read as 'Shipped (demo)' in the catalog, but a real server-side
    # scan never actually evaluated them — every persisted scan silently showed
    # PASS for every HTML file, regardless of content. Ported here to close that
    # false-PASS gap; predicates mirror frontend/src/rules/wcag-*.js exactly.

    # 1.3.1 Info and Relationships — form control with no accessible name at all
    # (broader than 4.1.2's check above: also credits implicit <label>wrapping).
    SELF_NAMED_TYPES = {"hidden", "button", "submit", "reset", "image"}
    for inp in root.iter("input", "select", "textarea"):
        if inp.tag == "input" and (inp.get("type") or "text").lower() in SELF_NAMED_TYPES:
            continue
        if inp.get("aria-label") or inp.get("aria-labelledby"):
            continue
        if next(inp.iterancestors("label"), None) is not None:
            continue
        if inp.get("id", "") in labelled_ids:
            continue
        issues.append({"ruleId": "HTML_FORM_CONTROL_NO_NAME", "wcag": "1.3.1 Info and Relationships", "severity": "CRITICAL"})

    # 1.3.1 — text styled to look like a heading but never marked up as one. One finding per
    # element (docx emits one per document; html can carry many sections on one page, and the
    # fix promotes each, so under-reporting here would understate the work the way the 2.4.6
    # `break` did). See html_pseudo_headings for why this is 1.3.1 and not 2.4.6.
    for el in html_pseudo_headings(root):
        issues.append({"ruleId": "HTML_PSEUDO_HEADING", "wcag": "1.3.1 Info and Relationships",
                       "severity": "MODERATE",
                       "detail": f"Text styled as a heading but left as <{el.tag}>: "
                                 f"{(el.text_content() or '').strip()[:60]}"})

    # 1.4.1 Use of Color — link styled by inline color alone, no underline
    for a in root.iter("a"):
        style = a.get("style") or ""
        if not style:
            continue
        if re.search(r"(?:^|;)\s*color\s*:", style) and not re.search(r"text-decoration\s*:[^;]*underline", style, re.I):
            issues.append({"ruleId": "HTML_LINK_COLOR_ONLY", "wcag": "1.4.1 Use of Color", "severity": "SERIOUS"})

    # 1.4.3 Contrast (Minimum, AA) — inline color likely below 4.5:1 (luma > 0.62).
    # Same _INLINE_COLOR/_luma helpers as 1.4.6 above; AA's threshold is looser.
    for el in root.iter():
        style = el.get("style") if callable(getattr(el, "get", None)) else None
        if not style:
            continue
        m = _INLINE_COLOR.search(style)
        if m and _luma(m.group(1)) > 0.62:
            issues.append({"ruleId": "HTML_LOW_CONTRAST_AA", "wcag": "1.4.3 Contrast (Minimum)", "severity": "SERIOUS"})

    # 1.4.4 Resize Text — viewport meta blocks pinch-zoom / text resize
    for meta in root.iter("meta"):
        if (meta.get("name") or "").lower() != "viewport":
            continue
        content = meta.get("content") or ""
        if re.search(r"user-scalable\s*=\s*(no|0)|maximum-scale\s*=\s*(0|1)(\.0+)?\b", content, re.I):
            issues.append({"ruleId": "HTML_VIEWPORT_BLOCKS_ZOOM", "wcag": "1.4.4 Resize Text", "severity": "SERIOUS"})

    # 1.4.10 Reflow — a real page (has meta/link/style) with no responsive viewport
    has_head_content = any(next(root.iter(t), None) is not None for t in ("meta", "link", "style"))
    has_viewport = any((m.get("name") or "").lower() == "viewport" for m in root.iter("meta"))
    if has_head_content and not has_viewport:
        issues.append({"ruleId": "HTML_NO_VIEWPORT_REFLOW", "wcag": "1.4.10 Reflow", "severity": "SERIOUS"})

    # 1.4.11 Non-text Contrast (AA) — inline border color likely below 3:1
    for el in root.iter():
        style = el.get("style") if callable(getattr(el, "get", None)) else None
        if not style:
            continue
        m = re.search(r"border(?:-[a-z]+)?:[^;]*?#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b", style, re.I)
        if m and _luma(m.group(1)) > 0.62:
            issues.append({"ruleId": "HTML_BORDER_LOW_CONTRAST", "wcag": "1.4.11 Non-text Contrast", "severity": "MODERATE"})

    # 1.4.12 Text Spacing — fixed-pixel line-height blocks the user's spacing override
    for el in root.iter():
        style = el.get("style") if callable(getattr(el, "get", None)) else None
        if style and re.search(r"line-height:\s*\d+px", style, re.I):
            issues.append({"ruleId": "HTML_FIXED_LINE_HEIGHT", "wcag": "1.4.12 Text Spacing", "severity": "MODERATE"})

    # 2.4.3 Focus Order — positive tabindex overrides natural reading order
    for el in root.iter():
        ti = el.get("tabindex") if callable(getattr(el, "get", None)) else None
        if ti is None:
            continue
        try:
            if int(ti) > 0:
                issues.append({"ruleId": "HTML_POSITIVE_TABINDEX", "wcag": "2.4.3 Focus Order", "severity": "SERIOUS"})
        except ValueError:
            continue

    # 2.4.7 Focus Visible — outline suppressed (CSS or inline) with interactive content present
    css_blocks = "\n".join((s.text_content() or "") for s in root.iter("style"))
    inline_suppressed = any(
        re.search(r"outline:\s*(none|0)\b", el.get("style") or "", re.I)
        for el in root.iter() if callable(getattr(el, "get", None)) and el.get("style")
    )
    outline_suppressed = bool(re.search(r"outline:\s*(none|0)\b", css_blocks, re.I)) or inline_suppressed
    has_interactive = next(root.iter("a", "button", "input", "select", "textarea"), None) is not None
    if outline_suppressed and has_interactive:
        issues.append({"ruleId": "HTML_FOCUS_OUTLINE_SUPPRESSED", "wcag": "2.4.7 Focus Visible", "severity": "SERIOUS"})

    # 3.1.4 Abbreviations — known abbreviation with no <abbr title> expansion.
    # ABBR mirrors frontend/src/rules/utils.js's ABBR dict (a small editorial
    # glossary) — kept in sync by hand, same posture as RULE_CATALOG vs PLAIN_NAMES.
    ABBR = {
        "WCAG": "Web Content Accessibility Guidelines", "ADA": "Americans with Disabilities Act",
        "PDF": "Portable Document Format", "PPO": "Preferred Provider Organization",
        "HDHP": "High-Deductible Health Plan", "FSA": "Flexible Spending Account",
        "HSA": "Health Savings Account", "FAQ": "Frequently Asked Questions",
        "PII": "Personally Identifiable Information", "UTSW": "UT Southwestern", "HR": "Human Resources",
    }
    ABBR_RE = re.compile(r"\b(" + "|".join(ABBR) + r")\b")
    SKIP_ANCESTOR_TAGS = {"abbr", "script", "style", "title"}
    for el in root.iter():
        tag = el.tag if isinstance(el.tag, str) else ""
        if tag in SKIP_ANCESTOR_TAGS or any(a.tag in SKIP_ANCESTOR_TAGS for a in el.iterancestors()):
            continue
        for text in (el.text, el.tail):
            if text and ABBR_RE.search(text):
                issues.append({"ruleId": "HTML_UNEXPANDED_ABBR", "wcag": "3.1.4 Abbreviations", "severity": "MINOR"})

    return {"succeeded": True, "issues": issues, "errors": []}


def detect_acp_stamp(path: Path, ext: str) -> str | None:
    """Detect a prior Mova.io ACP remediation stamp in a file (the provenance written
    by the remediators); return the remediation date, 'yes' if undated, else None.
    Lets a scan flag already-remediated documents."""
    try:
        if ext in OFFICE:
            with zipfile.ZipFile(path) as z:
                if "docProps/custom.xml" in z.namelist():
                    x = z.read("docProps/custom.xml").decode("utf-8", "replace")
                    if "Mova.io ACP" in x:
                        m = re.search(r"Remediation Date.*?<vt:lpwstr>([^<]+)</vt:lpwstr>", x, re.S)
                        return m.group(1).strip() if m else "yes"
        elif ext == ".pdf":
            import pikepdf
            with pikepdf.open(str(path)) as pdf:
                rb = pdf.docinfo.get("/RemediatedBy")
                if rb is not None and "Mova.io ACP" in str(rb):
                    d = pdf.docinfo.get("/RemediationDate")
                    return str(d) if d is not None else "yes"
        elif ext in HTML_EXTS:
            txt = path.read_text("utf-8", errors="replace")[:4000]
            if "Mova.io ACP" in txt and ("generator" in txt or "Remediated by" in txt):
                m = re.search(r"remediated (\d{4}-\d\d-\d\d)", txt)
                return m.group(1) if m else "yes"
    except Exception:
        pass
    return None


def _file_extent(path: Path, ext: str) -> dict:
    """Cheap physical metadata for the file drawer: size always; page count for
    PDF (pikepdf — already a scan dependency), slide/sheet counts read straight
    from the OOXML zip directory. Never raises — metadata must never fail a scan."""
    out: dict = {}
    try:
        out["size_kb"] = max(1, round(path.stat().st_size / 1024))
    except Exception:
        return out
    try:
        if ext == ".pdf":
            import pikepdf
            with pikepdf.open(str(path)) as pdf:
                out["pages"] = len(pdf.pages)
        elif ext == ".pptx":
            with zipfile.ZipFile(path) as z:
                out["pages"] = sum(1 for n in z.namelist()
                                   if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)) or None
        elif ext == ".xlsx":
            with zipfile.ZipFile(path) as z:
                out["sheets"] = sum(1 for n in z.namelist()
                                    if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)) or None
    except Exception:
        pass
    return {k: v for k, v in out.items() if v is not None}


# Reading order is a low-confidence heuristic the partner engine emits PER SLIDE
# ("Reading order may not match visual order"). Left as-is, N per-slide SERIOUS
# findings zero a deck's score on a suspicion. Collapse them into a single MODERATE
# advisory — one penalty, still visible and routed to human review to verify —
# rather than N confirmed serious failures. Remediation reorders every slide, so a
# remediated file still re-scans clean (zero reading-order findings).
_READING_ORDER_RULES = {"PPTX-ORDER-001"}


def _collapse_reading_order(issues: list[dict]) -> list[dict]:
    ro = [i for i in issues if i.get("ruleId") in _READING_ORDER_RULES]
    if len(ro) <= 1:
        for i in ro:
            i["severity"] = "MODERATE"
        return issues
    kept = [i for i in issues if i.get("ruleId") not in _READING_ORDER_RULES]
    adv = dict(ro[0])
    adv["severity"] = "MODERATE"
    adv["detail"] = (f"Reading order may not match visual order on {len(ro)} slides"
                     " — a heuristic flag; verify the reading order (routed to review).")
    return kept + [adv]


# The first-party 1.1.1 image detectors (formats/<fmt>/detectors/non_text_content.py). They
# exist so the IN-PROCESS re-scan can observe 1.1.1 — proposals.verify_residual_scs runs
# first-party checks only, and without them the write-back lane credited approved alt text on a
# criterion nothing could report. They are a floor, not a second opinion.
_FIRST_PARTY_ALT_RULES = frozenset({
    "DOCX_IMAGE_NO_ALT", "PPTX_IMAGE_NO_ALT", "XLSX_IMAGE_NO_ALT", "PDF_FIGURE_NO_ALT",
})
# The criterion, in its normalised form. Compared through store._extract_sc rather than by
# string prefix because the wcag field arrives in several spellings — bare, SC_-prefixed with
# underscores, or with the criterion name appended — and a prefix test would match only one.
# (Those spellings are named without quoting them: tests/test_rules_index.py scans this module's
# raw source for rule-id-shaped literals, and a quoted SC_ form reads as one even in a comment.)
_ALT_SC = "1.1.1"


def _collapse_duplicate_alt(issues: list[dict]) -> list[dict]:
    """Drop the first-party 1.1.1 findings when the partner engine already reported 1.1.1.

    Both detectors answer the same question about the same images, so when both run every
    undescribed image is counted TWICE — inflating the finding count on every scan and raising
    two review rows for one picture. The engine is the richer detector, so it wins where it ran;
    the first-party check is what keeps the criterion observable where it did not.

    Scoped to 1.1.1 and to these rule ids deliberately: this must never suppress a first-party
    finding the engine did not also make.
    """
    from store import _extract_sc          # the one SC normaliser: '1.1.1', 'SC_1_1_1', …
    engine_alt = any(_extract_sc(str(i.get("wcag", ""))) == _ALT_SC
                     and i.get("ruleId") not in _FIRST_PARTY_ALT_RULES
                     for i in issues)
    if not engine_alt:
        return issues
    return [i for i in issues if i.get("ruleId") not in _FIRST_PARTY_ALT_RULES]


def _scoped_for_scoring(issues: list[dict], filename: str) -> list[dict]:
    """The findings a SCORE may be computed from, for one file — the operator scope applied.

    Both `rb.assess` call sites go through here so the single-file path and the batch path cannot
    diverge on what a score counts (they already diverged once on which of them filtered disabled
    rules). Returns `issues` unchanged when no scope is set, so an unscoped deployment scores
    exactly as it did before this existed.

    The Store is consulted for the scope rather than `in_scope`'s storeless fallback, which cannot
    see the `scan_scope` setting.

    NOT wrapped in a bare try/except. The obvious defensive shape here — swallow everything and
    return the unfiltered list — is how this feature was broken in the first place: a gate that
    fails open and says nothing is indistinguishable from a gate that was never wired up, and the
    only symptom is numbers that look plausible. `core` and `store` are imported inside the
    function (the module-level idiom here, to avoid a circular import at load), so a resolution
    failure is a real defect and should surface as one.
    """
    import core
    from store import active_scope, filter_issues_to_scope, _file_format
    scope = active_scope(core.store)
    if not scope:
        return issues
    return filter_issues_to_scope(issues, _file_format(filename), scope)


def analyse_and_assess(tmp: Path, name: str, *, detect_pii: bool = False):
    """Analyse + rubric-assess ONE already-downloaded file (fan-out path, ADR 0007).
    `tmp` is a directory containing `name`. Returns (assessed_file_dict, pii_info),
    or (None, None) for an unsupported extension. Engines catch their own errors and
    return an error result rather than raising."""
    rb = Rubric.load_active(ACP / "config")
    ext = Path(name).suffix.lower()
    # Per-file progress logging (the fan-out path was silent — no way to tell a slow file from a
    # stuck one in the container logs). The heavy steps are already bounded: the .NET office CLI
    # has ACP_OFFICE_CLI_TIMEOUT (180s) and OCR caps at ACP_OCR_MAX_IMAGES (30) + downscales, so a
    # single image-heavy deck can't hang its worker indefinitely.
    _t0 = time.monotonic()
    print(f"[scan] analysing {name} ({ext or '?'}) …", flush=True)
    if ext == ".pdf":
        raw = {"engine": "python/pdf", **_analyse_pdf(tmp / name)}
    elif ext in OFFICE:
        office = _analyse_office(tmp)                 # .NET CLI over the one-file dir
        raw = {"engine": ".net/office",
               **office.get(name, {"succeeded": False, "issues": [], "errors": ["no engine result"]})}
    elif ext in HTML_EXTS:
        raw = {"engine": "python/html", **_analyse_html(tmp / name)}
    else:
        return None, None
    # 1.4.5 / 1.4.9 Images of Text — OCR embedded images; self-gates + never raises.
    try:
        import ocr as _ocr_mod
        raw["issues"] = (list(raw.get("issues", []))
                          + _ocr_mod.images_of_text(tmp / name, ext)
                          + _ocr_mod.images_of_text_no_exception(tmp / name, ext))
    except Exception:
        pass
    # 1.3.3 Sensory Characteristics + 3.1.2 Language of Parts — text-content checks.
    try:
        import pii as _pii_mod2
        import textchecks as _txt_mod
        raw["issues"] = list(raw.get("issues", [])) + _txt_mod.content_findings(_pii_mod2.extract_text(tmp / name))
    except Exception:
        pass
    # 2.4.6 / 2.4.9 / 1.4.3 / 1.4.6 — first-party OOXML/PDF structural checks
    # (docx/pptx headings + link-purpose, PDF contrast); partner engine doesn't
    # reach these for these formats. Self-contained; never raises.
    try:
        import office_structure as _off_mod
        raw["issues"] = list(raw.get("issues", [])) + _off_mod.checks_for(tmp / name, ext)
    except Exception:
        pass
    raw["issues"] = _collapse_duplicate_alt(_collapse_reading_order(raw["issues"]))
    raw["issues"] = [i for i in raw["issues"] if i["ruleId"] not in rb.disabled]
    raw["errors"] = [e for e in raw["errors"]
                     if (e.get("rule") if isinstance(e, dict) else None) not in rb.disabled]
    # Score over the IN-SCOPE findings, but keep every finding on the record. `Rubric.assess`
    # computes `100 - sum(penalty(severity))` over whatever it is handed and knows nothing about
    # scope, so scoring the full list gave a scoped scan unscoped scores — a document with no
    # in-scope findings beside a penalised score, which is the contradiction the scope gate exists
    # to prevent. `raw["issues"]` is passed on untouched, so re-scoping needs no re-scan.
    # A no-op when no scope is set.
    assessed = rb.assess(raw["succeeded"], _scoped_for_scoring(raw["issues"], name),
                         raw["errors"])
    fdict = {"file": name, "engine": raw["engine"], **assessed, "issues": raw["issues"],
             "acp_stamped": detect_acp_stamp(tmp / name, ext),
             **_file_extent(tmp / name, ext)}
    # ADR 0020 stage 2 — Discover-side inventory classification (cheap container peek, no
    # rule engine). Carried on the file result so the document upsert can persist it;
    # additive, never affects findings, never raises.
    try:
        import classify as _cls
        fdict["classify"] = _cls.classify(tmp / name, ext)
    except Exception:
        pass
    pinfo = None
    if detect_pii:
        import pii as _pii_mod
        pinfo = _pii_mod.detect_file(tmp / name)
    print(f"[scan] {name}: {len(raw.get('issues', []))} finding(s) in {time.monotonic() - _t0:.1f}s", flush=True)
    return fdict, pinfo


def run_scan(source: str = "local", progress=_noop, drive_token: str | None = None,
             folder: str | None = None, sp_token: str | None = None,
             ai_enabled: bool = True, scan_id: str | None = None,
             user: str | None = None, detect_pii: bool = False,
             exclude_remediated: bool = False) -> dict:
    from store import RULE_CATALOG, _extract_sc  # import here to avoid circular at module load
    rb = Rubric.load_active(ACP / "config")
    started = datetime.now(timezone.utc).isoformat()
    scan_id = scan_id or uuid.uuid4().hex[:12]
    tmp = Path(tempfile.mkdtemp(prefix="acp-api-scan-"))
    # Per-user token: default to whole-Drive search. ADC/demo: pinned demo folder.
    effective_folder = folder if folder else ("root" if drive_token else None)
    try:
        progress({"phase": "connecting", "files_found": 0, "files_done": 0, "current": None})
        svc = None if source in ("local", "sharepoint") else _drive_service(drive_token)
        scope: dict = {}
        items = _list(source, svc, folder=effective_folder, sp_token=sp_token,
                     exclude_remediated=exclude_remediated, scope_out=scope)
        n = len(items)
        progress({"phase": "discovering", "files_found": n, "files_done": 0, "current": None})

        for i, it in enumerate(items):
            progress({"phase": "reading", "files_found": n, "files_done": i, "current": it["name"]})
            _download(it, tmp, svc, sp_token=sp_token)
            cache_source_bytes(tmp, it["name"], scan_id, user)   # ADR 0020 §1 — best-effort

        office = _analyse_office(tmp)

        import pii as _pii_mod  # sensitive-data detection dimension (ADR 0006)
        import ocr as _ocr_mod  # 1.4.5 images-of-text OCR detection
        import textchecks as _txt_mod  # 1.3.3 sensory + 3.1.2 language-of-parts
        import office_structure as _off_mod  # docx/pptx headings+links, PDF contrast
        pii_by_file: dict[str, dict] = {}
        raw: dict[str, dict] = {}

        # Analyse each file + detect PII concurrently. Each call builds a fresh
        # analyser (no shared state) and reads only its own temp file, so the work
        # parallelises safely; pikepdf/lxml release the GIL. Langfuse spans are then
        # emitted sequentially from the main thread (one trace, no concurrent writes).
        # Opt-out (detect_pii=False) skips PII text extraction — faster on PDF estates.
        def _analyse_one(it):
            name, ext = it["name"], Path(it["name"]).suffix.lower()
            if ext == ".pdf":
                r = {"engine": "python/pdf", **_analyse_pdf(tmp / name)}
            elif ext in OFFICE:
                r = {"engine": ".net/office",
                     **office.get(name, {"succeeded": False, "issues": [], "errors": ["no engine result"]})}
            elif ext in HTML_EXTS:
                r = {"engine": "python/html", **_analyse_html(tmp / name)}
            else:
                return None
            # 1.4.5 / 1.4.9 Images of Text — OCR embedded images; self-gates + never raises.
            try:
                r["issues"] = (list(r.get("issues", []))
                                + _ocr_mod.images_of_text(tmp / name, ext)
                                + _ocr_mod.images_of_text_no_exception(tmp / name, ext))
            except Exception:
                pass
            # 1.3.3 Sensory Characteristics + 3.1.2 Language of Parts — text-content checks.
            try:
                r["issues"] = list(r.get("issues", [])) + _txt_mod.content_findings(_pii_mod.extract_text(tmp / name))
            except Exception:
                pass
            # 2.4.6 / 2.4.9 / 1.4.3 / 1.4.6 — first-party OOXML/PDF structural checks.
            try:
                r["issues"] = list(r.get("issues", [])) + _off_mod.checks_for(tmp / name, ext)
            except Exception:
                pass
            r["issues"] = _collapse_duplicate_alt(_collapse_reading_order(r["issues"]))
            try:                                          # ADR 0020 stage 2 — inventory peek
                import classify as _cls
                r["classify"] = _cls.classify(tmp / name, ext)
            except Exception:
                pass
            pinfo = _pii_mod.detect_file(tmp / name) if detect_pii else None
            return (name, r, pinfo)

        progress({"phase": "analysing", "files_found": n, "files_done": 0, "current": None})
        # as_completed, not map: `map` yields nothing until the whole batch finishes, so the
        # analysing phase — the long one — reported "0 documents" for its entire duration and
        # the UI looked stalled. Report each document as it lands. Order is not load-bearing:
        # `raw`/`assessed` are keyed by filename and `aggregate` sums over values.
        analysed = []
        with _cf.ThreadPoolExecutor(max_workers=_SCAN_WORKERS) as _ex:
            _futs = [_ex.submit(_analyse_one, it) for it in items]
            for _done_n, _fut in enumerate(_cf.as_completed(_futs), start=1):
                _res = _fut.result()
                if _res is not None:
                    analysed.append(_res)
                progress({"phase": "analysing", "files_found": n, "files_done": _done_n,
                          "current": _res[0] if _res else None})

        for done_i, (name, r, pinfo) in enumerate(analysed):
            # files_done stays at n through scoring: every document has been analysed by now,
            # and scoring is a fast post-pass over results already in memory. Reporting the
            # scoring index here would make the counter fall from n back to 0 — the UI read as
            # "0 documents" while the Score stage was lit, which is what it did before.
            progress({"phase": "scoring", "files_found": n, "files_done": n, "current": name})
            raw[name] = r
            engine = r["engine"]
            pii_total = 0
            if detect_pii and pinfo is not None:
                pii_by_file[name] = pinfo
                pii_total = pinfo.get("total", 0)
            # File-centric tracing: each file gets its OWN Langfuse trace (Discover here;
            # Assess/Remediate spans land on this same trace later, when those phases run),
            # grouped into a session keyed by scan_id. Always emitted — unlike the old
            # deep-scan-only gate — so every file has a trace to open from FileDrawer
            # regardless of whether the deep scan ran; the PII sub-span stays conditional.
            ftrace = _lf_mod.file_trace(scan_id, name, user=user)
            dspan = _lf_mod.discover_span(ftrace, engine)
            if detect_pii and pii_total:
                _lf_mod.pii_span(dspan, pinfo, filename=name)
            dspan.end(output={"engine": engine, "sensitive_data": pii_total})

        progress({"phase": "scoring", "files_found": n, "files_done": n, "current": None})
        for r in raw.values():
            r["issues"] = [i for i in r["issues"] if i["ruleId"] not in rb.disabled]
            r["errors"] = [e for e in r["errors"] if (e.get("rule") if isinstance(e, dict) else None) not in rb.disabled]
        # Scored over the in-scope findings; `r["issues"]` stays whole on the record. Same helper
        # as the single-file path above, so the two cannot disagree about what a score counts.
        assessed = {k: rb.assess(r["succeeded"], _scoped_for_scoring(r["issues"], k), r["errors"])
                    for k, r in raw.items()}
        summary = rb.aggregate(assessed)
        _lf_mod.flush()

        # Build name → Drive file id map so write-back can reference the original.
        drive_id_map = {it["name"]: it.get("id") for it in items}

        return {
            "_scan_id": scan_id,   # hint to save_scan so it reuses the same ID → trace joins
            "rubric": {"name": rb.name, "version": rb.version, "hash": rb.hash},
            "summary": summary,
            "started_at": started,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "scope": scope,           # WHAT this scan covered — never just the count (see _list)
            "owner": user,            # per-user isolation: who ran this scan

            "files": [{"file": k, "engine": raw[k]["engine"], **assessed[k], "issues": raw[k]["issues"],
                       "drive_file_id": drive_id_map.get(k), "pii": pii_by_file.get(k),
                       "acp_stamped": detect_acp_stamp(tmp / k, Path(k).suffix.lower()),
                       "classify": raw[k].get("classify"),   # ADR 0020 stage 2 — inventory peek
                       **_file_extent(tmp / k, Path(k).suffix.lower())}
                      for k in sorted(raw)],
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # ephemeral: documents never retained
