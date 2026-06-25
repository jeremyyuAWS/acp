"""acp control-plane API (MVP).

Endpoints:
  GET  /healthz            liveness
  GET  /rubric             active rubric (name, version, content hash)
  POST /scans?source=...   run a scan ('local' corpus or 'drive'), persist, return summary
  GET  /scans              list past scan runs
  GET  /scans/{id}         one run: summary + per-file results + issues
  GET  /inventory          idempotent inventory (first/last seen per file)

Scans run synchronously here for simplicity; the productized control plane starts the
Temporal workflow and returns immediately (see temporal/).
"""
from __future__ import annotations
import base64
import json
import os
import sys
import threading
import uuid
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from scanner import run_scan
from store import Store
from report import build_report
from rubric import Rubric

ACP = Path(__file__).resolve().parent.parent
app = FastAPI(title="acp — accessibility compliance API", version="0.1.0")
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])

# Public-deploy access gate: if ACP_ACCESS_CODE is set, every request except the
# liveness probe needs HTTP Basic auth whose password matches it. No-op locally
# (env unset). This is a thin shared-passcode gate in front of the demo; it is
# replaced by per-user "Sign in with Google" (GIS) once a Web OAuth client exists.
ACCESS_CODE = os.environ.get("ACP_ACCESS_CODE")
# When a Web OAuth client id is configured, the SPA does per-user "Sign in with
# Google" (GIS) and sends each user's Drive access token as X-Drive-Token; the
# passcode gate is then disabled at deploy time. Unset = demo mode (baked ADC).
GOOGLE_CLIENT_ID = os.environ.get("ACP_GOOGLE_CLIENT_ID") or None
DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
]


@app.middleware("http")
async def _access_gate(request, call_next):
    if ACCESS_CODE and request.url.path != "/healthz":
        ok = False
        hdr = request.headers.get("authorization", "")
        if hdr.startswith("Basic "):
            try:
                ok = base64.b64decode(hdr[6:]).decode().split(":", 1)[1] == ACCESS_CODE
            except Exception:
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="acp"'})
    return await call_next(request)


store = Store()
JOBS: dict[str, dict] = {}

_scheduler = BackgroundScheduler()
_scheduler.start()


def _do_scheduled_scan():
    try:
        report = run_scan("local")
        store.save_scan(report)
        print(f"scheduled scan complete: {report['summary']['files']} files", flush=True)
    except Exception as e:
        print(f"scheduled scan failed: {e}", flush=True)


def _reload_scheduler():
    cfg = store.get_schedule()
    _scheduler.remove_all_jobs()
    if cfg["enabled"] and cfg["interval_minutes"] > 0:
        _scheduler.add_job(_do_scheduled_scan, "interval",
                           minutes=cfg["interval_minutes"],
                           id="scheduled_local_scan",
                           coalesce=True, max_instances=1)


_reload_scheduler()
def active_rubric():
    return Rubric.load_active(ACP / "config")


@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "acp", "rubric_hash": active_rubric().hash}


@app.get("/config")
def config():
    """Tells the SPA how to authenticate: GIS per-user (client id present) vs demo."""
    return {"google_client_id": GOOGLE_CLIENT_ID,
            "drive_scope": DRIVE_SCOPES[0],
            "auth": "gis" if GOOGLE_CLIENT_ID else "demo"}


class ScheduleUpdate(BaseModel):
    enabled: bool
    interval_minutes: int


@app.get("/schedule")
def schedule():
    cfg = store.get_schedule()
    job = _scheduler.get_job("scheduled_local_scan")
    cfg["next_at"] = job.next_run_time.isoformat() if job and job.next_run_time else None
    scans = store.list_scans()
    cfg["last_at"] = scans[0]["completed_at"] if scans else None
    return cfg


@app.put("/schedule")
def update_schedule(body: ScheduleUpdate):
    store.save_schedule(body.enabled, body.interval_minutes)
    _reload_scheduler()
    return schedule()


@app.get("/rubric")
def rubric():
    rb = active_rubric()
    return {"name": rb.name, "version": rb.version, "hash": rb.hash,
            "target": rb.cfg.get("conformance_target"), "threshold": rb.threshold,
            "criteria": rb.criteria}


