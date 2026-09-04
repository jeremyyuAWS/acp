"""Which capability each API route requires (PRD §11), as one table.

WHY A TABLE AND NOT 236 DECORATORS. This repo has 236 routes. Decorating each one puts the
authorization decision in 236 places, and PRD §18 asks for "100% of workflow routes mapped to a
capability" — a claim nobody can check by reading 236 files. Worse, the failure mode of the
decorator approach is silent: a route added without one is simply unprotected, and looks exactly
like a route that was deliberately left open.

So the mapping lives here, enforcement happens once (api/app.py's middleware), and
tests/test_capability_map_is_complete.py asserts that EVERY route the app actually dispatches is
either mapped or explicitly exempt with a reason. A new route fails that test until somebody
decides which it is. That is the difference between "we mapped everything" and "we can show that
everything is mapped".

ANY-OF, NOT ALL-OF, and that is the important modelling choice. A route is reachable if the caller
holds ANY of the capabilities listed for it. Routes do not belong to one tab: GET /scans/{sid}
backs Discover, Assess, Remediate and Release, and requiring `discover.view` for it would break
Assess for a Viewer whose Discover is hidden — a role the PRD's own §7 grid defines. So a shared
READ route lists the view capability of every tab that legitimately uses it, and a MUTATING route
lists the single capability that names the action.

    read  /scans/{sid}          -> {discover.view, assess.view, remediate.view, release.view}
    write POST /scans/{sid}/remediate -> {remediate.run}

Getting this backwards — one capability per route, chosen by whichever tab came to mind — is how
enforcement ships as a pile of 403s for roles the PRD says should work.

EXEMPT IS NOT "FORGOTTEN". Every exemption carries a reason, and the three kinds are:
  * unauthenticated by design (health, the public verify endpoint, the SPA's config)
  * identity, which must answer before a role can be known (/me, /me/access, the bootstrap)
  * a DIFFERENT authorization boundary that PRD §3 says not to disturb — every /acr route is
    governed by acr_authz per report, and workspace roles must not silently start gating them.
"""
from __future__ import annotations

import workspace_rbac as rbac

# Shorthand for the read-side unions that appear repeatedly below.
_SCAN_READ = frozenset({"discover.view", "assess.view", "remediate.view", "release.view",
                        "monitor.view"})
_ASSESS_READ = frozenset({"assess.view", "remediate.view", "release.view"})
_REMEDIATE_READ = frozenset({"remediate.view", "release.view"})
_SOURCES_READ = frozenset({"sources.view", "discover.view"})

# (method, path) -> the capabilities that grant it; holding ANY is enough.
ROUTE_CAPABILITIES: dict[tuple[str, str], frozenset[str]] = {}


def _map(method: str, path: str, caps) -> None:
    ROUTE_CAPABILITIES[(method.upper(), path)] = frozenset(caps)


def _map_many(pairs, caps) -> None:
    for method, path in pairs:
        _map(method, path, caps)


# ── Sources (the Sources tab) ─────────────────────────────────────────────────
_map_many([
    ("GET", "/sources"), ("GET", "/sources/locations"), ("GET", "/folders"),
    ("GET", "/sharepoint/sites"), ("GET", "/sharepoint/folders"),
    ("GET", "/sharepoint/sites/{site_id:path}/drives"),
    ("GET", "/drive/folder-name"), ("GET", "/drive/adc-scopes"),
], _SOURCES_READ)
# Changing where ACP looks is `sources.manage` (PRD §5), not merely seeing the tab.
_map_many([("PUT", "/sources/locations")], {"sources.manage"})
# Uploading INTO a source is a write to the customer's estate.
_map_many([("POST", "/drive/upload"), ("POST", "/sharepoint/upload")], {"sources.manage"})

