"""Scan lifecycle, results, traces, manifest, report, inventory, and per-file
remediation endpoints."""
from __future__ import annotations
import os
import threading
import uuid

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response

import core
from scanner import run_scan
from report import build_report

router = APIRouter()


def _owner(request: Request) -> str:
    """The current user for per-user data isolation — the gate-verified email, or
    'demo' for the keyless/demo path. Matches the owner stamped on scans at creation."""
    return getattr(request.state, "user_email", None) or "demo"


@router.post("/scans")
def start_scan(request: Request, source: str = Query("local", pattern="^(local|drive|sharepoint)$"),
               sync: bool = False, folder: str | None = Query(None),
               ai: bool = Query(True), queue: bool = Query(False),
               pii: bool = Query(True), fanout: bool = Query(False),
               batch: bool = Query(False), exclude_remediated: bool = Query(False)):
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
    # Owner for per-user isolation: the gate-verified email, else 'demo' (keyless/demo).
    user = getattr(request.state, "user_email", None) or "demo"

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
                    "user": user, "pii": pii, "batch": batch,
                    "exclude_remediated": exclude_remediated},
            scan_id=scan_id)
        return {"scan_id": scan_id, "job_id": job_id, "queued": True,
                "fanout": fanout, "batch": batch, "workers": core.WORKERS}

    if sync:  # synchronous path for scripts/tests
        report = run_scan(source, drive_token=token, folder=folder, sp_token=sp_token,
                          ai_enabled=effective_ai, user=user, detect_pii=pii,
                          exclude_remediated=exclude_remediated)
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
                              ai_enabled=effective_ai, user=user, detect_pii=pii,
                              exclude_remediated=exclude_remediated)
            sid = core.store.save_scan(report)
            core.finalize_scan(sid, effective_ai, source)
            core.JOBS[job_id].update({"phase": "done", "done": True, "scan_id": sid,
                                      "files_done": core.JOBS[job_id].get("files_found", 0)})
        except Exception as e:
            core.JOBS[job_id].update({"phase": "error", "done": True, "error": str(e)})

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": job_id}


@router.post("/scans/{sid}/remediate")
async def remediate_scan(sid: str, request: Request):
    """Async server-side remediation (ADR 0005): enqueue a remediate_file job per
    HTML file in the scan that came from Drive. The worker fixes it and writes the
    corrected copy back to a Remediated/ folder. Needs ACP_WORKERS>0.

    Optional body: {"scope": ["file1.html", "file2.pdf", ...]} — when provided,
    only the listed filenames are enqueued (respects the triage decisions made in
    the UI). Omit or pass an empty body to remediate all eligible files."""
    res = core.store.get_scan(sid)
    if res is None:
        raise HTTPException(404, "scan not found")
    token = request.headers.get("x-drive-token")
    core.register_scan_tokens(sid, drive=token)  # in-memory only

    # Parse optional scope list from request body.
    scope_set = None
    try:
        body = await request.json()
        if isinstance(body.get("scope"), list):
            scope_set = set(body["scope"])
    except Exception:
        pass  # missing or non-JSON body — treat as no scope filter

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
        # Honour the triage scope: skip files the user marked N/A or deferred.
        if scope_set is not None and f["file"] not in scope_set:
            continue
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
def scans(request: Request):
    return core.store.list_scans(owner=_owner(request))


# Registered before /scans/{sid} so "active" isn't treated as a scan id.
@router.get("/scans/active")
def active_scan(request: Request):
    """The in-flight scan, if any — lets the UI reconnect to a running scan after a
    page reload (the durable fan-out keeps running server-side). Scoped to the user."""
    return core.store.active_scan(owner=_owner(request)) or {}


@router.get("/scans/{sid}")
def scan(sid: str, request: Request):
    res = core.store.get_scan(sid, owner=_owner(request))
    if res is None:
        raise HTTPException(404, "scan not found")
    return res


@router.post("/scans/{sid}/assess")
def assess(sid: str, request: Request, level: str = Query("AA")):
    """Write the WCAG rule assessment to Langfuse on demand — separate from the scan
    trace (which is discovery + deep-scan only). Enqueued to the durable worker."""
    if core.store.get_scan(sid, owner=_owner(request)) is None:
        raise HTTPException(404, "scan not found")
    # Mark the scan assessed — the results views (Overview/Dashboard/Monitor) gate on this,
    # so scores only appear once the user has explicitly run Assess.
    import datetime as _dt
    core.store.mark_assessed(sid, _dt.datetime.now(_dt.timezone.utc).isoformat())
    jid = core.store.enqueue_job("assess_trace", {"scan_id": sid, "level": level}, scan_id=sid)
    return {"scan_id": sid, "level": level, "job_id": jid, "workers": core.WORKERS}