@app.get("/rules")
def rules():
    catalog = json.loads((ACP / "config/rule-catalog.json").read_text())
    disabled = set(active_rubric().disabled)
    findings = store.rule_findings()
    # Exclude the _meta key; enrich each rule with runtime state.
    return {
        fmt: [
            {
                **r,
                "enabled": r["id"] not in disabled,
                "findings": findings.get(r["id"], 0),
                # wcag_level already present in the enriched catalog; fall back for
                # older catalog rows that only have the legacy wcag key.
                "level": r.get("wcag_level") or ("AA" if r.get("wcag") == "SC_1_4_3" else "A"),
            }
            for r in items
        ]
        for fmt, items in catalog.items()
        if fmt != "_meta"
    }


class RubricUpdate(BaseModel):
    disabled_rules: list[str] | None = None
    compliant_threshold: int | None = None


@app.put("/rubric")
def update_rubric(body: RubricUpdate):
    base = ACP / "config" / ("rubric.active.json" if (ACP / "config/rubric.active.json").exists()
                             else "rubric.default.json")
    cfg = json.loads(base.read_text())
    if body.disabled_rules is not None:
        cfg["disabled_rules"] = sorted(set(body.disabled_rules))
    if body.compliant_threshold is not None:
        cfg["compliant_threshold"] = int(body.compliant_threshold)
    (ACP / "config/rubric.active.json").write_text(json.dumps(cfg, indent=2))
    rb = active_rubric()
    return {"hash": rb.hash, "disabled_rules": sorted(rb.disabled), "threshold": rb.threshold}


@app.post("/scans")
def start_scan(request: Request, source: str = Query("local", pattern="^(local|drive|sharepoint)$"),
               sync: bool = False, folder: str | None = Query(None)):
    token = request.headers.get("x-drive-token")      # per-user Drive token (GIS)
    sp_token = request.headers.get("x-sp-token")      # per-user MS Graph token (MSAL)
    # ACP_DEMO_DRIVE_KEY lets the E2E test and demo scripts trigger a server-side
    # ADC Drive scan without needing per-user GIS — pass as X-Demo-Key header.
    DEMO_KEY = os.environ.get("ACP_DEMO_DRIVE_KEY", "")
    demo_key = request.headers.get("x-demo-key", "")
    is_demo_drive = source == "drive" and DEMO_KEY and demo_key == DEMO_KEY
    if source == "drive" and GOOGLE_CLIENT_ID and not token and not is_demo_drive:
        raise HTTPException(401, "sign in with Google to scan your Drive")
    if source == "sharepoint" and not sp_token:
        raise HTTPException(401, "sign in with Microsoft to scan OneDrive")
    if sync:  # synchronous path for scripts/tests
        report = run_scan(source, drive_token=token, folder=folder, sp_token=sp_token)
        return {"scan_id": store.save_scan(report), "source": source, "summary": report["summary"]}
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"phase": "queued", "files_found": 0, "files_done": 0, "current": None,
                    "done": False, "scan_id": None, "error": None, "source": source}

    def work():
        try:
            report = run_scan(source, progress=lambda d: JOBS[job_id].update(d),
                              drive_token=token, folder=folder, sp_token=sp_token)
            JOBS[job_id].update({"phase": "done", "done": True, "scan_id": store.save_scan(report),
                                 "files_done": JOBS[job_id].get("files_found", 0)})
        except Exception as e:
            JOBS[job_id].update({"phase": "error", "done": True, "error": str(e)})

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": job_id}


@app.get("/scans/jobs/{job_id}")
def scan_job(job_id: str):
    j = JOBS.get(job_id)
    if j is None:
        raise HTTPException(404, "job not found")
    return j


@app.get("/scans")
def scans():
    return store.list_scans()


@app.get("/scans/{sid}")
def scan(sid: str):
    res = store.get_scan(sid)
    if res is None:
        raise HTTPException(404, "scan not found")
    return res


@app.get("/ai/explain")
def ai_explain(scan_id: str = Query(...), file: str = Query(...), rule_id: str = Query(...)):
    """Generate a plain-English explanation + fix example for one WCAG finding.

    Calls the local Ollama instance (OLLAMA_BASE_URL, default http://localhost:11434).
    Returns 503 when Ollama is unavailable — callers should handle gracefully.
    """
    import ai as _ai
    trace = store.get_trace_row(scan_id, file, rule_id)
    if trace is None:
        raise HTTPException(404, "trace not found")
    engine_rule_ids = store.get_issue_rule_ids(scan_id, file, rule_id)
    result = _ai.explain_finding(
        rule_id=rule_id,
        rule_name=trace["rule_name"],
        level=trace["level"],
        filename=file,
        finding_count=trace["finding_count"],
        severity=trace.get("severity", ""),
        engine_rule_ids=engine_rule_ids,
    )
    if result is None:
        raise HTTPException(503, "AI explanation unavailable — is Ollama running?")
    return result


