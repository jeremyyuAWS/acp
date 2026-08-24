"""Scan lifecycle, results, traces, manifest, report, inventory, and per-file
remediation endpoints."""
from __future__ import annotations
import os
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel

import core
from scanner import run_scan
from report import build_report

router = APIRouter()


def _owner(request: Request) -> str:
    """The current user for per-user data isolation — the gate-verified email, or
    'demo' for the keyless/demo path. Matches the owner stamped on scans at creation."""
    return getattr(request.state, "user_email", None) or "demo"


def _inv_capability(row: dict) -> dict:
    """Add the estate capability {format, status} to a scan_inventory row, derived from its mime/name
    the same way estate_inventory.summarize classifies the whole estate — so the per-file list/export
    carries the identical assessable/metadata-only/unsupported label the dashboard shows."""
    import estate_inventory as ei
    c = ei.classify({"id": row.get("drive_file_id"), "name": row.get("file"),
                     "mimeType": row.get("mime")})
    return {**row, "format": c["format"], "status": c["status"]}


@router.post("/scans")
def start_scan(request: Request, source: str = Query(..., pattern="^(local|drive|sharepoint)$"),
               sync: bool = False, folder: str | None = Query(None),
               # Repeatable: ?folders=<id>&folders=<id>. `folder` stays the single-root form, so
               # every existing caller, saved link and already-queued job is unaffected. A
               # SharePoint/OneDrive folder is written `<driveId>/<itemId>` — the pair, because a
               # Graph item id is unique only within its drive.
               folders: list[str] | None = Query(None),
               # Subtrees to carve OUT of the chosen folders — a selected parent with an
               # excluded child (PRD 6.3). Ignored without `folders`, since there is nothing
               # to carve out of and applying them to a whole-estate scan would narrow it
               # invisibly.
               exclude_folders: list[str] | None = Query(None),
               ai: bool = Query(True), queue: bool = Query(False),
               # PII (deep) scan is opt-in: it doubles scan time by extracting + regex-scanning
               # every file's text, so a scan is fast unless the caller explicitly asks for it.
               # The UI mirrors this (deepScan defaults off). Scheduled sweeps / API callers that
               # want sensitive-data detection must pass pii=true.
               pii: bool = Query(False), fanout: bool = Query(False),
               batch: bool = Query(False), exclude_remediated: bool = Query(False),
               incremental: bool = Query(True)):
    token = request.headers.get("x-drive-token")      # per-user Drive token (GIS)
    sp_token = request.headers.get("x-sp-token")      # per-user MS Graph token (MSAL)
    # ACP_DEMO_DRIVE_KEY lets the E2E test and demo scripts trigger a server-side
    # ADC Drive scan without needing per-user GIS — pass as X-Demo-Key header.
    DEMO_KEY = os.environ.get("ACP_DEMO_DRIVE_KEY", "")
    demo_key = request.headers.get("x-demo-key", "")
    # The demo/ADC scan bypass is FAIL-CLOSED (core.TEST_BYPASS_ENABLED): off unless an
    # operator explicitly opts in, and refused in production regardless. It used to key off
    # `not core.IS_PROD`, which was True in production because nothing ever set the env var.
    is_demo_drive = core.TEST_BYPASS_ENABLED and source == "drive" and DEMO_KEY and demo_key == DEMO_KEY
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
            jtype, {"source": source, "scan_id": scan_id, "folder": folder, "folders": folders,
                    "exclude_folders": exclude_folders, "ai": ai,
                    "user": user, "pii": pii, "batch": batch,
                    "exclude_remediated": exclude_remediated, "incremental": incremental},
            scan_id=scan_id)
        return {"scan_id": scan_id, "job_id": job_id, "queued": True,
                "fanout": fanout, "batch": batch, "workers": core.WORKERS,
                # Split topology (#113): the API runs ACP_WORKERS=0 and a standalone worker
                # container carries the pool — report its heartbeat so the client's
                # "no workers" guard doesn't refuse a perfectly manned queue.
                "worker_tier_alive": core.store.worker_tier_alive()}

    if sync:  # synchronous path for scripts/tests
        from handlers import _defer_analysis_to_assess
        if _defer_analysis_to_assess():
            # Metadata-only discovery is the DEFAULT (ADR 0020): list + classify from metadata +
            # persist inventory and STOP — nothing is downloaded or opened. The download + WCAG
            # analysis run when Assess is called on this scan. Delegates to the same _scan_discover
            # the fan-out path uses, so the 'discovered' state (inventory + assess_params) is
            # identical. Set ACP_DEFER_ANALYSIS_TO_ASSESS=0 to force a full download+analyse scan.
            from handlers import _scan_discover
            scan_id = uuid.uuid4().hex[:12]
            core.register_scan_tokens(scan_id, drive=token, sp=sp_token)  # in-memory only
            # `folders`/`exclude_folders` MUST come along. Deferred discovery is the default
            # since #436, so this is the primary path — and a payload that carries only `folder`
            # drops a chosen scope silently: the card says "Scans: HR" and the scan covers the
            # whole Drive. Widening is the one direction nobody re-checks.
            _scan_discover({"source": source, "scan_id": scan_id, "folder": folder,
                            "folders": folders, "exclude_folders": exclude_folders, "ai": ai,
                            "user": user, "pii": pii, "batch": batch,
                            "exclude_remediated": exclude_remediated, "incremental": incremental},
                           {"scan_id": scan_id})
            return {"scan_id": scan_id, "source": source, "discovered": True}
        inv: list = []
        report = run_scan(source, drive_token=token, folder=folder, sp_token=sp_token,
                          **({"folders": folders} if folders else {}),
                          **({"exclude_folders": exclude_folders} if exclude_folders else {}),
                          ai_enabled=effective_ai, user=user, detect_pii=pii,
                          exclude_remediated=exclude_remediated, inventory_out=inv)
        sid = core.store.save_scan(report)
        # Persist per-file inventory + evaluate archival/deletion rules — same as the fanout path.
        from handlers import persist_discovery_inventory
        persist_discovery_inventory(sid, inv, source, user)
        core.finalize_scan(sid, effective_ai, source)
        return {"scan_id": sid, "source": source, "summary": report["summary"]}

    # Default: in-process background thread (fast, but lost on restart).
    job_id = uuid.uuid4().hex[:12]
    # Written through core.set_job/update_job so the poll can be served by ANY replica. Writing
    # straight into the dict is what made ingress session affinity load-bearing, and affinity is
    # what blocks multi-revision mode and therefore blue-green.
    core.set_job(job_id, {"phase": "queued", "files_found": 0, "files_done": 0, "current": None,
                          "done": False, "scan_id": None, "error": None, "source": source,
                          "ai": effective_ai})

    # Liveness heartbeat, separate from progress. The deferred-discovery path below makes exactly
    # one core.update_job call (at the very end) — during the crawl itself, a large estate can go
    # a long time with no progress write, which is indistinguishable from a dead replica unless
    # something else proves the replica is still up. This companion thread does only that: touch
    # updated_at every core._JOB_HEARTBEAT_SECONDS regardless of what work() has found so far, so
    # core.get_job_state's staleness check tracks "is the replica alive" rather than "how big is
    # this estate" — and stops the moment work() ends, one way or another, via the Event below.
    _stop_heartbeat = threading.Event()

    def _heartbeat():
        while not _stop_heartbeat.wait(core._JOB_HEARTBEAT_SECONDS):
            core.update_job(job_id, {})

    def work():
        try:
            from handlers import _defer_analysis_to_assess
            if _defer_analysis_to_assess():
                # Metadata-only discovery is the DEFAULT (ADR 0020): list + classify from metadata
                # + persist inventory and STOP — nothing downloaded. The download + WCAG analysis
                # run when Assess is called. Delegates to the fan-out _scan_discover so the
                # 'discovered' state is identical; tokens stay registered for the later Assess.
                # ACP_DEFER_ANALYSIS_TO_ASSESS=0 forces the legacy full download+analyse scan.
                from handlers import _scan_discover
                sid = uuid.uuid4().hex[:12]
                core.register_scan_tokens(sid, drive=token, sp=sp_token)  # in-memory only
                # Same as the sync branch above: the chosen scope has to travel with the
                # payload or the default scan silently widens to the whole source.
                _scan_discover({"source": source, "scan_id": sid, "folder": folder,
                                "folders": folders, "exclude_folders": exclude_folders, "ai": ai,
                                "user": user, "pii": pii, "batch": batch,
                                "exclude_remediated": exclude_remediated,
                                "incremental": incremental}, {"scan_id": sid})
                core.update_job(job_id, {"phase": "discovered", "done": True, "scan_id": sid})
                return
            inv: list = []
            report = run_scan(source, progress=lambda d: core.update_job(job_id, d),
                              drive_token=token, folder=folder, sp_token=sp_token,
                              **({"folders": folders} if folders else {}),
                              **({"exclude_folders": exclude_folders} if exclude_folders else {}),
                              ai_enabled=effective_ai, user=user, detect_pii=pii,
                              exclude_remediated=exclude_remediated, inventory_out=inv)
            sid = core.store.save_scan(report)
            # Persist per-file inventory + evaluate archival/deletion rules — same as the fanout path,
            # so a default in-process Discover marks Archive/Delete candidates too (not only fanout).
            from handlers import persist_discovery_inventory
            persist_discovery_inventory(sid, inv, source, user)
            core.finalize_scan(sid, effective_ai, source)
            done = core.get_job_state(job_id) or {}
            core.update_job(job_id, {"phase": "done", "done": True, "scan_id": sid,
                                     "files_done": done.get("files_found", 0)})
        except Exception as e:
            core.update_job(job_id, {"phase": "error", "done": True, "error": str(e)})
        finally:
            _stop_heartbeat.set()

    threading.Thread(target=_heartbeat, daemon=True).start()
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
             "remediated_folder_id": remediated_folder_id, "drive_token": token},
            scan_id=sid)
        enqueued.append(jid)
    return {"scan_id": sid, "enqueued": len(enqueued), "job_ids": enqueued,
            "workers": core.WORKERS, "worker_tier_alive": core.store.worker_tier_alive()}