@router.get("/scans/{sid}/trace/session")
def open_session(sid: str):
    """'View this scan' target under file-centric tracing (see lf.file_trace): every file
    in this scan shares a Langfuse SESSION keyed by the scan id, so this is the
    replacement for the old single scan/assess/remediate trace chips. No ensure-exists
    polling needed — an empty/not-yet-ingested session renders as 'no traces yet' in
    Langfuse, not a 404, so this redirects immediately. Public — see core.is_public.
    Registered BEFORE /trace/{kind} below — that's a single-path-segment wildcard that
    would otherwise shadow this literal "session" path (FastAPI matches routes in
    registration order; the more specific route must come first)."""
    import lf as _lf
    if core.store.get_scan(sid) is None:
        raise HTTPException(404, "scan not found")
    link = _lf.session_deep_link(sid)
    if not link:
        raise HTTPException(404, "tracing is not configured")
    return RedirectResponse(link, status_code=302)


@router.get("/scans/{sid}/trace/{kind}")
def open_trace(sid: str, request: Request, kind: str, level: str = Query("AA")):
    """Reliable 'View trace' target. Ensures the {kind} Langfuse trace for this scan
    exists, then 302s to its deep link — so the chips never land on a Not-Found. The
    assess trace is (re)built SYNCHRONOUSLY here on the API image when missing, which
    removes the async-job / worker-drift / early-return / ingestion-lag failure modes
    that made the direct deep-links flaky. Public (a plain <a> navigation target that
    only redirects to a Langfuse URL — see core.is_public)."""
    import time

    import lf as _lf
    if kind not in ("scan", "assess", "remediate"):
        raise HTTPException(404, "unknown trace kind")
    if core.store.get_scan(sid) is None:
        raise HTTPException(404, "scan not found")
    trace_id = sid if kind == "scan" else f"{sid}-{kind}"
    link = _lf.trace_deep_link(trace_id)
    if not link:
        raise HTTPException(404, "tracing is not configured")
    # Create the assess trace on the spot if Langfuse doesn't have it yet. (The scan and
    # remediate traces are written at their own lifecycle stage and can't be rebuilt
    # here, but the wait below still covers their ingestion lag.)
    if kind == "assess" and not _lf.trace_exists(trace_id):
        try:
            from handlers import ensure_assess_trace
            ensure_assess_trace(sid, level)
        except Exception:
            pass
    # Wait briefly for Langfuse ingestion (async after flush) so the detail view doesn't
    # 404 the instant we land on it — best-effort; redirect anyway after ~5s.
    for _ in range(8):
        if _lf.trace_exists(trace_id):
            break
        time.sleep(0.6)
    return RedirectResponse(link, status_code=302)


@router.get("/scans/{sid}/trace/{kind}/exists")
def trace_exists(sid: str, kind: str):
    """Returns {available: bool} — whether the Langfuse trace for this scan exists.
    Used by the UI to grey out the trace chip for scans that have no trace yet
    (e.g. scans from before tracing was wired up). Public — no auth needed.
    Historical (kind-based) traces only — see /trace/file/{file} for the current,
    file-centric model."""
    import lf as _lf
    if kind == "session":
        return {"available": _lf.session_exists(sid)}
    if kind not in ("scan", "assess", "remediate"):
        return {"available": False}
    trace_id = sid if kind == "scan" else f"{sid}-{kind}"
    return {"available": _lf.trace_exists(trace_id)}


@router.get("/scans/{sid}/trace/file/{filename:path}")
def open_file_trace(sid: str, filename: str, level: str = Query("AA")):
    """Reliable 'View trace' target for ONE file — its Discover/Assess/Remediate spans
    all live on this single trace (file-centric tracing). Ensures it exists (re-running
    the Assess write for this file if Langfuse doesn't have it yet — the same
    synchronous-rebuild approach as the old per-scan endpoint) then 302s to its deep
    link. Public — see core.is_public."""
    import time

    import lf as _lf
    if core.store.get_scan(sid) is None:
        raise HTTPException(404, "scan not found")
    trace_id = f"{sid}::{filename}"
    link = _lf.trace_deep_link(trace_id)
    if not link:
        raise HTTPException(404, "tracing is not configured")
    if not _lf.trace_exists(trace_id):
        try:
            from handlers import ensure_assess_trace
            ensure_assess_trace(sid, level)
        except Exception:
            pass
    for _ in range(8):
        if _lf.trace_exists(trace_id):
            break
        time.sleep(0.6)
    return RedirectResponse(link, status_code=302)