# ── Discover ──────────────────────────────────────────────────────────────────
_map_many([("POST", "/scans"), ("POST", "/discovery/preflight")], {"discover.run"})
_map_many([
    ("GET", "/scans"), ("GET", "/scans/active"), ("GET", "/inventory"),
    ("GET", "/scans/{sid}"), ("GET", "/scans/{sid}/status"), ("GET", "/scans/{sid}/live"),
    ("GET", "/scans/{sid}/events"), ("GET", "/scans/{sid}/history"),
    ("GET", "/scans/{sid}/timeline"), ("GET", "/scans/{sid}/timings"),
    ("GET", "/scans/{sid}/manifest"), ("GET", "/scans/{sid}/digest"),
    ("GET", "/scans/{sid}/inventory"), ("GET", "/scans/{sid}/inventory-diff"),
    ("GET", "/scans/{sid}/inventory.csv"), ("GET", "/scans/{sid}/exceptions.csv"),
    ("GET", "/scans/{sid}/source-status"),
    ("GET", "/scans/{sid}/queue-estimate"), ("GET", "/scans/{sid}/pii"),
    ("GET", "/scans/jobs/{job_id}"), ("GET", "/scans/{sid}/comment-counts"),
    ("GET", "/scans/{sid}/comments"), ("GET", "/decisions"), ("GET", "/scans/{sid}/decisions"),
    ("GET", "/scans/{sid}/files/{filename:path}/examined"),
    ("GET", "/scans/{sid}/files/{filename:path}/status"),
], _SCAN_READ)
# A scan's own lifecycle. Cancel is `assess.cancel` (PRD §11 names it); delete and token
# management belong to whoever may RUN discovery, since they are that scan's controls.
_map_many([("POST", "/scans/{sid}/cancel")], {"assess.cancel", "discover.run"})
_map_many([
    ("DELETE", "/scans/{sid}"), ("POST", "/scans/{sid}/drive-token"),
    ("POST", "/scans/{sid}/sp-token"), ("DELETE", "/scans/{sid}/tokens"),
    ("PUT", "/scans/{sid}/acknowledge"), ("DELETE", "/scans/{sid}/acknowledge"),
], {"discover.run"})
_map_many([("POST", "/scans/{sid}/comments")], _SCAN_READ)   # commenting is part of reviewing
_map_many([
    ("PUT", "/scans/{sid}/decisions"), ("PUT", "/scans/{sid}/decisions/{filename:path}"),
    ("POST", "/scans/{sid}/files/{filename:path}/confirm"),
], {"discover.run", "assess.run", "remediate.run"})
# Scope rules decide WHAT is scanned — a discovery-shaped decision.
_map_many([("GET", "/scope/rules"), ("GET", "/scope/selectors")], {"discover.view"})
_map_many([("POST", "/scope/rules"), ("PATCH", "/scope/rules/{rule_id}"),
           ("DELETE", "/scope/rules/{rule_id}")], {"discover.run"})

# ── Assess ────────────────────────────────────────────────────────────────────
_map_many([("POST", "/scans/{sid}/assess"), ("POST", "/scans/{sid}/rescore")], {"assess.run"})
_map_many([
    ("GET", "/assess/codeset"), ("GET", "/assess/eligibility"),
    ("GET", "/assess/eligibility/scoped"), ("GET", "/scans/{sid}/traces"),
    ("GET", "/scans/{sid}/ai_calls"), ("GET", "/rules"), ("GET", "/capability"),
    ("GET", "/scans/{sid}/trace/session"), ("GET", "/scans/{sid}/trace/session/data"),
    ("GET", "/scans/{sid}/trace/{kind}/exists"),
    ("GET", "/scans/{sid}/trace/file/{filename:path}/data"),
    ("GET", "/scans/{sid}/trace/file/{filename:path}/exists"),
    ("GET", "/scans/{sid}/trace/file/{filename:path}/history"),
], _ASSESS_READ)
# The evidence primitives — page renders, geometry, contrast checks. Read-only views OF a
# document, used by both the Assess worklist and the Remediate review card.
_map_many([
    ("GET", "/scans/{scan_id}/files/{filename:path}/content"),
    ("GET", "/scans/{scan_id}/files/{filename:path}/thumbnail"),
    ("GET", "/scans/{scan_id}/files/{filename:path}/page/{page}"),
    ("GET", "/scans/{scan_id}/files/{filename:path}/geometry"),
    ("GET", "/scans/{scan_id}/files/{filename:path}/source_link"),
    ("GET", "/scans/{scan_id}/files/{filename:path}/heading-outline"),
    ("GET", "/scans/{scan_id}/files/{filename:path}/table-structure"),
    ("GET", "/scans/{scan_id}/files/{filename:path}/verify-contrast"),
    ("GET", "/scans/{scan_id}/files/{filename:path}/verify-resize"),
    ("GET", "/scans/{scan_id}/files/{filename:path}/verify-pdf-contrast"),
    ("GET", "/scans/{scan_id}/files/{filename:path}/dispositions"),
], _ASSESS_READ)
_map_many([
    ("POST", "/scans/{scan_id}/files/{filename:path}/dispose"),
], {"assess.run"})
# The rubric is what "compliant" MEANS. Reading it is part of assessing; changing it is a
# platform-configuration act, which is why it sits behind Settings rather than Assess.
_map_many([("GET", "/rubric")], _ASSESS_READ)
_map_many([("PUT", "/rubric")], {"settings.view"})