@router.post("/scans/{sid}/cancel")
def cancel_scan(sid: str, request: Request):
    """Stop an in-flight fan-out scan (found live 2026-07-11: there was NO way to stop a
    scan — a wedged one blocked all new scans until the lease sweeper caught up). Kills the
    scan's outstanding jobs and closes the run as 'cancelled'; files already analysed keep
    their records. Owner-scoped: you can only cancel your own scan.

    Falls back to cancel_queued_job when cancel_scan says no: a scan_id issued by the durable
    (queued) start path is real and known to the caller from the moment it's enqueued, but has
    no scan_runs row — and so nothing for cancel_scan to find — until a worker actually claims
    it (found live 2026-08-21: a scan stuck waiting for a worker had no way to be cancelled
    either, the other half of the 2026-07-11 gap this route was built to close)."""
    if core.store.cancel_scan(sid, owner=_owner(request)):
        return {"scan_id": sid, "status": "cancelled"}
    if core.store.cancel_queued_job(sid):
        return {"scan_id": sid, "status": "cancelled", "was_queued": True}
    raise HTTPException(409, "scan not found, not yours, or not running")


@router.get("/scans/jobs/{job_id}")
def scan_job(job_id: str):
    # core.get_job_state, not core.JOBS: the poll must be answerable by whichever replica the
    # request lands on, which is the whole point of removing session affinity.
    j = core.get_job_state(job_id)
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


@router.get("/scans/{sid}/timings")
def scan_timings(sid: str, request: Request):
    """Per-stage timing rollup for one scan (ADR 0037 Step 0 — measure first): where the scan spent its
    time (download vs analyse), the per-stage average seconds, and the bottleneck stage. Owner-scoped via
    the same get_scan gate, so it never reveals another user's scan; a scan with nothing recorded reports
    zeros and bottleneck=null rather than a fabricated number."""
    if core.store.get_scan(sid, owner=_owner(request)) is None:
        raise HTTPException(404, "scan not found")
    return core.store.scan_timings(sid)


@router.get("/scans/{sid}/files/{filename:path}/status")
def get_file_accessibility_status(sid: str, filename: str, request: Request):
    """ADR 0026 — the authoritative Accessibility Status for one file. Derived-at-read over the
    per-file certification facts (the SAME `_rule_outcome` the coverage matrix uses), so the hero
    card can never disagree with the detail. Owner-scoped; always 200 — an unknown scan/file returns
    `{available: false}` so the card degrades rather than erroring."""
    import accessibility_status as _status

    owner = _owner(request)
    if core.store.get_scan(sid, owner=owner) is None:
        return {"available": False, "reason": "scan_not_found"}
    return _status.file_status(core.store, sid, filename)


@router.get("/scans/{sid}/status")
def get_scan_accessibility_status(sid: str, request: Request, prefix: str | None = None):
    """ADR 0026 PR 3 — the Accessibility Status for a whole scan: the per-file models summed and the
    state machine re-derived over the totals (same derivation → the roll-up can never disagree with
    the per-file cards). ?prefix= narrows to a folder (same summation over the subset). Powers the
    scan-level card + the Confidence Dashboard. Owner-scoped, always-200 degrade."""
    import accessibility_status as _status

    if core.store.get_scan(sid, owner=_owner(request)) is None:
        return {"available": False, "reason": "scan_not_found"}
    return _status.scan_status(core.store, sid, path_prefix=prefix or None)


@router.get("/scans/{sid}/live")
def get_live_snapshot(sid: str, request: Request):
    """The authoritative live-run snapshot for the Assess running screen (Live Assessment Experience
    PRD §8): the reconciled file-outcome KPIs (read from the SAME run summary the final cert uses, so
    running can never disagree with final), the eligible denominator, and — when the queue layer is
    present — the live worker/queue block, as ONE owner-scoped object the running screen consumes and
    reconnects against. Always 200: an unknown or foreign scan returns {"available": false} so the
    screen degrades rather than erroring."""
    import datetime as _dt
    import live_snapshot as _ls
    return _ls.build_snapshot(core.store, sid, owner=_owner(request),
                              now_iso=_dt.datetime.now(_dt.timezone.utc).isoformat())


# Server-Sent-Events stream tuning. Interval: how often the server re-reads the run's state (§9 asks
# for 500–2000ms batching — 1s sits in that band). Heartbeat: idle intervals between comment frames
# that keep the connection warm without a data frame. Max iters: a safety ceiling (~30 min) so a run
# that never terminates can't hold a socket forever — the client (SSE) auto-reconnects and resumes.
_STREAM_INTERVAL_S = 1.0
_HEARTBEAT_EVERY = 15
_MAX_STREAM_ITERS = 1800


@router.get("/scans/{sid}/events")
async def stream_live_events(sid: str, request: Request):
    """Server-Sent-Events stream of the live-run snapshot (Live Assessment Experience PRD §8): the SAME
    authoritative object /scans/{sid}/live returns, PUSHED as it changes instead of polled. The server
    tails the run's persisted state; a `data:` frame is emitted only when the snapshot's content
    changes (generated_at aside), a comment frame keeps the connection warm between changes, and the
    stream sends a final frame then closes when the run reaches a terminal state (or the client
    disconnects, or the safety ceiling trips). Owner-scoped. Reconnect is free: SSE auto-reconnects and
    the first frame is the current snapshot, carrying the same `sequence` the client dedupes on. No
    worker changes — reconciles with /live by construction (same builder)."""
    import asyncio
    import datetime as _dt
    import json as _json
    import live_snapshot as _ls

    owner = _owner(request)

    async def _gen():
        last_sig = None
        idle = 0
        for _ in range(_MAX_STREAM_ITERS):
            if await request.is_disconnected():
                return
            now = _dt.datetime.now(_dt.timezone.utc).isoformat()
            # build_snapshot is sync DB work — run it off the event loop so one stream can't block others.
            snap = await asyncio.to_thread(_ls.build_snapshot, core.store, sid, owner, now)
            sig = _ls.snapshot_signature(snap)
            if sig != last_sig:
                last_sig = sig
                idle = 0
                yield f"data: {_json.dumps(snap)}\n\n"
            else:
                idle += 1
                if idle >= _HEARTBEAT_EVERY:
                    idle = 0
                    yield ": keep-alive\n\n"
            # Terminal: an unknown/foreign scan, or a run no longer active — the final frame is already
            # out, so close. The client sees the terminal snapshot and stops reconnecting.
            if not snap.get("available") or not snap.get("active"):
                return
            await asyncio.sleep(_STREAM_INTERVAL_S)

    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                                      "X-Accel-Buffering": "no"})


