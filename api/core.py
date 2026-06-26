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
# Production mode: hard-disables the test/demo auth bypasses (X-E2E-Key, X-Demo-Key)
# regardless of whether their keys are set — defence in depth, so a stray env var
# can't reopen a backdoor in prod. Set ACP_ENV=production on production deployments.
IS_PROD = os.environ.get("ACP_ENV", "").lower() in ("production", "prod")
# Smoke/e2e test key: requests with X-E2E-Key bypass auth. Only honoured when
# IS_PROD is false AND the key is set — inert in production.
E2E_KEY = (os.environ.get("ACP_E2E_KEY") or None) if not IS_PROD else None
# Comma-separated domains allowed in GIS mode. DENY-BY-DEFAULT: empty unless the
# operator configures ACP_ALLOWED_DOMAINS, so a fresh deploy admits no one until
# explicitly opened to a domain.
ALLOWED_DOMAINS = [
    d.strip() for d in os.environ.get("ACP_ALLOWED_DOMAINS", "").split(",") if d.strip()
]
# Comma-separated individual emails allowed in GIS mode, in addition to the
# domains above. Lets you permit a specific outside account (e.g. a personal
# gmail used for a demo) without opening the whole gmail.com domain.
ALLOWED_EMAILS = {
    e.strip().lower() for e in os.environ.get("ACP_ALLOWED_EMAILS", "").split(",") if e.strip()
}


