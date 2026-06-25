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
                            content='{"detail":"Sign in with Google required"}')
        email = core.verify_gis_token(hdr[7:])
        if not email:
            return Response(status_code=401, media_type="application/json",
                            content='{"detail":"Google token expired — sign in again"}')
        if not any(email.endswith("@" + d) for d in core.ALLOWED_DOMAINS):
            return Response(status_code=403, media_type="application/json",
                            content='{"detail":"Access restricted to authorized accounts"}')
    return await call_next(request)


for _router in ROUTERS:
    app.include_router(_router)


# Serve the built React SPA same-origin in the deploy container (ACP_STATIC_DIR
# points at the vite `dist`). Registered last so all /api routes take precedence;
# unset locally (the SPA runs on the vite dev server instead).
_static = os.environ.get("ACP_STATIC_DIR")
if _static and Path(_static).is_dir():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=_static, html=True), name="spa")
