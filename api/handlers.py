"""Job handlers for the durable async queue (ADR 0004).

Registered with the worker by importing this module (see core.start_workers).
Each handler runs one job to completion; raising re-queues it with backoff,
raising FatalJobError dead-letters it.

Current handlers:
  scan            — run a full scan asynchronously (durable + retryable), persist
                    results, emit per-file/per-rule Langfuse spans, finalize.

Per-file parallelism is intentionally NOT used here: the .NET Office analyser
processes a directory in one batch, so the natural durable unit is one scan job.
Per-file fan-out (PDF/HTML) is a possible future optimization (ADR 0004 step 3).
"""
from __future__ import annotations

import core
from worker import handler, FatalJobError
from scanner import run_scan
from remediate import remediate_html


def _drive_client(token: str):
    """Drive client for a worker (no request). GIS token → far-future expiry so the
    client never attempts the (impossible) refresh."""
    import datetime as _dt
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(token=token, scopes=core.DRIVE_SCOPES)
    # NAIVE UTC: google-auth compares expiry to a naive utcnow() (aware → TypeError).
    creds.expiry = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None) + _dt.timedelta(hours=1)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def ensure_remediated_folder(svc) -> str:
    """Find-or-create the single 'Remediated' Drive folder. If legacy duplicates
    exist, picks the oldest deterministically. Call this ONCE per remediate batch
    (in the request handler) and pass the id to the jobs — calling it concurrently
    from many workers is what created duplicate folders."""
    q = "name='Remediated' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    folders = svc.files().list(q=q, fields="files(id)", orderBy="createdTime",
                               pageSize=1).execute().get("files", [])
    if folders:
        return folders[0]["id"]
    return svc.files().create(
        body={"name": "Remediated", "mimeType": "application/vnd.google-apps.folder"},
        fields="id").execute()["id"]


@handler("scan")
def _scan(payload: dict, job: dict) -> None:
    """Run a scan to completion: discover → analyse → score → persist → finalize.

    payload: {source, scan_id, folder?, sp?, ai}
    The Drive/SharePoint tokens are looked up from the in-memory registry by
    scan_id (never carried in the job payload / Postgres)."""
    scan_id = payload.get("scan_id") or job.get("scan_id")
    if not scan_id:
        raise FatalJobError("scan job missing scan_id")
    source = payload.get("source", "local")
    ai = bool(payload.get("ai", True))
    effective_ai = ai and core.store.get_ai_enabled()
    toks = core.get_scan_tokens(scan_id)

    report = run_scan(
        source,
        drive_token=toks.get("drive"),
        sp_token=toks.get("sp"),
        folder=payload.get("folder"),
        ai_enabled=effective_ai,
        scan_id=scan_id,
        user=payload.get("user"),
        detect_pii=payload.get("pii", True),
    )
    core.store.save_scan(report)
    core.finalize_scan(scan_id, effective_ai, source)
    core.clear_scan_tokens(scan_id)