@router.get("/scans/{sid}/trace/file/{filename:path}/exists")
def file_trace_exists(sid: str, filename: str):
    """Returns {available: bool} for one file's trace — the file-centric counterpart to
    /trace/{kind}/exists above. Public — no auth needed."""
    import lf as _lf
    return {"available": _lf.trace_exists(f"{sid}::{filename}")}


# ── Per-scan decision snapshots (PRD: time-travel) ────────────────────────────
@router.get("/scans/{sid}/decisions")
def get_decisions(sid: str, request: Request):
    """All persisted decisions for a scan — used to restore state on time-travel."""
    owner = _owner(request)
    if core.store.get_scan(sid, owner=owner) is None:
        raise HTTPException(404, "scan not found")
    return core.store.get_decisions(sid, owner=owner)


@router.put("/scans/{sid}/decisions")
def put_decisions_batch(sid: str, request: Request, body: dict):
    """Batch upsert/delete decisions — body {items: [{file, kind, value}]} (value=null deletes).
    Used by the save effect so a bulk triage is one request, not one-per-file."""
    import datetime as _dt
    import json as _json
    owner = _owner(request)
    if core.store.get_scan(sid, owner=owner) is None:
        raise HTTPException(404, "scan not found")
    when = _dt.datetime.now(_dt.timezone.utc).isoformat()
    n = 0
    for it in (body.get("items") or []):
        file, kind, value = it.get("file"), it.get("kind"), it.get("value")
        if not file or kind not in ("triage", "action"):
            continue
        if value is None:
            core.store.delete_decision(sid, file, kind)
        else:
            core.store.save_decision(sid, file, kind,
                                     value if isinstance(value, str) else _json.dumps(value), owner, when)
        n += 1
    return {"ok": True, "saved": n}


@router.put("/scans/{sid}/decisions/{filename:path}")
def put_decision(sid: str, filename: str, request: Request, body: dict,
                 kind: str = Query("triage", pattern="^(triage|action)$")):
    """Upsert one decision for a file on this scan. body {value}: a string (triage:
    inscope|na|defer) or an object (action: {state, action}); value=null deletes it."""
    import datetime as _dt
    import json as _json
    owner = _owner(request)
    if core.store.get_scan(sid, owner=owner) is None:
        raise HTTPException(404, "scan not found")
    value = body.get("value")
    if value is None:
        core.store.delete_decision(sid, filename, kind)
        return {"ok": True, "deleted": True}
    val = value if isinstance(value, str) else _json.dumps(value)
    core.store.save_decision(sid, filename, kind, val, owner,
                             _dt.datetime.now(_dt.timezone.utc).isoformat())
    return {"ok": True}


@router.get("/scans/{sid}/remediation-status")
def remediation_status(sid: str, request: Request):
    """Live remediation progress (in-flight jobs + latest fixed file) for the bar.
    Owner-scoped — latest_file could otherwise leak another user's filename by scan id."""
    if core.store.get_scan(sid, owner=_owner(request)) is None:
        raise HTTPException(404, "scan not found")
    return core.store.remediation_status(sid)


@router.get("/scans/{sid}/traces")
def scan_traces(sid: str, request: Request, file: str | None = None):
    """Per-rule trace for a scan. Returns one row per (file, rule) pair showing
    PASS/FAIL/SKIP and the finding count. Optionally filter to a single file."""
    if core.store.get_scan(sid, owner=_owner(request)) is None:
        raise HTTPException(404, "scan not found")
    return core.store.get_scan_traces(sid, file=file)


@router.get("/scans/{sid}/diff")
def scan_diff(sid: str, request: Request, vs: str | None = Query(None)):
    """Regression diff (ADR 0009): which documents got worse / better vs a prior scan, and
    the WCAG criteria that flipped pass→fail. Owner-scoped. `vs` defaults to the caller's
    immediately-prior scan."""
    owner = _owner(request)
    if core.store.get_scan(sid, owner=owner) is None:
        raise HTTPException(404, "scan not found")
    if not vs:                                          # default baseline = the prior scan
        ids = [s["id"] for s in core.store.list_scans(owner=owner)]
        i = ids.index(sid) if sid in ids else -1
        vs = ids[i + 1] if 0 <= i and i + 1 < len(ids) else None
    if not vs:
        return {"summary": {"regressed": 0, "improved": 0, "new": 0, "removed": 0},
                "regressed": [], "improved": [], "new": [], "removed": [], "no_baseline": True}
    diff = core.store.get_scan_diff(sid, vs, owner=owner)
    if diff is None:
        raise HTTPException(404, "scan not found")
    return diff


_digest_cache: dict = {}


