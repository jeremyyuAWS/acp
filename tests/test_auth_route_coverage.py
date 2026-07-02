"""Every registered API route must be covered by the auth gate.

core.is_public is DEFAULT-OPEN — any path not under core.API_PREFIXES is served
without auth (that's how the SPA's static files and client routes fall through).
The failure mode is silent: a new APIRouter whose prefix isn't added to
API_PREFIXES ships every one of its endpoints unauthenticated (/campaigns and
/disposition both did). This test walks the real FastAPI route table and fails
on any API route that is_public would wave through unintentionally.
"""
from __future__ import annotations
import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import core  # noqa: E402

# Public by intent — pre-auth bootstrap paths and plain <a> navigation targets.
INTENTIONALLY_PUBLIC = set(core.ALWAYS_PUBLIC)


def _app_routes():
    from app import app
    from fastapi.routing import APIRoute
    return [r for r in app.routes if isinstance(r, APIRoute)]


def test_every_api_route_is_auth_gated_or_intentionally_public():
    uncovered = []
    for r in _app_routes():
        path = r.path
        if path in INTENTIONALLY_PUBLIC:
            continue
        if path.startswith("/scans/") and "/trace/" in path:
            continue  # Langfuse redirect targets — documented public carve-out
        if core.is_public(path):
            uncovered.append(path)
    assert not uncovered, (
        "these API routes are served WITHOUT auth — add their prefix to "
        f"core.API_PREFIXES (or ALWAYS_PUBLIC if truly intended): {sorted(set(uncovered))}"
    )


def test_known_sensitive_prefixes_are_gated():
    for p in ("/disposition/policies", "/campaigns", "/scans", "/settings", "/inventory"):
        assert core.is_public(p) is False, f"{p} must require auth"