@app.get("/ai/status")
def ai_status():
    """Check whether the local Ollama instance is reachable."""
    import ai as _ai
    return {"available": _ai.is_available(), "base_url": _ai.OLLAMA_BASE_URL, "model": _ai.OLLAMA_MODEL}


@app.get("/scans/{sid}/traces")
def scan_traces(sid: str, file: str | None = None):
    """Per-rule trace for a scan. Returns one row per (file, rule) pair showing
    PASS/FAIL/SKIP and the finding count. Optionally filter to a single file."""
    if store.get_scan(sid) is None:
        raise HTTPException(404, "scan not found")
    return store.get_scan_traces(sid, file=file)


@app.get("/scans/{sid}/manifest")
def scan_manifest(sid: str):
    """Rule-execution manifest for a scan.

    Returns per-file completeness: how many rules were expected to run (based on
    the file type's rule catalog), how many ran successfully (PASS or FAIL), and
    how many errored (ENGINE failed to assess that rule). A scan is COMPLETE when
    rules_errored_total == 0. Use this to detect partial assessments before acting
    on a score.
    """
    if store.get_scan(sid) is None:
        raise HTTPException(404, "scan not found")
    return store.get_scan_manifest(sid)


_HITL_WEBHOOK = os.environ.get("HITL_WEBHOOK_URL", "")


def _fire_webhook(items: list[dict]) -> None:
    """POST new HITL items to the configured webhook URL (best-effort, non-blocking)."""
    if not _HITL_WEBHOOK or not items:
        return
    import threading
    def _post():
        try:
            import httpx
            httpx.post(_HITL_WEBHOOK, json={"event": "hitl.queued", "items": items}, timeout=8)
        except Exception as e:
            print(f"HITL webhook failed: {e}", flush=True)
    threading.Thread(target=_post, daemon=True).start()


class HitlUpdate(BaseModel):
    status: str                     # pending | approved | rejected | skipped
    reviewer_note: str | None = None


@app.post("/hitl/queue/{scan_id}/auto")
def hitl_auto_queue(scan_id: str):
    """Auto-populate the HITL review queue from ai-assisted FAILs in an existing scan.

    Idempotent — safe to call multiple times. Returns the newly created items.
    Fires a webhook (HITL_WEBHOOK_URL) if configured.
    """
    if store.get_scan(scan_id) is None:
        raise HTTPException(404, "scan not found")
    created = store.queue_hitl_items(scan_id)
    _fire_webhook(created)
    return {"queued": len(created), "items": created}


@app.get("/hitl/queue")
def hitl_list(status: str | None = None, scan_id: str | None = None):
    """List HITL review items. Filter by status (pending/approved/rejected/skipped) or scan_id."""
    return store.list_hitl_queue(status=status, scan_id=scan_id)


