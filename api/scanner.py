"""Reusable scan core: source -> engines -> rubric -> report dict.

Emits progress via a callback (phase / files_found / files_done / current) so the
control plane can stream live activity. Ephemeral working copies are deleted when the
scan finishes (the "documents never retained" guarantee).
"""
from __future__ import annotations
import concurrent.futures as _cf
import io, json, os, re, shutil, subprocess, sys, tempfile, uuid, zipfile
from datetime import datetime, timezone
from pathlib import Path
import lf as _lf_mod

# Per-file analysis is CPU/IO bound and independent; run it across a small thread
# pool. pikepdf/lxml release the GIL and each analyser is built fresh per call.
_SCAN_WORKERS = min(8, (os.cpu_count() or 2) * 2)

ACP = Path(__file__).resolve().parent.parent
# Engine + corpus locations default to the local dev layout but are env-overridable
# so the same code runs inside the deploy container (paths set in the Dockerfile).
WP = Path(os.environ.get("ACP_PDF_ENGINE") or os.path.expanduser("~/projects/_review-digital-accessibility/worker-python"))
DOTNET = os.environ.get("ACP_DOTNET") or os.path.expanduser("~/.dotnet/dotnet")
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
        import datetime as _dt
        from google.oauth2.credentials import Credentials
        creds = Credentials(token=drive_token, scopes=SCOPES)
        # GIS tokens are short-lived and carry no refresh_token. Set an expiry so
        # the client library never tries to refresh; Drive returns 401 on its own
        # if the token actually expired. NOTE: google-auth stores expiry as a
        # NAIVE UTC datetime and compares it against a naive utcnow() — an aware
        # value raises "can't compare offset-naive and offset-aware datetimes".
        creds.expiry = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None) + _dt.timedelta(hours=1)
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
    for f in files:
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
                continue
            name = _safe_name(raw_name)
        # Deduplicate: Drive can have same-name files in different folders
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
                               pageSize=1).execute().get("files", [])
    return folders[0]["id"] if folders else None


def _search_drive(svc, max_files: int = 500, exclude_remediated: bool = False) -> list[dict]:
    """Whole-Drive search — returns all scannable files regardless of folder."""
    excl_id = _find_remediated_folder_id(svc) if exclude_remediated else None
    q = f"({_DRIVE_MIME_Q}) and trashed=false"
    if excl_id:
        # Drive query syntax — files NOT in that folder. A file can have multiple
        # parents, so this only excludes files whose ACP-remediated copy is their
        # sole/primary location, which matches the actual upload behavior.
        q += f" and not '{excl_id}' in parents"
    files: list[dict] = []
    page_token = None
    while len(files) < max_files:
        resp = svc.files().list(
            q=q,
            fields="nextPageToken,files(id,name,mimeType,md5Checksum)",
            pageSize=200,
            orderBy="name",
            pageToken=page_token,
        ).execute()
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return _normalize(files[:max_files])


def _search_folder(svc, folder_id: str, max_files: int = 1000, exclude_remediated: bool = False) -> list[dict]:
    """BFS over a folder subtree — returns all scannable files in the folder AND
    every nested subfolder. Bounded by max_files (newest folders may be skipped
    once the cap is hit) and a cycle guard, so a huge tree can't run unbounded.

    exclude_remediated: don't recurse into the configured Drive mirror folder
    (default 'Remediated', admin-configurable) — cheaper than tracking each file's
    parent-folder lineage, and sufficient since ACP only ever writes remediated
    output to that one well-known folder (handlers.ensure_remediated_folder)."""
    remediated_folder_name = None
    if exclude_remediated:
        import core
        remediated_folder_name = core.store.get_drive_mirror_folder()
    queue = [folder_id]
    seen_folders: set[str] = set()
    raw: list[dict] = []
    while queue and len(raw) < max_files:
        fid = queue.pop(0)
        if fid in seen_folders:
            continue
        seen_folders.add(fid)
        page_token = None
        while True:
            resp = svc.files().list(
                q=f"'{fid}' in parents and trashed=false",
                fields="nextPageToken,files(id,name,mimeType,md5Checksum)",
                pageSize=200,
                pageToken=page_token,
            ).execute()
            for f in resp.get("files", []):
                if f["mimeType"] == "application/vnd.google-apps.folder":
                    if exclude_remediated and f["name"] == remediated_folder_name:
                        continue
                    queue.append(f["id"])
                else:
                    raw.append(f)
            page_token = resp.get("nextPageToken")
            if not page_token or len(raw) >= max_files:
                break
    return _normalize(raw[:max_files])


