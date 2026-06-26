"""Scan lifecycle, results, traces, manifest, report, inventory, and per-file
remediation endpoints."""
from __future__ import annotations
import os
import threading
import uuid

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

import core
from scanner import run_scan
from report import build_report

router = APIRouter()


@router.post("/scans")
def start_scan(request: Request, source: str = Query("local", pattern="^(local|drive|sharepoint)$"),
               sync: bool = False, folder: str | None = Query(None),
               ai: bool = Query(True), queue: bool = Query(False),
               pii: bool = Query(True), fanout: bool = Query(False)):
    token = request.headers.get("x-drive-token")      # per-user Drive token (GIS)
    sp_token = request.headers.get("x-sp-token")      # per-user MS Graph token (MSAL)
    # ACP_DEMO_DRIVE_KEY lets the E2E test and demo scripts trigger a server-side
    # ADC Drive scan without needing per-user GIS — pass as X-Demo-Key header.
    DEMO_KEY = os.environ.get("ACP_DEMO_DRIVE_KEY", "")
    demo_key = request.headers.get("x-demo-key", "")
    # The demo/ADC scan bypass is disabled in production (see core.IS_PROD).
    is_demo_drive = (not core.IS_PROD) and source == "drive" and DEMO_KEY and demo_key == DEMO_KEY
    if source == "drive" and core.GOOGLE_CLIENT_ID and not token and not is_demo_drive:
        raise HTTPException(401, "sign in with Google to scan your Drive")
    if source == "sharepoint" and not sp_token:
        raise HTTPException(401, "sign in with Microsoft to scan OneDrive")
    # Admin deterministic-only mode is a HARD override: if AI is disabled platform-wide,
    # no scan runs AI regardless of the per-scan ?ai= request.
    effective_ai = ai and core.store.get_ai_enabled()
    # Who ran this scan (GIS email, set by the access-gate). Used to group traces
    # by user in Langfuse; falls back to the demo identity on the keyless path.
    user = getattr(request.state, "user_email", None) or ("demo" if is_demo_drive else None)

    # ── Durable async path: enqueue a scan job for the worker pool (ADR 0004). ──
    # Survives restarts, retries on transient failure, shows up in /jobs + Grafana.
    if queue:
        scan_id = uuid.uuid4().hex[:12]
        core.register_scan_tokens(scan_id, drive=token, sp=sp_token)  # in-memory only
        # fanout=true → decompose into per-file jobs (ADR 0007); else the monolithic
        # 'scan' job (default, proven). Both are durable and resume across replicas.
        jtype = "scan_discover" if fanout else "scan"
        job_id = core.store.enqueue_job(
            jtype, {"source": source, "scan_id": scan_id, "folder": folder, "ai": ai,
                    "user": user, "pii": pii},
            scan_id=scan_id)
        return {"scan_id": scan_id, "job_id": job_id, "queued": True,
                "fanout": fanout, "workers": core.WORKERS}

    if sync:  # synchronous path for scripts/tests
        report = run_scan(source, drive_token=token, folder=folder, sp_token=sp_token,
                          ai_enabled=effective_ai, user=user, detect_pii=pii)
        sid = core.store.save_scan(report)
        core.finalize_scan(sid, effective_ai, source)
        return {"scan_id": sid, "source": source, "summary": report["summary"]}

    # Default: in-process background thread (fast, but lost on restart).
    job_id = uuid.uuid4().hex[:12]
    core.JOBS[job_id] = {"phase": "queued", "files_found": 0, "files_done": 0, "current": None,
                         "done": False, "scan_id": None, "error": None, "source": source, "ai": effective_ai}

    def work():
        try:
            report = run_scan(source, progress=lambda d: core.JOBS[job_id].update(d),
                              drive_token=token, folder=folder, sp_token=sp_token,
                              ai_enabled=effective_ai, user=user, detect_pii=pii)
            sid = core.store.save_scan(report)
            core.finalize_scan(sid, effective_ai, source)
            core.JOBS[job_id].update({"phase": "done", "done": True, "scan_id": sid,
                                      "files_done": core.JOBS[job_id].get("files_found", 0)})
        except Exception as e:
            core.JOBS[job_id].update({"phase": "error", "done": True, "error": str(e)})

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": job_id}