@router.get("/scans/{sid}/files/{filename:path}/examined")
def get_examined_counts(sid: str, filename: str, request: Request):
    """Engine-reported examined-element counts for one document (ADR 0026 Epic 2): the classify()
    inventory persisted at scan time — a real walk of the package/PDF, so the manifest can say
    "of N images examined" honestly. Owner-scoped, always-200 degrade ({available:false} when the
    document was never classified)."""
    if core.store.get_scan(sid, owner=_owner(request)) is None:
        return {"available": False, "reason": "scan_not_found"}
    row = core.store.get_document_examined(filename)
    if not row:
        return {"available": False, "reason": "not_classified"}
    return {"available": True, "pages": row.get("pages"), "images": row.get("images"),
            "has_text": bool(row.get("has_text")), "is_scanned": bool(row.get("is_scanned"))}


@router.post("/scans/{sid}/files/{filename:path}/confirm")
async def confirm_review_criterion(sid: str, filename: str, request: Request):
    """Confirm-the-pass (ADR 0026 / Epic 3): record a human's verification of a 🟡 review
    criterion. Body: {"sc": "1.4.11", "note": "..."} — writes the same immutable hitl.approved
    decision the review queue writes, so every downstream surface (status buckets, certification
    facts, Assessment Timeline) picks it up unchanged. Guarded: only a REVIEW-outcome criterion can
    be confirmed (a FAIL needs a fix, not a signature). Owner-scoped."""
    import accessibility_status as _status

    owner = _owner(request)
    if core.store.get_scan(sid, owner=owner) is None:
        raise HTTPException(404, "scan not found")
    try:
        body = await request.json()
    except Exception:
        body = {}
    return _status.confirm_review_criterion(
        core.store, sid, filename, (body.get("sc") or "").strip(), owner, body.get("note"))


@router.post("/scans/{sid}/assess")
def assess(sid: str, request: Request, level: str = Query("AA"),
           include_lifecycle_flagged: bool = Query(False)):
    """Run the assessment. In the deferred-analysis model (ADR 0020) a Discover-only scan has an
    inventory but no assessed file_records yet, so this KICKS OFF the download+WCAG fan-out (the
    heavy work now lives here, not in Discover) — assessed_at is stamped when that analysis
    finalizes. In the immediate model it just marks assessed + builds the assess trace, as before.
    Both enqueue to the durable worker."""
    scan = core.store.get_scan(sid, owner=_owner(request))
    if scan is None:
        raise HTTPException(404, "scan not found")
    import datetime as _dt
    # Deferred: analysis hasn't run yet (inventory present, no assessed rows, scan 'discovered').
    # Start it; do NOT mark assessed here — that happens at finalize when results actually exist.
    deferred_pending = (
        (scan.get("run", {}).get("status") == "discovered")
        and core.store.count_inventory(sid) > 0
        and core.store.get_setting(f"assess_params:{sid}") is not None
    )
    if deferred_pending:
        # include_lifecycle_flagged (PRD §4.5) is the authorized override that pulls
        # archive/delete-flagged files back into Assess. This route already gates on the scan
        # owner (get_scan owner=... above), so reaching here IS the owner-gate.
        # Phase 3a freeze: if no scope was captured at discover time (operator configured it
        # after the discover ran), freeze the current operator scope NOW before enqueuing so
        # _scan_assess / analyse_and_assess read the intended criteria, not an open slate.
        if core.store.get_scan_scope(sid) is None:
            from assessment_policy import active_scope as _active_scope, scope_as_json as _scope_as_json
            _live = _active_scope(core.store)
            if _live:
                core.store.merge_scan_scope(sid, {"scan_scope": _scope_as_json(_live)})
        jid = core.store.enqueue_job(
            "scan_assess",
            {"scan_id": sid, "user": _owner(request),
             "include_lifecycle_flagged": include_lifecycle_flagged}, scan_id=sid)
        return {"scan_id": sid, "level": level, "job_id": jid, "workers": core.WORKERS,
                "worker_tier_alive": core.store.worker_tier_alive(),
                "phase": "assessing", "deferred": True}
    # Immediate model — the results views gate on assessed_at; stamp it + build the assess trace.
    core.store.mark_assessed(sid, _dt.datetime.now(_dt.timezone.utc).isoformat())
    jid = core.store.enqueue_job("assess_trace", {"scan_id": sid, "level": level}, scan_id=sid)
    return {"scan_id": sid, "level": level, "job_id": jid, "workers": core.WORKERS}


@router.get("/scans/{sid}/trace/session/data")
def session_trace_data(sid: str):
    """Data source for the IN-APP session panel: the whole scan's Langfuse session (every file's
    trace) fetched server-side (lf.fetch_session) and returned as a PHI-safe list + rollup, so ACP
    renders the aggregate inline. This is the view that hung the Langfuse UI on large scans; in-app
    it is a plain, capped list ACP controls. Honest states like the file /data route:
      • {"status": "not_configured"} — tracing keys absent
      • {"status": "pending"}        — session not ingested yet
      • {"status": "ok", "session": …}
    Registered BEFORE the literal /trace/session and the /trace/{kind} wildcard (registration
    order), though its two-segment suffix already keeps it unambiguous. Public — read-only."""
    import lf as _lf
    if core.store.get_scan(sid) is None:
        raise HTTPException(404, "scan not found")
    if not _lf.enabled():
        return {"status": "not_configured"}
    data = _lf.fetch_session(sid)
    if data is None:
        return {"status": "pending"}
    return {"status": "ok", "session": data}


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


# MUST be registered BEFORE open_file_trace below: that route's {filename:path} is a greedy
# catch-all (`.*`) that also matches ".../{file}/data", and Starlette returns the first
# matching route — so a later /data route would be shadowed and 302 to Langfuse instead of
# serving JSON. Declaring it first lets the trailing literal /data win. (The same greedy match
# already shadows /exists above; that route is best-effort and the SPA tolerates it, so it is
# left as-is rather than reordered in this change.)
@router.get("/scans/{sid}/trace/file/{filename:path}/data")
def file_trace_data(sid: str, filename: str, level: str = Query("AA")):
    """Data source for the IN-APP trace panel: the file's Langfuse trace fetched
    server-side (lf.fetch_trace) and returned as PHI-safe JSON, so ACP renders it
    inline with no Langfuse login. Langfuse's own trace page hangs for logged-out
    users on our self-hosted v3 and sends X-Frame-Options: SAMEORIGIN, so it can be
    neither linked-to nor iframed — this is the replacement.

    Honest states, never a 500 for a missing trace:
      • {"status": "not_configured"} — tracing keys absent
      • {"status": "pending"}        — trace not ingested yet (async after flush)
      • {"status": "ok", "trace": …} — the normalized trace
    Public — read-only apart from the same best-effort assess-trace rebuild the
    redirect route does, so a never-opened Assess trace still materializes."""
    import lf as _lf
    if core.store.get_scan(sid) is None:
        raise HTTPException(404, "scan not found")
    if not _lf.enabled():
        return {"status": "not_configured"}
    trace_id = f"{sid}::{filename}"
    data = _lf.fetch_trace(trace_id)
    if data is None:
        try:
            from handlers import ensure_assess_trace
            ensure_assess_trace(sid, level)
        except Exception:
            pass
        import time
        for _ in range(5):
            time.sleep(0.6)
            data = _lf.fetch_trace(trace_id)
            if data is not None:
                break
    if data is None:
        return {"status": "pending"}
    return {"status": "ok", "trace": data}