def _sp_list(token: str, max_files: int = 200) -> list[dict]:
    """List scannable files from OneDrive personal via MS Graph search."""
    import httpx
    exts = {".docx", ".pptx", ".xlsx", ".pdf", ".html", ".htm"}
    hdrs = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    files: list[dict] = []
    url = "https://graph.microsoft.com/v1.0/me/drive/root/search(q='')?$select=id,name,file&$top=200"
    while url and len(files) < max_files:
        r = httpx.get(url, headers=hdrs, timeout=30, follow_redirects=True)
        r.raise_for_status()
        data = r.json()
        for item in data.get("value", []):
            if "file" not in item:
                continue
            name = item.get("name", "")
            if Path(name).suffix.lower() in exts:
                files.append({"name": _safe_name(name), "id": item["id"], "sp": True})
        url = data.get("@odata.nextLink")
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
          max_files: int | None = None, exclude_remediated: bool = False) -> list[dict]:
    # The monolithic scan keeps conservative caps (one box's disk holds every file);
    # the fan-out path (ADR 0007) passes a high cap since each file is its own job.
    if source == "local":
        # ACP_LOCAL_CORPUS: point local scans at a different directory — the test
        # suite uses it to scan the frozen oracle corpus (test-corpus/oracle/)
        # instead of the demo estate, which changes with the demo's needs.
        corpus = Path(os.environ.get("ACP_LOCAL_CORPUS") or (ACP / "test-corpus/files"))
        result = [{"name": p.name, "path": str(p)} for p in sorted(corpus.glob("*"))
                   if p.suffix.lower() in OFFICE + (".pdf",) + HTML_EXTS]
    elif source == "sharepoint":
        result = _sp_list(sp_token, max_files or 200)
    elif folder and folder != "root":
        # Specific folder: recursive BFS
        result = _search_folder(svc, folder, max_files or 1000, exclude_remediated=exclude_remediated)
    elif folder == "root" or folder is None:
        # No specific folder chosen: search the whole Drive
        result = _search_drive(svc, max_files or 500, exclude_remediated=exclude_remediated)
    else:
        # ADC/demo mode with a pinned folder
        resp = svc.files().list(q=f"'{_DEMO_FOLDER}' in parents and trashed=false",
                                fields="files(id,name,mimeType,md5Checksum)", pageSize=200,
                                orderBy="name").execute()
        result = _normalize(resp.get("files", []))
    return _dedupe_names(result)


def _download(item: dict, dest: Path, svc=None, sp_token: str | None = None) -> None:
    out = dest / item["name"]
    if "path" in item:
        out.write_bytes(Path(item["path"]).read_bytes())
        return
    if item.get("sp"):
        _sp_download(sp_token, item, dest)
        return
    from googleapiclient.http import MediaIoBaseDownload
    buf = io.BytesIO()
    if "mime" in item:
        # Google Workspace native — export as OOXML
        export_mime = EXPORT_MAP[item["mime"]][0]
        req = svc.files().export_media(fileId=item["id"], mimeType=export_mime)
    else:
        req = svc.files().get_media(fileId=item["id"])
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    out.write_bytes(buf.getvalue())


def _analyse_pdf(path: Path) -> dict:
    import asyncio
    sys.path.insert(0, str(WP))
    from analysers.pdf_analyser import PdfAnalyser
    from models.manifest import AnalysisJob, FileType
    job = AnalysisJob(job_id=uuid.uuid4(), batch_run_id=uuid.uuid4(), file_id=uuid.uuid4(),
                      file_path=str(path), file_type=FileType.PDF, queue="pdf",
                      enqueued_at=datetime.now(timezone.utc), department_id=uuid.uuid4(), disabled_rule_ids=[])
    try:
        r = asyncio.run(PdfAnalyser().analyse(path, job))
        return {"succeeded": r.succeeded,
                "issues": [{"ruleId": i.rule_id, "wcag": i.wcag_criterion.name, "severity": i.severity.name} for i in r.issues],
                "errors": [{"message": e.message, "rule": e.rule_id} for e in r.errors]}
    except Exception as e:
        return {"succeeded": False, "issues": [], "errors": [{"message": f"{type(e).__name__}: {e}", "rule": None}]}


def _office_err(e: dict) -> dict:
    code = e.get("Code", "") if isinstance(e, dict) else ""
    rule = code[len("RULE_EXECUTION_ERROR_"):] if code.startswith("RULE_EXECUTION_ERROR_") else None
    msg = (e.get("message") or e.get("Message") or str(e)) if isinstance(e, dict) else str(e)
    return {"message": msg, "rule": rule}