@handler("remediate_file")
def _remediate_file(payload: dict, job: dict) -> None:
    """Apply server-side remediation to one file and write the fixed copy to Drive.

    payload: {scan_id, file, drive_file_id}
    HTML files are remediated deterministically (ADR 0005); other types are routed
    to human review (no in-repo Office/PDF remediator yet)."""
    scan_id = payload.get("scan_id") or job.get("scan_id")
    filename = payload.get("file")
    drive_file_id = payload.get("drive_file_id")
    if not (scan_id and filename and drive_file_id):
        raise FatalJobError("remediate_file job missing scan_id/file/drive_file_id")

    _OFFICE_MIME = {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ("html", "htm", "pdf", *_OFFICE_MIME):
        # No server-side remediator for this type → human review.
        core.store.log_decision("system", "remediate.deferred", scan_id=scan_id,
                                file=filename, detail=f"no server-side remediator for .{ext}")
        return

    token = core.get_scan_tokens(scan_id).get("drive")
    if not token:
        raise FatalJobError("no Drive token for this scan (expired/restarted) — re-trigger")

    svc = _drive_client(token)
    data = svc.files().get_media(fileId=drive_file_id).execute()

    if ext in ("html", "htm"):
        fixed_html, applied, _deferred = remediate_html(
            data.decode("utf-8", errors="replace"), ai_enabled=core.store.get_ai_enabled())
        fixed_bytes = fixed_html.encode("utf-8")
        mimetype = "text/html"
    else:  # pdf / office — file-based deterministic remediators (ADR 0005 step 4)
        import tempfile
        from pathlib import Path as _Path
        with tempfile.TemporaryDirectory(prefix="acp-rem-") as _d:
            src = _Path(_d) / filename
            src.write_bytes(data)
            if ext == "pdf":
                from remediate_pdf import remediate_pdf
                out_path, applied, _skipped = remediate_pdf(src)
                mimetype = "application/pdf"
            else:  # docx / pptx / xlsx
                from remediate_office import remediate_office
                out_path, applied, _skipped = remediate_office(src)
                mimetype = _OFFICE_MIME[ext]
            if not out_path or not _Path(out_path).exists():
                core.store.log_decision("system", "remediate.deferred", scan_id=scan_id,
                                        file=filename, detail=f".{ext}: no deterministic fixes applied")
                return
            fixed_bytes = _Path(out_path).read_bytes()

    import io
    from googleapiclient.http import MediaIoBaseUpload
    # Folder id is created once per batch in the endpoint and passed in, so
    # concurrent workers don't each create their own 'Remediated' folder.
    # Fall back to find-or-create for a standalone job.
    folder_id = payload.get("remediated_folder_id") or ensure_remediated_folder(svc)
    media = MediaIoBaseUpload(io.BytesIO(fixed_bytes), mimetype=mimetype, resumable=False)
    # Upsert: update an existing fixed copy rather than piling up duplicates on re-run.
    safe = filename.replace("\\", "\\\\").replace("'", "\\'")
    existing = svc.files().list(
        q=f"name='{safe}' and '{folder_id}' in parents and trashed=false",
        fields="files(id)", pageSize=1).execute().get("files", [])
    if existing:
        result = svc.files().update(fileId=existing[0]["id"], media_body=media,
                                    fields="id,webViewLink").execute()
    else:
        result = svc.files().create(body={"name": filename, "parents": [folder_id]},
                                    media_body=media, fields="id,webViewLink").execute()
    web_url = result.get("webViewLink", "")

    core.store.record_remediation(scan_id, filename, drive_write_url=web_url)
    core.emit_remediation_span(scan_id, filename, drive_write_url=web_url)
    core.store.log_decision("system", "remediate.applied", scan_id=scan_id, file=filename,
                            detail="; ".join(applied) or "no auto fixes needed")


# ── Fan-out scan pipeline (ADR 0007): discover → scan_file → finalize ─────────
import datetime as _dt
import shutil as _shutil
import tempfile as _tempfile
from pathlib import Path as _Path


@handler("scan_discover")
def _scan_discover(payload: dict, job: dict) -> None:
    """List the source (paginated, no cap), create the scan_runs row, open the
    Langfuse trace, and enqueue one scan_file job per file."""
    import lf as _lf
    from rubric import Rubric
    from scanner import _list, _drive_service, ACP, FANOUT_MAX_FILES
    scan_id = payload.get("scan_id") or job.get("scan_id")
    source = payload.get("source", "drive")
    ai = bool(payload.get("ai", True)) and core.store.get_ai_enabled()
    pii = bool(payload.get("pii", True))
    user = payload.get("user")
    folder = payload.get("folder")
    toks = core.get_scan_tokens(scan_id)
    rb = Rubric.load_active(ACP / "config")
    svc = None if source in ("local", "sharepoint") else _drive_service(toks.get("drive"))
    effective_folder = folder if folder else ("root" if toks.get("drive") else None)
    items = _list(source, svc, folder=effective_folder, sp_token=toks.get("sp"),
                  max_files=FANOUT_MAX_FILES)
    started = _dt.datetime.now(_dt.timezone.utc).isoformat()
    core.store.init_scan_run(scan_id, source, len(items), started, rb.name, rb.hash)
    _lf.scan_trace(scan_id, source, len(items), ai_enabled=ai, user=user)
    if not items:
        core.store.enqueue_job("scan_finalize",
                               {"scan_id": scan_id, "source": source, "ai": ai, "pii": pii}, scan_id=scan_id)
        return
    for it in items:
        core.store.enqueue_job("scan_file", {
            "scan_id": scan_id, "source": source, "file": it["name"],
            "drive_file_id": it.get("id"), "mime": it.get("mime"), "path": it.get("path"),
            "ai": ai, "pii": pii, "user": user}, scan_id=scan_id)


@handler("scan_file")
def _scan_file(payload: dict, job: dict) -> None:
    """Download + analyse + assess + persist ONE file, emit its Langfuse spans, then
    bump the done counter — the job that completes the count enqueues finalize.
    Resilient: a fetch/analyse failure is recorded as an 'error' file so the counter
    always advances and the scan can finalize."""
    import lf as _lf
    from scanner import _download, _drive_service, analyse_and_assess
    from store import RULE_CATALOG, _extract_sc
    scan_id = payload["scan_id"]
    name = payload["file"]
    source = payload.get("source", "drive")
    pii = bool(payload.get("pii", True))
    toks = core.get_scan_tokens(scan_id)
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    tmp = _Path(_tempfile.mkdtemp(prefix="acp-scanone-"))
    fdict = pinfo = None
    try:
        try:
            svc = None if source in ("local", "sharepoint") else _drive_service(toks.get("drive"))
            item = {"name": name, "id": payload.get("drive_file_id")}
            if payload.get("mime"):
                item["mime"] = payload["mime"]
            if payload.get("path"):                 # local source — read from disk
                item["path"] = payload["path"]
            _download(item, tmp, svc, sp_token=toks.get("sp"))
            fdict, pinfo = analyse_and_assess(tmp, name, detect_pii=pii)
        except Exception as e:
            core.store.log_decision("system", "scan.file_error", scan_id=scan_id, file=name,
                                    detail=f"{type(e).__name__}: {e}"[:200])
        if fdict is None:                              # fetch/analyse failed → error record
            fdict = {"file": name, "engine": "n/a", "status": "error", "score": None,
                     "compliant": 0, "skipped_rules": 0, "issues": []}
        fdict["drive_file_id"] = payload.get("drive_file_id")
        if pinfo:
            fdict["pii"] = pinfo
        core.store.save_file_result(scan_id, fdict, now)
        # Langfuse spans for this file (on the trace by id).
        fspan = _lf.file_span_for(scan_id, name, fdict["engine"])
        sc_counts: dict[str, int] = {}
        sc_sev: dict[str, str] = {}
        for issue in fdict.get("issues", []):
            sc = _extract_sc(issue.get("wcag", ""))
            if sc:
                sc_counts[sc] = sc_counts.get(sc, 0) + 1
                if issue.get("severity") and sc not in sc_sev:
                    sc_sev[sc] = issue["severity"]
        _lf.rule_spans(fspan, sc_counts, RULE_CATALOG, severity_map=sc_sev, filename=name)
        if pinfo and pinfo.get("total"):
            _lf.pii_span(fspan, pinfo, filename=name)
        fspan.end(output={"issue_count": len(fdict.get("issues", [])), "engine": fdict["engine"],
                          "sensitive_data": (pinfo or {}).get("total", 0)})
    finally:
        _shutil.rmtree(tmp, ignore_errors=True)
    done, total = core.store.bump_files_done(scan_id)
    if done >= total > 0:
        core.store.enqueue_job("scan_finalize",
                               {"scan_id": scan_id, "source": source,
                                "ai": bool(payload.get("ai", True)), "pii": pii}, scan_id=scan_id)


@handler("scan_finalize")
def _scan_finalize(payload: dict, job: dict) -> None:
    """Aggregate the per-file results into the scan summary, finish the Langfuse
    trace, and run the shared post-scan step (HITL routing + audit)."""
    import lf as _lf
    scan_id = payload["scan_id"]
    source = payload.get("source", "drive")
    ai = bool(payload.get("ai", True)) and core.store.get_ai_enabled()
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    summary = core.store.finalize_scan_run(scan_id, now)
    roll = core.store.pii_summary(scan_id)
    _lf.finish_scan_trace_by_id(scan_id, summary, source=source, ai_enabled=ai,
                                pii_docs=roll.get("documents", 0), pii_total=roll.get("items", 0))
    _lf.flush()
    core.finalize_scan(scan_id, ai, source)
    core.clear_scan_tokens(scan_id)