# MUST be registered BEFORE open_file_trace (its {filename:path} is a greedy catch-all that also
# matches ".../{file}/history"). `filename` here is the trace-facing document LABEL (what the trace
# panel holds as `document`), not a raw filename — lf.fetch_document_history uses it as-is.
@router.get("/scans/{sid}/trace/file/{filename:path}/history")
def file_trace_history(sid: str, filename: str):
    """CROSS-SCAN history for one document: its trace in every scan it appears in, newest first —
    the "this document over time" view Langfuse's own session-grouped UI cannot give. Honest states
    like the /data route: {status: not_configured | pending | ok}. Public — read-only."""
    import lf as _lf
    if core.store.get_scan(sid) is None:
        raise HTTPException(404, "scan not found")
    if not _lf.enabled():
        return {"status": "not_configured"}
    data = _lf.fetch_document_history(filename)
    if data is None:
        return {"status": "pending"}
    return {"status": "ok", "history": data}


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
        if not file or kind not in ("triage", "action", "assignee", "due_date"):
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
                 kind: str = Query("triage", pattern="^(triage|action|assignee|due_date)$")):
    """Upsert one decision for a file on this scan. body {value}: a string (triage:
    inscope|na|defer; assignee: the assignee's email; due_date: an ISO date, R19) or an object
    (action: {state, action}); value=null deletes it."""
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
    Owner-scoped — latest_file could otherwise leak another user's filename by scan id.

    Also carries `activity`: the one line naming the file, the criterion and the action currently
    in flight. The counts answer "how much is left"; a queue depth of 3 tells a user nothing about
    whether their document is being OCR'd, waiting on a vision model, or stuck. Served from the
    same poll rather than a new endpoint, so the bar that already exists gains a line without the
    UI gaining a second timer."""
    if core.store.get_scan(sid, owner=_owner(request)) is None:
        raise HTTPException(404, "scan not found")
    import activity
    out = core.store.remediation_status(sid)
    out["activity"] = activity.current(sid)
    return out


@router.get("/scans/{sid}/source-status")
def source_status(sid: str, request: Request):
    """Has each file's SOURCE changed in Drive since ACP scanned it?

    Compares the source's CURRENT modifiedTime (fetched now with the caller's read-only Drive
    creds) to the baseline captured at scan time (file_records.source_modified). Owner-scoped.

    A file with no baseline or no Drive id — and EVERY file when the scan's source isn't Drive —
    is 'untracked', never a false 'unchanged'. A source that 404s/403s is 'unavailable', not
    stale; one unreadable file never fails the batch. The Drive service is built lazily, so a scan
    with nothing trackable answers without needing a Drive token at all."""
    import source_staleness as _ss
    scan = core.store.get_scan(sid, owner=_owner(request))
    if scan is None:
        raise HTTPException(404, "scan not found")
    files = scan.get("files") or []
    source_is_drive = (scan.get("run") or {}).get("source") == "drive"
    trackable = source_is_drive and any(f.get("source_modified") and f.get("drive_file_id") for f in files)
    svc = core.drive_service(request) if trackable else None   # 401 in GIS mode without X-Drive-Token
    from googleapiclient.errors import HttpError
    rows = []
    for f in files:
        baseline, drive_id = f.get("source_modified"), f.get("drive_file_id")
        if not source_is_drive or not drive_id or not baseline:
            row = _ss.classify_file(f, None, source_is_drive=source_is_drive)
        else:
            current, err = None, None
            try:
                current = svc.files().get(fileId=drive_id, fields="modifiedTime",
                                          supportsAllDrives=True).execute().get("modifiedTime")
            except HttpError as e:
                status = getattr(getattr(e, "resp", None), "status", None)
                err = "not_found" if status == 404 else "forbidden" if status == 403 else "drive_error"
            except Exception:
                err = "drive_error"   # a bad file must never 500 the batch
            row = _ss.classify_file(f, current, source_is_drive=source_is_drive, fetch_error=err)
        rows.append({"file": f["file"], "drive_file_id": drive_id, **row})
    count = lambda st: sum(1 for r in rows if r["state"] == st)
    return {"scan_id": sid, "stale_count": count("stale"), "untracked_count": count("untracked"),
            "unavailable_count": count("unavailable"), "files": rows}


@router.get("/scans/{sid}/inventory")
def scan_inventory_list(sid: str, request: Request,
                        offset: int = Query(0, ge=0),
                        limit: int = Query(200, ge=1, le=1000)):
    """The whole per-file discover inventory, paginated — EVERY discovered file with its source
    metadata (owner, size, path, dates, lifecycle) plus the estate capability (format/status),
    owner-scoped. This is the full list the capped 200/status dashboard sample could not provide
    (ADR 0020): `total` is the real count, page through it with offset/limit. Export via the
    `.csv` sibling. NB: the estate `status` is derived per row, so filtering by it is a client
    concern for now — a server-side status filter needs the classification persisted (follow-up)."""
    if core.store.get_scan(sid, owner=_owner(request)) is None:
        raise HTTPException(404, "scan not found")
    rows = core.store.list_inventory_page(sid, limit=limit, offset=offset)
    return {"scan_id": sid, "total": core.store.count_inventory(sid),
            "offset": offset, "limit": limit,
            "rows": [_inv_capability(r) for r in rows]}


@router.get("/scans/{sid}/inventory.csv")
def scan_inventory_csv(sid: str, request: Request):
    """The whole per-file estate inventory as CSV (owner-scoped) — every discovered file, source
    metadata + capability, for offline analysis / an auditor. Not paginated: it IS the export."""
    if core.store.get_scan(sid, owner=_owner(request)) is None:
        raise HTTPException(404, "scan not found")
    import csv
    import io
    # lifecycle_rule_id/lifecycle_reason/lifecycle_override_* were missing here even though
    # store.list_inventory already selects them (_INV_COLS) — an auditor exporting the estate saw
    # THAT a file was tagged (lifecycle_status) but not WHICH rule tagged it, WHY, or whether a
    # human overrode the recommendation (lifecycle rules #8). Added alongside lifecycle_status,
    # not in place of it.
    cols = ["file", "owner", "size_kb", "mime", "format", "status", "doc_class",
            "lifecycle_status", "lifecycle_rule_id", "lifecycle_reason",
            "lifecycle_override_reason", "lifecycle_overridden_by", "lifecycle_overridden_at",
            "path", "parent_folder", "created_at", "source_modified",
            "discovered_at", "drive_file_id"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in core.store.list_inventory(sid):
        e = _inv_capability(r)
        w.writerow([e.get(c, "") if e.get(c) is not None else "" for c in cols])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="inventory-{sid}.csv"'})


@router.get("/scans/{sid}/files/{filename:path}/remediation-state")
def file_remediation_state(sid: str, filename: str, request: Request):
    """Per-violation remediation state (ADR 0003 Phase 2) for one file — which specific
    WCAG rules were auto-fixed vs. still open, so the UI can distinguish a criterion that
    always passed from one that passes because remediation fixed it."""
    if core.store.get_scan(sid, owner=_owner(request)) is None:
        raise HTTPException(404, "scan not found")
    return core.store.get_remediation_state_for_file(sid, filename)


@router.get("/scans/{sid}/traces")
def scan_traces(sid: str, request: Request, file: str | None = None):
    """Per-rule trace for a scan. Returns one row per (file, rule) pair showing
    PASS/FAIL/SKIP and the finding count. Optionally filter to a single file."""
    if core.store.get_scan(sid, owner=_owner(request)) is None:
        raise HTTPException(404, "scan not found")
    return core.store.get_scan_traces(sid, file=file)


@router.get("/scans/{sid}/timeline")
def scan_timeline(sid: str, request: Request, file: str = Query(...)):
    """Audit trail (maturity Phase 4): the chronological provenance of one document in this
    scan — scanned → AI drafted → human decided → fix written → published — assembled from
    rows the pipeline already persists. Owner-scoped like every per-scan surface."""
    if core.store.get_scan(sid, owner=_owner(request)) is None:
        raise HTTPException(404, "scan not found")
    return core.store.document_timeline(sid, file)


class LifecycleOverrideIn(BaseModel):
    reason: str


@router.post("/scans/{sid}/files/{filename:path}/lifecycle-override")
def override_file_lifecycle(sid: str, filename: str, body: LifecycleOverrideIn, request: Request):
    """Lifecycle rules #8: record a human's reasoned disagreement with a rule's Archive/Delete
    Candidate recommendation for ONE file. A reason is required — an undocumented override is
    exactly the unaccountable state this exists to prevent (same discipline as W4's
    DispositionControl). It does not change the file's lifecycle_status: like every other
    lifecycle surface, this is itself only a recommendation, not an action.

    Writes BOTH audit tables, the same dual-write convention every other disposition route
    follows: `disposition_audit` (the audit_id-precise, action-typed record) and `log_decision`
    (the file-scoped record `document_timeline`/the Assessment Timeline drawer already reads —
    this is what makes the override show up in a file's existing audit history without a new
    viewer)."""
    if core.store.get_scan(sid, owner=_owner(request)) is None:
        raise HTTPException(404, "scan not found")
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(422, "a reason is required — it becomes part of the audit record")
    owner = _owner(request)
    prior = core.store.override_lifecycle(sid, filename, reason=reason, actor=owner)
    if prior is None:
        raise HTTPException(409, "this file has no archive/delete recommendation to override")
    rule_id = prior.get("lifecycle_rule_id")
    doc_id = f"scan:{sid}:{filename}"
    if rule_id:
        core.store.create_disposition_audit(uuid.uuid4().hex, doc_id=doc_id, policy_id=rule_id,
            action="tag", result="overridden", detail=reason, owner_email=owner)
    core.store.log_decision(owner, "disposition.file_overridden", scan_id=sid, file=filename,
        rule_id=rule_id, detail=reason)
    return core.store.get_lifecycle_status(sid, filename)


@router.get("/scans/{sid}/comments")
def list_finding_comments(sid: str, request: Request, finding_key: str = Query(...)):
    """R18 · Comments on a finding — the human discussion thread for ONE finding, oldest first.
    Owner-scoped like every per-scan surface: a user reads only their own scans' threads."""
    if core.store.get_scan(sid, owner=_owner(request)) is None:
        raise HTTPException(404, "scan not found")
    return core.store.list_finding_comments(sid, finding_key)


