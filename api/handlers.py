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
    q = "name='Remediated' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    folders = svc.files().list(q=q, fields="files(id)", pageSize=1).execute().get("files", [])
    folder_id = folders[0]["id"] if folders else svc.files().create(
        body={"name": "Remediated", "mimeType": "application/vnd.google-apps.folder"},
        fields="id").execute()["id"]
    media = MediaIoBaseUpload(io.BytesIO(fixed_bytes), mimetype=mimetype, resumable=False)
    result = svc.files().create(
        body={"name": filename, "parents": [folder_id]},
        media_body=media, fields="id,webViewLink").execute()
    web_url = result.get("webViewLink", "")

    core.store.record_remediation(scan_id, filename, drive_write_url=web_url)
    core.emit_remediation_span(scan_id, filename, drive_write_url=web_url)
    core.store.log_decision("system", "remediate.applied", scan_id=scan_id, file=filename,
                            detail="; ".join(applied) or "no auto fixes needed")
