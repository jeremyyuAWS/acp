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
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


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
WCAG_LEVEL = {"SC_1_4_3": "AA"}  # the only AA criterion in our rule set; rest are level A


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
    return {fmt: [{**r, "enabled": r["id"] not in disabled,
                   "findings": findings.get(r["id"], 0), "level": WCAG_LEVEL.get(r["wcag"], "A")}
                  for r in items] for fmt, items in catalog.items()}


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
def start_scan(request: Request, source: str = Query("local", pattern="^(local|drive)$"),
               sync: bool = False, folder: str | None = Query(None)):
    token = request.headers.get("x-drive-token")  # per-user Drive token (GIS); captured before the thread
    if source == "drive" and GOOGLE_CLIENT_ID and not token:
        raise HTTPException(401, "sign in with Google to scan your Drive")
    if sync:  # synchronous path for scripts/tests
        report = run_scan(source, drive_token=token, folder=folder)
        return {"scan_id": store.save_scan(report), "source": source, "summary": report["summary"]}
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"phase": "queued", "files_found": 0, "files_done": 0, "current": None,
                    "done": False, "scan_id": None, "error": None, "source": source}

    def work():
        try:
            report = run_scan(source, progress=lambda d: JOBS[job_id].update(d),
                              drive_token=token, folder=folder)
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
            # Count all scannable files across the whole Drive (mirrors the scan search)
            resp = svc.files().list(q=f"({_DRIVE_MIME_Q}) and trashed=false",
                                    fields="files(id)", pageSize=200).execute()
            n = len(resp.get("files", []))
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