@router.get("/scans/{sid}/comment-counts")
def finding_comment_counts(sid: str, request: Request):
    """How many comments each finding in the scan carries, keyed by finding_key — so the inbox
    can show a '💬 n' marker without fetching every thread. Owner-scoped."""
    if core.store.get_scan(sid, owner=_owner(request)) is None:
        raise HTTPException(404, "scan not found")
    return core.store.count_finding_comments(sid)


@router.post("/scans/{sid}/comments")
async def add_finding_comment(sid: str, request: Request):
    """R18 · Post one comment to a finding's thread. Body: {"finding_key": "...", "body": "...",
    "file": "...", "rule_id": "..."}. The author is the signed-in user, never the client — so a
    comment cannot be attributed to someone else. Append-only; empty bodies are rejected."""
    owner = _owner(request)
    if core.store.get_scan(sid, owner=owner) is None:
        raise HTTPException(404, "scan not found")
    try:
        body = await request.json()
    except Exception:
        body = {}
    finding_key = (body.get("finding_key") or "").strip()
    text = (body.get("body") or "").strip()
    if not finding_key:
        raise HTTPException(422, "finding_key is required")
    if not text:
        raise HTTPException(422, "comment body is required")
    return core.store.add_finding_comment(
        sid, finding_key, owner, text,
        file=(body.get("file") or "").strip(), rule_id=(body.get("rule_id") or "").strip())


@router.get("/scans/{sid}/applied-fixes")
def scan_applied_fixes(sid: str, request: Request):
    """The concrete values AI fixes wrote this scan (vision-generated alt text + a small
    image thumbnail), newest first — so 'Recent AI fixes' can show what was really applied
    instead of a canned template. Owner-scoped."""
    if core.store.get_scan(sid, owner=_owner(request)) is None:
        raise HTTPException(404, "scan not found")
    return core.store.list_applied_fixes(sid)


@router.get("/scans/{sid}/ai_calls")
def scan_ai_calls(sid: str, request: Request):
    """The AI provenance ledger for a scan (ADR 0019 Phase 0b) — one row per model call with its
    surface, provider, model, privacy zone (local vs cloud), latency, and outcome, newest first.
    This is the auditable answer to 'what model saw my document, where did it run, how long did it
    take?' that the review card's audit panel and the certification record surface. Owner-scoped."""
    if core.store.get_scan(sid, owner=_owner(request)) is None:
        raise HTTPException(404, "scan not found")
    return core.store.list_ai_calls(sid)


@router.post("/scans/{sid}/files/{filename:path}/undo-fix")
async def undo_fix(sid: str, filename: str, request: Request):
    """R15 — undo one deterministic fix ACP claims to have applied to this file.

    Body: {"rule_id": "1.1.1"}. There is no file to restore: remediation only ever produces a
    SEPARATE corrected copy (ensure_remediated_folder), never overwriting the source, so this
    cannot mean 'put the bytes back' — it means ACP stops claiming the finding is fixed. See
    store.undo_applied_fix for exactly what that clears. Owner-scoped like every other
    remediation route; 404s the same way as an unknown/foreign scan, 400 for a missing rule_id."""
    if core.store.get_scan(sid, owner=_owner(request)) is None:
        raise HTTPException(404, "scan not found")
    try:
        body = await request.json()
    except Exception:
        body = {}
    rule_id = str(body.get("rule_id") or "").strip()
    if not rule_id:
        raise HTTPException(400, "rule_id required")
    undone = core.store.undo_applied_fix(sid, filename, rule_id)
    return {"undone": undone}


@router.get("/scans/{sid}/files/{filename:path}/remediation-diffs")
def file_remediation_diffs(sid: str, filename: str, request: Request):
    """Per-fix before→after evidence for one file — the original text/markup and the
    remediated version of every deterministic fix that verifiably cleared. Feeds the
    certification PDF's 'Before → After' section. Owner-scoped like remediation-state."""
    if core.store.get_scan(sid, owner=_owner(request)) is None:
        raise HTTPException(404, "scan not found")
    return core.store.get_remediation_diffs(sid, filename)


@router.get("/scans/{sid}/remediation-diffs")
def scan_remediation_diffs(sid: str, request: Request):
    """Scan-wide before→after evidence — every verified-cleared fix across all files, so the
    Remediation view can group REAL applied fixes by rule/category (image descriptions,
    reading order, titles, headings, tables) without inventing counts. Covers all fix types,
    unlike applied-fixes (image alt text only). Owner-scoped."""
    if core.store.get_scan(sid, owner=_owner(request)) is None:
        raise HTTPException(404, "scan not found")
    return core.store.list_remediation_diffs(sid)


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


