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
import threading
import time as _time
from pathlib import Path

# Resolve sibling modules (scanner/store/rubric/report/ai/lf) and ../scripts.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from apscheduler.schedulers.background import BackgroundScheduler

from scanner import run_scan
from store import Store
from rubric import Rubric
from swallowed import swallowed

ACP = Path(__file__).resolve().parent.parent

# ── Config (env) ──────────────────────────────────────────────────────────────
ACCESS_CODE = os.environ.get("ACP_ACCESS_CODE")
GOOGLE_CLIENT_ID = os.environ.get("ACP_GOOGLE_CLIENT_ID") or None
# Microsoft Entra app (client) and directory (tenant) ids for the SharePoint/OneDrive connect.
# Served to the SPA via /config so a deployment can be pointed at a tenant WITHOUT rebuilding the
# bundle — the same runtime-config pattern as GOOGLE_CLIENT_ID, and the reason the frontend prefers
# these over its build-time VITE_AZURE_* fallback. Tenant defaults to 'common' only if unset.
AZURE_CLIENT_ID = os.environ.get("ACP_AZURE_CLIENT_ID") or None
AZURE_TENANT_ID = os.environ.get("ACP_AZURE_TENANT_ID") or None


def _load_microsoft_tenants() -> list[dict]:
    """Every Microsoft/Entra app registration this deployment can connect SharePoint/OneDrive
    through, as a data-source connection — NOT the identity provider that gates sign-in to ACP
    itself (that stays AZURE_CLIENT_ID/AZURE_TENANT_ID alone; SignIn.jsx's "Sign in with
    Microsoft" is unchanged by this).

    Single-tenant Entra app registrations (docs/sharepoint-app-registration.md) reach exactly one
    organization's SharePoint/OneDrive each — this deployment was structurally unable to reach a
    second, separate production tenant's estate no matter how a user signed in. `ACP_AZURE_CLIENT_ID`/
    `ACP_AZURE_TENANT_ID` become slot "primary"; `ACP_AZURE_CLIENT_ID_2`/`ACP_AZURE_TENANT_ID_2` (and
    `_3`, `_4`, ...) add more, each requiring its own app registration and admin consent in ITS OWN
    tenant (docs/sharepoint-app-registration.md's steps, repeated per tenant — nothing here
    substitutes for that). `_N_LABEL` names the slot for the connect-source picker; unset falls back
    to "Tenant N". Contiguous numbering only — a gap (2 set, 3 unset, 4 set) stops the scan, since a
    silently-skipped slot is worse than an obviously-missing one.
    """
    tenants = []
    if AZURE_CLIENT_ID and AZURE_TENANT_ID:
        tenants.append({"key": "primary",
                        "label": os.environ.get("ACP_AZURE_TENANT_LABEL") or "Primary",
                        "client_id": AZURE_CLIENT_ID, "tenant_id": AZURE_TENANT_ID})
    n = 2
    while True:
        cid = os.environ.get(f"ACP_AZURE_CLIENT_ID_{n}")
        tid = os.environ.get(f"ACP_AZURE_TENANT_ID_{n}")
        if not (cid and tid):
            break
        tenants.append({"key": f"tenant{n}",
                        "label": os.environ.get(f"ACP_AZURE_TENANT_{n}_LABEL") or f"Tenant {n}",
                        "client_id": cid, "tenant_id": tid})
        n += 1
    return tenants


MICROSOFT_TENANTS = _load_microsoft_tenants()
# Deployment environment. ACP_DEPLOY_ENV is canonical; ACP_ENV is a legacy alias, still read.
#
# ACP_ENV used to mean two different things: this, and the Container Apps *environment name* in
# deploy.sh / standup.sh. docs/production-hardening.md told operators to set ACP_ENV=production,
# which the deploy scripts read as an ACA environment name -- so it never reached the container,
# IS_PROD stayed False on the public demo, and the X-E2E-Key bypass stayed live. The scripts now
# use ACP_ACA_ENV for the environment name and refuse ACP_ENV outright, so the name has exactly
# one meaning again.
#
# The alias is kept because reading it can only make IS_PROD *more* likely true, which is the
# safe direction: an existing container that sets ACP_ENV=production must not silently drop out
# of production mode on upgrade. Set ACP_DEPLOY_ENV in anything new.
IS_PROD = (os.environ.get("ACP_DEPLOY_ENV") or os.environ.get("ACP_ENV") or "").lower() in ("production", "prod")

# Test/demo auth bypasses (X-E2E-Key, X-Demo-Key). FAIL-CLOSED: off unless an operator
# explicitly opts in, and refused in production regardless of the opt-in.
#
# These were previously enabled whenever IS_PROD was false — i.e. enabled by the ABSENCE of
# an env var. Since nothing set ACP_ENV on the container, IS_PROD was False in production and
# the X-E2E-Key gate bypass was live on the public demo. A security control must not depend on
# a variable being present; make the safe state the default and require an explicit opt-in for
# the dangerous one, so no missing/renamed/typo'd variable can reopen the backdoor.
TEST_BYPASS_ENABLED = (
    os.environ.get("ACP_ENABLE_TEST_BYPASS", "").strip().lower() in ("1", "true", "yes")
    and not IS_PROD
)
# Smoke/e2e test key: requests with X-E2E-Key bypass the access gate. Only when the bypass
# is explicitly enabled AND the key is set.
E2E_KEY = (os.environ.get("ACP_E2E_KEY") or None) if TEST_BYPASS_ENABLED else None
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
# The one email that can NEVER be removed from the list (anti-lockout safety). Defaults
# to ACP_OWNER_EMAIL, else the first ACP_ALLOWED_EMAILS entry.
OWNER_EMAIL = (os.environ.get("ACP_OWNER_EMAIL", "").strip().lower()
               or (sorted(ALLOWED_EMAILS)[0] if ALLOWED_EMAILS else ""))
# Additional Platform Admins beyond the single protected OWNER_EMAIL. They get the SAME admin
# rights — the scope editor, platform Settings (AI mode, Drive mirror, worker pool, reset), and
# access management — so a team can have more than one admin instead of everything routing through
# one person. Unlike OWNER_EMAIL these are NOT the anti-lockout owner: they can be removed. Comma-
# separated; case-insensitive; empty by default (a fresh deploy still has exactly one owner).
ADMIN_EMAILS = {
    e.strip().lower() for e in os.environ.get("ACP_ADMIN_EMAILS", "").split(",") if e.strip()
}

# OPEN-ACCESS MODEL. When on (the default), there is NO separate admin view: every user who is
# admitted at all (email_allowed — owner, allow-listed tester, or an allowed domain) sees the same
# screens and can use the same non-destructive features, including creating lifecycle rules. It is
# deliberately NOT a bypass of the login perimeter — an unauthenticated caller (empty email) is
# still nobody — and it does NOT open the genuinely destructive, irreversible actions, which stay
# owner-only via _require_owner: wiping all data (POST /admin/reset), managing who can log in
# (PUT /admin/allowlist, POST /admin/invite, PUT /admin/admins), and authorising/performing a file
# move-or-trash (disposition approve/execute). Set ACP_OPEN_ACCESS=0 to restore role-based admin
# (owner + ACP_ADMIN_EMAILS + owner-promoted store admins).
OPEN_ACCESS = os.environ.get("ACP_OPEN_ACCESS", "1").strip().lower() not in ("0", "false", "no", "off")
# Public base URL for the verify-this-report QR code (R15). When set, the PDF embeds a QR pointing
# to {PUBLIC_URL}/public/verify/{scan_id}. When unset the QR encodes a plain scan-id URI instead.
PUBLIC_URL = os.environ.get("ACP_PUBLIC_URL", "").rstrip("/")


def is_owner(email: str | None) -> bool:
    """The single protected owner (ACP_OWNER_EMAIL) — the root of trust that manages who else is an
    admin, and the one identity that can never be demoted or removed. True for everyone only when no
    owner is configured (local dev / demo / no-auth)."""
    if not OWNER_EMAIL:
        return True
    return (email or "").strip().lower() == OWNER_EMAIL


def is_admin(email: str | None) -> bool:
    """May this identity use the platform-admin surfaces (scope editor, platform Settings, the
    lifecycle rule builder, access-management views)? True for the protected OWNER_EMAIL, any
    ACP_ADMIN_EMAILS entry (env, permanent), any email the owner promoted from Settings (store
    `admin_emails`), or — when no owner is configured (local dev / demo / no-auth) — everyone.

    Under the OPEN_ACCESS model (the default, see the constant above) it is additionally True for ANY
    authenticated, admitted user: there is no separate admin view, so everyone who can sign in gets
    the same screens and features. An empty email (unauthenticated) is still never an admin — the
    login perimeter is unchanged — and the destructive actions are separately owner-gated.

    This is the single source of truth both the SPA flag (is_scope_owner) and the API gate
    (_require_admin) consult, so they can never disagree about who sees the admin surface."""
    if not OWNER_EMAIL:
        return True
    e = (email or "").strip().lower()
    if not e:
        return False
    if e == OWNER_EMAIL or e in ADMIN_EMAILS:
        return True
    if OPEN_ACCESS:
        return True   # any authenticated, admitted user — same views/features for everyone
    try:
        return e in get_store().get_admins()
    except Exception:
        return False