# ── Remediate ─────────────────────────────────────────────────────────────────
_map_many([
    ("POST", "/scans/{sid}/remediate"),
    ("POST", "/scans/{scan_id}/files/{filename:path}/remediate"),
    ("POST", "/scans/{sid}/files/{filename:path}/undo-fix"),
], {"remediate.run"})
_map_many([
    ("GET", "/scans/{sid}/remediation-status"), ("GET", "/scans/{sid}/remediation-diffs"),
    ("GET", "/scans/{sid}/files/{filename:path}/remediation-diffs"),
    ("GET", "/scans/{sid}/files/{filename:path}/remediation-state"),
    ("GET", "/scans/{sid}/applied-fixes"), ("GET", "/scans/{sid}/diff"),
    ("GET", "/scans/{scan_id}/files/{filename:path}/remediated"),
    ("GET", "/hitl/queue"), ("GET", "/hitl/analytics"),
    ("GET", "/hitl/queue/{item_id}/companion"),
], _REMEDIATE_READ)
# The review queue: approving or rejecting a proposed fix IS the review action (PRD §11's
# `remediate.review`), and it is deliberately not the same as running remediation.
_map_many([
    ("PUT", "/hitl/queue/{item_id}"), ("PATCH", "/hitl/queue/{item_id}/assign"),
    ("POST", "/hitl/queue/{scan_id}/auto"), ("POST", "/hitl/queue/{scan_id}/verify"),
], {"remediate.review"})
# AI drafting assists a reviewer; it writes nothing to a document on its own.
_map_many([("GET", "/ai/suggest"), ("GET", "/ai/explain"), ("GET", "/ai/validate"),
           ("GET", "/ai/copilot")],
          {"remediate.review", "remediate.run"})

# ── Release ───────────────────────────────────────────────────────────────────
# Publishing is a GRANT (PRD §5), never implied by seeing the Release tab.
_map_many([("POST", "/scans/{sid}/publish")], {"release.publish"})
_map_many([("GET", "/scans/{sid}/report.pdf")], {"release.view", "reports.export"})

# ── Monitor ───────────────────────────────────────────────────────────────────
_map_many([("GET", "/monitor/estate"), ("GET", "/schedule"),
           ("GET", "/analytics/compliance-trend")], {"monitor.view"})
_map_many([("PUT", "/schedule")], {"monitor.view", "settings.view"})

# ── Live Operations ───────────────────────────────────────────────────────────
_map_many([("GET", "/admin/activity"), ("GET", "/jobs"), ("GET", "/jobs/{job_id}"),
           ("GET", "/control/estate"), ("GET", "/control/workers/capacity"),
           ("GET", "/control/costs"),
           ("GET", "/control/workers/replicas"), ("GET", "/control/workers/revisions")],
          {"operations.view"})
_map_many([("POST", "/admin/jobs/clear-dead"), ("PATCH", "/control/workers/replicas")],
          {"workers.manage"})

# ── Scan Analytics ────────────────────────────────────────────────────────────
_map_many([("GET", "/admin/analytics/overview"), ("GET", "/ai/costs")], {"analytics.view"})

# ── Settings and platform administration ──────────────────────────────────────
_map_many([("GET", "/settings"), ("GET", "/ai/providers"), ("GET", "/ai/status")],
          {"settings.view"})
_map_many([("PUT", "/settings"), ("PUT", "/ai/providers"), ("POST", "/ai/providers/test")],
          {"settings.view"})
_map_many([("PUT", "/workers")], {"workers.manage"})
_map_many([("GET", "/admin/people"), ("GET", "/admin/allowlist"), ("GET", "/admin/admins")],
          {"people.manage"})
_map_many([
    ("POST", "/admin/people"), ("PUT", "/admin/people/{email:path}"),
    ("DELETE", "/admin/people/{email:path}"), ("PUT", "/admin/allowlist"),
    ("POST", "/admin/invite"), ("PUT", "/admin/admins"),
], {"people.manage"})
_map_many([("PUT", "/admin/people/{email:path}/role"),
           ("GET", "/admin/people/{email:path}/role-impact")], {"people.manage"})
_map_many([
    ("GET", "/admin/roles"), ("GET", "/admin/roles/{role_id}"), ("GET", "/admin/capabilities"),
    ("POST", "/admin/roles"), ("PUT", "/admin/roles/{role_id}"),
    ("DELETE", "/admin/roles/{role_id}"), ("POST", "/admin/workspace-roles/bootstrap"),
    ("GET", "/admin/workspace-roles/preflight"),
], {"roles.manage"})
# Wiping the workspace is the most destructive action ACP has; it stays owner-only at the route
# (_require_owner) and is additionally mapped here so it can never be reached by a role.
_map_many([("POST", "/admin/reset")], {"roles.manage"})