@router.get("/scans/{sid}/inventory-diff")
def scan_inventory_diff(sid: str, request: Request, vs: str | None = Query(None)):
    """Discovery diff: what this run's inventory gained, lost and changed vs a prior run of the
    SAME SOURCE.

    Deliberately not `/diff`, which compares `file_records` — the assessed grain, empty for an
    ADR 0020 Discover-only run. This reads `scan_inventory`, so it answers for the runs a source
    operations panel is actually about.

    THE BASELINE IS PER-SOURCE, and that is the difference that matters here. `/diff` defaults
    `vs` to the caller's immediately-prior scan across every source, which is the right default
    for "did my estate regress" and the wrong one for "what did OneDrive find this time": with
    two connectors alternating, the prior scan is routinely the OTHER source, and every file in
    it would read as removed while every file in this one reads as new. So the default walks back
    to the previous run of this run's own source, and returns `no_baseline` when there is none
    rather than diffing against something unrelated.

    An explicit `vs` is honoured as given — the caller may have a better baseline in mind (the
    drawer passes the prior run it is already displaying) — but is still owner-scoped by
    get_inventory_diff.
    """
    owner = _owner(request)
    run = core.store.get_scan(sid, owner=owner)
    if run is None:
        raise HTTPException(404, "scan not found")
    if not vs:
        vs = core.store.previous_run_for_source(sid, owner=owner)
    if not vs:
        return {"summary": {"new": 0, "changed": 0, "removed": 0, "unchanged": 0,
                            "not_listed": 0, "indeterminate": 0},
                "new": [], "changed": [], "removed": [], "not_listed": [], "indeterminate": [],
                "no_baseline": True}
    diff = core.store.get_inventory_diff(sid, vs, owner=owner)
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
    pdf = build_report(res["run"], res["files"], meta, decisions=core.store.get_decisions(sid),
                       evidence=core.store.get_remediation_evidence(sid),
                       facts=core.store.get_certification_facts(sid, apply_document_selection=True))
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


@router.post("/scans/{sid}/rescore")
def rescore_file(sid: str, request: Request, file: str = Query(...)):
    """Re-download and re-analyse ONE file that a user fixed externally, then refresh the
    scan aggregate. Enqueues a rescore_file worker job and returns its id for polling."""
    scan = core.store.get_scan(sid, owner=_owner(request))
    if scan is None:
        raise HTTPException(404, "scan not found")
    run = scan.get("run", {})
    source = run.get("source", "local")
    drive_token = request.headers.get("x-drive-token")
    jid = core.store.enqueue_job(
        "rescore_file",
        {"scan_id": sid, "file": file, "source": source,
         "drive_token": drive_token, "user": _owner(request)},
        scan_id=sid,
    )
    return {"scan_id": sid, "file": file, "job_id": jid, "workers": core.WORKERS,
            "worker_tier_alive": core.store.worker_tier_alive()}


@router.post("/scans/{sid}/drive-token")
def refresh_scan_drive_token(sid: str, request: Request):
    """Refresh the Drive token of a RUNNING scan (ADR 0014). GIS access tokens expire ~1h;
    the frontend silently re-mints one and POSTs it here so a scan that outlasts the token
    keeps its Drive auth. Owner-checked; updates the ephemeral per-scan token store that
    scan_file/scan_batch workers re-read on every job."""
    if core.store.get_scan(sid, owner=_owner(request)) is None:
        raise HTTPException(404, "scan not found")
    token = request.headers.get("x-drive-token")
    if not token:
        raise HTTPException(422, "x-drive-token header required")
    core.register_scan_tokens(sid, drive=token)
    return {"scan_id": sid, "refreshed": True}


@router.post("/scans/{sid}/sp-token")
def refresh_scan_sp_token(sid: str, request: Request):
    """Refresh the SharePoint token of a RUNNING scan. MSAL tokens expire ~1h; the frontend
    silently re-acquires one and POSTs it here so a scan that outlasts the token keeps its
    SharePoint auth. Owner-checked; updates the ephemeral per-scan token store."""
    if core.store.get_scan(sid, owner=_owner(request)) is None:
        raise HTTPException(404, "scan not found")
    token = request.headers.get("x-sp-token")
    if not token:
        raise HTTPException(422, "x-sp-token header required")
    core.register_scan_tokens(sid, sp=token)
    return {"scan_id": sid, "refreshed": True}


@router.delete("/scans/{sid}/tokens")
def clear_scan_tokens(sid: str, request: Request):
    """Clear the token store for a scan — called on sign-out so a running scan's worker does not
    keep stale Drive/SharePoint credentials after the user has signed out. Best-effort: a 404
    (scan finished or never existed) is treated as success since the goal is just to not leave
    tokens around."""
    if core.store.get_scan(sid, owner=_owner(request)) is None:
        return {"scan_id": sid, "cleared": True}
    core.clear_scan_tokens(sid)
    return {"scan_id": sid, "cleared": True}


@router.post("/scans/{sid}/publish")
def publish_files(sid: str, request: Request, body: dict):
    """Publish one or more re-validated files — ADR 0010 archive-copy, NON-destructive.
    The fixed copy (durable in Blob) is placed in a distinct Drive "Published (Accessible)"
    folder as the official document-of-record; the original source file is never
    overwritten. Records published_at + the published Drive URL. Absent Drive token /
    read-only grant / no Blob copy → record-only publish (Blob stays the durable copy).
    Body: {"files": ["fname1", "fname2"]} or {"file": "fname"}."""
    if core.store.get_scan(sid, owner=_owner(request)) is None:
        raise HTTPException(404, "scan not found")
    files = body.get("files") or ([body["file"]] if body.get("file") else [])
    if not files:
        raise HTTPException(422, "provide 'file' or 'files' in body")
    # Best-effort Drive service + published folder, resolved once for the batch.
    token = request.headers.get("x-drive-token")
    owner_email = (core.store.get_scan(sid) or {}).get("run", {}).get("owner_email")
    import publish as _publish
    svc = folder_id = None
    if token:
        try:
            import handlers
            svc = handlers._drive_client(token)
            folder_id = _publish.ensure_published_folder(svc)
        except Exception:
            svc = folder_id = None
    results = []
    for f in files:
        url = _publish.archive_copy_publish(svc, folder_id, owner_email, sid, f)
        ts = core.store.record_publish(sid, f, published_url=url)
        results.append({"file": f, "published_at": ts, "published_url": url})
    return {"published": results}


@router.get("/scans/{scan_id}/files/{filename:path}/remediated")
def get_remediated_file(scan_id: str, filename: str, request: Request):
    """Stream a remediated file's fixed bytes (ADR 0010): Blob first (the durable source
    of truth), falling back to a redirect to the Drive mirror copy for a pre-ADR-0010
    remediation that only ever wrote there. 404 if neither exists."""
    import blob as _blob
    owner = _owner(request)
    # OWNERSHIP FIRST, like every other per-scan route. This endpoint was the one that did not,
    # and it was exploitable: `get_remediation_urls` has no owner predicate, the blob read below
    # is correctly scoped and so returns None for a foreign document, and the Drive fall-through
    # then handed the caller a link to somebody else's remediated file. Measured, not theorised —
    # tests/test_remediated_download_isolation.py redirected an allow-listed non-owner (307) to
    # the owner's Drive URL before this line existed.
    #
    # 404 rather than 403, matching tests/test_foreign_scan_404.py: a non-owner must not be able
    # to confirm the scan exists. That also closes the oracle — "wrong filename" and "not your
    # scan" were distinguishable (404 vs 307), which leaks which documents a scan contains.
    # "scan not found" verbatim: tests/test_scan_not_found_detail.py pins every owner-check 404
    # in this router to that exact string, because the SPA only recovers from that one. It also
    # gives the property this check needs — a non-owner gets the same answer for a foreign scan
    # as for one that never existed, so the response tells them nothing either way.
    if core.store.get_scan(scan_id, owner=owner) is None:
        raise HTTPException(404, "scan not found")
    urls = core.store.get_remediation_urls(scan_id, filename, owner=owner)
    src_scan_id, src_file = scan_id, filename
    if not urls or not (urls.get("blob_url") or urls.get("drive_write_url")):
        # ADR 0011: an incremental re-scan mints a new scan_id and, for an unchanged file,
        # never re-remediates — so the fixed copy (Blob object + DB record) lives under the
        # scan_id that actually ran the remediation. Both are scan_id-keyed, so resolve the
        # document across this owner's scans and stream from where the bytes really are.
        alt = core.store.find_remediation_for_file(owner, scan_id, filename)
        if not alt or not (alt.get("blob_url") or alt.get("drive_write_url")):
            raise HTTPException(404, "no remediated copy recorded for this file")
        urls, src_scan_id, src_file = alt, alt["scan_id"], alt["file"]
    data = _blob.download_remediated(owner, src_scan_id, src_file)
    if data is not None:
        ext = src_file.rsplit(".", 1)[-1].lower() if "." in src_file else "bin"
        mime_map = {"html": "text/html", "htm": "text/html", "pdf": "application/pdf",
                    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}
        return Response(data, media_type=mime_map.get(ext, "application/octet-stream"))
    if urls.get("drive_write_url"):
        return RedirectResponse(urls["drive_write_url"])
    raise HTTPException(404, "remediated copy recorded but not retrievable "
                             "(Blob not configured and no Drive mirror)")


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