def email_allowed(email: str) -> bool:
    """True if an email may use the app: the protected owner (or an additional admin), the runtime
    test-user list managed from Settings → Test users, or an allowed domain. ACP_ALLOWED_EMAILS is a
    one-time SEED for that list (see seed_allowlist_once), NOT a separate permanent grant
    — so a user removed from the list is genuinely revoked. Admins are always admitted: an admin who
    could not sign in would be a contradiction."""
    email = (email or "").lower()
    if email and (email == OWNER_EMAIL or email in ADMIN_EMAILS):
        return True
    try:
        if email in get_store().get_allowlist():
            return True
    except Exception:
        swallowed("core.email_allowed: reading the e-mail allowlist failed")
    return any(email.endswith("@" + d.lower()) for d in ALLOWED_DOMAINS)


def is_scope_owner(email: str | None) -> bool:
    """May this identity edit the scan scope? Scope writes go through PUT /settings, which is
    admin-only (_require_admin), so this is the same gate the API enforces — it exists so the SPA can
    hide the scope editor for non-admins POST-auth instead of letting a non-admin attempt a write
    that the server will 403.

    Delegates to is_admin(), so additional Platform Admins (ACP_ADMIN_EMAILS) — not just the single
    owner — get the editor. Name kept for SPA/`/me` compatibility. True when no owner is configured
    (local dev / demo / no-auth — _require_admin is a no-op there, so everyone may edit)."""
    return is_admin(email)


def seed_allowlist_once(st: Store) -> None:
    """One-time bootstrap: copy ACP_ALLOWED_EMAILS into the editable runtime list so
    pre-existing users appear in Settings → Test users and can be removed. Guarded by a
    marker so it never resurrects a user the admin later deletes.

    Takes the Store explicitly: it runs from inside get_store(), before the singleton is
    published, so it cannot reach it through the module attribute."""
    try:
        if st.get_setting("allowlist_seeded") == "true":
            return
        if ALLOWED_EMAILS:
            st.set_allowlist(sorted(set(st.get_allowlist()) | ALLOWED_EMAILS))
        st.set_setting("allowlist_seeded", "true")
    except Exception:
        swallowed("core.seed_allowlist_once: seeding the allowlist once failed")
DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
]
# Same knob and same reasoning as scanner._DRIVE_HTTP_TIMEOUT_S — shared here rather than
# imported from scanner because core.py must not depend on it (scanner already imports core-
# adjacent modules; core stays the lower layer). Kept as one env var name across both so a
# deploy-time override covers both call sites with a single setting.
_DRIVE_HTTP_TIMEOUT_S = int(os.environ.get("ACP_DRIVE_HTTP_TIMEOUT_S", "60"))
HITL_WEBHOOK = os.environ.get("HITL_WEBHOOK_URL", "")

# ── Shared singletons ─────────────────────────────────────────────────────────
# `store` is built on FIRST USE, never at import. Store() opens — and creates — the database
# in its constructor, so a module-level `store = Store()` meant that merely *importing* core
# touched the disk: a CLI script, a test module collected by pytest, a tool reading the route
# table. Worse, whatever store._SQLITE_PATH happened to say at that instant was frozen into
# core.store for the life of the process, so anything that repointed the path afterwards was
# silently talking to a different database than core was.
#
# Access it as `core.store` (PEP 562 __getattr__ below) or `core.get_store()`. Both resolve to
# the same object; neither runs until someone actually needs a database.
_store_lock = threading.Lock()


def get_store() -> Store:
    """The process-wide Store, constructed on first use.

    Resolves through the module's own `store` attribute rather than a private slot, so a test
    doing `monkeypatch.setattr(core, "store", fake)` is honoured by core's *internal* callers
    too (finalize_scan, the scheduled scan, the job workers) — not just by the modules that
    read `core.store` from outside.
    """
    st = globals().get("store")
    if st is None:
        with _store_lock:
            st = globals().get("store")          # another thread may have won the race
            if st is None:
                st = Store()
                globals()["store"] = st          # publish before seeding: seeding uses `st`
                seed_allowlist_once(st)
    return st


def __getattr__(name: str):
    """PEP 562: only consulted when normal attribute lookup fails. Once get_store() publishes
    `store` into the module globals (or a test monkeypatches it), this stops being called."""
    if name == "store":
        return get_store()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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


# ── Microsoft (Entra) token verification (cached) ─────────────────────────────
# token → (email, monotonic_expiry). Same posture and cache window as GIS above.
#
# #239 added a "Sign in with Microsoft" button but never taught this backend to authenticate the
# resulting user — the access gate only accepted Google tokens, so every Microsoft sign-in 401'd
# the moment the SPA made its first call ("session expired", immediately). This closes that gap.
#
# We verify the SAME way the Google path does — by asking the provider rather than validating a JWT
# locally: call Microsoft Graph /me with the delegated access token MSAL already holds (it carries
# User.Read). A 200 proves the token is a live Microsoft token for a real user, and hands back the
# identity; email_allowed() then decides access exactly as for Google. This matches the existing
# security model (valid provider token + allow-listed identity) rather than adding a stricter,
# audience-pinned JWKS check that the Google lane does not have either — if we tighten one, we
# tighten both, deliberately and together.
_ms_cache: dict[str, tuple[str, float]] = {}