# ── Lifecycle / disposition ───────────────────────────────────────────────────
# Deciding what happens to a document at end of life is a Release-shaped decision, and executing
# it moves or trashes real files — which is why the two are separated.
_map_many([
    ("GET", "/disposition/policies"), ("GET", "/disposition/policies/conflicts"),
    ("GET", "/disposition/audit"), ("GET", "/disposition/approvals"),
    ("GET", "/scans/{sid}/lifecycle/files"), ("GET", "/scans/{sid}/lifecycle/rules"),
    ("GET", "/scans/{sid}/lifecycle/summary"),
    ("GET", "/scans/{sid}/lifecycle/files/{document_id:path}"),
    ("GET", "/scans/{sid}/lifecycle/files/{document_id:path}/history"),
], {"release.view", "monitor.view"})
_map_many([
    ("POST", "/disposition/policies"), ("PUT", "/disposition/policies/{policy_id}"),
    ("DELETE", "/disposition/policies/{policy_id}"),
    ("PUT", "/disposition/policies/{policy_id}/enabled"),
    ("PUT", "/disposition/policies/reorder"), ("POST", "/disposition/preview"),
    ("POST", "/disposition/policies/{policy_id}/preview"),
    ("POST", "/scans/{sid}/files/{filename:path}/lifecycle-override"),
    ("POST", "/disposition/approvals"), ("POST", "/disposition/approvals/plan"),
], {"release.view"})
# Approving and executing a move-or-trash. `release.publish` because it is the same class of act:
# an irreversible change to the customer's estate.
_map_many([
    ("POST", "/disposition/approvals/{audit_id}/approve"),
    ("POST", "/disposition/approvals/{audit_id}/reject"),
    ("POST", "/disposition/approvals/{audit_id}/undo"),
    ("POST", "/disposition/policies/{policy_id}/execute"),
], {"release.publish"})

# ── Campaigns, org memory, content workspaces ─────────────────────────────────
_map_many([("GET", "/campaigns"), ("GET", "/campaigns/{campaign_id}")], _REMEDIATE_READ)
_map_many([
    ("POST", "/campaigns"), ("PUT", "/campaigns/{campaign_id}/status"),
    ("PUT", "/campaigns/{campaign_id}/batches/{batch_id}/status"),
], {"remediate.run"})
_map_many([("GET", "/org-memory")], _REMEDIATE_READ)
_map_many([("POST", "/org-memory"), ("POST", "/org-memory/derive"),
           ("PUT", "/org-memory/{mid}/status")], {"remediate.review"})
_map_many([
    ("GET", "/content-workspaces"), ("GET", "/content-workspaces/{workspace_id}"),
    ("GET", "/content-workspaces/{workspace_id}/documents"),
    ("GET", "/content-workspaces/{workspace_id}/documents/{document_id}"),
    ("GET", "/content-workspaces/{workspace_id}/documents/{document_id}/versions/{version_id}/assessment"),
    ("GET", "/content-workspaces/{workspace_id}/documents/{document_id}/versions/{version_id}/download"),
], _SOURCES_READ)
_map_many([
    ("POST", "/content-workspaces"),
    ("POST", "/content-workspaces/{workspace_id}/documents/upload-session"),
    ("POST", "/content-workspaces/{workspace_id}/documents/{document_id}/complete"),
    ("POST", "/content-workspaces/{workspace_id}/documents/{document_id}/resolve-duplicate"),
    ("POST", "/content-workspaces/{workspace_id}/documents/{document_id}/versions/upload-session"),
], {"sources.manage"})
_map_many([
    ("POST", "/content-workspaces/{workspace_id}/assess"),
    ("POST", "/content-workspaces/{workspace_id}/documents/{document_id}/versions/{version_id}/assess"),
], {"assess.run"})

# ── Exports (PRD §5's "Export reports or inventory") ──────────────────────────
_map_many([("GET", "/hub")], {"reports.export", "monitor.view"})