def _source_bytes_for_render(request: Request, scan_id: str, filename: str, owner: str) -> bytes | None:
    """Best-effort original bytes to rasterize for a preview (ADR 0015), tried cheapest-first
    and preferring the *original* the reviewer is looking at over the remediated copy:
      1. local corpus file  (source=local — the demo default; no token, on disk)
      2. Drive original      (via drive_file_id + a live x-drive-token)
      3. remediated blob copy (post-remediation fallback; accessibility fixes are structurally
         near-identical to the original page, so it's an acceptable last resort)
    Returns None if none are reachable — the caller then 404s. Never raises."""
    scan = core.store.get_scan(scan_id, owner=owner)
    source = (scan or {}).get("run", {}).get("source")

    if source == "local":
        try:
            import scanner
            corpus = Path(os.environ.get("ACP_LOCAL_CORPUS") or (scanner.ACP / "test-corpus/files"))
            p = corpus / filename
            if p.is_file():
                return p.read_bytes()
        except Exception:
            pass

    drive_file_id = core.store.get_file_drive_id(scan_id, filename)
    if drive_file_id:
        try:
            svc = core.drive_service(request)
            return svc.files().get_media(fileId=drive_file_id).execute()
        except Exception:
            pass

    try:
        import blob as _blob
        return _blob.download_remediated(owner, scan_id, filename)
    except Exception:
        return None


@router.get("/scans/{scan_id}/files/{filename:path}/thumbnail")
def get_file_thumbnail(scan_id: str, filename: str, request: Request,
                       fresh: int = Query(0)):
    """Serve a page-1 PNG preview of a file (ADR 0015): blob cache → render-on-demand →
    cache → serve. Opt-in and non-blocking — any miss or failure is a 404, never a 500, and
    nothing here touches scan/remediate/report. PDF only in phase 1; Office → 404 → the UI
    shows a placeholder. ?fresh=1 bypasses the cache read (forced re-render)."""
    import blob as _blob
    import render as _render

    owner = _owner(request)
    if core.store.get_scan(scan_id, owner=owner) is None:
        raise HTTPException(404, "scan not found")

    ext = os.path.splitext(filename)[1].lower()
    if not _render.can_render(ext):
        raise HTTPException(404, "no preview available for this file type")

    if not fresh:
        cached = _blob.download_render(owner, scan_id, filename)
        if cached is not None:
            return Response(cached, media_type="image/png",
                            headers={"Cache-Control": "private, max-age=86400"})

    data = _source_bytes_for_render(request, scan_id, filename, owner)
    if not data:
        raise HTTPException(404, "source document not retrievable for preview")

    png = _render.render_page1_png(data, ext)
    if not png:
        raise HTTPException(404, "could not render a preview for this document")

    _blob.upload_render(owner, scan_id, filename, png)  # best-effort cache; never raises
    return Response(png, media_type="image/png",
                    headers={"Cache-Control": "private, max-age=86400"})


@router.get("/scans/{scan_id}/files/{filename:path}/page/{page}")
def get_file_page(scan_id: str, filename: str, page: int, request: Request,
                  fresh: int = Query(0)):
    """Serve a PNG of page N of a file — the rendering primitive the Intelligent Review
    Workspace's 'locate in document' evidence uses. Same blob-cache → render-on-demand →
    cache → serve as the thumbnail; the renderer clamps `page` to the document's real range.
    PDF only in phase 1 (Office → 404 → placeholder). Owner-scoped, non-blocking."""
    import blob as _blob
    import render as _render

    owner = _owner(request)
    if core.store.get_scan(scan_id, owner=owner) is None:
        raise HTTPException(404, "scan not found")

    ext = os.path.splitext(filename)[1].lower()
    if not _render.can_render(ext):
        raise HTTPException(404, "no preview available for this file type")

    page = max(1, min(int(page or 1), 5000))          # sane bound; renderer clamps to real range
    cache_key = f"{filename}#p{page}"                  # page-specific blob cache entry
    if not fresh:
        cached = _blob.download_render(owner, scan_id, cache_key)
        if cached is not None:
            return Response(cached, media_type="image/png",
                            headers={"Cache-Control": "private, max-age=86400"})

    data = _source_bytes_for_render(request, scan_id, filename, owner)
    if not data:
        raise HTTPException(404, "source document not retrievable for preview")

    png = _render.render_page_png(data, ext, page)
    if not png:
        raise HTTPException(404, "could not render this page")

    _blob.upload_render(owner, scan_id, cache_key, png)   # best-effort cache; never raises
    return Response(png, media_type="image/png",
                    headers={"Cache-Control": "private, max-age=86400"})


@router.get("/scans/{scan_id}/files/{filename:path}/geometry")
def get_file_geometry(scan_id: str, filename: str, request: Request,
                      locator: str = Query(...)):
    """Normalized bounding box `{page, x, y, w, h}` (fractions of the page) for the shape a
    finding's `part#rId` locator names — the rectangle the frontend overlays on the page render
    (ADR 0018 Slice 2). Owner-scoped and non-blocking: a shape whose geometry can't be attributed
    (grouped/inherited transform, a non-pptx format, a bad locator) returns `{"bbox": null}` — a
    200 with no box, so the card degrades to the plain large preview, never an error. Honesty rule
    (ADR 0016): a real measured rectangle or nothing — the box is never guessed."""
    import render as _render

    owner = _owner(request)
    if core.store.get_scan(scan_id, owner=owner) is None:
        raise HTTPException(404, "scan not found")

    ext = os.path.splitext(filename)[1].lower()
    # Only formats we can both render AND read geometry from are worth resolving bytes for.
    if not _render.can_render(ext):
        return {"bbox": None}

    data = _source_bytes_for_render(request, scan_id, filename, owner)
    if not data:
        return {"bbox": None}

    import geometry as _geom
    return {"bbox": _geom.shape_bbox(data, ext, locator)}


@router.get("/scans/{scan_id}/files/{filename:path}/heading-outline")
def get_heading_outline(scan_id: str, filename: str, request: Request):
    """The docx heading outline `{before,after}` for a heading finding's Structure evidence — the
    document's real styled headings in order, and a never-skip correction of them. docx-only (a PDF
    exposes heading PRESENCE, not an extractable outline, exactly as geometry is pptx/xlsx-only).
    Owner-scoped and non-blocking: any other format, a doc with fewer than two headings, or an
    outline that already nests correctly returns `{"outline": null}` — a 200 with nothing, so the
    card degrades to the honest generic note rather than erroring. Honesty (ADR 0016): real extracted
    headings + a deterministic renumber, never a fabricated tree."""
    owner = _owner(request)
    if core.store.get_scan(scan_id, owner=owner) is None:
        raise HTTPException(404, "scan not found")
    ext = os.path.splitext(filename)[1].lower()
    if ext != ".docx":
        return {"outline": None}
    data = _source_bytes_for_render(request, scan_id, filename, owner)
    if not data:
        return {"outline": None}
    import doc_structure as _ds
    return {"outline": _ds.heading_outline(data, ext)}


@router.get("/scans/{scan_id}/files/{filename:path}/table-structure")
def get_table_structure(scan_id: str, filename: str, request: Request):
    """The docx table(s) as `{tables:[{rows, headerRow, headerMarked, truncated}]}` for a
    header-association finding's (1.3.1) Structure evidence — real cell text, which row is the header,
    and whether that row is actually marked so a screen reader announces it. docx-only, owner-scoped,
    non-blocking: any other format, or a doc with no qualifying (multi-row, multi-column) table,
    returns `{"tables": null}` (a 200) so the card degrades to the honest generic note. Honesty
    (ADR 0016): extracted table content only — no fabricated grid, no invented header."""
    owner = _owner(request)
    if core.store.get_scan(scan_id, owner=owner) is None:
        raise HTTPException(404, "scan not found")
    ext = os.path.splitext(filename)[1].lower()
    if ext != ".docx":
        return {"tables": None}
    data = _source_bytes_for_render(request, scan_id, filename, owner)
    if not data:
        return {"tables": None}
    import doc_structure as _ds
    result = _ds.table_structure(data, ext)
    return {"tables": (result or {}).get("tables") if result else None}