def _graph_me_email(token: str) -> str | None:
    """GET https://graph.microsoft.com/v1.0/me and return the user's email/UPN, or None. Split out
    so tests can substitute the network call without patching urllib."""
    import urllib.request as _ur
    import json as _json
    req = _ur.Request(
        "https://graph.microsoft.com/v1.0/me",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with _ur.urlopen(req, timeout=5) as r:
            data = _json.load(r)
    except Exception:
        return None
    # `mail` is the routable address; `userPrincipalName` is the sign-in name and the reliable
    # fallback when a mailbox isn't provisioned (common on dev-tenant test accounts).
    email = (data.get("mail") or data.get("userPrincipalName") or "").strip()
    return email or None


def verify_ms_token(token: str) -> str | None:
    now = _time.monotonic()
    cached = _ms_cache.get(token)
    if cached:
        email, exp = cached
        if now < exp:
            return email
        del _ms_cache[token]
    email = _graph_me_email(token)
    if not email:
        return None
    _ms_cache[token] = (email, now + 540)
    return email


# ── Access-gate path policy ───────────────────────────────────────────────────
# Paths that bypass all auth (needed before the user has a token).
ALWAYS_PUBLIC = {"/healthz", "/readyz", "/config", "/hub", "/ai/status", "/alerts/webhook",
                 "/capability", "/monitor/estate",
                 # The health/heartbeat Swagger document (routes/openapi_health.py) — a curated,
                 # non-sensitive description of the endpoints above plus the owner-scoped
                 # progress/heartbeat routes. Public on purpose: the whole point is a monitor or
                 # integrator can read it without signing in. See that module's own docstring for
                 # why this is a separate document rather than making FastAPI's own /docs public.
                 "/openapi/health.json", "/docs/health"}
# Shared secret for the Grafana alert webhook (public path, key-validated).
ALERT_KEY = os.environ.get("ACP_ALERT_KEY", "acp-alert-demo-key")
# Shared secret for the production monitor's aggregate endpoint (public path, key-validated —
# the same posture as ALERT_KEY above, and deliberately NOT the X-E2E-Key gate bypass).
#
# The monitor's deep checks used to authenticate with X-E2E-Key, which cannot work in
# production BY DESIGN: E2E_KEY is None whenever IS_PROD, so the header the monitor sent was
# never going to be honoured on the one deployment worth monitoring. Setting ACP_E2E_KEY would
# not have fixed it; enabling ACP_ENABLE_TEST_BYPASS would have "fixed" it by reopening the
# whole-gate backdoor that fail-closed default exists to keep shut.
#
# So this key unlocks exactly one read-only route that returns COUNTS — no filenames, no
# owners, no document content. NO DEFAULT VALUE: a monitoring credential that ships with a
# well-known fallback is a backdoor, so an unset key disables the route rather than opening it.
MONITOR_KEY = os.environ.get("ACP_MONITOR_KEY") or None
# FAIL-CLOSED gate (2026-08-22, replacing a fail-open manually-maintained allowlist).
#
# The previous design was a hand-maintained tuple of "protected" prefixes (API_PREFIXES) with
# everything else served unauthenticated by default — the natural default for a small surface,
# but one that silently missed FIVE separate route groups over five weeks as the app grew
# (/campaigns, /disposition, then /assess, /analytics, /control, /org-memory, /scope,
# /sharepoint — the last including an unauthenticated file-upload endpoint). Each shipped
# unauthenticated not because anyone decided it should be public, but because nobody remembered
# to extend a list a mile from the route definition. tests/test_auth_route_coverage.py is the
# guard that should have caught this and, for a stretch, silently couldn't (see that file's own
# history) — a second line of defense is not a substitute for removing the failure mode itself.
#
# This checks the REAL, REGISTERED route table instead: any path FastAPI would actually dispatch
# to requires auth by default, unless explicitly listed in ALWAYS_PUBLIC (or the one path-pattern
# carve-out below). A new APIRouter is protected automatically the moment it's included — there
# is no list left to forget.
#
# `_PROTECTED_ROUTES` is populated two ways, both safe against the app.py/core.py import order
# (app.py imports core, not the reverse — core.py cannot import app.py at ITS OWN module level
# without creating a cycle):
#   1. Explicitly: app.py calls register_protected_routes() at module level, immediately after
#      every router is included — the normal path in the real running app.
#   2. Lazily: if is_public() is ever reached before that (a test that imports core directly
#      without going through app.py first, or a future startup-ordering change), _protected_routes()
#      below imports `app` itself — a LOCAL import, deferred until first actual use, which is safe
#      specifically because is_public() is only ever called from inside the request-handling
#      middleware, never at either module's IMPORT time. By the time any request is served,
#      app.py has already finished executing top to bottom and sits fully built in sys.modules,
#      so this local import is a cache hit, not a re-execution — no cycle, regardless of which
#      module happened to import first.
_PROTECTED_ROUTES: list | None = None


def register_protected_routes(routes) -> None:
    """Called by app.py at module level, immediately after `for _router in ROUTERS:
    app.include_router(_router)` completes. Stores the real APIRoute objects so is_public() can
    match a live request path against them via Starlette's own Route.matches() — not a
    hand-rolled startswith(), which is exactly the kind of parallel, driftable string-matching
    scheme this redesign exists to avoid. Parameterized routes (/scans/{sid}/trace/{kind},
    /scope/rules/{rule_id}, .../{id:path}) only match correctly through the framework's own
    path-compilation; a prefix/startswith scheme cannot see path parameters at all.

    Also the override a test reaches for directly, to check is_public()'s MATCHING logic against
    a small synthetic route set without booting the whole real app."""
    global _PROTECTED_ROUTES
    _PROTECTED_ROUTES = list(routes)


def _protected_routes() -> list:
    """The route list is_public() matches against — registered explicitly (the normal path) or,
    failing that, imported lazily on first use. See the module comment above for why the lazy
    import is safe here specifically (deferred past both modules' own import time)."""
    global _PROTECTED_ROUTES
    if _PROTECTED_ROUTES is None:
        from app import app as _fastapi_app
        _PROTECTED_ROUTES = enumerate_api_routes(_fastapi_app)
    return _PROTECTED_ROUTES


def enumerate_api_routes(app) -> list:
    """Every real endpoint `app` will actually dispatch to — the APIRoute objects backing each
    `include_router()` registration, unwrapped from FastAPI's opaque `_IncludedRouter` wrapper.

    Takes `app` as a parameter rather than importing it, so this stays import-cycle-safe (core.py
    is imported BY app.py) and callable from both the real startup path and its own test, which
    both need identical logic — two implementations of "what routes exist" is how one of them
    ends up silently checking a different (or empty) set than the real gate uses.

    On FastAPI 0.137.1, `app.routes` does NOT hand back flat `APIRoute`s for anything added via
    `include_router()` — each becomes an opaque `_IncludedRouter`, and `app.routes` holds none of
    the original `APIRoute`s directly. `_IncludedRouter.original_router` is the actual `APIRouter`
    instance passed to `include_router()`, whose own `.routes` are ordinary `APIRoute`s with their
    final paths already resolved (nothing here uses `include_router(prefix=...)`, so no
    prefix-joining is needed). Falls back to treating `r` itself as the router for older/newer
    FastAPI internals that don't wrap routers this way."""
    from fastapi.routing import APIRoute

    def _expand(r):
        if isinstance(r, APIRoute):
            return [r]
        router = getattr(r, "original_router", r)
        return [sub for sub in getattr(router, "routes", ()) if isinstance(sub, APIRoute)]

    return [route for r in app.routes for route in _expand(r)]


def _matches_a_protected_route(path: str) -> bool:
    """True iff `path` matches ANY registered API route's pattern, by method or not — even a
    request with the wrong HTTP method for a real endpoint (Match.PARTIAL) is still a real API
    path and must be gated, not waved through because the verb didn't line up. Only Match.NONE
    against every registered route means "not a recognized backend path at all" — the SPA's own
    client-side routes and static assets, which is the only thing this now falls through for.

    Builds the minimal ASGI scope Route.matches() actually reads (type/path/method/path_params —
    verified against the installed Starlette's own Route.matches source) rather than requiring
    callers to construct a full request scope; the method is a placeholder since it never affects
    whether NONE vs. PARTIAL/FULL is returned for THIS gate's purposes."""
    from starlette.routing import Match
    scope = {"type": "http", "path": path, "method": "GET", "path_params": {}}
    for route in _protected_routes():
        match, _ = route.matches(scope)
        if match != Match.NONE:
            return True
    return False


def is_public(path: str) -> bool:
    if path in ALWAYS_PUBLIC:
        return True
    # The trace-redirect endpoint (/scans/{sid}/trace/{kind}) is a plain <a> navigation
    # target — no auth header — so it must be public; it only 302s to a Langfuse deep
    # link. Matches singular "/trace/", NOT the authed "/traces" JSON endpoint.
    if path.startswith("/scans/") and "/trace/" in path:
        return True
    # R15 verify-this-report endpoint: anyone can check a scan's digest without signing in.
    if path.startswith("/public/"):
        return True
    if _matches_a_protected_route(path):
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
        from google.oauth2.credentials import Credentials
        # GIS tokens are short-lived (1 h) and carry no refresh_token, so leave `expiry` None:
        # google-auth reports `expired` False for a credential without an expiry and never
        # attempts a refresh. Drive answers 401 if the token really has expired — the honest
        # signal. Setting `expiry = now + 1h` (as this did, while claiming the opposite) invited
        # google-auth to refresh the instant that hour lapsed, raising "credentials do not
        # contain the necessary fields need to refresh the access token".
        creds = Credentials(token=token, scopes=DRIVE_SCOPES)
    elif GOOGLE_CLIENT_ID:
        raise HTTPException(401, "sign in with Google to connect your Drive")
    else:
        import google.auth
        creds, _ = google.auth.default(scopes=DRIVE_SCOPES)
    # See scanner._drive_service's identical fix (found live 2026-08-29) for why this can't stay
    # `credentials=creds`: that shortcut builds its own AuthorizedHttp with no way to bound its
    # socket, so a stalled connection (not just a slow one — one that never returns data or an
    # error) blocks this request thread forever. build() refuses `http=` and `credentials=`
    # together, so the AuthorizedHttp has to be constructed here instead.
    import httplib2
    from google_auth_httplib2 import AuthorizedHttp
    http = AuthorizedHttp(creds, http=httplib2.Http(timeout=_DRIVE_HTTP_TIMEOUT_S))
    return build("drive", "v3", http=http, cache_discovery=False)


# ── HITL webhook ──────────────────────────────────────────────────────────────
def fire_webhook(items: list[dict], *, event: str = "hitl.queued") -> None:
    """POST HITL events to the configured webhook URL (best-effort, non-blocking).

    Supported events: hitl.queued (new items), hitl.assigned (reviewer set),
    hitl.resolved (approved / rejected / skipped).
    """
    if not HITL_WEBHOOK or not items:
        return
    import threading

    def _post():
        try:
            import httpx
            httpx.post(HITL_WEBHOOK, json={"event": event, "items": items}, timeout=8)
        except Exception as e:
            print(f"HITL webhook failed: {e}", flush=True)
    threading.Thread(target=_post, daemon=True).start()


# ── Langfuse remediation span ─────────────────────────────────────────────────
def emit_remediation_span(scan_id: str, filename: str, drive_write_url: str | None, *,
                          fixes_applied: int | None = None, fixes_skipped: int | None = None,
                          per_rule: dict | None = None):
    """Emit a 'Remediate' span on this file's OWN Langfuse trace (file-centric tracing —
    see lf.file_trace): the same trace that already carries its Discover and (if run)
    Assess spans, so the file's full lifecycle lives in one place.

    fixes_applied/fixes_skipped/per_rule are the deterministic remediation outcome from
    handlers._remediate_file (COUNTS only, PHI-safe). Optional: the manual-upload and
    mark-remediated routes have no fix pass to report and leave them None."""
    try:
        import lf as _lf
        owner = (get_store().get_scan(scan_id) or {}).get("run", {}).get("owner_email")
        trace = _lf.file_trace(scan_id, filename, user=owner)
        _lf.remediate_span(trace, drive_write_url, fixes_applied=fixes_applied,
                           fixes_skipped=fixes_skipped, per_rule=per_rule)
        _lf.flush()
    except Exception:
        swallowed("core.emit_remediation_span: emitting the remediation span failed", scan_id)


# ── Background scheduler (periodic local scans) ───────────────────────────────
# Constructed at import (cheap, no thread), but NOT started: scheduler.start() spawns a
# background thread, and importing a module should not. Every pytest process and every CLI
# script that touched `import core` was running one. app.py starts it from its startup hook
# and shuts it down again on SIGTERM.
#
# add_job()/remove_all_jobs()/get_job() all work on a stopped scheduler — APScheduler holds
# them as pending jobs and runs them once started — so reload_scheduler() may arm it first.
scheduler = BackgroundScheduler()


def start_scheduler() -> bool:
    """Start the background scheduler. Idempotent; returns True if this call started it."""
    if scheduler.running:
        return False
    scheduler.start()
    return True


def stop_scheduler() -> None:
    """Stop the scheduler if running. Safe to call when it never started."""
    if scheduler.running:
        scheduler.shutdown(wait=False)


def _drive_delta_check(cursor_key: str, owner: str | None,
                       build_svc) -> tuple[list[dict], set] | None:
    """The shared core of the Drive delta gate: advance (or seed) the stored cursor at
    `cursor_key` and return (changed_files, removed_ids) from Drive's Changes API, or None
    when there is nothing yet to compare — a first-ever check for this cursor_key, or the
    check itself failed. None is NEVER 'nothing changed': both callers below must fall back
    to a full listing on None, and both do.

    `cursor_key` is what gives the scheduled sweep and an interactive scan two independent
    cursors under one cursor store with no schema change: the sweep's own identity is the
    fixed string "drive" (unchanged since #933), while an interactive caller namespaces its
    key per signed-in user (see _interactive_drive_sync_plan) so two different users' Drive
    accounts never share or clobber each other's delta position.

    `build_svc` is a zero-arg callable returning the Drive service to check against — called
    INSIDE the try below, deferred, so a broken build is covered by the same fallback-to-full-
    listing guarantee as the API calls after it. The scheduled sweep has nothing built yet and
    passes a fresh `lambda: _drive_service(None)` (ADC); an interactive caller already has a
    service built for the very same request it is about to list with and passes THAT one back
    (`lambda: svc`) rather than have this function build a second one from the raw token —
    building a second service per request is both wasteful and, in any caller that mocks
    scanner._drive_service to assert it was called exactly once, a real regression.
    """
    from scanner import drive_changes_since, drive_start_page_token
    cur = get_store().get_sync_cursor(cursor_key)
    try:
        svc = build_svc()
        if not cur or not cur.get("page_token"):
            # No baseline yet for this cursor_key — nothing to compare against. Seed one now
            # so the NEXT check has something to gate on.
            get_store().save_sync_cursor(cursor_key, owner, drive_start_page_token(svc))
            return None
        changed, removed_ids, new_token = drive_changes_since(svc, cur["page_token"])
        get_store().save_sync_cursor(cursor_key, owner, new_token)  # advance regardless of outcome
        return changed, removed_ids
    except BaseException as e:
        # BaseException, deliberately wider than the rest of this codebase's `except
        # Exception`: a broken native dependency in the googleapiclient/google-auth import
        # chain (e.g. a cryptography/cffi ABI mismatch) surfaces as a Rust pyo3_runtime.
        # PanicException, which subclasses BaseException specifically so it is NOT caught by
        # `except Exception` — and this function's whole contract is "never turn uncertainty
        # into an unvouched-for reconstruction," which an uncaught panic here would silently
        # violate by crashing the caller instead of falling back to it. An expired/invalid
        # page token (Drive 404s that after ~1 week unused) and ordinary API/ADC failures
        # fall through here too.
        print(f"drive sync check ({cursor_key}): change-check failed ({e}) — falling back to "
              f"a full listing", flush=True)
        return None


def _drive_prior_inventory_for_account(owner: str | None, account_id: str | None) -> list[dict] | None:
    """The most recent completed Drive scan's inventory, but ONLY if it was actually run as
    THIS Google account. store.latest_scan_inventory_items has no account-scoped query of its
    own — it returns whatever the most recent 'drive'-source scan for this owner covered,
    regardless of which Google identity a per-request drive_token authenticated as.

    A Drive token is a per-request browser OAuth credential, never a server-bound "connected
    account", so nothing else stops the same ACP owner email presenting a DIFFERENT Google
    account between scans — the same signed-in ACP user can sign into a different Google
    account in the browser's Drive picker from one interactive scan to the next. Reconstructing
    one account's estate from another's inventory would silently show the wrong documents, so
    an account_id mismatch on ANY row is treated the same as 'no prior scan to reconstruct
    from' — never a partial or approximate match, matching _sp_prior_inventory_for_drive's
    identical contract for SharePoint. An empty-but-real prior scan is not a mismatch and still
    returns (as `[]`, not None).

    `account_id` can itself be None (scanner.drive_account_id's own best-effort failure mode) —
    that still participates in the comparison rather than skipping it: None only matches other
    Nones, so an unverifiable CURRENT identity checked against a KNOWN prior one is correctly
    treated as a mismatch, never a silent pass."""
    prior = get_store().latest_scan_inventory_items(owner, "drive")
    if prior is None:
        return None
    if any(r.get("drive_account_id") != account_id for r in prior):
        return None
    return prior


def _drive_sync_plan(owner: str | None) -> tuple[bool, dict | None]:
    """PRD Phase 3: decide what the scheduled Drive sweep should do, from the stored sync
    cursor. Returns (skip, drive_delta):

      - (True, None)    — a stored cursor confirms nothing changed since the last sweep; skip
                          the scan entirely.
      - (False, {...})  — something changed; {"prior_files", "changed", "removed_ids"} for
                          run_scan's drive_delta= to reconstruct the estate from, without
                          walking Drive.
      - (False, None)   — proceed with TODAY's full, fresh Drive listing: first sweep ever, no
                          prior completed scan to reconstruct from, or the change-check itself
                          failed.

    Uncertainty always resolves to (False, None) — a full, already-correct scan — never to a
    skip, and never to a reconstruction this function can't vouch for. A SKIP is the right
    answer for THIS caller specifically because nobody is waiting on a scheduled sweep's
    result — see _interactive_drive_sync_plan below for why an interactive scan can never use
    the same shortcut.

    The reconstruction baseline is also verified against the CURRENT Google account
    (_drive_prior_inventory_for_account) before it is trusted — see that function's docstring
    for why a Drive token is not guaranteed to be the same identity from one sweep to the
    next (an operator-rotated ADC credential, in this caller's case)."""
    from scanner import _drive_service, drive_account_id
    result = _drive_delta_check("drive", owner, lambda: _drive_service(None))
    if result is None:
        return False, None
    changed, removed_ids = result
    if not changed and not removed_ids:
        return True, None
    try:
        account_id = drive_account_id(_drive_service(None))
    except Exception:
        account_id = None
    prior = _drive_prior_inventory_for_account(owner, account_id)
    if prior is None:
        # A cursor exists but no completed scan does (e.g. every prior sweep since it was
        # seeded has failed before saving, or the most recent one ran as a different Google
        # account) — nothing to reconstruct FROM. A full listing gives the NEXT sweep a real
        # baseline again.
        print(f"scheduled drive sweep: {len(changed)} changed, {len(removed_ids)} removed/"
              f"trashed, but no prior scan to reconstruct from — running a full scan",
              flush=True)
        return False, None
    print(f"scheduled drive sweep: {len(changed)} changed, {len(removed_ids)} removed/"
          f"trashed since last sync — reconstructing the estate instead of a full re-list",
          flush=True)
    from scanner import _drive_file_from_inventory_row
    prior_files = [_drive_file_from_inventory_row(r) for r in prior]
    return False, {"prior_files": prior_files, "changed": changed, "removed_ids": removed_ids}


def _interactive_drive_sync_plan(owner: str, svc) -> dict | None:
    """PRD Phase 3, interactive scans: the same drive_delta reconstruction _drive_sync_plan
    gives the scheduled sweep, but for a user-initiated whole-Drive scan — keyed per SIGNED-
    IN USER (cursor_key=f"drive:{owner}"). `svc` is the Drive service the CALLER already built
    for this same request (from this user's own per-request token, never ADC) — reused here
    rather than built a second time (see _drive_delta_check's docstring for why).

    Returns the SAME drive_delta dict _list()'s drive_delta= already knows how to reconstruct
    from (see drive_reconstructed_listing), or None to fall back to a normal full listing.

    DELIBERATELY NO SKIP, unlike _drive_sync_plan. The scheduled sweep's "nothing changed —
    do nothing" is only correct because nobody is watching it; a user who clicked "scan"
    is watching, and is owed a completed scan every time, even when nothing changed. So
    'nothing changed' here still returns a drive_delta — {"changed": [], "removed_ids":
    set()} reconstructs the prior scan's inventory UNCHANGED, which is a genuine, complete,
    just very fast scan rather than the absence of one.

    Callers restrict this to a whole-Drive request (no folder/folders narrowing) before
    calling — see handlers._scan_discover. Drive's Changes API has no folder filter, so
    reconciling it against a folder-scoped baseline would need a containment check this
    function does not do.

    The prior-scan baseline is also verified against the CURRENT Google account
    (_drive_prior_inventory_for_account) before it is trusted — unlike the scheduled sweep's
    fixed ADC identity, a signed-in ACP user can sign into a DIFFERENT Google account in the
    browser's Drive picker from one interactive scan to the next, and reconstructing from the
    wrong account's inventory would silently show the wrong documents.
    """
    from scanner import drive_account_id
    result = _drive_delta_check(f"drive:{owner}", owner, lambda: svc)
    if result is None:
        return None
    changed, removed_ids = result
    prior = _drive_prior_inventory_for_account(owner, drive_account_id(svc))
    if prior is None:
        # A cursor exists but no completed whole-Drive scan for this user does (their first
        # scan predates this cursor, every prior one failed before saving, or the most recent
        # one was a different Google account) — nothing to reconstruct FROM. A full listing
        # gives the NEXT interactive scan a real baseline.
        return None
    if changed or removed_ids:
        print(f"interactive drive scan ({owner}): {len(changed)} changed, {len(removed_ids)} "
              f"removed/trashed since last sync — reconstructing the estate instead of a full "
              f"re-list", flush=True)
    from scanner import _drive_file_from_inventory_row
    prior_files = [_drive_file_from_inventory_row(r) for r in prior]
    return {"prior_files": prior_files, "changed": changed, "removed_ids": removed_ids}


def _sp_delta_check(cursor_key: str, owner: str | None, token: str,
                    drive_id: str | None) -> tuple[list[dict], set] | None:
    """The shared core of the SharePoint delta gate — the SharePoint mirror of
    _drive_delta_check. Advance (or seed) the stored cursor at `cursor_key` and return
    (changed_files, removed_ids) from Graph's delta query, or None when there is nothing yet
    to compare — a first-ever check for this cursor_key, or the check itself failed. None is
    NEVER 'nothing changed': every caller below must fall back to a full listing on None.

    Best-effort bookkeeping: always advances (or seeds) the stored cursor before returning. A
    SEED call is more expensive than Drive's equivalent (drive_start_page_token): Graph's delta
    API has no free-standing "just give me a baseline" call, so a token-less first call walks
    the ENTIRE current tree to reach the first deltaLink — paid once, here, and discarded rather
    than processed, not paid again until the drive itself resets."""
    from scanner import sp_delta_since
    cur = get_store().get_sync_cursor(cursor_key)
    try:
        if not cur or not cur.get("page_token"):
            _, _, new_link = sp_delta_since(token, drive_id, None)
            get_store().save_sync_cursor(cursor_key, owner, new_link)
            return None
        changed, removed_ids, new_link = sp_delta_since(token, drive_id, cur["page_token"])
        get_store().save_sync_cursor(cursor_key, owner, new_link)  # advance regardless of outcome
        return changed, removed_ids
    except BaseException as e:
        # BaseException — same reasoning as _drive_delta_check's identical catch: a broken
        # native dependency in an HTTP/crypto import chain must never turn uncertainty into an
        # unvouched-for reconstruction.
        print(f"sharepoint sync check ({cursor_key}): change-check failed ({e}) — falling back "
              f"to a full listing", flush=True)
        return None


def _sp_prior_inventory_for_drive(owner: str | None, drive_id: str | None) -> list[dict] | None:
    """The most recent completed SharePoint scan's inventory, but ONLY if it was actually a
    scan of THIS drive_id. store.latest_scan_inventory_items has no drive-scoped query of its
    own — it returns whatever the most recent 'sharepoint'-source scan for this owner covered.

    For the scheduled sweep that is a non-issue (every sweep targets the one configured
    sp_sync.sync_drive_id(), so the most recent scan is always for that same drive) UNLESS an
    operator repoints ACP_SP_SYNC_DRIVE_ID at a different library, in which case the stored
    inventory belongs to the OLD one. For an interactive scan it is a real, expected case: a
    signed-in user can scan a different SharePoint library — or their own OneDrive — from one
    scan to the next, and each has its own identity.

    Either way, reconstructing one drive's estate from another's inventory would silently show
    the wrong documents, so a drive_id mismatch on ANY row is treated the same as 'no prior scan
    to reconstruct from' — never a partial or approximate match. An empty-but-real prior scan
    (a library that was genuinely empty) is not a mismatch and still returns (as `[]`, not
    None) — this is the same 'is a real answer, not missing data' distinction None vs. []
    already carries for _drive_sync_plan's own use of latest_scan_inventory_items."""
    prior = get_store().latest_scan_inventory_items(owner, "sharepoint")
    if prior is None:
        return None
    if any(r.get("drive_id") != drive_id for r in prior):
        return None
    return prior


def _sp_sync_plan(owner: str | None, token: str) -> tuple[bool, dict | None]:
    """PRD Phase 3: the SharePoint mirror of _drive_sync_plan — decide what the scheduled
    sweep should do, from the stored Graph deltaLink. Returns (skip, sp_delta):

      - (True, None)    — a stored cursor confirms nothing changed since the last sweep; skip
                          the scan entirely.
      - (False, {...})  — something changed; {"prior_files", "changed", "removed_ids"} for
                          run_scan's sp_delta= to reconstruct the estate from, without walking
                          SharePoint (scanner.sp_reconstructed_listing).
      - (False, None)   — proceed with TODAY's full, fresh listing: first sweep ever, no prior
                          completed scan to reconstruct from, or the change-check itself failed.

    Uncertainty always resolves to (False, None) — a full, already-correct scan — never to a
    skip, and never to a reconstruction this function can't vouch for. A SKIP is the right
    answer for THIS caller specifically because nobody is waiting on a scheduled sweep's
    result — see _interactive_sp_sync_plan below for why an interactive scan can never use the
    same shortcut. Only ever called once sp_sync.sp_sync_configured() is already true — `token`
    is the dedicated sync app's own token, never a signed-in user's."""
    import sp_sync
    drive_id = sp_sync.sync_drive_id()
    result = _sp_delta_check("sharepoint", owner, token, drive_id)
    if result is None:
        return False, None
    changed, removed_ids = result
    if not changed and not removed_ids:
        return True, None
    prior = _sp_prior_inventory_for_drive(owner, drive_id)
    if prior is None:
        # A cursor exists but no completed scan of THIS drive does (e.g. every prior sweep
        # since it was seeded has failed before saving, or the configured drive changed) —
        # nothing to reconstruct FROM. A full listing gives the NEXT sweep a real baseline.
        print(f"scheduled sharepoint sweep: {len(changed)} changed, {len(removed_ids)} "
              f"removed since last sync, but no prior scan to reconstruct from — running a "
              f"full scan", flush=True)
        return False, None
    print(f"scheduled sharepoint sweep: {len(changed)} changed, {len(removed_ids)} removed "
          f"since last sync — reconstructing the estate instead of a full re-list",
          flush=True)
    from scanner import _sp_file_from_inventory_row
    prior_files = [_sp_file_from_inventory_row(r) for r in prior]
    return False, {"prior_files": prior_files, "changed": changed, "removed_ids": removed_ids}


def _sp_interactive_cursor_key(owner: str | None, drive_id: str | None) -> str:
    """The per-(owner, drive) cursor key for an interactive SharePoint scan — JSON-encoded, not
    an f-string colon-join. `drive_id` comes from scanner._sp_locations, which parses it off a
    CLIENT-supplied `folder` request value with no format validation (`r.partition("/")`):
    a folder like "a:b/root" yields drive_id="a:b". A naive f"sharepoint:{owner}:{drive_id}"
    key made two different (owner, drive_id) pairs collide on the identical string whenever one
    of them happened to contain a literal colon — e.g. owner="x", drive_id="y:z" produced the
    same key as owner="x:y", drive_id="z". `owner` itself is a trusted authenticated email, but
    `drive_id` is not, so the delimiter can't be trusted to never appear in it.

    Practical impact of a collision was always bounded (_sp_prior_inventory_for_drive still
    verifies drive_id per row before trusting any reconstruction), so this was cursor-row
    corruption risk, not a data-leakage one — but json.dumps of the pair is unambiguous by
    construction and costs nothing to get right, so there is no reason to keep relying on hoping
    ":" never collides."""
    import json
    return f"sharepoint:{json.dumps([owner, drive_id])}"


def _interactive_sp_sync_plan(owner: str, token: str, drive_id: str | None) -> dict | None:
    """PRD Phase 3, interactive SharePoint scans: the same delta reconstruction _sp_sync_plan
    gives the scheduled sweep, but for a user-initiated whole-library (or whole OneDrive,
    drive_id=None) SharePoint scan — keyed per (SIGNED-IN USER, DRIVE) via
    _sp_interactive_cursor_key(owner, drive_id). Unlike Drive (one account, one drive, always
    the same) and unlike the scheduled sweep (always the one configured drive), a SharePoint
    user can interactively scan a DIFFERENT library from one scan to the next, so there is no
    single fixed cursor or baseline to assume — both are keyed (and, for the baseline, VERIFIED
    via _sp_prior_inventory_for_drive) per drive, not just per user.

    Returns the SAME sp_delta dict shape scanner.sp_reconstructed_listing already knows how to
    build from, or None to fall back to a normal full listing.

    DELIBERATELY NO SKIP, same reasoning as _interactive_drive_sync_plan: an interactive user is
    owed a completed scan every time, so 'nothing changed' still returns a delta with empty
    changed/removed sets rather than signalling 'do nothing'.

    Callers restrict this to a single whole Graph drive (see
    scanner._sp_whole_library_target / handlers._scan_discover) — sp_delta_since has no folder
    filter of its own, so it cannot honor a sub-folder narrowing, and it is scoped to exactly
    one drive, so it cannot answer for a multi-library site scan either. `token` is the
    signed-in user's own Graph token, never the scheduled sweep's dedicated sync app token."""
    result = _sp_delta_check(_sp_interactive_cursor_key(owner, drive_id), owner, token, drive_id)
    if result is None:
        return None
    changed, removed_ids = result
    prior = _sp_prior_inventory_for_drive(owner, drive_id)
    if prior is None:
        return None
    if changed or removed_ids:
        print(f"interactive sharepoint scan ({owner}, drive={drive_id}): {len(changed)} "
              f"changed, {len(removed_ids)} removed since last sync — reconstructing the "
              f"estate instead of a full re-list", flush=True)
    from scanner import _sp_file_from_inventory_row
    prior_files = [_sp_file_from_inventory_row(r) for r in prior]
    return {"prior_files": prior_files, "changed": changed, "removed_ids": removed_ids}


def _do_scheduled_scan():
    """A scheduled sweep. Re-scans the configured source (Drive via the service-account
    ADC identity — no user token is available in the background), stamps it with the
    owner who set the schedule so it shows up in their scan list, and finalizes it."""
    cfg = get_store().get_schedule()

    # THE SETTING IS AUTHORITATIVE ON EVERY FIRE, not only when reload_scheduler() runs.
    #
    # `PUT /schedule` calls reload_scheduler() in the process that served the request. Only
    # acp-app has ingress, so that is the ONLY process it can ever reach — while worker_main.py
    # arms its own scheduler with this same job (worker_main:49-50). Turning the schedule off in
    # the UI therefore left the worker's copy running until the container happened to restart,
    # with nothing on any surface saying so.
    #
    # Checking here fixes that without cross-container messaging, which is why it is done here
    # rather than by broadcasting a reload: every process that fires this job reads the same row,
    # so none of them can disagree with the setting for longer than one interval. It also covers
    # a stale job left by a failed reload, which a broadcast would not.
    if not cfg.get("enabled"):
        print("scheduled sweep skipped — the schedule is off (stale job in this process)", flush=True)
        reload_scheduler()      # self-heal: drops the job here so it stops firing at all
        return

    owner = cfg.get("owner_email")
    source = cfg.get("source") or "drive"
    ai = get_store().get_ai_enabled()

    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()

    drive_delta = None
    sp_delta = None
    sp_token = None
    sp_folder = None
    if source == "drive":
        skip, drive_delta = _drive_sync_plan(owner)
        if skip:
            print("scheduled drive sweep skipped — no changes since the last sync", flush=True)
            get_store().record_sweep_outcome(ok=True, when=now, source=source, skipped=True)
            return
    elif source == "sharepoint":
        import sp_sync
        if sp_sync.sp_sync_configured():
            # The dedicated sync app's own token authenticates BOTH the change-check and, when
            # something changed, the full scan below — this is what makes an unattended
            # SharePoint sweep work at all for the first time, not only more efficient. Without
            # this configured, sp_token stays None and the sweep proceeds exactly as it always
            # has: no unattended SharePoint credential, so it fails with the same
            # PermissionError it always has. Zero behavior change when unconfigured.
            sp_token = sp_sync.app_token()
            # `{drive_id}/root` — the <driveId>/<itemId> folder-location syntax _sp_locations
            # already parses, with Graph's own "root" item-id alias so this targets the WHOLE
            # configured library with no folder narrowing and no site enumeration (an app-only
            # token has no "signed-in user" for the site-less OneDrive default to fall back to).
            sp_folder = f"{sp_sync.sync_drive_id()}/root"
            skip, sp_delta = _sp_sync_plan(owner, sp_token)
            if skip:
                print("scheduled sharepoint sweep skipped — no changes since the last sync",
                      flush=True)
                get_store().record_sweep_outcome(ok=True, when=now, source=source, skipped=True)
                return

    try:
        report = run_scan(source, drive_token=None, ai_enabled=ai, user=owner,   # ADC for drive
                          drive_delta=drive_delta, sp_delta=sp_delta,
                          sp_token=sp_token, folder=sp_folder)
        sid = get_store().save_scan(report)
        finalize_scan(sid, ai, source)
        get_store().record_sweep_outcome(ok=True, when=now, source=source, scan_id=sid,
                                         files=report["summary"]["files"])
        print(f"scheduled {source} sweep complete: {report['summary']['files']} files "
              f"(owner={owner})", flush=True)
    except Exception as e:
        # DO NOT substitute a different corpus. This used to fall back to `local` and save +
        # finalize that as a scan, which is how a 258-document Drive estate was displaced every
        # five minutes by a 1-file scan of the bundled samples — and because every "latest" view
        # takes scan_runs ordered by completed_at, that fallback became the estate as far as the
        # dashboard, the report and the scan selector were concerned.
        #
        # The fallback was written for "Drive/ADC may be unconfigured in this environment", and
        # for that case it is still wrong: an unconfigured source should report that it is
        # unconfigured, not quietly produce numbers about something else. A sweep that cannot
        # reach its source has nothing to say, so it says nothing and leaves the last real scan
        # standing.
        #
        # But "leaves the last real scan standing" is only honest if somebody is told. Until this
        # was recorded, the sole trace of a failing sweep was this log line inside the container,
        # while the UI kept presenting an hours-old scan as the live estate — which is how a
        # 403 insufficient-scopes loop ran unnoticed on 2026-07-29. /schedule reports it now.
        get_store().record_sweep_outcome(ok=False, when=now, source=source, error=str(e))
        print(f"scheduled {source} sweep FAILED — no scan was saved, the previous scan stands: {e}",
              flush=True)


def _derive_review_memory_tick() -> None:
    """Nightly ADR 0021 derivation: for every org, read recent HITL behaviour and PROPOSE
    (never activate) house-style rules. Best-effort; only armed when review memory is on."""
    import memory as _mem
    st = get_store()
    for org in st.list_org_owners():
        try:
            _mem.derive_org_memory(st, org)
        except Exception:
            continue


def reload_scheduler():
    cfg = get_store().get_schedule()
    scheduler.remove_all_jobs()
    if cfg["enabled"] and cfg["interval_minutes"] > 0:
        scheduler.add_job(_do_scheduled_scan, "interval",
                          minutes=cfg["interval_minutes"],
                          id="scheduled_local_scan",
                          coalesce=True, max_instances=1)
    # ADR 0021 stage 3 — nightly review-memory derivation, only when the feature is on. Dark
    # by default (flag unset), so it adds no scheduled work to today's deploys.
    if os.environ.get("ACP_REVIEW_MEMORY", "").strip().lower() in ("1", "true", "yes", "on"):
        scheduler.add_job(_derive_review_memory_tick, "cron", hour=3, minute=17,
                          id="review_memory_derive", coalesce=True, max_instances=1)


# NOT called at import: reload_scheduler() reads the schedule out of the database, which would
# build the Store as a side effect of `import core` and defeat the laziness above. app.py calls
# it from its startup hook. This also stops a non-API process that merely imports core (a job
# worker, a CLI script) from arming its own copy of the scheduled scan.


# ── Async job-queue worker pool (ADR 0004) ────────────────────────────────────
# Opt-in: set ACP_WORKERS>0 to run N in-process worker threads that drain the
# `jobs` table (async assess + remediation). Off by default so existing behavior
# is unchanged until the handlers + enqueue paths are wired.
#
# ACP_RUNTIME_MODE controls the default when ACP_WORKERS is not set:
#   "single-node"  — one process handles both API and worker duties; default 4 workers.
#   "distributed"  — a separate worker container handles the queue; default 0 (correct for Azure).
#   "auto"         — backward-compatible default: 0 (matches prior behaviour).
# Explicit ACP_WORKERS always wins regardless of mode.
_RUNTIME_MODE = os.environ.get("ACP_RUNTIME_MODE", "auto")
_WORKER_DEFAULT = "4" if _RUNTIME_MODE == "single-node" else "0"
WORKERS = int(os.environ.get("ACP_WORKERS", _WORKER_DEFAULT) or _WORKER_DEFAULT)
_worker_handles: list = []
_worker_seq = 0          # monotonic id source so scaled-in workers get fresh ids
_MAX_WORKERS = 16        # safety cap on live scaling


def _discovery_reservation(pool_size):
    # Reserve existing capacity, never the last general-purpose slot.
    try:
        requested = int(os.environ.get("ACP_DISCOVERY_RESERVED_WORKERS", "0"))
    except ValueError:
        requested = 0
    return max(0, min(requested, pool_size - 1))


# THE DISCOVERY STAGE IS TWO JOB TYPES, NOT ONE. `scan_discover` lists the source and fans out
# one `scan_folder` per top-level folder; those folder jobs are what actually enumerate the
# estate. Naming only the entry job means the Discovery lane — whether that is a reserved slot in
# a mixed pool or a whole dedicated service (ACP_WORKER_ROLE=discovery) — takes the first job,
# fans out, and then goes idle while its own follow-on work queues in the processing lane behind
# the content backlog. It covers the starting gun and not the race.
#
# `scan` is deliberately NOT here. Under ACP_DEFER_ANALYSIS_TO_ASSESS=0 it downloads and analyses
# the whole estate, and a lane sized for short metadata work must not be occupied for minutes by
# one content job. It gets queue precedence (store.job_priority) but no dedicated slot.
DISCOVERY_LANE_JOB_TYPES = ("scan_discover", "scan_folder")


def _worker_job_types(index, pool_size):
    """Route dedicated services before falling back to the mixed pool reservation."""
    from worker import HANDLERS
    role = os.environ.get("ACP_WORKER_ROLE", "mixed").strip().lower()
    if role == "discovery":
        return DISCOVERY_LANE_JOB_TYPES
    if role == "processing":
        # Excludes the WHOLE Discovery stage, not just its entry job. Otherwise "isolate
        # Discovery and processing by role" leaks: processing workers claim the scan_folder
        # jobs the discovery service just fanned out, which is both a breach of the isolation
        # and the reason a dedicated discovery service would sit idle mid-scan.
        return tuple(sorted(n for n in HANDLERS if n not in DISCOVERY_LANE_JOB_TYPES))
    if role != "mixed":
        raise ValueError("ACP_WORKER_ROLE must be mixed, discovery, or processing")
    return DISCOVERY_LANE_JOB_TYPES if index < _discovery_reservation(pool_size) else None


def _spawn_worker() -> None:
    import threading
    from worker import JobWorker
    global _worker_seq
    # on_retry=update_job: lets a worker announce "failed, waiting to retry" on the live job
    # poll/SSE stream without worker.py importing core (it is deliberately infra-only — see its
    # own docstring). See _job_is_stale's phase=='retrying' exemption below for why this signal
    # can outlive the normal 90s staleness window (backoff can run up to 600s).
    w = JobWorker(get_store(), worker_id=f"w{_worker_seq}", on_retry=update_job)
    w.job_types = _worker_job_types(len(_worker_handles), WORKERS)
    t = threading.Thread(target=w.run_forever, daemon=True, name=f"jobworker-{_worker_seq}")
    _worker_seq += 1
    t.start()
    _worker_handles.append((w, t))


def set_worker_count(n: int) -> int:
    """Scale the in-process worker pool to n live workers (spawn or stop threads).
    Stopped workers finish their current job before exiting. Live for THIS process
    only -- a restart/redeploy always resets to ACP_WORKERS (see start_workers).
    Returns the new live count."""
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
    for index, (worker, _thread) in enumerate(_worker_handles):
        worker.job_types = _worker_job_types(index, n)
    return len(_worker_handles)


def stop_workers() -> None:
    """Graceful drain for shutdown/redeploy. Signals every worker to stop after its
    current job (the loop checks between jobs), briefly joins so idle/near-done workers
    exit cleanly instead of being SIGKILLed and left 'running' until the 30-min lease
    sweeper reclaims them on the next container. A long in-flight job still can't be
    interrupted — it falls back to lease reclaim — but the common idle/between-jobs
    deploy now drains cleanly. Best-effort and time-bounded so shutdown can't hang.
    Flushes Langfuse last so a redeploy doesn't drop the last job's spans."""
    global WORKERS
    import time as _t
    for w, _t2 in _worker_handles:
        try:
            w.stop()
        except Exception:
            swallowed("core.stop_workers: stopping a worker failed")
    deadline = _t.monotonic() + float(os.environ.get("ACP_SHUTDOWN_DRAIN_SECONDS", "20"))
    for _w, t in _worker_handles:
        remaining = deadline - _t.monotonic()
        if remaining > 0:
            try:
                t.join(timeout=remaining)
            except Exception:
                swallowed("core.stop_workers: joining a worker thread failed")
    _worker_handles.clear()
    WORKERS = 0
    try:
        import lf as _lf
        _lf.flush()
    except Exception:
        swallowed("core.stop_workers: flushing Langfuse on shutdown failed")


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
        swallowed("core.reset_langfuse_traces: resetting Langfuse traces failed")
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
            # fall through to in-memory
            swallowed("core.register_scan_tokens: registering the scan tokens in Redis failed", scan_id)
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
            swallowed("core.get_scan_tokens: reading the scan tokens from Redis failed", scan_id)
    return SCAN_TOKENS.get(scan_id, {})


def clear_scan_tokens(scan_id: str) -> None:
    r = _get_redis()
    if r is not None:
        try:
            r.delete(f"scantok:{scan_id}")
        except Exception:
            swallowed("core.clear_scan_tokens: clearing the scan tokens from Redis failed", scan_id)
    SCAN_TOKENS.pop(scan_id, None)


# ── Threaded-scan progress, readable from any replica ─────────────────────────────────────
# JOBS (the module-level dict above) is written by the in-process scan thread and read by the
# UI's poll. Both used to hit the same dict, which is only true when both land on the SAME
# REPLICA — so acp-app carried ingress session affinity to guarantee it. That affinity is what
# blocks multi-revision mode, and therefore blue-green: ACA refuses
# `ContainerAppInvalidIngressStickySessionRevisionMode`.
#
# Same shape as SCAN_TOKENS directly above: Redis when REDIS_URL is set (it is, in the deployed
# environment, already there for cross-replica scan-token durability), the in-memory dict when it
# is not, so local dev and the test suite are unchanged.
#
# WHAT THIS DOES AND DOES NOT FIX. It makes the PROGRESS READABLE from any replica, which is the
# only thing affinity was buying. The work still runs as a thread on one replica, so it is still
# lost if that replica restarts — exactly as the code comment beside it has always said. NOTE
# (2026-08-21): the comment used to claim the durable queue is the default via `queuedScan`; the
# frontend's actual default is `queuedScan = false` ("session-scoped is the pilot default",
# App.jsx) and the switch to opt into the durable queue was deliberately removed from the UI
# (ScanReviewModal.jsx). So THIS thread-based path is, in practice, the only path a user can
# reach today — which is exactly why a job stuck here needs to fail loudly instead of hanging
# forever (see _JOB_STALE_SECONDS below), not why it's a rare edge case.
_JOB_TTL = 3600                            # a scan poll outlives the scan; nothing needs longer
# Coalesce high-frequency progress ticks: at most one Redis write per window, unless the patch
# carries a phase change, done, or error flag — those always flush immediately.
_JOB_COALESCE_SECONDS = float(os.environ.get("ACP_JOB_COALESCE_SECONDS", "0.5") or "0.5")
_JOB_LAST_REDIS_WRITE: dict[str, float] = {}   # monotonic timestamps, never persisted

# scan_id → job_id mapping so scan-based SSE streams can locate the current job without
# the caller having to thread job_id through every API surface.  Written on set_job (when
# scan_id is already in the initial state) and on update_job (when it first appears).
_SCAN_JOB_MAP: dict[str, str] = {}             # in-memory fallback; Redis is canonical

# Durable recovery checkpoint (Redis live-state spec, 2026-08-26): Redis is the fast, frequent
# live source, but it is EPHEMERAL — gone if unreachable, a key TTLs out, or a replica with no
# Redis falls to a JOBS dict no other replica can see. Without a fallback, a caller reading a
# scan's progress with Redis down gets nothing to show at all, not even "last known state, N
# seconds ago". This accumulates the SAME patches update_job already receives (no extra reads —
# scan_id only arrives in the initial set_job call on the durable-queue path, or later via
# update_job on the thread path, so it is cached here rather than re-derived) and flushes to
# Postgres sparsely: on every phase/done transition, and otherwise at most once per
# _CHECKPOINT_INTERVAL_S. That cadence is deliberate — this must stay far below the write volume
# that caused 2026-08-26's Postgres connection exhaustion; it is a recovery aid, not a live feed.
_JOB_SCAN_ID: dict[str, str] = {}              # job_id -> scan_id, for routing checkpoint writes
_JOB_CHECKPOINT_STATE: dict[str, dict] = {}    # job_id -> accumulated patch state
_JOB_LAST_CHECKPOINT: dict[str, float] = {}    # job_id -> monotonic time of last Postgres write
_CHECKPOINT_INTERVAL_S = float(os.environ.get("ACP_CHECKPOINT_INTERVAL_S", "20") or "20")


def _maybe_checkpoint(job_id: str, patch: dict) -> None:
    """Best-effort durable checkpoint — see the module comment above _JOB_SCAN_ID. Never raises:
    a diagnostic write must never fail the job it is describing, and this runs on the same
    worker thread doing the real work."""
    import time as _t
    if patch.get("scan_id"):
        _JOB_SCAN_ID[job_id] = patch["scan_id"]
    scan_id = _JOB_SCAN_ID.get(job_id)
    if not scan_id:
        return
    acc = _JOB_CHECKPOINT_STATE.setdefault(job_id, {})
    acc.update(patch)
    phase_changed = "phase" in patch or "done" in patch or "error" in patch
    now = _t.monotonic()
    last = _JOB_LAST_CHECKPOINT.get(job_id, 0.0)
    if not (phase_changed or now - last >= _CHECKPOINT_INTERVAL_S):
        return
    _JOB_LAST_CHECKPOINT[job_id] = now
    try:
        get_store().checkpoint_scan_progress(scan_id, dict(acc), patch["updated_at"])
    except Exception:
        swallowed("core._maybe_checkpoint: checkpointing scan progress failed")


def _write_scan_job_mapping(scan_id: str, job_id: str) -> None:
    r = _get_redis()
    if r is not None:
        try:
            r.set(f"scan_to_job:{scan_id}", job_id, ex=_JOB_TTL)
            return
        except Exception:
            swallowed("core._write_scan_job_mapping: writing the scan-to-job mapping to Redis "
                      "failed", scan_id)
    _SCAN_JOB_MAP[scan_id] = job_id


def get_job_id_for_scan(scan_id: str) -> str | None:
    """Return the current job_id for a scan (set on the durable queue path when the worker
    claims it, or on the thread path once the scan_id is assigned in update_job)."""
    r = _get_redis()
    if r is not None:
        try:
            return r.get(f"scan_to_job:{scan_id}")
        except Exception:
            swallowed("core.get_job_id_for_scan: reading the job id for this scan from Redis "
                      "failed", scan_id)
    return _SCAN_JOB_MAP.get(scan_id)

# A job stuck on a replica that died (redeploy, crash, OOM) leaves NO trace: the thread that
# would have called update_job() on error or completion is simply gone, so the job sits at
# whatever phase it was last written to, forever, with no error and no timeout. Live incident
# 2026-08-21: a scan queued shortly before a routine merge-triggered redeploy never advanced
# past phase="queued", scan_id=null — Assess correctly reported 0 eligible documents because
# there was, and would always be, no scan to be eligible under. Nothing surfaced that; the
# Discover screen just kept showing "scanning...".
#
# Detected here at READ time, not by a separate sweeper thread/cron: a sweeper is itself just
# another thread that can die with the replica, which is the exact failure mode this exists to
# catch — a mechanism to detect "the replica died" that itself lives on a replica is not a fix.
# A read-time check has no such single point of failure: whichever replica answers the poll
# computes staleness fresh from the shared timestamp, so it works even if every worker replica
# has been recycled since the job was written.
#
# The threshold has to be longer than the gap between liveness signals or a slow-but-alive job
# false-positives as dead. set_job/update_job stamp `updated_at` on EVERY write, and the scan
# thread below (routes/scans.py's `work()`) runs a heartbeat companion thread that touches it
# every _JOB_HEARTBEAT_SECONDS regardless of scan progress — so `updated_at` going stale means
# the REPLICA is gone, not merely that this particular scan is slow. That decouples the staleness
# signal from how long a legitimately large estate takes to crawl.
_JOB_HEARTBEAT_SECONDS = 20
_JOB_STALE_SECONDS = int(os.environ.get("ACP_JOB_STALE_SECONDS", "90") or "90")


def _job_now_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _job_is_stale(state: dict) -> bool:
    """True if `state` describes unfinished work with no liveness signal recent enough to trust.
    A MISSING updated_at (a job written before this instrumentation existed, or one whose replica
    died before its first heartbeat) counts as stale, not exempt — that is precisely the case the
    live incident above was.

    phase=='retrying' and phase=='reclaimed' are exempt for the same reason 'done' is: both are
    legitimate WAITING states,
    not a stalled one. No worker holds this job while it sits out its backoff — heartbeats
    stop by design — and rate-limit backoff alone can run up to 600s, well past the normal 90s
    staleness window. The exemption is bounded in practice: fail_job's own idempotency guard
    (see worker.py's on_retry call) only ever writes this phase when the job is genuinely
    'queued' for another attempt, and the next real attempt overwrites it with a live phase
    within seconds of being claimed."""
    if state.get("done") or state.get("phase") in ("retrying", "reclaimed"):
        return False
    ts = state.get("updated_at")
    if not ts:
        return True
    import datetime as _dt
    try:
        age = (_dt.datetime.now(_dt.timezone.utc) - _dt.datetime.fromisoformat(ts)).total_seconds()
    except Exception:
        return True                        # unparseable timestamp is as untrustworthy as none
    return age > _JOB_STALE_SECONDS


def set_job(job_id: str, state: dict) -> None:
    """Write a fresh job record, replacing any prior state. Uses a Redis hash (HSET) so
    subsequent update_job calls can atomically patch individual fields without a read-modify-write
    race. seq is initialised to 0; every update_job call increments it, giving the SSE stream a
    cheap change signal without a full diff."""
    state = {**state, "updated_at": _job_now_iso(), "seq": 0}
    _maybe_checkpoint(job_id, state)   # independent of Redis/in-memory below — see its own comment
    r = _get_redis()
    if r is not None:
        try:
            import json as _j
            mapping = {k: _j.dumps(v) for k, v in state.items()}
            pipe = r.pipeline()
            pipe.delete(f"job:{job_id}")
            pipe.hset(f"job:{job_id}", mapping=mapping)
            pipe.expire(f"job:{job_id}", _JOB_TTL)
            pipe.execute()
            _JOB_LAST_REDIS_WRITE[job_id] = 0.0   # reset coalesce clock
            if state.get("scan_id"):
                _write_scan_job_mapping(state["scan_id"], job_id)
            return
        except Exception:
            # fall through to in-memory
            swallowed("core.set_job: writing the job state to Redis failed")
    if not REDIS_URL:
        import logging as _log
        _log.warning("REDIS_URL not set — job %s state stored in-memory only; "
                     "progress will NOT be visible across replicas", job_id)
    JOBS[job_id] = state
    if state.get("scan_id"):
        _write_scan_job_mapping(state["scan_id"], job_id)


def update_job(job_id: str, patch: dict) -> None:
    """Merge patch into the stored job record.

    Redis path uses HSET (atomic per-field write, no read needed) followed by HINCRBY on the seq
    counter — both in a single pipeline. Concurrent heartbeat and progress writes can no longer
    race and overwrite each other's data, unlike the old read-modify-write approach.

    High-frequency ticks (e.g. files_found incrementing during listing) are coalesced: the Redis
    write is skipped when the last write was < _JOB_COALESCE_SECONDS ago AND the patch carries no
    phase/done/error key. Those keys always flush immediately so the UI sees transitions right away.
    The in-memory JOBS dict (same-replica poll fallback) is always updated regardless."""
    import time as _t
    patch = {**patch, "updated_at": _job_now_iso()}
    _maybe_checkpoint(job_id, patch)   # independent of Redis/in-memory below — see its own comment
    r = _get_redis()
    if r is not None:
        now = _t.monotonic()
        is_immediate = "phase" in patch or "done" in patch or "error" in patch
        last = _JOB_LAST_REDIS_WRITE.get(job_id, 0.0)
        if is_immediate or now - last >= _JOB_COALESCE_SECONDS:
            try:
                import json as _j
                mapping = {k: _j.dumps(v) for k, v in patch.items()}
                pipe = r.pipeline()
                pipe.hset(f"job:{job_id}", mapping=mapping)
                pipe.hincrby(f"job:{job_id}", "seq", 1)
                pipe.expire(f"job:{job_id}", _JOB_TTL)
                pipe.execute()
                _JOB_LAST_REDIS_WRITE[job_id] = now
                if patch.get("scan_id"):
                    _write_scan_job_mapping(patch["scan_id"], job_id)
                return
            except Exception:
                swallowed("core.update_job: patching the job state in Redis failed")
    # scan_id mapping must be written even when the coalesce window suppressed the main write.
    if patch.get("scan_id"):
        _write_scan_job_mapping(patch["scan_id"], job_id)
    # In-memory fallback — either Redis unavailable or coalesce window suppressed the write.
    # Also updates JOBS in the coalesce case so same-replica reads stay current.
    if job_id in JOBS:
        JOBS[job_id].update(patch)


def get_job_state(job_id: str) -> dict | None:
    """The poll's answer, with staleness resolved into an honest terminal state rather than left
    for the caller to notice. Never mutates the stored record — every replica computes this fresh,
    so an already-dead job reads the same way from whichever replica answers the next poll.

    Reads from a Redis hash (HGETALL). Falls back to the old JSON-string format during the
    deployment window when string-type keys from pre-HSET instances are still live in Redis."""
    r = _get_redis()
    state = None
    if r is not None:
        try:
            import json as _j
            raw = r.hgetall(f"job:{job_id}")
            if raw:
                state = {k: _j.loads(v) for k, v in raw.items()}
        except Exception:
            # Key may be the old JSON-string type (pre-HSET deployment) — try a plain GET.
            try:
                import json as _j
                v = r.get(f"job:{job_id}")
                if v:
                    state = _j.loads(v)
            except Exception:
                swallowed("core.get_job_state: reading the job state from Redis failed")
    if state is None:
        state = JOBS.get(job_id)
    if state is None:
        return None
    if _job_is_stale(state):
        return {**state, "phase": "error", "done": True,
                "error": (state.get("error") or
                          "scan interrupted — the server likely restarted mid-run; "
                          "please start a new scan")}
    return state


def finalize_scan(scan_id: str, effective_ai: bool, source: str) -> None:
    """Shared post-scan step: audit the run and, in deterministic mode, auto-route
    ai-assisted findings to the HITL queue. Used by both the threaded and queued
    scan paths so they behave identically.

    Finalize-once (ADR 0013): a crash between a fan-out file's bump and completion used to
    re-trigger and double-emit HITL/audit. mark_finalized claims the scan atomically, so
    only the first caller runs this body; duplicate/concurrent scan_finalize jobs no-op."""
    if not get_store().mark_finalized(scan_id):
        return
    get_store().log_decision(
        "system", "scan.completed", scan_id=scan_id,
        detail=f"source={source} mode={'ai-assisted' if effective_ai else 'deterministic'}")
    if not effective_ai:
        created = get_store().queue_hitl_items(scan_id)
        if created:
            fire_webhook(created)
            get_store().log_decision(
                "system", "hitl.auto_routed", scan_id=scan_id,
                detail=f"deterministic mode → {len(created)} ai-assisted findings routed to HITL")


def start_workers() -> int:
    """Spawn the worker pool + a stuck-job sweeper. Pool size = ACP_WORKERS,
    always -- a deploy-time env var must mean what it says. (Previously a
    persisted worker_count setting from a prior live-scale action silently
    overrode ACP_WORKERS on every restart, so setting ACP_WORKERS at deploy
    time had no visible effect once anyone had ever used the +/- live-scale
    buttons.) Live-scaling via the UI still works for the running process; it
    just no longer survives the next restart. No-op when ACP_WORKERS is 0."""
    global WORKERS
    if _worker_handles:
        return len(_worker_handles)
    import threading
    import handlers  # noqa: F401 — registers job handlers with the worker
    WORKERS = max(0, min(WORKERS, _MAX_WORKERS))
    for _ in range(WORKERS):
        _spawn_worker()

    # Always start the sweeper (even at 0 workers) so a later live scale-up is covered.
    #
    # Delegates to sweeper.run_sweep() (ADR 0004 step 5) rather than reimplementing the
    # checks inline. Found live 2026-08-27: run_sweep() already covered four checks —
    # reclaim_stuck_jobs, sweep_exhausted_jobs, sweep_orphaned_scans, rescue_unfinalized_scans
    # — and was fully tested (tests/test_reconciliation_sweeper.py), but nothing in
    # production ever imported it. This inline loop called only two of the four directly,
    # so a queued job past max_attempts was never dead-lettered, and a 'running' scan_runs
    # row with zero outstanding jobs (worker died between fan-out and finalize) was never
    # marked 'interrupted' — both sat silently stuck with no error and no error visible
    # anywhere. Wiring run_sweep() here means the next sweep check added to sweeper.py
    # takes effect in production automatically, not on the next person to remember this
    # loop exists too.
    def _sweep():
        import time as _t
        import sweeper as _sweeper
        import content_workspace_retention as _retention
        ticks = 0
        while True:
            try:
                # 30-min lease: scans of large estates legitimately run ~10-15min, so
                # reclaim only clearly-dead jobs. The worker heartbeat (best-effort)
                # extends this further; this is the reliable floor if it can't. Grace
                # window for orphaned-scan detection uses sweeper.py's own env-driven
                # default (ACP_SWEEP_GRACE_S, 600s) — no prior production value to match.
                _sweeper.run_sweep(get_store(), lease_seconds=1800)
                # ADR 0044 / PRD §28: same thread, same "wire it in or it never runs in
                # production" lesson this loop's own history already taught (see the comment
                # above this function) — a separate, untested-in-production thread is exactly
                # how a capability sits fully built and never actually fires.
                _retention.run_content_workspace_retention_sweep(get_store())
                ticks += 1
                if ticks % 60 == 0:      # ~hourly: trim old completed jobs so the jobs
                    d = get_store().purge_done_jobs(older_than_hours=24)   # table + claim index don't bloat (audit P2)
                    if d:
                        print(f"[sweeper] purged {d} old done job(s)", flush=True)
            except Exception as e:
                print(f"[sweeper] error: {e}", flush=True)
            _t.sleep(60)
    threading.Thread(target=_sweep, daemon=True, name="jobsweeper").start()
    return WORKERS
