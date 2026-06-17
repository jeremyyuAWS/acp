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
