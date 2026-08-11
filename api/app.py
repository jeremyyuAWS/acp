"""acp control-plane API — application entrypoint.

Thin assembly layer: creates the FastAPI app, installs the access-gate
middleware, includes the route modules (routes/*.py), and mounts the built SPA.
All shared state and helpers live in core.py; the endpoints live in routes/.

Run:  uvicorn app:app --host 0.0.0.0 --port 8077

Endpoint groups (see routes/):
  system  — /healthz /config /schedule /hub
  rubric  — /rubric /rules
  scans   — /scans* /inventory + per-file remediation
  drive   — /me /sources /folders /drive/upload
  hitl    — /hitl/queue*
  ai      — /ai/explain /ai/status
"""
from __future__ import annotations
import base64
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

import core
from routes import ROUTERS

app = FastAPI(title="acp — accessibility compliance API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def _access_gate(request, call_next):
    """Public-deploy access gate. With ACP_ACCESS_CODE set, every non-public request
    needs HTTP Basic auth matching it; with ACP_GOOGLE_CLIENT_ID set, every non-public
    request needs a valid GIS Bearer token for an allowed domain. No-op when neither
    is set (local dev). X-E2E-Key bypasses the gate for smoke tests when ACP_E2E_KEY
    is configured."""
    if core.E2E_KEY and request.headers.get("x-e2e-key") == core.E2E_KEY:
        return await call_next(request)
    if core.is_public(request.url.path):
        return await call_next(request)
    if core.ACCESS_CODE:
        ok = False
        hdr = request.headers.get("authorization", "")
        if hdr.startswith("Basic "):
            try:
                ok = base64.b64decode(hdr[6:]).decode().split(":", 1)[1] == core.ACCESS_CODE
            except Exception:
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="acp"'})
    elif core.GOOGLE_CLIENT_ID:
        hdr = request.headers.get("authorization", "")
        if not hdr.startswith("Bearer "):
            return Response(status_code=401, media_type="application/json",
                            content='{"detail":"Sign in required"}')
        # The SPA tags Microsoft sign-ins with X-Auth-Provider so we verify against the right
        # issuer (Graph) rather than trying Google first and paying a failed round-trip on every
        # Microsoft request. Absent the header we default to Google — the original behaviour.
        provider = request.headers.get("x-auth-provider", "").lower()
        if provider == "microsoft":
            email = core.verify_ms_token(hdr[7:])
        else:
            email = core.verify_gis_token(hdr[7:])
        if not email:
            return Response(status_code=401, media_type="application/json",
                            content='{"detail":"Session expired — sign in again"}')
        if not core.email_allowed(email):
            return Response(status_code=403, media_type="application/json",
                            content='{"detail":"Access restricted to authorized accounts"}')
        request.state.user_email = email   # so routes can attribute the scan (Langfuse user)
    return await call_next(request)


for _router in ROUTERS:
    app.include_router(_router)


@app.on_event("startup")
def _start_job_workers():
    """Open the database, arm and start the scheduler, then start the workers — in that order.

    Nothing here happens at import any more. core.store is lazy (built on first use), so the
    database is opened and the schema/allowlist bootstrap runs here rather than being paid for
    by the first HTTP request — and a boot-time failure surfaces at startup instead of as a 500
    on some route. reload_scheduler() reads the schedule out of that store, so it must follow
    it; the scheduler thread then starts with its jobs already pending."""
    core.get_store()
    _announce_isolation_mode()
    core.reload_scheduler()
    core.start_scheduler()
    n = core.start_workers()
    if n:
        print(f"[acp] started {n} async job worker(s)", flush=True)


def _announce_isolation_mode() -> None:
    """Say out loud whether per-user data isolation is ON. It is the right behaviour in a demo
    and a serious misconfiguration for a tenant, and until now the two were indistinguishable.

    `_owner()` reads request.state.user_email, which only the `elif GOOGLE_CLIENT_ID` branch of
    the access gate sets. So with ACCESS_CODE set — or with neither configured — every user
    resolves to the single owner 'demo' and shares one estate: one person's remediated documents
    are readable by anyone else who can sign in. For a hospital that is patient-record
    disclosure, not a preference.

    Two ways to arrive here without meaning to, both silent before this:
      * ACCESS_CODE and GOOGLE_CLIENT_ID are an if/ELIF. Setting an access code on a deployment
        that HAS Google configured does not add a second factor — it takes the first branch and
        stops user_email being stamped at all, turning isolation off as a side effect.
      * deploy/compose/docker-compose.yml defaults ACP_GOOGLE_CLIENT_ID to empty, so a
        customer-VPC install from that file runs shared-estate unless someone supplies it.

    Printed, not raised. Refusing to boot would be the fail-closed choice for production and is
    worth considering, but it can lock out a running deployment, so that stays a deliberate
    decision rather than a side effect of this change.
    """
    isolated = bool(core.GOOGLE_CLIENT_ID) and not core.ACCESS_CODE
    if isolated:
        print("[acp] per-user data isolation: ON (owner = verified sign-in email)", flush=True)
        return
    why = ("ACP_ACCESS_CODE is set, so the gate never stamps a user email"
           if core.ACCESS_CODE else "no ACP_GOOGLE_CLIENT_ID is configured")
    print(f"[acp] *** per-user data isolation is OFF — {why}. Every user shares the 'demo' "
          f"estate and can read every other user's scans and remediated files. Correct for a "
          f"demo; NOT safe for multi-user or PHI data.{' PRODUCTION.' if core.IS_PROD else ''} "
          f"***", flush=True)


@app.on_event("shutdown")
def _drain_job_workers():
    # Azure Container Apps sends SIGTERM then waits (~30s) before SIGKILL on every
    # deploy/scale event; uvicorn runs this hook in that window. Draining here means
    # in-flight jobs aren't stranded ~31min waiting for the lease sweeper on the new
    # container (audit P1).
    try:
        core.stop_workers()
        print("[acp] drained job workers for shutdown", flush=True)
    except Exception as e:
        print(f"[acp] shutdown drain error: {e}", flush=True)
    # The scheduler owns a thread of its own; stop it in the same window rather than leaving
    # uvicorn to be killed with it still running. Independent of the drain above: a failed
    # drain must not leave the scheduler thread alive.
    try:
        core.stop_scheduler()
    except Exception as e:
        print(f"[acp] scheduler shutdown error: {e}", flush=True)


@app.on_event("startup")
def _ollama_prewarm():
    """Keep the Ollama model loaded so 'Why?' explanations don't eat a cold start
    (the model load alone is ~15s on CPU). Best-effort daemon: pings every 10 min
    with keep_alive=30m; a missing/unreachable Ollama just makes each ping a no-op.
    Opt out with ACP_OLLAMA_KEEPALIVE=0."""
    if os.environ.get("ACP_OLLAMA_KEEPALIVE", "1") == "0":
        return
    import threading
    import time

    def _loop():
        import httpx

        import ai as _ai
        while True:
            try:
                httpx.post(f"{_ai.OLLAMA_BASE_URL}/api/generate",
                           json={"model": _ai.OLLAMA_MODEL, "prompt": " ",
                                 "keep_alive": "30m", "options": {"num_predict": 1}},
                           timeout=60)
            except Exception:
                pass
            time.sleep(600)

    threading.Thread(target=_loop, daemon=True, name="ollama-prewarm").start()


# Serve the built React SPA same-origin in the deploy container (ACP_STATIC_DIR
# points at the vite `dist`). Registered last so all /api routes take precedence;
# unset locally (the SPA runs on the vite dev server instead).
_static = os.environ.get("ACP_STATIC_DIR")
if _static and Path(_static).is_dir():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=_static, html=True), name="spa")
