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
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from scanner import run_scan
from store import Store
from rubric import Rubric

ACP = Path(__file__).resolve().parent.parent
app = FastAPI(title="acp — accessibility compliance API", version="0.1.0")
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])
store = Store()
rb = Rubric.load(ACP / "config/rubric.default.json")


@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "acp", "rubric_hash": rb.hash}


@app.get("/rubric")
def rubric():
    return {"name": rb.name, "version": rb.version, "hash": rb.hash,
            "target": rb.cfg.get("conformance_target"), "threshold": rb.threshold,
            "criteria": rb.criteria}


@app.post("/scans")
def start_scan(source: str = Query("local", pattern="^(local|drive)$")):
    report = run_scan(source)          # sync for the MVP; Temporal in production
    sid = store.save_scan(report)
    return {"scan_id": sid, "source": source, "summary": report["summary"]}


@app.get("/scans")
def scans():
    return store.list_scans()


@app.get("/scans/{sid}")
def scan(sid: str):
    res = store.get_scan(sid)
    if res is None:
        raise HTTPException(404, "scan not found")
    return res


@app.get("/inventory")
def inventory():
    return store.inventory()


def _drive():
    import google.auth
    from googleapiclient.discovery import build
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/drive.readonly"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)


@app.get("/me")
def me():
    """Signed-in identity = the connected Google account (real, via the Drive API).
    Production swaps in a 'Sign in with Google' (GIS) flow; the screen is the same."""
    try:
        u = _drive().about().get(fields="user").execute().get("user", {})
    except Exception as e:
        raise HTTPException(401, f"no connected Google account: {e}")
    return {"email": u.get("emailAddress"), "name": u.get("displayName"), "photo": u.get("photoLink")}


@app.get("/sources")
def sources():
    folder = "1W27ULZsstP7gYGzgKKBId0qEfNxeKn0_"
    n = len(_drive().files().list(q=f"'{folder}' in parents and trashed=false",
                                  fields="files(id)", pageSize=200).execute().get("files", []))
    return [{"type": "google_drive", "name": "acp-demo-corpus", "id": folder,
             "files": n, "access": "read-only"}]
