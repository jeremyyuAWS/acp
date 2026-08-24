"""Every registered API route must be covered by the auth gate.

core.is_public() is FAIL-CLOSED (2026-08-22): it matches a request path against the REAL,
registered route table (core._PROTECTED_ROUTES, populated by app.py via
register_protected_routes() at import time) rather than a hand-maintained prefix allowlist. The
allowlist it replaced silently missed FIVE route groups over five weeks (/campaigns,
/disposition, then /assess, /analytics, /control, /org-memory, /scope, /sharepoint — the last
including an unauthenticated file upload) because nothing forced the list to stay in sync with
the route table a mile away. This test still matters even though the gate now checks the real
table itself: it is the guard against `is_public()` or `enumerate_api_routes()` regressing back
toward a scheme that can silently drift, and against a route being added to ALWAYS_PUBLIC by
mistake.
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
    """Every real endpoint FastAPI will actually dispatch to — delegates to
    core.enumerate_api_routes(), the SAME function app.py calls at import time to populate the
    real gate. Sharing one implementation is the point: two separate "what routes exist" walks
    is how one of them ends up silently checking a different (or empty) set than the gate
    actually uses — which is exactly how this file's own route-enumeration broke once already
    (see git history / test_route_enumeration_actually_finds_routes below)."""
    from app import app
    return core.enumerate_api_routes(app)


def test_route_enumeration_actually_finds_routes():
    """A sanity floor for `_app_routes()` itself. Without this, a FastAPI internals change that
    breaks the walk again (the exact failure this file already had once) makes the coverage test
    below iterate an empty list and pass — looking green while checking nothing. 100 is well
    under the real count (148 at the time this was written) and well above zero."""
    assert len(_app_routes()) > 100


def test_every_api_route_is_auth_gated_or_intentionally_public():
    """Narrower than it was under the old prefix allowlist, and honestly so: is_public() now
    matches a path against the SAME registered-route table this test walks, so every route found
    here is structurally guaranteed to be gated UNLESS it was explicitly added to ALWAYS_PUBLIC
    (or matches the one path-pattern carve-out below). A new router can no longer slip through by
    omission — there is no separate list left to forget. What this still catches: a route added to
    ALWAYS_PUBLIC (or the carve-out) that shouldn't have been. That is a real, if narrower,
    mistake to guard against, so this stays rather than being deleted as redundant."""
    uncovered = []
    for r in _app_routes():
        path = r.path
        if path in INTENTIONALLY_PUBLIC:
            continue
        if path.startswith("/scans/") and "/trace/" in path:
            continue  # Langfuse redirect targets — documented public carve-out
        if path.startswith("/public/"):
            continue  # R15 verify-this-report — intentionally unauthenticated
        if core.is_public(path):
            uncovered.append(path)
    assert not uncovered, (
        "these API routes are served WITHOUT auth — remove them from core.ALWAYS_PUBLIC (or the "
        f"trace-redirect carve-out in is_public) if that was not intended: {sorted(set(uncovered))}"
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
