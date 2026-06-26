"""Shared state, config, and helpers for the acp control plane.

Everything that the route modules (routes/*.py) and the access-gate middleware
need in common lives here: env config, the Store singleton, the in-memory JOBS
map, GIS token verification, the Drive client factory, the scheduler, and the
Langfuse remediation span. The route modules import from this module; this module
imports no route module (no cycles).
"""
from __future__ import annotations
import os
import sys
import time as _time
from pathlib import Path

# Resolve sibling modules (scanner/store/rubric/report/ai/lf) and ../scripts.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from apscheduler.schedulers.background import BackgroundScheduler

from scanner import run_scan
from store import Store
from rubric import Rubric

ACP = Path(__file__).resolve().parent.parent

# ── Config (env) ──────────────────────────────────────────────────────────────
ACCESS_CODE = os.environ.get("ACP_ACCESS_CODE")
GOOGLE_CLIENT_ID = os.environ.get("ACP_GOOGLE_CLIENT_ID") or None
# Smoke/e2e test key: requests with X-E2E-Key matching this value bypass auth.
# Set ACP_E2E_KEY in the container env — leave unset in production if not needed.
E2E_KEY = os.environ.get("ACP_E2E_KEY") or None
# Comma-separated domains allowed in GIS mode (default: movate.com).
ALLOWED_DOMAINS = [
    d.strip() for d in os.environ.get("ACP_ALLOWED_DOMAINS", "movate.com").split(",") if d.strip()
]
# Comma-separated individual emails allowed in GIS mode, in addition to the
# domains above. Lets you permit a specific outside account (e.g. a personal
# gmail used for a demo) without opening the whole gmail.com domain.
ALLOWED_EMAILS = {
    e.strip().lower() for e in os.environ.get("ACP_ALLOWED_EMAILS", "").split(",") if e.strip()
}


def email_allowed(email: str) -> bool:
    """True if an email passes the GIS allow-list (exact email OR allowed domain)."""
    email = (email or "").lower()
    if email in ALLOWED_EMAILS:
        return True
    return any(email.endswith("@" + d.lower()) for d in ALLOWED_DOMAINS)
DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
]
HITL_WEBHOOK = os.environ.get("HITL_WEBHOOK_URL", "")

# ── Shared singletons ─────────────────────────────────────────────────────────
store = Store()
JOBS: dict[str, dict] = {}


def active_rubric() -> Rubric:
    return Rubric.load_active(ACP / "config")


# ── GIS token verification (cached) ───────────────────────────────────────────
# token → (email, monotonic_expiry). Tokens live 1h; we cache 9 min.
_gis_cache: dict[str, tuple[str, float]] = {}


def verify_gis_token(token: str) -> str | None:
    now = _time.monotonic()
    cached = _gis_cache.get(token)
    if cached:
        email, exp = cached
        if now < exp:
            return email
        del _gis_cache[token]
    import urllib.request as _ur
    import json as _json
    try:
        with _ur.urlopen(
            f"https://www.googleapis.com/oauth2/v1/tokeninfo?access_token={token}",
            timeout=5,
        ) as r:
            data = _json.load(r)
    except Exception:
        return None
    if "error" in data:
        return None
    email = data.get("email", "")
    _gis_cache[token] = (email, now + 540)
    return email


# ── Access-gate path policy ───────────────────────────────────────────────────
# Paths that bypass all auth (needed before the user has a token).
ALWAYS_PUBLIC = {"/healthz", "/config", "/hub", "/ai/status"}
# API routes require auth; everything else is the SPA (static file or client route).
API_PREFIXES = (
    "/scans", "/rubric", "/rules", "/inventory", "/schedule",
    "/me", "/sources", "/folders", "/drive", "/hitl", "/ai",
    "/settings", "/decisions", "/jobs",
)


def is_public(path: str) -> bool:
    if path in ALWAYS_PUBLIC:
        return True
    if any(path == p or path.startswith(p + "/") for p in API_PREFIXES):
        return False
    return True


