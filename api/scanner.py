"""Reusable scan core: source -> engines -> rubric -> report dict.

Emits progress via a callback (phase / files_found / files_done / current) so the
control plane can stream live activity. Ephemeral working copies are deleted when the
scan finishes (the "documents never retained" guarantee).
"""
from __future__ import annotations
import concurrent.futures as _cf
import io, json, os, re, shutil, subprocess, sys, tempfile, uuid
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
        result.append({"name": unique, "id": f["id"], **({"mime": mime} if mime in EXPORT_MAP else {})})
    return result


def _search_drive(svc, max_files: int = 500) -> list[dict]:
    """Whole-Drive search — returns all scannable files regardless of folder."""
    files: list[dict] = []
    page_token = None
    while len(files) < max_files:
        resp = svc.files().list(
            q=f"({_DRIVE_MIME_Q}) and trashed=false",
            fields="nextPageToken,files(id,name,mimeType)",
            pageSize=200,
            orderBy="name",
            pageToken=page_token,
        ).execute()
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return _normalize(files[:max_files])


def _search_folder(svc, folder_id: str, max_files: int = 1000) -> list[dict]:
    """BFS over a folder subtree — returns all scannable files in the folder AND
    every nested subfolder. Bounded by max_files (newest folders may be skipped
    once the cap is hit) and a cycle guard, so a huge tree can't run unbounded."""
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
                fields="nextPageToken,files(id,name,mimeType)",
                pageSize=200,
                pageToken=page_token,
            ).execute()
            for f in resp.get("files", []):
                if f["mimeType"] == "application/vnd.google-apps.folder":
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


def _list(source: str, svc=None, folder: str | None = None, sp_token: str | None = None,
          max_files: int | None = None) -> list[dict]:
    # The monolithic scan keeps conservative caps (one box's disk holds every file);
    # the fan-out path (ADR 0007) passes a high cap since each file is its own job.
    if source == "local":
        return [{"name": p.name, "path": str(p)} for p in sorted((ACP / "test-corpus/files").glob("*"))
                if p.suffix.lower() in OFFICE + (".pdf",) + HTML_EXTS]
    if source == "sharepoint":
        return _sp_list(sp_token, max_files or 200)
    if folder and folder != "root":
        # Specific folder: recursive BFS
        return _search_folder(svc, folder, max_files or 1000)
    elif folder == "root" or folder is None:
        # No specific folder chosen: search the whole Drive
        return _search_drive(svc, max_files or 500)
    # ADC/demo mode with a pinned folder
    resp = svc.files().list(q=f"'{_DEMO_FOLDER}' in parents and trashed=false",
                            fields="files(id,name,mimeType)", pageSize=200,
                            orderBy="name").execute()
    return _normalize(resp.get("files", []))


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

    return {"succeeded": True, "issues": issues, "errors": []}


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
    raw["issues"] = [i for i in raw["issues"] if i["ruleId"] not in rb.disabled]
    raw["errors"] = [e for e in raw["errors"]
                     if (e.get("rule") if isinstance(e, dict) else None) not in rb.disabled]
    assessed = rb.assess(raw["succeeded"], raw["issues"], raw["errors"])
    fdict = {"file": name, "engine": raw["engine"], **assessed, "issues": raw["issues"]}
    pinfo = None
    if detect_pii:
        import pii as _pii_mod
        pinfo = _pii_mod.detect_file(tmp / name)
    return fdict, pinfo


def run_scan(source: str = "local", progress=_noop, drive_token: str | None = None,
             folder: str | None = None, sp_token: str | None = None,
             ai_enabled: bool = True, scan_id: str | None = None,
             user: str | None = None, detect_pii: bool = True) -> dict:
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
        items = _list(source, svc, folder=effective_folder, sp_token=sp_token)
        n = len(items)
        progress({"phase": "discovering", "files_found": n, "files_done": 0, "current": None})

        for i, it in enumerate(items):
            progress({"phase": "reading", "files_found": n, "files_done": i, "current": it["name"]})
            _download(it, tmp, svc, sp_token=sp_token)

        office = _analyse_office(tmp)

        # One Langfuse trace covers the full scan; one span per file; one child span per rule.
        trace = _lf_mod.scan_trace(scan_id, source, n, ai_enabled=ai_enabled, user=user)

        import pii as _pii_mod  # sensitive-data detection dimension (ADR 0006)
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
            pinfo = _pii_mod.detect_file(tmp / name) if detect_pii else None
            return (name, r, pinfo)

        progress({"phase": "analysing", "files_found": n, "files_done": 0, "current": None})
        with _cf.ThreadPoolExecutor(max_workers=_SCAN_WORKERS) as _ex:
            analysed = [x for x in _ex.map(_analyse_one, items) if x is not None]

        for done_i, (name, r, pinfo) in enumerate(analysed):
            progress({"phase": "scoring", "files_found": n, "files_done": done_i, "current": name})
            raw[name] = r
            engine = r["engine"]
            fspan = _lf_mod.file_span(trace, name, engine)
            sc_counts: dict[str, int] = {}
            sc_severity: dict[str, str] = {}
            for issue in r.get("issues", []):
                sc = _extract_sc(issue.get("wcag", ""))
                if sc:
                    sc_counts[sc] = sc_counts.get(sc, 0) + 1
                    if issue.get("severity") and sc not in sc_severity:
                        sc_severity[sc] = issue["severity"]
            _lf_mod.rule_spans(fspan, sc_counts, RULE_CATALOG, severity_map=sc_severity)
            pii_total = 0
            if detect_pii and pinfo is not None:
                pii_by_file[name] = pinfo
                pii_total = pinfo.get("total", 0)
                if pii_total:
                    _lf_mod.pii_span(fspan, pinfo)
            fspan.end(output={"issue_count": len(r.get("issues", [])),
                              "engine": engine, "sensitive_data": pii_total})

        progress({"phase": "scoring", "files_found": n, "files_done": n, "current": None})
        for r in raw.values():
            r["issues"] = [i for i in r["issues"] if i["ruleId"] not in rb.disabled]
            r["errors"] = [e for e in r["errors"] if (e.get("rule") if isinstance(e, dict) else None) not in rb.disabled]
        assessed = {k: rb.assess(r["succeeded"], r["issues"], r["errors"]) for k, r in raw.items()}
        summary = rb.aggregate(assessed)
        pii_docs = sum(1 for p in pii_by_file.values() if p.get("total"))
        pii_total = sum(p.get("total", 0) for p in pii_by_file.values())
        _lf_mod.finish_scan_trace(trace, scan_id, summary, source=source, ai_enabled=ai_enabled,
                                  pii_docs=pii_docs, pii_total=pii_total)
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
            "files": [{"file": k, "engine": raw[k]["engine"], **assessed[k], "issues": raw[k]["issues"],
                       "drive_file_id": drive_id_map.get(k), "pii": pii_by_file.get(k)}
                      for k in sorted(raw)],
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # ephemeral: documents never retained
