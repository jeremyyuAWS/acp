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
    """Every real endpoint FastAPI will actually dispatch to.

    `app.routes` does NOT hand back flat `APIRoute`s for anything added via
    `include_router()` on this FastAPI version (0.137.1) — each becomes an
    opaque `_IncludedRouter` wrapper, and `app.routes` holds none of the
    original `APIRoute`s directly. A prior version of this helper filtered
    `isinstance(r, APIRoute)` straight over `app.routes` and found ZERO
    routes on every run — the assertion below then passed over an empty
    list, which is indistinguishable from "everything is covered" without
    actually checking anything. That is exactly how `/assess/eligibility`,
    `/assess/codeset`, and `/assess/eligibility/scoped` shipped unauthenticated
    for real: every request resolved to the shared 'demo' owner regardless of
    who was signed in, and this guard never fired because it was silently
    checking nothing (found live 2026-08-22, chasing a "why does eligibility
    always read as owner=demo" bug).

    `_IncludedRouter.original_router` is the actual `APIRouter` instance that
    was passed to `include_router()`, and its own `.routes` are ordinary
    `APIRoute`s with their final paths already resolved (nothing here uses
    `include_router(prefix=...)`, so no prefix-joining is needed). Falls back
    to treating `r` itself as the router for older/newer FastAPI internals —
    a route contributing 0 routes is silently swallowed by either branch, so
    the sanity floor in the test below is what actually catches a regression
    of this exact kind.
    """
    from app import app
    from fastapi.routing import APIRoute

    def _expand(r):
        if isinstance(r, APIRoute):
            return [r]
        router = getattr(r, "original_router", r)
        return [sub for sub in getattr(router, "routes", ()) if isinstance(sub, APIRoute)]

    return [route for r in app.routes for route in _expand(r)]


def test_route_enumeration_actually_finds_routes():
    """A sanity floor for `_app_routes()` itself. Without this, a FastAPI internals change that
    breaks the walk again (the exact failure this file already had once) makes the coverage test
    below iterate an empty list and pass — looking green while checking nothing. 100 is well
    under the real count (148 at the time this was written) and well above zero."""
    assert len(_app_routes()) > 100


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
    for p in ("/disposition/policies", "/campaigns", "/scans", "/settings", "/inventory",
              # Found live 2026-08-22 by this file's own route-enumeration fix, once it started
              # actually walking routes instead of silently checking zero of them:
              # /assess/eligibility resolved every request to the shared 'demo' owner regardless
              # of who was signed in, because /assess was never added to API_PREFIXES. The same
              # sweep also caught /analytics, /control, /org-memory, and /sharepoint (including
              # /sharepoint/upload) in the same unauthenticated state.
              "/assess/eligibility", "/assess/codeset", "/analytics/compliance-trend",
              "/control/estate", "/org-memory", "/scope/rules", "/sharepoint/upload"):
        assert core.is_public(p) is False, f"{p} must require auth"