# ── SSE streams (PRD §16) ─────────────────────────────────────────────────────
# "SSE streams enforce the same permissions as their corresponding status endpoints." Listed
# together, and asserted against those endpoints in the tests, because a stream is the ONE place
# where forgetting is invisible: a 403 on a status poll is obvious in the UI, while an unguarded
# stream just keeps delivering — the data still flows, nobody sees an error, and the leak looks
# like the feature working.
STREAM_TWINS: dict[tuple[str, str], tuple[str, str]] = {
    ("GET", "/scans/{scan_id}/discover/stream"): ("GET", "/scans/{sid}/status"),
    ("GET", "/scans/{sid}/remediation/stream"): ("GET", "/scans/{sid}/remediation-status"),
    ("GET", "/scans/jobs/{job_id}/stream"): ("GET", "/scans/jobs/{job_id}"),
    ("GET", "/admin/activity/stream"): ("GET", "/admin/activity"),
}
for _stream, _twin in STREAM_TWINS.items():
    _map(_stream[0], _stream[1], ROUTE_CAPABILITIES[_twin])


# ── exempt, with reasons ──────────────────────────────────────────────────────
# Each entry says WHY. An exemption without one is indistinguishable from an oversight, and the
# completeness test refuses a route that is in neither table.
EXEMPT: dict[tuple[str, str], str] = {
    ("GET", "/healthz"): "liveness probe — must answer before anything is configured",
    ("GET", "/readyz"): "readiness probe — same",
    ("GET", "/probe/readyz"): "readiness probe — same",
    ("GET", "/docs/health"): "documentation health, no customer data",
    ("GET", "/openapi/health.json"): "schema of the health endpoint, no customer data",
    ("GET", "/config"): "fetched PRE-AUTH by the SPA to know how to sign in",
    ("GET", "/public/verify/{scan_id}"): "R15 — anyone may verify a report digest without an account",
    ("POST", "/alerts/webhook"): "inbound webhook, authenticated by its own shared secret",
    # Identity must answer BEFORE a role can be known. Gating these on a capability is circular:
    # the SPA cannot learn it has no access without being allowed to ask.
    ("GET", "/me"): "identity — must answer before a role can be resolved",
    ("GET", "/me/access"): "the role answer itself; gating it on a capability is circular",
    ("GET", "/workspace/bootstrap"): "carries /me/access; same circularity",
    ("POST", "/me/reset-data"): "self-service, scoped to the caller's OWN scans by construction",
    ("GET", "/settings/mine"): "the caller's own preferences",
    ("PUT", "/settings/mine"): "the caller's own preferences",
    ("DELETE", "/settings/mine"): "the caller's own preferences",
    # A plain <a> navigation target with no auth header; it only 302s to a Langfuse deep link,
    # and core.is_public already treats it as public.
    ("GET", "/scans/{sid}/trace/{kind}"): "unauthenticated redirect target (see core.is_public)",
    ("GET", "/scans/{sid}/trace/file/{filename:path}"): "same redirect target, per-file form",
}

# Every /acr route: a DIFFERENT authorization boundary. PRD §3 — "They must not replace or
# silently change ACR approval roles, which govern a different authorization boundary" — and §14
# — "Existing ACR roles remain independently enforced". api/acr_authz.py gates these per report;
# adding a workspace capability on top would mean a workspace role could silently deny an
# approver their own report, which is exactly the interference the PRD forbids.
ACR_PREFIX_EXEMPT = "/acr"


def is_exempt(method: str, path: str) -> bool:
    if path == ACR_PREFIX_EXEMPT or path.startswith(ACR_PREFIX_EXEMPT + "/"):
        return True
    return (method.upper(), path) in EXEMPT


def required_capabilities(method: str, path: str) -> frozenset[str] | None:
    """What this route needs, or None when it is exempt or unknown.

    None is DELIBERATELY ambiguous between "exempt" and "not in the table", and the middleware
    treats it as allow — because an unknown route is a bug in this file, and a 403 on every
    unmapped route would take the product down on the day somebody adds an endpoint. The
    completeness test is what makes that safe: an unmapped route cannot reach main.
    """
    return ROUTE_CAPABILITIES.get((method.upper(), path))


def unmapped_routes(routes) -> list[tuple[str, str]]:
    """Every (method, path) that is neither mapped nor exempt. Empty is the invariant."""
    out = []
    for route in routes:
        for method in (route.methods or ()):
            if method in ("HEAD", "OPTIONS"):
                continue
            key = (method.upper(), route.path)
            if key not in ROUTE_CAPABILITIES and not is_exempt(*key):
                out.append(key)
    return sorted(set(out))


def unknown_capabilities() -> list[str]:
    """Capabilities named here that the catalog does not define — a typo in this file otherwise
    produces a route nobody can ever reach, since no role can hold a capability that is not real."""
    named = {cap for caps in ROUTE_CAPABILITIES.values() for cap in caps}
    return sorted(named - rbac.CAPABILITIES)