# ── Drive client factory ──────────────────────────────────────────────────────
def drive_service(request=None):
    """Drive client for the request. A per-user GIS token (X-Drive-Token) scans that
    user's Drive; otherwise ADC (demo identity). In GIS mode a token is required."""
    from fastapi import HTTPException
    from googleapiclient.discovery import build
    token = request.headers.get("x-drive-token") if request is not None else None
    if token:
        import datetime as _dt
        from google.oauth2.credentials import Credentials
        creds = Credentials(token=token, scopes=DRIVE_SCOPES)
        # GIS tokens are short-lived (1 h) and have no refresh_token. Set an expiry
        # so the client never attempts refresh; Drive returns 401 if it actually
        # expired. google-auth stores expiry as NAIVE UTC and compares it to a
        # naive utcnow() — an aware value raises an offset-naive/aware TypeError.
        creds.expiry = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None) + _dt.timedelta(hours=1)
    elif GOOGLE_CLIENT_ID:
        raise HTTPException(401, "sign in with Google to connect your Drive")
    else:
        import google.auth
        creds, _ = google.auth.default(scopes=DRIVE_SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


# ── HITL webhook ──────────────────────────────────────────────────────────────
def fire_webhook(items: list[dict]) -> None:
    """POST new HITL items to the configured webhook URL (best-effort, non-blocking)."""
    if not HITL_WEBHOOK or not items:
        return
    import threading

    def _post():
        try:
            import httpx
            httpx.post(HITL_WEBHOOK, json={"event": "hitl.queued", "items": items}, timeout=8)
        except Exception as e:
            print(f"HITL webhook failed: {e}", flush=True)
    threading.Thread(target=_post, daemon=True).start()


# ── Langfuse remediation span ─────────────────────────────────────────────────
def emit_remediation_span(scan_id: str, filename: str, drive_write_url: str | None):
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


# ── Background scheduler (periodic local scans) ───────────────────────────────
scheduler = BackgroundScheduler()
scheduler.start()


def _do_scheduled_scan():
    try:
        report = run_scan("local")
        store.save_scan(report)
        print(f"scheduled scan complete: {report['summary']['files']} files", flush=True)
    except Exception as e:
        print(f"scheduled scan failed: {e}", flush=True)


def reload_scheduler():
    cfg = store.get_schedule()
    scheduler.remove_all_jobs()
    if cfg["enabled"] and cfg["interval_minutes"] > 0:
        scheduler.add_job(_do_scheduled_scan, "interval",
                          minutes=cfg["interval_minutes"],
                          id="scheduled_local_scan",
                          coalesce=True, max_instances=1)


reload_scheduler()


# ── Async job-queue worker pool (ADR 0004) ────────────────────────────────────
# Opt-in: set ACP_WORKERS>0 to run N in-process worker threads that drain the
# `jobs` table (async assess + remediation). Off by default so existing behavior
# is unchanged until the handlers + enqueue paths are wired.
WORKERS = int(os.environ.get("ACP_WORKERS", "0") or "0")
_worker_handles: list = []

# In-memory per-scan auth tokens for the worker pool. Tokens are NEVER written to
# the jobs table (which lives in Postgres) — a scan job carries only the scan_id
# and the worker looks the tokens up here. Lost on restart (an in-flight per-user
# scan then fails and must be re-triggered); demo/ADC scans need no token.
SCAN_TOKENS: dict[str, dict] = {}


def register_scan_tokens(scan_id: str, *, drive: str | None = None, sp: str | None = None) -> None:
    toks = {}
    if drive:
        toks["drive"] = drive
    if sp:
        toks["sp"] = sp
    if toks:
        SCAN_TOKENS[scan_id] = toks


def get_scan_tokens(scan_id: str) -> dict:
    return SCAN_TOKENS.get(scan_id, {})


def clear_scan_tokens(scan_id: str) -> None:
    SCAN_TOKENS.pop(scan_id, None)


def finalize_scan(scan_id: str, effective_ai: bool, source: str) -> None:
    """Shared post-scan step: audit the run and, in deterministic mode, auto-route
    ai-assisted findings to the HITL queue. Used by both the threaded and queued
    scan paths so they behave identically."""
    store.log_decision(
        "system", "scan.completed", scan_id=scan_id,
        detail=f"source={source} mode={'ai-assisted' if effective_ai else 'deterministic'}")
    if not effective_ai:
        created = store.queue_hitl_items(scan_id)
        if created:
            fire_webhook(created)
            store.log_decision(
                "system", "hitl.auto_routed", scan_id=scan_id,
                detail=f"deterministic mode → {len(created)} ai-assisted findings routed to HITL")


def start_workers() -> int:
    """Spawn the worker pool + a stuck-job sweeper. No-op when ACP_WORKERS<=0."""
    if WORKERS <= 0 or _worker_handles:
        return 0
    import threading
    import handlers  # noqa: F401 — registers job handlers with the worker
    from worker import JobWorker
    for i in range(WORKERS):
        w = JobWorker(store, worker_id=f"w{i}")
        t = threading.Thread(target=w.run_forever, daemon=True, name=f"jobworker-{i}")
        t.start()
        _worker_handles.append((w, t))

    def _sweep():
        import time as _t
        while True:
            try:
                n = store.reclaim_stuck_jobs(lease_seconds=600)
                if n:
                    print(f"[sweeper] reclaimed {n} stuck job(s)", flush=True)
            except Exception as e:
                print(f"[sweeper] error: {e}", flush=True)
            _t.sleep(60)
    threading.Thread(target=_sweep, daemon=True, name="jobsweeper").start()
    return WORKERS