@app.put("/hitl/queue/{item_id}")
def hitl_update(item_id: str, body: HitlUpdate):
    """Update a HITL review item status (approve, reject, skip) with an optional reviewer note."""
    item = store.get_hitl_item(item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    valid = {"pending", "approved", "rejected", "skipped"}
    if body.status not in valid:
        raise HTTPException(422, f"status must be one of {sorted(valid)}")
    return store.update_hitl_item(item_id, body.status, body.reviewer_note)


@app.get("/scans/{sid}/report.pdf")
def report_pdf(sid: str):
    res = store.get_scan(sid)
    if res is None:
        raise HTTPException(404, "scan not found")
    rb = active_rubric()
    meta = {"target": rb.cfg.get("conformance_target"), "version": rb.version,
            "hash": res["run"].get("rubric_hash") or rb.hash}
    pdf = build_report(res["run"], res["files"], meta)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="acp-report-{sid}.pdf"'})


@app.get("/inventory")
def inventory():
    return store.inventory()


@app.get("/hub", response_class=Response)
def hub():
    """Landing page — all key links in one place."""
    hub_file = ACP / "hub" / "index.html"
    if not hub_file.exists():
        raise HTTPException(404, "hub/index.html not found")
    return Response(hub_file.read_bytes(), media_type="text/html")


# ── Remediation endpoints ─────────────────────────────────────────────────────

@app.post("/scans/{scan_id}/files/{filename:path}/remediate")
def mark_remediated(scan_id: str, filename: str):
    """Record that a file was remediated (download or Drive write-back)."""
    now = store.record_remediation(scan_id, filename)
    _emit_remediation_span(scan_id, filename, drive_write_url=None)
    return {"remediated_at": now}


@app.get("/scans/{scan_id}/files/{filename:path}/content")
def get_file_content(scan_id: str, filename: str, request: Request):
    """Fetch the original file bytes from Drive using the stored drive_file_id.
    Returns raw bytes so the browser can run remediateHtml() client-side."""
    drive_file_id = store.get_file_drive_id(scan_id, filename)
    if not drive_file_id:
        raise HTTPException(404, "drive_file_id not recorded for this file — was it scanned from Drive?")
    try:
        svc = _drive(request)
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


@app.post("/drive/upload")
async def drive_upload(request: Request):
    """Upload a remediated file to Google Drive → Remediated/ folder.
    Body: multipart/form-data with fields: scan_id, file (filename), blob (file bytes)."""
    from fastapi import Form, UploadFile, File
    import io
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

        # Find or create the Remediated/ folder
        q = "name='Remediated' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        folders = svc.files().list(q=q, fields="files(id)", pageSize=1).execute().get("files", [])
        if folders:
            folder_id = folders[0]["id"]
        else:
            folder_id = svc.files().create(
                body={"name": "Remediated", "mimeType": "application/vnd.google-apps.folder"},
                fields="id"
            ).execute()["id"]

        media = MediaIoBaseUpload(io.BytesIO(content), mimetype=content_type, resumable=False)
        result = svc.files().create(
            body={"name": filename, "parents": [folder_id]},
            media_body=media, fields="id,webViewLink"
        ).execute()
        web_url = result.get("webViewLink", "")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Drive upload failed: {e}")

    if scan_id and filename:
        store.record_remediation(scan_id, filename, drive_write_url=web_url)
        _emit_remediation_span(scan_id, filename, drive_write_url=web_url)

    return {"url": web_url, "file_id": result.get("id", "")}


def _emit_remediation_span(scan_id: str, filename: str, drive_write_url: str | None):
    """Emit a Langfuse observation for the remediation write-back step."""
    try:
        import lf as _lf
        lf = _lf.client()
        if lf is None:
            return
        trace = lf.trace(id=scan_id, name="acp-scan")
        trace.span(
            name="remediate",
            input={"file": filename},
            output={"drive_write_url": drive_write_url, "written_to_drive": drive_write_url is not None},
            metadata={"step": "6-remediate"},
        )
        lf.flush()
    except Exception:
        pass


def _drive(request: Request | None = None):
    """Drive client for the request. A per-user GIS token (X-Drive-Token) scans that
    user's Drive; otherwise ADC (demo identity). In GIS mode a token is required."""
    from googleapiclient.discovery import build
    token = request.headers.get("x-drive-token") if request is not None else None
    if token:
        from google.oauth2.credentials import Credentials
        creds = Credentials(token=token, scopes=DRIVE_SCOPES)
    elif GOOGLE_CLIENT_ID:
        raise HTTPException(401, "sign in with Google to connect your Drive")
    else:
        import google.auth
        creds, _ = google.auth.default(scopes=DRIVE_SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


@app.get("/me")
def me(request: Request):
    """Signed-in identity = the connected Google account (real, via the Drive API)."""
    try:
        u = _drive(request).about().get(fields="user").execute().get("user", {})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(401, f"no connected Google account: {e}")
    return {"email": u.get("emailAddress"), "name": u.get("displayName"), "photo": u.get("photoLink")}


@app.get("/sources")
def sources(request: Request):
    from scanner import _DRIVE_MIME_Q
    token = request.headers.get("x-drive-token")
    name = "My Drive" if token else "acp-demo-corpus"
    try:
        svc = _drive(request)
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
        raise HTTPException(502, f"Drive connection failed: {e}")


@app.get("/folders")
def folders(request: Request, parent: str = "root"):
    """List immediate subfolders of a Drive folder — drives the frontend folder picker."""
    try:
        svc = _drive(request)
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
        raise HTTPException(502, f"Drive folder listing failed: {e}")


# Serve the built React SPA same-origin in the deploy container (ACP_STATIC_DIR
# points at the vite `dist`). Registered last so all /api routes take precedence;
# unset locally (the SPA runs on the vite dev server instead).
_static = os.environ.get("ACP_STATIC_DIR")
if _static and Path(_static).is_dir():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=_static, html=True), name="spa")