def _analyse_office(dest: Path) -> dict:
    out = dest / "_o.json"
    env = {**os.environ, "DOTNET_ROOT": os.path.expanduser("~/.dotnet"),
           "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1"}
    subprocess.run([DOTNET, str(CLI_DLL), str(dest), str(out)], capture_output=True, text=True, env=env)
    res = {}
    if out.exists():
        for item in json.loads(out.read_text()):
            res[item["file"]] = {
                "succeeded": item["succeeded"],
                "issues": [{"ruleId": i["ruleId"], "wcag": i["wcag"], "severity": i["severity"]} for i in item.get("issues", [])],
                "errors": [_office_err(e) for e in item.get("errors", [])],
            }
    return res


_VAGUE_LINK_TEXT = frozenset({"click here", "here", "read more", "more", "link", "this", "click", "learn more", "details"})

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

    # 2.4.6 Headings and Labels — skipped heading levels (e.g. h1 → h3)
    HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
    prev_level = 0
    for el in root.iter():
        if el.tag in HEADING_TAGS:
            level = int(el.tag[1])
            if prev_level > 0 and level > prev_level + 1:
                issues.append({"ruleId": "HTML_HEADING_SKIP", "wcag": "2.4.6 Headings and Labels", "severity": "MODERATE"})
                break
            prev_level = level

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


def analyse_and_assess(tmp: Path, name: str, *, detect_pii: bool = True):
    """Analyse + rubric-assess ONE already-downloaded file (fan-out path, ADR 0007).
    `tmp` is a directory containing `name`. Returns (assessed_file_dict, pii_info),
    or (None, None) for an unsupported extension. Engines catch their own errors and
    return an error result rather than raising."""
    rb = Rubric.load_active(ACP / "config")
    ext = Path(name).suffix.lower()
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
    raw["issues"] = [i for i in raw["issues"] if i["ruleId"] not in rb.disabled]
    raw["errors"] = [e for e in raw["errors"]
                     if (e.get("rule") if isinstance(e, dict) else None) not in rb.disabled]
    assessed = rb.assess(raw["succeeded"], raw["issues"], raw["errors"])
    fdict = {"file": name, "engine": raw["engine"], **assessed, "issues": raw["issues"],
             "acp_stamped": detect_acp_stamp(tmp / name, ext),
             **_file_extent(tmp / name, ext)}
    pinfo = None
    if detect_pii:
        import pii as _pii_mod
        pinfo = _pii_mod.detect_file(tmp / name)
    return fdict, pinfo


def run_scan(source: str = "local", progress=_noop, drive_token: str | None = None,
             folder: str | None = None, sp_token: str | None = None,
             ai_enabled: bool = True, scan_id: str | None = None,
             user: str | None = None, detect_pii: bool = True,
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
        items = _list(source, svc, folder=effective_folder, sp_token=sp_token,
                     exclude_remediated=exclude_remediated)
        n = len(items)
        progress({"phase": "discovering", "files_found": n, "files_done": 0, "current": None})

        for i, it in enumerate(items):
            progress({"phase": "reading", "files_found": n, "files_done": i, "current": it["name"]})
            _download(it, tmp, svc, sp_token=sp_token)

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
            pinfo = _pii_mod.detect_file(tmp / name) if detect_pii else None
            return (name, r, pinfo)

        progress({"phase": "analysing", "files_found": n, "files_done": 0, "current": None})
        with _cf.ThreadPoolExecutor(max_workers=_SCAN_WORKERS) as _ex:
            analysed = [x for x in _ex.map(_analyse_one, items) if x is not None]

        for done_i, (name, r, pinfo) in enumerate(analysed):
            progress({"phase": "scoring", "files_found": n, "files_done": done_i, "current": name})
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
        assessed = {k: rb.assess(r["succeeded"], r["issues"], r["errors"]) for k, r in raw.items()}
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
            "owner": user,            # per-user isolation: who ran this scan

            "files": [{"file": k, "engine": raw[k]["engine"], **assessed[k], "issues": raw[k]["issues"],
                       "drive_file_id": drive_id_map.get(k), "pii": pii_by_file.get(k),
                       "acp_stamped": detect_acp_stamp(tmp / k, Path(k).suffix.lower()),
                       **_file_extent(tmp / k, Path(k).suffix.lower())}
                      for k in sorted(raw)],
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # ephemeral: documents never retained