@router.get("/scans/{sid}/digest")
def scan_digest(sid: str, request: Request, refresh: bool = Query(False)):
    """AI Compliance Digest (bundle #2): an executive paragraph grounded in REAL scan data —
    score, regressions vs the prior scan, the top systemic issue, and a recommended action.
    Deterministic facts + an AI-written narrative (fallback prose if the model is off/down).
    Owner-scoped; cached per scan (the model call is slow)."""
    import ai as _ai
    owner = _owner(request)
    res = core.store.get_scan(sid, owner=owner)
    if res is None:
        raise HTTPException(404, "scan not found")
    if not refresh and sid in _digest_cache:
        return _digest_cache[sid]
    run, files = res["run"], res["files"]
    total = len(files)
    certifiable = sum(1 for f in files if f.get("compliant"))
    # Drift vs the prior scan (reuses the ADR 0009 diff) + the score delta.
    ids = [s["id"] for s in core.store.list_scans(owner=owner)]
    i = ids.index(sid) if sid in ids else -1
    prev_id = ids[i + 1] if 0 <= i and i + 1 < len(ids) else None
    regressed, improved_count, score_delta = [], 0, None
    if prev_id:
        diff = core.store.get_scan_diff(sid, prev_id, owner=owner)
        if diff:
            regressed = diff.get("regressed", [])
            improved_count = diff.get("summary", {}).get("improved", 0)
            prev = core.store.get_scan(prev_id, owner=owner)
            if prev and prev["run"].get("avg_score") is not None and run.get("avg_score") is not None:
                score_delta = run["avg_score"] - prev["run"]["avg_score"]
    # Top systemic issues — criteria failing on the most documents (from per-rule traces).
    fail_by_rule: dict = {}
    for r in core.store.get_scan_traces(sid):
        if str(r.get("outcome", "")).upper() == "FAIL":
            k = r["rule_id"]
            fb = fail_by_rule.setdefault(k, {"sc": k, "name": r.get("plain_name") or r.get("rule_name"), "files": set()})
            fb["files"].add(r["file"])
    top_issues = sorted(
        ({"sc": v["sc"], "name": v["name"], "fail": len(v["files"])} for v in fail_by_rule.values()),
        key=lambda x: -x["fail"])[:3]
    pii = core.store.pii_summary(sid)
    data = {"avg_score": run.get("avg_score"), "total": total, "certifiable": certifiable,
            "regressed": regressed, "improved_count": improved_count, "score_delta": score_delta,
            "top_issues": top_issues, "pii_docs": (pii or {}).get("documents", 0)}
    digest = _ai.compliance_digest(data, ai_enabled=core.store.get_ai_enabled())
    digest["generated_at"] = run.get("completed_at")
    _digest_cache[sid] = digest
    return digest


@router.get("/scans/{sid}/pii")
def scan_pii(sid: str, request: Request):
    """Sensitive-data (PII) findings for a scan (ADR 0006).

    Returns a rollup (documents affected, total items, per-type counts) plus the
    per-document detail. All samples are MASKED — raw PII is never stored or
    returned."""
    if core.store.get_scan(sid, owner=_owner(request)) is None:
        raise HTTPException(404, "scan not found")
    return {"summary": core.store.pii_summary(sid), "files": core.store.list_pii(sid)}


@router.get("/scans/{sid}/manifest")
def scan_manifest(sid: str, request: Request):
    """Rule-execution manifest for a scan.

    Returns per-file completeness: how many rules were expected to run (based on
    the file type's rule catalog), how many ran successfully (PASS or FAIL), and
    how many errored (ENGINE failed to assess that rule). A scan is COMPLETE when
    rules_errored_total == 0. Use this to detect partial assessments before acting
    on a score.
    """
    if core.store.get_scan(sid, owner=_owner(request)) is None:
        raise HTTPException(404, "scan not found")
    return core.store.get_scan_manifest(sid)


@router.get("/scans/{sid}/report.pdf")
def report_pdf(sid: str, request: Request):
    # Owner-scoped. The frontend fetches this WITH the Bearer token (XHR → blob → open),
    # so a plain tokenless <a href> no longer works — that's intentional: it stops anyone
    # pulling another user's full report by guessing/replaying a scan id.
    res = core.store.get_scan(sid, owner=_owner(request))
    if res is None:
        raise HTTPException(404, "scan not found")
    rb = core.active_rubric()
    meta = {"target": rb.cfg.get("conformance_target"), "version": rb.version,
            "hash": res["run"].get("rubric_hash") or rb.hash}
    pdf = build_report(res["run"], res["files"], meta, decisions=core.store.get_decisions(sid))
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