def email_allowed(email: str) -> bool:
    """True if an email passes the allow-list: the env baseline (ACP_ALLOWED_EMAILS,
    a bootstrap so the owner is never locked out), the runtime list managed from
    Settings, or an allowed domain."""
    email = (email or "").lower()
    if email in ALLOWED_EMAILS:
        return True
    try:
        if email in store.get_allowlist():
            return True
    except Exception:
        pass
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
ALWAYS_PUBLIC = {"/healthz", "/config", "/hub", "/ai/status", "/alerts/webhook"}
# Shared secret for the Grafana alert webhook (public path, key-validated).
ALERT_KEY = os.environ.get("ACP_ALERT_KEY", "acp-alert-demo-key")
# API routes require auth; everything else is the SPA (static file or client route).
API_PREFIXES = (
    "/scans", "/rubric", "/rules", "/inventory", "/schedule",
    "/me", "/sources", "/folders", "/drive", "/hitl", "/ai",
    "/settings", "/decisions", "/jobs", "/workers", "/admin",
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
    """Emit a Langfuse span for the remediation write-back (Step 6) on its OWN trace —
    keyed off the scan id with a '-remediate' suffix, so it never muddies the Step 1–2
    scan trace. One span per fixed document; the trace accumulates them."""
    try:
        import lf as _lf
        lf = _lf.client()
        if lf is None:
            return
        trace = lf.trace(
            id=f"{scan_id}-remediate",
            name="Step 6 · Remediate",
            tags=["accessibility-remediation", "step:6"],
            metadata={"scan_id": scan_id, "workflow_step": "6 · Remediate"},
        )
        trace.span(
            name=filename,
            input={"file": filename},
            output={"drive_write_url": drive_write_url, "written_to_drive": drive_write_url is not None},
            metadata={"workflow_step": "6 · Remediate"},
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
_worker_seq = 0          # monotonic id source so scaled-in workers get fresh ids
_MAX_WORKERS = 16        # safety cap on live scaling


def _spawn_worker() -> None:
    import threading
    from worker import JobWorker
    global _worker_seq
    w = JobWorker(store, worker_id=f"w{_worker_seq}")
    t = threading.Thread(target=w.run_forever, daemon=True, name=f"jobworker-{_worker_seq}")
    _worker_seq += 1
    t.start()
    _worker_handles.append((w, t))


def set_worker_count(n: int) -> int:
    """Scale the in-process worker pool to n live workers (spawn or stop threads).
    Stopped workers finish their current job before exiting. Persisted so a restart
    keeps the chosen size. Returns the new live count."""
    global WORKERS
    n = max(0, min(int(n), _MAX_WORKERS))
    import handlers  # noqa: F401 — ensure job handlers are registered before spawning
    cur = len(_worker_handles)
    if n > cur:
        for _ in range(n - cur):
            _spawn_worker()
    elif n < cur:
        for w, _t in _worker_handles[n:]:
            w.stop()                       # exits after the current job (if any)
        del _worker_handles[n:]
    WORKERS = n
    try:
        store.set_setting("worker_count", str(n))
    except Exception:
        pass
    return len(_worker_handles)


def reset_langfuse_traces() -> int:
    """Best-effort: delete all traces in the ACP Langfuse project via the public
    API. Returns the count deleted (0 if Langfuse isn't configured, or its version
    doesn't support trace deletion — the Postgres reset still works regardless)."""
    import lf as _lf
    host, pk, sk = _lf._HOST, _lf._PK, _lf._SK
    if not (host and pk and sk):
        return 0
    import base64
    import httpx
    auth = {"Authorization": "Basic " + base64.b64encode(f"{pk}:{sk}".encode()).decode()}
    deleted = 0
    try:
        with httpx.Client(timeout=30) as c:
            ids: list[str] = []
            for page in range(1, 101):                       # cap at 10k traces
                r = c.get(f"{host}/api/public/traces",
                          params={"limit": 100, "page": page}, headers=auth)
                r.raise_for_status()
                data = r.json().get("data", [])
                ids += [t["id"] for t in data if t.get("id")]
                if len(data) < 100:
                    break
            for i in range(0, len(ids), 100):                # bulk delete in batches
                resp = c.request("DELETE", f"{host}/api/public/traces",
                                 json={"traceIds": ids[i:i + 100]}, headers=auth)
                if resp.status_code < 300:
                    deleted += len(ids[i:i + 100])
    except Exception:
        pass
    return deleted


# Per-scan auth tokens for the worker pool. With REDIS_URL set they live in Redis
# with a short TTL — SHARED across replicas, so a scan enqueued on one replica is
# processable by a worker on another (enables horizontal scaling). Without it they
# live in process memory (single replica). Either way tokens are NEVER written to
# Postgres; Redis is transient (TTL + no persistence). A job carries only scan_id.
_TOKEN_TTL = 3600                         # GIS tokens live ~1h and don't refresh
SCAN_TOKENS: dict[str, dict] = {}          # in-memory fallback
REDIS_URL = os.environ.get("REDIS_URL", "")
_redis = None


def _get_redis():
    global _redis
    if not REDIS_URL:
        return None
    if _redis is None:
        import redis
        _redis = redis.Redis.from_url(REDIS_URL, decode_responses=True,
                                      socket_timeout=3, socket_connect_timeout=3)
    return _redis


def register_scan_tokens(scan_id: str, *, drive: str | None = None, sp: str | None = None) -> None:
    toks = {}
    if drive:
        toks["drive"] = drive
    if sp:
        toks["sp"] = sp
    if not toks:
        return
    r = _get_redis()
    if r is not None:
        try:
            import json as _j
            r.set(f"scantok:{scan_id}", _j.dumps(toks), ex=_TOKEN_TTL)
            return
        except Exception:
            pass                          # fall through to in-memory
    SCAN_TOKENS[scan_id] = toks


def get_scan_tokens(scan_id: str) -> dict:
    r = _get_redis()
    if r is not None:
        try:
            import json as _j
            v = r.get(f"scantok:{scan_id}")
            if v:
                return _j.loads(v)
        except Exception:
            pass
    return SCAN_TOKENS.get(scan_id, {})


def clear_scan_tokens(scan_id: str) -> None:
    r = _get_redis()
    if r is not None:
        try:
            r.delete(f"scantok:{scan_id}")
        except Exception:
            pass
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
    """Spawn the worker pool + a stuck-job sweeper. Pool size = the persisted
    worker_count setting if set (live-scaled via the UI), else ACP_WORKERS.
    No-op when the resolved size is 0."""
    global WORKERS
    if _worker_handles:
        return len(_worker_handles)
    import threading
    import handlers  # noqa: F401 — registers job handlers with the worker
    try:
        saved = store.get_setting("worker_count")
        target = int(saved) if saved not in (None, "") else WORKERS
    except Exception:
        target = WORKERS
    WORKERS = max(0, min(target, _MAX_WORKERS))
    for _ in range(WORKERS):
        _spawn_worker()

    # Always start the sweeper (even at 0 workers) so a later live scale-up is covered.
    def _sweep():
        import time as _t
        while True:
            try:
                # 30-min lease: scans of large estates legitimately run ~10-15min,
                # so reclaim only clearly-dead jobs. The worker heartbeat (best-effort)
                # extends this further; this is the reliable floor if it can't.
                n = store.reclaim_stuck_jobs(lease_seconds=1800)
                if n:
                    print(f"[sweeper] reclaimed {n} stuck job(s)", flush=True)
            except Exception as e:
                print(f"[sweeper] error: {e}", flush=True)
            _t.sleep(60)
    threading.Thread(target=_sweep, daemon=True, name="jobsweeper").start()
    return WORKERS