@router.post("/scans/{sid}/remediate")
def remediate_scan(sid: str, request: Request):
    """Async server-side remediation (ADR 0005): enqueue a remediate_file job per
    HTML file in the scan that came from Drive. The worker fixes it and writes the
    corrected copy back to a Remediated/ folder. Needs ACP_WORKERS>0."""
    res = core.store.get_scan(sid)
    if res is None:
        raise HTTPException(404, "scan not found")
    token = request.headers.get("x-drive-token")
    core.register_scan_tokens(sid, drive=token)  # in-memory only
    # Create the single 'Remediated' folder ONCE here (single-threaded), then pass
    # its id to every job — avoids concurrent workers each creating their own.
    remediated_folder_id = None
    if token:
        try:
            import handlers
            remediated_folder_id = handlers.ensure_remediated_folder(handlers._drive_client(token))
        except Exception:
            remediated_folder_id = None   # jobs fall back to find-or-create
    enqueued = []
    for f in res["files"]:
        # Server-side deterministic remediators (ADR 0005 step 4): HTML (in-repo),
        # PDF (vendored engine), and Office docx/pptx/xlsx (core-properties fixer).
        if not f["file"].lower().endswith((".html", ".htm", ".pdf", ".docx", ".pptx", ".xlsx")):
            continue
        # Skip already-clean files — nothing to remediate, no point queuing a job.
        if not f.get("issues"):
            continue
        drive_file_id = core.store.get_file_drive_id(sid, f["file"])
        if not drive_file_id:
            continue
        jid = core.store.enqueue_job(
            "remediate_file",
            {"scan_id": sid, "file": f["file"], "drive_file_id": drive_file_id,
             "remediated_folder_id": remediated_folder_id},
            scan_id=sid)
        enqueued.append(jid)
    return {"scan_id": sid, "enqueued": len(enqueued), "job_ids": enqueued, "workers": core.WORKERS}


@router.get("/scans/jobs/{job_id}")
def scan_job(job_id: str):
    j = core.JOBS.get(job_id)
    if j is None:
        raise HTTPException(404, "job not found")
    return j


@router.get("/scans")
def scans():
    return core.store.list_scans()


# Registered before /scans/{sid} so "active" isn't treated as a scan id.
@router.get("/scans/active")
def active_scan():
    """The in-flight scan, if any — lets the UI reconnect to a running scan after a
    page reload (the durable fan-out keeps running server-side)."""
    return core.store.active_scan() or {}


@router.get("/scans/{sid}")
def scan(sid: str):
    res = core.store.get_scan(sid)
    if res is None:
        raise HTTPException(404, "scan not found")
    return res


@router.get("/scans/{sid}/remediation-status")
def remediation_status(sid: str):
    """Live remediation progress (in-flight jobs + latest fixed file) for the bar."""
    return core.store.remediation_status(sid)


@router.get("/scans/{sid}/traces")
def scan_traces(sid: str, file: str | None = None):
    """Per-rule trace for a scan. Returns one row per (file, rule) pair showing
    PASS/FAIL/SKIP and the finding count. Optionally filter to a single file."""
    if core.store.get_scan(sid) is None:
        raise HTTPException(404, "scan not found")
    return core.store.get_scan_traces(sid, file=file)


@router.get("/scans/{sid}/pii")
def scan_pii(sid: str):
    """Sensitive-data (PII) findings for a scan (ADR 0006).

    Returns a rollup (documents affected, total items, per-type counts) plus the
    per-document detail. All samples are MASKED — raw PII is never stored or
    returned."""
    if core.store.get_scan(sid) is None:
        raise HTTPException(404, "scan not found")
    return {"summary": core.store.pii_summary(sid), "files": core.store.list_pii(sid)}


@router.get("/scans/{sid}/manifest")
def scan_manifest(sid: str):
    """Rule-execution manifest for a scan.

    Returns per-file completeness: how many rules were expected to run (based on
    the file type's rule catalog), how many ran successfully (PASS or FAIL), and
    how many errored (ENGINE failed to assess that rule). A scan is COMPLETE when
    rules_errored_total == 0. Use this to detect partial assessments before acting
    on a score.
    """
    if core.store.get_scan(sid) is None:
        raise HTTPException(404, "scan not found")
    return core.store.get_scan_manifest(sid)


@router.get("/scans/{sid}/report.pdf")
def report_pdf(sid: str):
    res = core.store.get_scan(sid)
    if res is None:
        raise HTTPException(404, "scan not found")
    rb = core.active_rubric()
    meta = {"target": rb.cfg.get("conformance_target"), "version": rb.version,
            "hash": res["run"].get("rubric_hash") or rb.hash}
    pdf = build_report(res["run"], res["files"], meta)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="acp-report-{sid}.pdf"'})


@router.get("/inventory")
def inventory():
    return core.store.inventory()


# ── Per-file remediation ──────────────────────────────────────────────────────

@router.post("/scans/{scan_id}/files/{filename:path}/remediate")
def mark_remediated(scan_id: str, filename: str):
    """Record that a file was remediated (download or Drive write-back)."""
    now = core.store.record_remediation(scan_id, filename)
    core.emit_remediation_span(scan_id, filename, drive_write_url=None)
    return {"remediated_at": now}


@router.get("/scans/{scan_id}/files/{filename:path}/content")
def get_file_content(scan_id: str, filename: str, request: Request):
    """Fetch the original file bytes from Drive using the stored drive_file_id.
    Returns raw bytes so the browser can run remediateHtml() client-side."""
    drive_file_id = core.store.get_file_drive_id(scan_id, filename)
    if not drive_file_id:
        raise HTTPException(404, "drive_file_id not recorded for this file — was it scanned from Drive?")
    try:
        svc = core.drive_service(request)
        data = svc.files().get_media(fileId=drive_file_id).execute()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Drive fetch failed: {e}")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    mime_map = {"html": "text/html", "htm": "text/html", "pdf": "application/pdf",
                "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}
    return Response(data, media_type=mime_map.get(ext, "application/octet-stream"))