# A reviewer opening one 1.4.3-hybrid card shouldn't trigger dozens of slide renders; bound the
# work per request (the OCR-cap precedent). A deck with more hybrid shapes than this reports the
# cap honestly (`checked` < `total`) rather than silently covering only some.
_TIER_B_SHAPE_CAP = 8


@router.get("/scans/{scan_id}/files/{filename:path}/verify-contrast")
def get_file_verify_contrast(scan_id: str, filename: str, request: Request,
                             locator: str = Query(None)):
    """ADR 0024 Tier B.1 — render-verified 1.4.3-hybrid contrast, ON DEMAND. The Tier-A scan flags
    "text over a picture/gradient fill — contrast unknowable from the file"; this endpoint renders
    the offending shape's page (ADR 0018 seam) and MEASURES the contrast from the actual pixels,
    upgrading the 🟡 flag from "possible" to "measured".

    With no `locator` it RE-DERIVES the hybrid shapes from the source and measures each (up to a
    per-request cap) — so the card needs only the file, and nothing is persisted at rest (ADR 0024,
    no schema change). A `locator` measures one named shape.

    View-time only — never in the bulk scan (same deferred posture as the thumbnail/geometry). Owner
    -scoped and always 200: every degrade (render disabled, no LibreOffice, unattributable geometry,
    ambiguous busy background) returns a `measured: false` shape, so the card falls back to the
    Tier-A 🟡, never an error and never a certified pass (ADR 0016). pptx only in B.1."""
    import office_structure as _off
    import render as _render
    import render_verify as _rv

    owner = _owner(request)
    if core.store.get_scan(scan_id, owner=owner) is None:
        raise HTTPException(404, "scan not found")

    ext = os.path.splitext(filename)[1].lower()
    if ext != ".pptx":
        return {"measured": False, "reason": "unsupported_format"}
    if not (_render.office_render_enabled() and _render.can_render(ext)):
        return {"measured": False, "reason": "render_unavailable"}

    data = _source_bytes_for_render(request, scan_id, filename, owner)
    if not data:
        return {"measured": False, "reason": "source_unavailable"}

    # One named shape → the single measurement (used by a per-shape "verify" action).
    if locator:
        return _rv.measure_hybrid_contrast(data, ext, locator)

    # No locator → re-derive every render-attributable hybrid shape and measure each, capped.
    targets = [t for t in _off.hybrid_contrast_locators(data) if t.get("shape")]
    if not targets:
        return {"measured": False, "reason": "no_hybrid_shapes"}
    shapes = []
    for t in targets[:_TIER_B_SHAPE_CAP]:
        m = _rv.measure_hybrid_contrast(data, ext, f"{t['part']}#{t['shape']}")
        shapes.append({"shape": t["shape"], "kind": t["kind"], **m})
    ok = [s for s in shapes if s.get("measured") and isinstance(s.get("ratio"), (int, float))]
    if not ok:
        # Nothing measurable (busy backgrounds / unattributable) — honest abstain, not a pass.
        return {"measured": False, "reason": "ambiguous_background",
                "checked": len(shapes), "total": len(targets)}
    worst = min(ok, key=lambda s: s["ratio"])
    return {"measured": True, "shapes": shapes,
            "worst_ratio": worst["ratio"], "worst_shape": worst["shape"],
            "any_fail_aa": any(not s["passes_aa"] for s in ok),
            "checked": len(shapes), "total": len(targets)}


@router.get("/scans/{scan_id}/files/{filename:path}/verify-resize")
def get_file_verify_resize(scan_id: str, filename: str, request: Request,
                           locator: str = Query(None)):
    """ADR 0024 Tier B.2 — render-verified 1.4.4 Resize Text, ON DEMAND. The Tier-A scan flags a
    fixed-size (auto-fit off) text box holding a lot of text — "may clip at 200%". This renders the
    box and MEASURES how much of it the text already fills: enlarging to 200% needs ≥2× the current
    text height, so a box already over half full overflows.

    Same posture as verify-contrast: view-time only, pptx-only, owner-scoped, always 200, re-derives
    targets from source (no schema change), degrades to the Tier-A 🟡. A measured overflow is
    actionable; measured headroom still says "verify" (rewrapping may clip) — never a certified pass."""
    import office_structure as _off
    import render as _render
    import render_verify as _rv

    owner = _owner(request)
    if core.store.get_scan(scan_id, owner=owner) is None:
        raise HTTPException(404, "scan not found")

    ext = os.path.splitext(filename)[1].lower()
    if ext != ".pptx":
        return {"measured": False, "reason": "unsupported_format"}
    if not (_render.office_render_enabled() and _render.can_render(ext)):
        return {"measured": False, "reason": "render_unavailable"}

    data = _source_bytes_for_render(request, scan_id, filename, owner)
    if not data:
        return {"measured": False, "reason": "source_unavailable"}

    if locator:
        return _rv.measure_resize_headroom(data, ext, locator)

    targets = [t for t in _off.resize_text_locators(data) if t.get("shape")]
    if not targets:
        return {"measured": False, "reason": "no_fixed_boxes"}
    boxes = []
    for t in targets[:_TIER_B_SHAPE_CAP]:
        m = _rv.measure_resize_headroom(data, ext, f"{t['part']}#{t['shape']}")
        boxes.append({"shape": t["shape"], **m})
    ok = [b for b in boxes if b.get("measured") and isinstance(b.get("height_frac"), (int, float))]
    if not ok:
        return {"measured": False, "reason": "no_text_measured",
                "checked": len(boxes), "total": len(targets)}
    worst = max(ok, key=lambda b: b["height_frac"])   # fullest box = closest to overflowing
    return {"measured": True, "boxes": boxes,
            "worst_fill": worst["height_frac"], "worst_shape": worst["shape"],
            "any_overflow_at_200": any(b["overflows_at_200"] for b in ok),
            "checked": len(boxes), "total": len(targets)}


@router.get("/scans/{scan_id}/files/{filename:path}/verify-pdf-contrast")
def get_file_verify_pdf_contrast(scan_id: str, filename: str, request: Request):
    """ADR 0025 Tier B — render-verified 1.4.3 text-over-image contrast for PDF, ON DEMAND. The
    scan-time detector flags "text sits over an image — declared colour can't prove contrast"; this
    renders the offending page (pdfium, no LibreOffice needed) and MEASURES the text-vs-image
    contrast from the pixels, upgrading the 🟡 flag from "possible" to "measured".

    Re-derives the text runs from the source bytes (no schema change, ADR 0024/0025 posture), so the
    card needs only the file. View-time only — never in the bulk scan. Owner-scoped and always 200:
    every degrade (not a PDF, pdfium missing, busy background) returns `measured: false`, so the card
    falls back to the scan-time 🟡, never an error and never a certified pass (ADR 0016). Unlike the
    Office Tier B endpoints this needs no `ACP_OFFICE_RENDER` — pdfium rasterizes PDF unconditionally."""
    import pdf_render_verify as _prv
    import render as _render

    owner = _owner(request)
    if core.store.get_scan(scan_id, owner=owner) is None:
        raise HTTPException(404, "scan not found")

    ext = os.path.splitext(filename)[1].lower()
    if ext != ".pdf":
        return {"measured": False, "reason": "unsupported_format"}
    if not _render.can_render(ext):
        return {"measured": False, "reason": "render_unavailable"}

    data = _source_bytes_for_render(request, scan_id, filename, owner)
    if not data:
        return {"measured": False, "reason": "source_unavailable"}

    return _prv.measure_pdf_over_image_contrast(data)
