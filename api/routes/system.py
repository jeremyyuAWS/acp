"""System & meta endpoints: liveness, SPA auth config, schedule, hub landing page."""
from __future__ import annotations

import hmac
import json
import re
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict

import core
from swallowed import swallowed

router = APIRouter()

# A secret REFERENCE is an environment-variable name (e.g. AZURE_OPENAI_API_KEY), never a key
# value. This shape is what keeps a pasted key out of the DB: a real key won't match it.
_SECRET_REF_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,64}$")


def _require_admin(request: Request) -> None:
    """Platform-admin gate for platform-mutating admin endpoints. The SPA hides these
    behind the Platform Admin role, but the API must enforce it too — any
    allow-listed user could otherwise flip platform settings (AI mode, Drive
    mirror, worker pool, data reset) with a direct call. Admin = the protected
    OWNER_EMAIL (the anti-lockout identity the allowlist can never drop) OR any
    ACP_ADMIN_EMAILS entry — the same `core.is_admin` set the SPA's is_scope_owner
    flag reads, so UI and API never disagree. No-op when no owner is configured
    (local dev without auth)."""
    if not core.OWNER_EMAIL:
        return
    email = (getattr(request.state, "user_email", None) or "").lower()
    if not core.is_admin(email):
        raise HTTPException(403, "admin access required")


def _require_owner(request: Request) -> None:
    """Owner-only gate — stricter than _require_admin. Managing WHO is an admin is the root-of-trust
    action, so only the protected OWNER_EMAIL may promote/demote admins; an admin cannot grant admin
    (nor remove the owner). No-op when no owner is configured (local dev without auth)."""
    if not core.OWNER_EMAIL:
        return
    email = (getattr(request.state, "user_email", None) or "").lower()
    if not core.is_owner(email):
        raise HTTPException(403, "owner access required")


@router.post("/admin/reset")
def admin_reset(request: Request,
                scope: str = Query("all", pattern="^(all|grafana|langfuse)$"),
                confirm: bool = Query(False)):
    _require_owner(request)   # destructive + irreversible (wipes data + blobs) — owner-only
    """Reset demo data so the charts start fresh (admin, audited).
    scope=grafana → clear the ACP Postgres analytics tables (Grafana + in-app
    charts); scope=langfuse → delete the project's Langfuse traces; all → both.
    Settings (worker count, AI mode, schedule, rubric) are preserved."""
    if not confirm:
        raise HTTPException(400, "confirmation required — pass confirm=true")
    cleared: list[str] = []
    lf_deleted = 0
    blobs_purged: dict = {}
    if scope in ("all", "grafana"):
        cleared = core.store.reset_analytics()
        # reset_analytics drops the remediation_state / applied_fixes / … ROWS but the fixed
        # file bytes, cached originals and previews live in blob storage — purge them too so
        # "reset" is a true clean slate and no legacy remediation survives. Best-effort:
        # no-op when blob isn't configured (local dev), never raises into the reset.
        try:
            from blob import purge_all
            blobs_purged = purge_all()
        except Exception as e:  # pragma: no cover - defensive; blob purge must not fail the reset
            blobs_purged = {"error": str(e)}
    if scope in ("all", "langfuse"):
        lf_deleted = core.reset_langfuse_traces()
    # Logged AFTER the wipe so the reset itself is recorded.
    _blob_total = sum(v for v in blobs_purged.values() if isinstance(v, int) and v > 0)
    core.store.log_decision("admin", "demo.reset",
                            detail=f"scope={scope} · tables={len(cleared)} · langfuse_traces={lf_deleted} · blobs={_blob_total}")
    return {"scope": scope, "cleared_tables": cleared, "langfuse_traces_deleted": lf_deleted,
            "blobs_purged": blobs_purged}


@router.post("/me/reset-data")
def reset_my_data(request: Request, confirm: bool = Query(False)):
    """Self-service reset (destructive + irreversible, DB rows only): clears the SIGNED-IN USER'S
    OWN scans and everything tied to them, so two people testing concurrently never clear each
    other's work — unlike /admin/reset, which wipes every user's data and is owner-only. No admin
    gate here on purpose: this only ever touches the caller's own rows (see
    store.reset_user_data's docstring for exactly what is and isn't cleared — notably, it does not
    purge Blob/Drive copies, and it does not delete the immutable decision_log; it appends to it)."""
    if not confirm:
        raise HTTPException(400, "confirmation required — pass confirm=true")
    owner = (getattr(request.state, "user_email", None) or "demo")
    result = core.store.reset_user_data(owner)
    core.store.log_decision(owner, "reset_user_data",
                            detail=f"tables={len(result['cleared_tables'])}")
    return result


@router.post("/alerts/webhook")
async def alert_webhook(request: Request, key: str = Query("")):
    """Receiver for Grafana alert notifications (public path, shared-secret).
    Each firing/resolved alert is recorded in the immutable decision log, so
    delivery is visible in-product (audit feed + the Grafana 'Recent decisions'
    panel) without needing external SMTP."""
    if key != core.ALERT_KEY:
        raise HTTPException(401, "bad alert key")
    try:
        body = await request.json()
    except Exception:
        body = {}
    alerts = body.get("alerts") or []
    for a in alerts:
        labels = a.get("labels", {}) or {}
        name = labels.get("alertname", "alert")
        status = a.get("status", "firing")
        summary = (a.get("annotations", {}) or {}).get("summary", "")
        core.store.log_decision("grafana", f"alert.{status}",
                                detail=f"{name}: {summary}".strip(" :"))
    # If a downstream HITL webhook is configured, forward a compact note too.
    if alerts and core.HITL_WEBHOOK:
        try:
            import httpx
            httpx.post(core.HITL_WEBHOOK, json={"event": "grafana.alert", "alerts": [
                {"name": (a.get("labels", {}) or {}).get("alertname"),
                 "status": a.get("status")} for a in alerts]}, timeout=6)
        except Exception:
            swallowed("routes.system.alert_webhook: posting the alert webhook failed")
    return {"received": len(alerts)}


@router.get("/admin/allowlist")
def get_allowlist():
    """Test users who can use the app: the editable list, the protected owner (can't be
    removed), and any always-allowed domains. `invite_enabled` tells the UI whether the opt-in
    guest-invite action is configured (ADR 0033) — it hides when the credential is unset."""
    import invites
    return {"emails": core.store.get_allowlist(),
            "owner": core.OWNER_EMAIL,
            "domains": core.ALLOWED_DOMAINS,
            "invite_enabled": invites.invite_configured()}


@router.post("/admin/invite")
def invite_tester(body: dict, request: Request):
    """Invite an external tester as an Entra B2B guest AND add them to the allowlist in one step
    (ADR 0033). Owner-only. 409 when the invite credential isn't configured — the feature ships
    dark, so this path simply doesn't exist until an operator opts in. Least-privilege: this sends
    a guest invite (Graph User.Invite.All), it does NOT create a tenant user."""
    _require_owner(request)   # manages the login perimeter — owner-only
    import invites
    email = (body.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "a valid email is required")
    if not invites.invite_configured():
        raise HTTPException(409, "guest invite is not configured — set ACP_INVITE_* to enable it")
    try:
        result = invites.send_guest_invite(email, body.get("redirect_url"))
    except Exception as e:
        raise HTTPException(502, f"invite failed: {e}")
    # Auto-add to the allowlist so the guest is admitted on first sign-in — keep the existing list,
    # dedupe, and never drop the owner (same anti-lockout rule as the PUT path).
    keep = list(dict.fromkeys([*core.store.get_allowlist(), email]
                              + ([core.OWNER_EMAIL] if core.OWNER_EMAIL else [])))
    saved = core.store.set_allowlist(keep)
    core.store.log_decision("admin", "settings.invite",
                            detail=f"invited {email} as a guest and added to the allowlist")
    return {"email": email, "emails": saved, "owner": core.OWNER_EMAIL,
            "redemption_url": result.get("redemption_url"), "status": result.get("status")}


@router.put("/admin/allowlist")
def set_allowlist(body: dict, request: Request):
    """Replace the editable test-user list. The owner is always kept (anti-lockout)."""
    _require_owner(request)   # manages the login perimeter — owner-only
    emails = body.get("emails", [])
    if not isinstance(emails, list):
        raise HTTPException(400, "emails must be a list of strings")
    if core.OWNER_EMAIL:
        emails = list(emails) + [core.OWNER_EMAIL]   # never drop the owner
    saved = core.store.set_allowlist(emails)
    core.store.log_decision("admin", "settings.allowlist",
                            detail=f"test-user list set to {len(saved)} email(s)")
    return {"emails": saved, "owner": core.OWNER_EMAIL}


_PEOPLE_ROLES = {"user", "admin"}
_PEOPLE_PROVIDERS = {"google", "microsoft"}


def _people_payload(can_manage: bool = True) -> dict:
    import invites
    records = {r["email"]: r for r in core.store.get_people()}
    admins = set(core.store.get_admins()) | set(core.ADMIN_EMAILS)
    for email in core.store.get_allowlist():
        records.setdefault(email, {"email": email, "provider": None, "status": "access_ready",
                                   "role": "admin" if email in admins else "user"})
    if core.OWNER_EMAIL:
        records[core.OWNER_EMAIL] = {**records.get(core.OWNER_EMAIL, {}),
                                     "email": core.OWNER_EMAIL, "status": "active",
                                     "role": "owner", "protected": True}
    return {"people": sorted(records.values(), key=lambda r: r["email"]),
            "invite_enabled": invites.invite_configured(), "domains": core.ALLOWED_DOMAINS,
            "can_manage": can_manage}


@router.get("/admin/people")
def list_people(request: Request):
    _require_admin(request)
    email = (getattr(request.state, "user_email", None) or "").lower()
    return _people_payload(can_manage=not core.OWNER_EMAIL or core.is_owner(email))


@router.post("/admin/people")
def add_person(body: dict, request: Request):
    """Authorize an existing identity and start provider-specific onboarding."""
    _require_owner(request)
    email = (body.get("email") or "").strip().lower()
    provider = (body.get("provider") or "").strip().lower()
    role = (body.get("role") or "user").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "a valid email is required")
    if provider not in _PEOPLE_PROVIDERS:
        raise HTTPException(400, "provider must be google or microsoft")
    if role not in _PEOPLE_ROLES:
        raise HTTPException(400, "role must be user or admin")
    if email == core.OWNER_EMAIL:
        raise HTTPException(409, "the owner already has access")
    if any(p["email"] == email for p in _people_payload()["people"]):
        raise HTTPException(409, "this person already has access")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    status, redemption_url, failure = "access_ready", None, None
    if provider == "microsoft":
        import invites
        if invites.invite_configured():
            try:
                invited = invites.send_guest_invite(email, body.get("redirect_url"))
                redemption_url, status = invited.get("redemption_url"), "invited"
            except Exception as exc:
                status, failure = "failed", str(exc)
        else:
            status = "setup_required"
    keep = list(dict.fromkeys([*core.store.get_allowlist(), email]
                              + ([core.OWNER_EMAIL] if core.OWNER_EMAIL else [])))
    core.store.set_allowlist(keep)
    if role == "admin":
        core.store.set_admins([*core.store.get_admins(), email])
    actor = getattr(request.state, "user_email", None) or "admin"
    record = core.store.upsert_person({"email": email, "provider": provider, "role": role,
                                       "status": status, "invited_at": now, "invited_by": actor,
                                       "redemption_url": redemption_url, "failure": failure})
    core.store.log_decision(actor, "settings.person.add",
                            detail=f"{email} · {provider} · {role} · {status}")
    return {"person": record, **_people_payload()}


@router.put("/admin/people/{email:path}")
def update_person(email: str, body: dict, request: Request):
    _require_owner(request)
    target = email.strip().lower()
    if target == core.OWNER_EMAIL:
        raise HTTPException(409, "the owner cannot be changed")
    current = next((r for r in _people_payload()["people"] if r["email"] == target), None)
    if current is None:
        raise HTTPException(404, "person not found")
    role = (body.get("role") or current.get("role") or "user").lower()
    status = (body.get("status") or current.get("status") or "access_ready").lower()
    if role not in _PEOPLE_ROLES:
        raise HTTPException(400, "role must be user or admin")
    if status not in {"access_ready", "invited", "setup_required", "failed", "suspended"}:
        raise HTTPException(400, "unsupported status")
    allowed = [e for e in core.store.get_allowlist() if e != target]
    if status != "suspended":
        allowed.append(target)
    core.store.set_allowlist(allowed + ([core.OWNER_EMAIL] if core.OWNER_EMAIL else []))
    admins = [e for e in core.store.get_admins() if e != target]
    if role == "admin" and status != "suspended":
        admins.append(target)
    core.store.set_admins(admins)
    record = core.store.upsert_person({**current, "role": role, "status": status,
                                       "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    actor = getattr(request.state, "user_email", None) or "admin"
    core.store.log_decision(actor, "settings.person.update", detail=f"{target} · {role} · {status}")
    return {"person": record, **_people_payload()}


@router.delete("/admin/people/{email:path}")
def delete_person(email: str, request: Request):
    _require_owner(request)
    target = email.strip().lower()
    if target == core.OWNER_EMAIL:
        raise HTTPException(409, "the owner cannot be removed")
    core.store.set_allowlist([e for e in core.store.get_allowlist() if e != target])
    core.store.set_admins([e for e in core.store.get_admins() if e != target])
    core.store.remove_person(target)
    actor = getattr(request.state, "user_email", None) or "admin"
    core.store.log_decision(actor, "settings.person.remove", detail=target)
    return _people_payload()


@router.get("/admin/admins")
def get_admins():
    """Who holds Platform Admin. Three tiers, so the UI can render each correctly:
      owner       — ACP_OWNER_EMAIL, immutable (root of trust, can never be demoted).
      env_admins  — ACP_ADMIN_EMAILS, permanent (set at deploy, not removable from the UI).
      admins      — the owner-managed set (store), promotable/demotable right here.
    Whether THIS caller may EDIT the managed set is the `is_owner` flag on GET /me — the PUT is
    owner-only and enforces it regardless."""
    return {"owner": core.OWNER_EMAIL,
            "env_admins": sorted(core.ADMIN_EMAILS),
            "admins": core.store.get_admins()}


@router.put("/admin/admins")
def set_admins(body: dict, request: Request):
    """Replace the owner-managed admin set. OWNER-ONLY (managing admins is the root-of-trust action,
    stricter than the admin-gated allowlist). The owner and env admins are never stored here and
    can't be demoted through this path."""
    _require_owner(request)
    emails = body.get("emails", [])
    if not isinstance(emails, list):
        raise HTTPException(400, "emails must be a list of strings")
    # The owner and env-admins are grants from elsewhere; keep them out of the managed set so the
    # list stays exactly "who the owner promoted" and a redundant entry can't imply it's removable.
    drop = {core.OWNER_EMAIL, *core.ADMIN_EMAILS}
    emails = [e for e in emails if (e or "").strip().lower() not in drop]
    saved = core.store.set_admins(emails)
    core.store.log_decision("admin", "settings.admins",
                            detail=f"platform-admin set to {len(saved)} email(s)")
    return {"owner": core.OWNER_EMAIL, "env_admins": sorted(core.ADMIN_EMAILS), "admins": saved}


@router.get("/me/access")
def my_access(request: Request):
    """What this identity may see and do (PRD §13).

    NOT AUTHORIZATION — a description of it. The SPA reads this to decide which tabs to render and
    whether a button says "Start" or "View"; every route still enforces its own capability
    (slice 4). If this endpoint and a route ever disagree, the route wins and the UI was merely
    wrong about what it offered. That ordering is the whole reason PRD §11 exists: "Hiding a tab
    alone is not considered a security control."

    Unauthenticated callers get an empty identity's answer rather than a 401, because the SPA
    calls this during sign-in bootstrapping — and with the flag off that answer is today's access,
    which is what it must be for a signed-out shell to render exactly as it does now.
    """
    import workspace_roles as wr
    email = getattr(request.state, "user_email", None)
    return wr.access_for_email(core.store, email, owner_email=core.OWNER_EMAIL,
                               is_suspended=_is_suspended)


def _is_suspended(email: str) -> bool:
    """Is this person suspended? PRD §14: a suspended user has no effective permissions.

    Read from the managed-person record, which is where the People screen already writes it —
    rather than inferred from absence in the allowlist, which would also be true of somebody who
    was never added and of the demo path where no allowlist is configured at all.
    """
    target = (email or "").strip().lower()
    person = next((p for p in core.store.get_people() if p.get("email") == target), None)
    return (person or {}).get("status") == "suspended"


@router.post("/admin/workspace-roles/bootstrap")
def bootstrap_workspace_roles(request: Request, body: dict | None = None):
    """Seed the six built-in workspace roles and map existing people onto them (PRD §15 step 1).

    OWNER-ONLY, and DRY BY DEFAULT. Pass {"apply": true} to write; anything else previews. The
    default is the safe direction because this is the migration's "Observe" step: an administrator
    is meant to read the generated assignments — who becomes Platform Admin, who becomes
    Compliance Manager — BEFORE those rows mean anything, and a preview you have to remember to
    ask for is one somebody skips.

    Safe to run repeatedly. Existing roles are not overwritten and already-assigned people are not
    reassigned, so a second call after an administrator has tightened somebody's role does not
    undo it (tests/test_workspace_roles_store.py pins both).

    WHETHER THESE ROWS ENFORCE ANYTHING DEPENDS ON THE ROLLOUT RUNG, which is reported in the
    response as `rollout` so the caller can see whether what they just wrote is inert — writing
    roles and believing they took effect is the one misreading this endpoint could invite. See
    api/workspace_rollout.py for the ladder, and GET /admin/workspace-roles/preflight for whether
    it is safe to climb it.
    """
    _require_owner(request)
    import workspace_roles as wr
    # `is True`, not truthiness. A bare `bool(...)` applies on ANY non-empty value, so a client
    # that serialises booleans as strings would migrate a live deployment by sending
    # {"apply": "false"} — the request that most clearly says do not. The only value that writes
    # is a JSON `true`.
    apply = (body or {}).get("apply") is True
    actor = getattr(request.state, "user_email", None) or "owner"
    out = wr.bootstrap(core.store, owner_email=core.OWNER_EMAIL, actor=actor, dry_run=not apply)
    if apply:
        core.store.log_decision(actor, "role.migration",
                                detail=f"seeded {len(out['roles_created'])} role(s), "
                                       f"assigned {sum(1 for a in out['assignments'] if a['applied'])}")
    return out


@router.get("/admin/workspace-roles/preflight")
def workspace_roles_preflight(request: Request):
    """Would advancing the rollout one rung break anybody? (PRD §15.)

    OWNER-ONLY, AND NOT BECAUSE IT WRITES — it writes nothing. It reports every managed person's
    email next to the capabilities they are about to lose, which is a personnel-shaped answer, and
    it is read at exactly the moment somebody is deciding whether to narrow other people's access.
    The person making that decision is the owner; `roles.manage` is the wrong gate because a role
    holding it could use this to enumerate the whole workspace's standing.

    READ IT, DO NOT POLL IT. It walks every person and resolves each one's role, so its cost is
    linear in headcount — fine once before a deployment, wasteful on a dashboard refresh.
    """
    _require_owner(request)
    import workspace_preflight as preflight
    return preflight.report(core.store, owner_email=core.OWNER_EMAIL,
                            routes=core.enumerate_api_routes(request.app),
                            is_suspended=_is_suspended)


@router.put("/workers")
def set_workers(request: Request, count: int = Query(..., ge=0, le=16)):
    """Admin: live-scale the in-process worker pool (0–16). Persisted + audited.
    Scaled-down workers finish their current job before exiting."""
    _require_admin(request)
    new = core.set_worker_count(count)
    core.store.log_decision("admin", "settings.worker_count",
                            detail=f"worker pool scaled to {new}")
    return {"workers": new}


def _build_info() -> dict:
    """Build provenance, plus whether this image was actually stamped by deploy.sh.

    deploy.sh stamps ACP_BUILD_VERSION with a CalVer string (e.g. 2026.7.10.005859) at
    deploy time. The Dockerfile's `ARG BUILD_VERSION=dev` default is what a bare
    `docker build` leaves behind, so an unstamped image is one that never went through
    deploy.sh. Such an image must not pass for a release: /healthz reports ok=false, so
    an operator sees it immediately instead of the app quietly serving "dev". ACA runs no
    health probe on this route, so this signal is advisory, not a rollout gate.
    """
    import os
    v = (os.environ.get("ACP_BUILD_VERSION") or "").strip()
    return {"version": v or "dev",
            "built_at": os.environ.get("ACP_BUILD_TIME") or None,
            "version_stamped": v.lower() not in ("", "dev")}


@router.get("/healthz")
def healthz():
    info = _build_info()
    return {"ok": info["version_stamped"], "service": "acp",
            "rubric_hash": core.active_rubric().hash, **info}


def pdf_engine_status() -> dict:
    """Is the PDF analyser importable in THIS process?

    worker-python is not vendored (unlike the Office analysers, which ADR 0012 brought in) —
    it is loaded at runtime from ACP_PDF_ENGINE. When that path is wrong the failure surfaces
    as a ModuleNotFoundError partway through scanning a PDF, which reads as "the scan broke"
    rather than "an engine was never installed". Probing it here turns a mid-scan crash into
    something an operator can see before anyone runs a scan.

    Import-only: the module is imported and discarded, never used to analyse anything.
    """
    import importlib.util
    import sys as _sys
    from pathlib import Path as _Path

    import scanner
    engine = _Path(str(scanner.WP))
    if not engine.exists():
        return {"available": False, "path": str(engine),
                "reason": "ACP_PDF_ENGINE path does not exist"}
    added = str(engine) not in _sys.path
    if added:
        _sys.path.insert(0, str(engine))
    try:
        found = importlib.util.find_spec("analysers.pdf_analyser") is not None
    except Exception as exc:
        return {"available": False, "path": str(engine),
                "reason": f"{exc.__class__.__name__}: {exc}"}
    return {"available": found, "path": str(engine),
            "reason": None if found else "analysers.pdf_analyser not importable from that path"}


@router.get("/readyz")
def readyz():
    """Functional readiness: can this deployment actually do work right now?

    DELIBERATELY SEPARATE FROM /healthz. That route answers "is this image what we think it
    is" — build provenance — and its docstring notes ACA runs no probe against it. Readiness
    is a different question with a different failure mode, and conflating them is a trap: if a
    platform probe were ever pointed at a combined route, a worker-tier outage would restart
    the API container, which cannot fix a worker tier and loses the API too.

    So: /healthz stays liveness + provenance, this is readiness, and an alert targets
    `ready` or a specific entry in `degraded`.

    `degraded` is a list of machine-readable reasons rather than prose, so a monitor can alert
    on one condition without pattern-matching a sentence.
    """
    workers = core.store.worker_tier_status()
    # Defended: a per-role read must never be able to 500 the readiness endpoint, the same posture
    # the source and vision probes below take. An empty dict reads as "no role ever beaten", which
    # is the honest answer when this cannot be established.
    try:
        role_status = core.store.worker_roles_status()
    except Exception as exc:  # pragma: no cover - defensive: a role probe must not break /readyz
        role_status = {"error": f"{exc.__class__.__name__}: {exc}"}
    local_pool = int(getattr(core, "WORKERS", 0) or 0)
    # Either tier can man the queue: the split topology (#113) runs the pool in a standalone
    # worker container, the single-tier setup runs it in-process. Readiness is the OR — the
    # scan-start guard in routes/scans.py makes exactly the same call.
    can_run_scans = bool(local_pool) or workers["alive"]

    # Capacity state mirrors discovery preflight — "starting" means the queue is durable and
    # scans can be submitted; "unavailable" means the worker tier was never started at all.
    if can_run_scans:
        capacity_state = "ready"
    elif workers["ever_seen"]:
        capacity_state = "starting"
    else:
        capacity_state = "unavailable"

    degraded: list[str] = []
    if not can_run_scans:
        degraded.append("no_workers" if workers["ever_seen"] else "worker_tier_never_started")
    pdf = pdf_engine_status()
    if not pdf["available"]:
        degraded.append("pdf_engine_missing")

    # Source-adapter readiness, reported INFORMATIONALLY — deliberately NOT folded into `degraded`.
    # A deployment that scans only Drive/SharePoint legitimately has no SMB config, so an
    # unconfigured SMB source is not a deployment fault and must not flip `ready`. Surfacing it here
    # gives the monitor and the Content Sources UI one place to read WHY an SMB scan would return an
    # empty estate — before one is started — which is the whole point of describe_smb_readiness
    # (config-only: it reads env and touches no network). Imported lazily, exactly as the scanner
    # does, and defended so a source probe can never 500 the readiness endpoint itself.
    try:
        import smb_source
        smb_ready = smb_source.describe_smb_readiness()
    except Exception as exc:  # pragma: no cover - defensive: a source probe must not break /readyz
        smb_ready = {"ready": False, "error": f"{exc.__class__.__name__}: {exc}"}

    # Vision/GPU readiness — reported INFORMATIONALLY (like sources.smb), NOT folded into `degraded`.
    # A text-only or AI-off deployment is not "degraded" for lacking a vision model, and image findings
    # degrade safely to human review when vision is down (ADR 0039) — so a missing vision model is not a
    # scan-blocking fault the way a missing PDF engine is. But it is otherwise INVISIBLE until a scan
    # silently produces no alt drafts. This surfaces `vision_unavailable_reason` — which names the exact
    # cause (endpoint unreachable, or the configured model not present: a typo, a failed pull, or a stale
    # admin override pinning a torn-down pod's model) AND the fix — so a monitor / the AI-settings UI
    # catches it up front. Probed via ai's memoised tags cache (no per-request network hit); defended so
    # a vision probe can never 500 /readyz.
    try:
        import ai as _ai
        vision = {"ready": _ai.vision_is_available(),
                  "reason": _ai.vision_unavailable_reason(),
                  "model": _ai.OLLAMA_VISION_MODEL,
                  "zone": _ai.provenance().get("zone")}
    except Exception as exc:  # pragma: no cover - defensive: a vision probe must not break /readyz
        vision = {"ready": False, "reason": f"{exc.__class__.__name__}: {exc}"}

    # Tagged-PDF renderer readiness — INFORMATIONAL, like vision and sources.smb, and for the same
    # reason: a deployment that cannot render a PDF/UA-1 ACR export is not thereby unable to scan,
    # assess or remediate anything. Folding it into `degraded` would flip `ready` false for the
    # whole deployment over one export route, which is precisely the mistake the container-probe
    # note below warns about.
    #
    # WHY IT IS HERE AT ALL. It is the one capability in this app whose absence is invisible until
    # somebody needs it and gets a 503 — and it depends on a SYSTEM library (Pango, via WeasyPrint)
    # that pip cannot supply, so "the requirements pinned it" is not the same claim as "this
    # container can produce a tagged PDF". On 2026-09-02 that gap could only be closed by
    # reproducing the base image's dependency hash by hand and reasoning about what the layer must
    # contain; there was no surface that simply answered the question. Now there is.
    #
    # `variant` states WHAT would be produced rather than only whether something would be — an
    # untagged PDF is indistinguishable from this one to everybody except the reader it is for, so
    # "ready: true" alone would be the same shape of half-answer as ACP's own `pdf.tagged` rule
    # passing on an empty structure tree.
    try:
        import acr_export_pdf as _acr_pdf
        _renderer_ok = _acr_pdf.is_available()
        report_pdf = {"ready": _renderer_ok,
                      "reason": None if _renderer_ok else _acr_pdf.MISSING_RENDERER,
                      "variant": _acr_pdf.PDF_VARIANT}
    except Exception as exc:  # pragma: no cover - defensive: a renderer probe must not break /readyz
        report_pdf = {"ready": False, "reason": f"{exc.__class__.__name__}: {exc}", "variant": None}

    return {
        "ready": not degraded,
        "capacity_state": capacity_state,
        "degraded": degraded,
        "workers": {**workers, "local_pool": local_pool, "can_run_scans": can_run_scans,
                    # PER-ROLE, because the fields above cannot answer "is each worker service
                    # running the build we shipped". They come from one shared heartbeat key that
                    # every worker overwrites, so with more than one service running (acp-worker
                    # and acp-discovery, since #1169) `version` and `pool_size` report whichever
                    # beat last — measured flapping between two services' answers in production on
                    # 2026-09-01. See store.worker_roles_status.
                    "roles": role_status},
        # `pdf` is the ANALYSER (can this deployment read a PDF); `pdf_renderer` is the tagged-PDF
        # WRITER (can it produce one). Deliberately not both under "pdf": they fail independently,
        # for unrelated reasons, and a single key would make one of them unanswerable.
        "engines": {"pdf": pdf, "vision": vision, "pdf_renderer": report_pdf},
        "sources": {"smb": smb_ready},
        "service": "acp",
    }


# ── Container-local readiness: the ONE route a platform probe may point at ────────────────
#
# WHY THIS EXISTS AS A THIRD HEALTH ROUTE. Neither of the two above can be a probe target.
#
#   /healthz  answers "is this the image deploy.sh stamped". It touches no dependency at all,
#             so it returns 200 from a replica that cannot reach the database — which is
#             exactly the replica a readiness gate has to hold traffic away from.
#   /readyz   answers "can this DEPLOYMENT do work" — worker tier, PDF engine. Its own
#             docstring says why pointing a probe at it would be a mistake: a worker-tier
#             outage would evict the API container, which cannot fix a worker tier and loses
#             the API too. `ready` there goes false for faults this container did not cause
#             and cannot cure by restarting.
#
# THE GAP THAT LEFT. With no probe configured, Azure Container Apps decides a new replica is
# ready as soon as its port accepts a TCP connection. uvicorn binds that port after the app's
# startup handlers finish, but binding is not the same as being able to serve, and on this
# deployment the difference is measurable. Sampled live during the deploy of #1151, against a
# single-replica app being swapped revision-for-revision:
#
#     t+20s   /healthz 200 in 0.39s      /readyz 000 after 25s     /config 000 after 25s
#     t+40s   /healthz 200 in 0.43s      /readyz 200 in 0.46s      /config 200 in 0.75s
#
# The non-database route was fast throughout; every database-backed route hung for the whole
# sampling window and then recovered on its own. Traffic was being sent to a replica that could
# not yet answer a database read. That window is what stranded a browser mid-submit on
# 2026-09-01 (the Discovery request that produced no preflight, no POST /scans and no job) —
# the client-side half of which is fixed in #1151; this is the server-side half, and it is the
# half that stops the window existing rather than making the browser survive it.
#
# WHAT THIS ROUTE CHECKS IS DELIBERATELY NARROW: this process, this container, its database.
# Nothing about the worker tier, the PDF engine, the vision model or any source adapter — all
# of which are legitimately absent or broken on a replica that is nonetheless perfectly able
# to serve, and none of which a restart of THIS container can repair. Adding a dependency here
# is not a small change: it hands the platform a new reason to take the API down.
#
# IT ANSWERS WITH A STATUS CODE, not a field. An httpGet probe reads the code and nothing else,
# so a 200 carrying {"ready": false} would be read as ready. Failure is 503.

# One in-flight database check at a time, process-wide.
#
# A sync FastAPI route runs on anyio's bounded worker threadpool (40 by default). A probe fires
# every few seconds forever, so if the database stops answering — the precise case this route
# exists to detect — an unguarded implementation parks one pooled thread per probe until the
# threadpool is gone, and takes down the replica's ability to serve anything at all. The gate
# turns that into at most one parked thread: while a check is outstanding, further probes are
# answered immediately and negatively, which is both the truthful answer and the cheap one.
_PROBE_DB_LOCK = threading.Lock()


def _probe_database() -> tuple[bool, str]:
    """(reachable, reason) for one database round-trip, never blocking on another probe."""
    if not _PROBE_DB_LOCK.acquire(blocking=False):
        # An earlier probe is still waiting on the database. Not "unknown" — a replica whose
        # last database read has not come back is not ready, and saying so is the point.
        return False, "db_check_in_flight"
    try:
        core.store.ping()
        return True, ""
    except Exception as exc:  # noqa: BLE001 — any failure to reach the DB means not ready
        # Class name only. This body is served to an unauthenticated caller, and a psycopg2
        # OperationalError's message carries the host, port and user from the DSN.
        return False, f"db_unreachable: {exc.__class__.__name__}"
    finally:
        _PROBE_DB_LOCK.release()


@router.get("/probe/readyz")
def probe_readyz(response: Response):
    """Is THIS container able to serve a database-backed request right now?

    The rollout gate. See the block comment above for why /healthz and /readyz cannot be it.
    """
    ok, reason = _probe_database()
    if not ok:
        response.status_code = 503
    return {"ready": ok, "checks": {"db": "ok" if ok else reason}, "service": "acp"}


# How many recent scans the estate summary reports. The monitor decides what counts as a
# collapse (scripts/monitor.py:COLLAPSE_RATIO/COLLAPSE_WINDOW); this only has to return enough
# history for that policy to be evaluated, and to stay a bounded response on a busy estate.
MONITOR_SCAN_WINDOW = 20


@router.get("/monitor/estate")
def monitor_estate(request: Request):
    """Aggregate counts for the production monitor. COUNTS ONLY — never records.

    WHY THIS EXISTS AS A SEPARATE ROUTE. The monitor's deep checks previously read /scans and
    /hitl/queue through the X-E2E-Key gate bypass, and that could never work in production:
    core.E2E_KEY is None whenever IS_PROD, so the header was rejected on the only deployment
    anyone needs monitored. The two ways to "fix" that were to set ACP_ENABLE_TEST_BYPASS in
    production — reopening a whole-gate backdoor on a public deployment to power a health
    check — or to give monitoring its own door. This is the door.

    It is deliberately the NARROWEST thing that answers the two questions the monitor asks:

      - did the newest scan collapse?  → recent per-scan file COUNTS, newest first
      - how big is the review backlog? → one pending COUNT

    No filenames, no owner emails, no findings, no document content. If ACP_MONITOR_KEY ever
    leaks, what leaks with it is a handful of integers, which is the entire point of not
    reaching for the bypass that would have handed over the estate.

    Owner-agnostic ON PURPOSE (owner=None → every tenant). The old check was subtly broken in a
    second way: /scans is scoped to _owner(request), and on the keyed path no user_email is ever
    set, so it read the 'demo' user's scans — near-certainly empty — and would have reported
    "no completed scans at all" against a perfectly healthy estate. A monitor asks about the
    deployment, not about a user.
    """
    # Fail CLOSED and LOUD. 503 (not 404) so an unconfigured deployment is distinguishable from
    # a route that moved — the monitor reports the two differently and neither reads as healthy.
    if not core.MONITOR_KEY:
        raise HTTPException(503, "monitoring is not configured on this deployment (ACP_MONITOR_KEY unset)")
    presented = request.headers.get("x-monitor-key", "")
    # compare_digest, not ==, so a wrong key cannot be recovered a byte at a time.
    if not hmac.compare_digest(presented, core.MONITOR_KEY):
        raise HTTPException(401, "bad monitor key")

    # list_scans() filters to completed_at IS NOT NULL, which an ADR 0020 Discover-only run
    # never sets — the exact 2026-08-21 blind spot (see list_finished_scans' own docstring).
    # Found live 2026-08-28: this route hit that identical gap, so "did the newest scan
    # collapse" could never see a Discover-only run at all — its "newest scan" was stale by
    # definition on any deployment where Discover-only is now the default scan type.
    # list_finished_scans() is the narrower fix: completed_at OR discovered_at, excluding
    # anything still in-flight (so a scan that started seconds ago and has not listed a single
    # file yet cannot masquerade as "the newest," the same dishonest-zero shape this checks for
    # in the first place).
    scans = core.store.list_finished_scans() or []
    pending = core.store.list_hitl_queue(status="pending") or []

    # The background scheduler (core._do_scheduled_scan) runs under the service-account ADC
    # identity, not a user's own OAuth token — it can legitimately see far fewer files than a
    # user's manual scan of the same source, since ADC's Drive access is whatever the service
    # account was explicitly granted, not the signed-in user's full permission set. Found live
    # 2026-08-28: "newest scan is full-size" (below) has no way to tell that shape apart from a
    # genuine collapse — both look identical, a small scan sitting where a large one was. This
    # says whether the newest scan run WAS a scheduled sweep and how many files it saw, so the
    # two causes stop being indistinguishable from the same three numbers.
    #
    # Config (enabled/interval) and a file COUNT only — no owner email, no scan id, matching
    # this route's own counts-only contract.
    cfg = core.store.get_schedule()
    last_sweep = core.store.get_last_sweep()
    return {
        "service": "acp",
        "scans": {
            "total": len(scans),
            # Newest first, exactly as list_finished_scans orders them
            # (COALESCE(completed_at, discovered_at) DESC).
            "recent_files": [int(s.get("files") or 0) for s in scans[:MONITOR_SCAN_WINDOW]],
        },
        "inbox": {"pending": len(pending)},
        "sweep": {
            "enabled": bool(cfg.get("enabled")),
            "interval_minutes": cfg.get("interval_minutes"),
            "last_ok": last_sweep.get("ok") if last_sweep else None,
            "last_at": last_sweep.get("at") if last_sweep else None,
            "last_files": last_sweep.get("files") if last_sweep else None,
            # PRD Phase 3: True when the last sweep found (via Drive's sync cursor) that
            # nothing had changed and skipped the full re-scan entirely — last_files is then
            # None, not 0, deliberately: 0 already means "a scan ran and legitimately saw no
            # files under ADC" elsewhere in this same block, and this must not read the same.
            "last_skipped": bool(last_sweep.get("skipped")) if last_sweep else None,
        },
    }


@router.get("/config")
def config(request: Request = None):
    """Tells the SPA how to authenticate: GIS per-user (client id present) vs demo."""
    import os
    # Public Langfuse trace base, so the SPA can deep-link "📊 View trace" chips straight
    # to the relevant trace (deterministic ids: {scan}, {scan}-assess, {scan}-remediate).
    # Null when Langfuse isn't configured → the frontend simply omits the chips.
    lf_host = os.environ.get("LANGFUSE_HOST", "").rstrip("/")
    import lf as _lf
    lf_project = _lf._project_id()
    import ai as _ai   # AI provenance (ADR 0019 Phase 0): active model + local/cloud zone
    import scanner
    return {"google_client_id": core.GOOGLE_CLIENT_ID,
            "drive_scope": core.DRIVE_SCOPES[0],
            # Entra app for the SharePoint/OneDrive connect — runtime so the tenant can be set per
            # deployment without rebuilding the SPA (the frontend falls back to VITE_AZURE_* only
            # when these are absent). Null when SharePoint isn't configured; the SPA hides the button.
            "azure_client_id": core.AZURE_CLIENT_ID,
            "azure_tenant_id": core.AZURE_TENANT_ID,
            # Every SharePoint/OneDrive DATA-SOURCE connection this deployment can reach — one entry
            # per Entra app registration (ACP_AZURE_CLIENT_ID[_N]/ACP_AZURE_TENANT_ID[_N]). Distinct
            # from azure_client_id/azure_tenant_id above, which stays the single identity provider
            # that gates SIGN-IN to ACP itself; connecting a second tenant's SharePoint as a scan
            # source does not change who is allowed to use the app. [] when unconfigured — same
            # "hide the button" contract as the singular fields.
            "microsoft_tenants": core.MICROSOFT_TENANTS,
            # How many SharePoint sites one scan may span (ACP_SP_MAX_SITES, default 30). Served
            # rather than hardcoded in the SPA because the enforcement is the SERVER's — the scan
            # route refuses a larger selection and the walk caps itself — and a picker holding its
            # own copy of the number would disagree with the deployment the moment an operator
            # raised it: the UI would either block a selection the server would accept, or wave
            # through one it will refuse after the operator has finished choosing.
            "sharepoint_max_sites": scanner._sp_max_sites(),
            "auth": "gis" if core.GOOGLE_CLIENT_ID else "demo",
            **_build_info(),
            "ai": _ai.provenance(),
            "scope": _active_scope_info(),
            # Ownership signal for the scope editor. /config is fetched PRE-auth, so identity is
            # usually absent here (None) — the authoritative per-user value is on `me` (GET /me).
            # When the request DOES carry a verified identity (the access gate ran), report it;
            # otherwise None. When no owner is configured at all, everyone is an owner.
            "is_scope_owner": (core.is_scope_owner(_ident)
                               if (_ident := getattr(getattr(request, "state", None), "user_email", None))
                               or not core.OWNER_EMAIL
                               else None),
            # Strict owner flag (root of trust) — gates the owner-only "who is an admin" controls in
            # Settings, above the admin-level is_scope_owner. Same PRE-auth None caveat as above.
            "is_owner": (core.is_owner(_ident)
                         if (_ident := getattr(getattr(request, "state", None), "user_email", None))
                         or not core.OWNER_EMAIL
                         else None),
            "langfuse_trace_base": (f"{lf_host}/project/{lf_project}/traces" if lf_host else None)}


def _active_scope_info() -> dict:
    """The operator scope the SERVER is actually gating on, for the SPA to render.

    Until this existed the SPA hard-coded `ACTIVE_SCOPE_PRESET = 'engagement-14'` in
    activeScope.js, so changing the `scan_scope` setting moved the server's gate while every
    denominator, "N of 20 in scope" line and out-of-scope note in the UI kept describing the
    preset compiled into the bundle. Two sources of truth for one question, and the wrong one
    was the one the customer could see.

    Shipped on /config rather than /settings because /config is ALWAYS_PUBLIC and the SPA
    already fetches it at boot — the scope is not a secret (it is a list of WCAG criteria the
    customer agreed to) and gating it behind sign-in would leave the pre-auth shell describing
    a scope nobody had confirmed.

    Returns the NAME and the resolved criteria map, deliberately both. The name is what an
    operator recognises; the map is what the UI must arithmetic over, and deriving it here
    means the SPA never has to keep its own copy of a preset's contents in step with ours.
    `{"name": "", "criteria": null}` means no restriction — every criterion in scope.
    """
    try:
        from store import active_scope, scope_problem, SCOPE_SETTING
        raw = core.store.get_setting(SCOPE_SETTING, "") or ""
        scope = active_scope(core.store)
        problem = scope_problem(core.store)
        # A scope written as DATA has no preset name to show. Reporting the raw JSON here would
        # put a wall of text where the UI expects a label, so it is named for what it is and the
        # criteria map — which the SPA already renders — carries the detail.
        name = "" if not raw else ("custom" if raw.strip().startswith("{") else raw)
        # `error` appears ONLY when there is something to say. The no-restriction response stays
        # byte-identical to what #138 pinned, so every existing consumer is untouched, and the
        # key's mere presence is the signal — it is the difference between "no scope is set" and
        # "a scope IS set and the server is ignoring it", which otherwise both read criteria:null.
        if not scope:
            out = {"name": "", "criteria": None}
            if problem:
                out["error"] = problem
            return out
        return {"name": name, "criteria": {sc: sorted(f) for sc, f in scope.items()}}
    except Exception:
        # A scope we cannot read must not be reported as a scope that excludes everything.
        return {"name": "", "criteria": None}


class ScheduleUpdate(BaseModel):
    enabled: bool
    interval_minutes: int


@router.get("/schedule")
def schedule():
    cfg = core.store.get_schedule()
    job = core.scheduler.get_job("scheduled_local_scan")
    cfg["next_at"] = job.next_run_time.isoformat() if job and job.next_run_time else None
    # list_scans() filters to completed_at IS NOT NULL, which an ADR 0020 Discover-only run
    # never sets (see list_finished_scans' own docstring) — a discover-only sweep landed here
    # and last_at kept showing the last scan that was ever ASSESSED, which can be arbitrarily
    # older than the estate's true last refresh. list_finished_scans() plus the same
    # COALESCE(completed_at, discovered_at) its own ordering uses is the fix: whichever
    # timestamp the newest row actually has.
    scans = core.store.list_finished_scans()
    cfg["last_at"] = (scans[0].get("completed_at") or scans[0].get("discovered_at")) if scans else None
    # The last sweep's OUTCOME, not just when a scan last completed. A failing sweep saves
    # nothing by design, so `last_at` keeps pointing at the last SUCCESSFUL scan and reads as
    # healthy while the estate quietly goes stale. None until a sweep has run.
    cfg["last_sweep"] = core.store.get_last_sweep()
    return cfg


@router.put("/schedule")
def update_schedule(body: ScheduleUpdate, request: Request):
    # Attribute scheduled sweeps to whoever set the schedule, so the resulting scans
    # show up in their (owner-scoped) scan list.
    owner = getattr(request.state, "user_email", None)
    core.store.save_schedule(body.enabled, body.interval_minutes, owner=owner, source="drive")
    core.reload_scheduler()
    return schedule()


@router.get("/hub", response_class=Response)
def hub():
    """Landing page — all key links in one place."""
    hub_file = core.ACP / "hub" / "index.html"
    if not hub_file.exists():
        raise HTTPException(404, "hub/index.html not found")
    return Response(hub_file.read_bytes(), media_type="text/html")


def _ai_base_url_error(val: str) -> str | None:
    """None when the value is acceptable. Empty is always allowed — it means "use the deploy
    default", which is how a burst-GPU detach gets back to the CPU endpoint."""
    if val and not val.startswith(("http://", "https://")):
        return "ai_base_url must be an http(s) URL (or empty to use the deploy default)"
    return None


# Per-field validators for the runtime AI endpoint settings, declared here rather than inlined in
# the write loop so update_settings can run EVERY one before it writes ANY field. Only ai_base_url
# has a rule today, and it is listed first, which is the only reason the previous
# validate-and-write-in-one-pass loop was safe: add a rule to a later field, or reorder the tuple,
# and a rejected PUT would have written the fields ahead of the bad one and then 422'd. The SPA
# sends the base URL and the vision model in a single Apply, so a partial write there is
# indistinguishable to the admin from "the setting will not save".
_AI_VALIDATORS = {"ai_base_url": _ai_base_url_error}


class SettingsUpdate(BaseModel):
    # A PUT naming a field this model does not have used to return 200 and change nothing —
    # the request echoed back as a success. That cost two debugging cycles on a production
    # vision-model override (2026-07-30/31): the setting was "saved" repeatedly and the worker
    # went on using the old value, with no error anywhere to explain it. A typo'd or renamed
    # field is now a 422 the caller can see, which matters most for the admin scope grid: a
    # scope that silently fails to save is indistinguishable from one that saved and is being
    # ignored, and only one of those is a bug the operator can act on.
    model_config = ConfigDict(extra="forbid")

    ai_enabled: bool | None = None
    # The operator scan scope. Accepts what the setting accepts — a preset NAME, or the scope as
    # DATA. `dict` is listed first so an admin UI can PUT the grid's own state without
    # stringifying it; "" clears the scope back to no restriction.
    scan_scope: dict[str, list[str]] | str | None = None
    drive_mirror_enabled: bool | None = None
    drive_mirror_folder: str | None = None
    auto_apply_validated: bool | None = None
    ai_base_url: str | None = None          # runtime AI endpoint override; "" clears → env default
    ai_vision_model: str | None = None
    ai_text_model: str | None = None


@router.get("/settings")
def get_settings():
    """Platform settings. ai_enabled=false → deterministic-only mode platform-wide
    (overrides per-scan ?ai=true and blocks /ai/explain). drive_mirror_enabled=false
    (ADR 0010) → remediated fixes stay Blob-only, no automatic Drive copy."""
    return {"ai_enabled": core.store.get_ai_enabled(),
            "drive_mirror_enabled": core.store.get_drive_mirror_enabled(),
            "drive_mirror_folder": core.store.get_drive_mirror_folder(),
            "auto_apply_validated": core.store.get_auto_apply_validated(),
            # Runtime AI endpoint override (GPU burst) — empty string = env default in use.
            "ai_base_url": core.store.get_setting("ai_base_url", "") or "",
            "ai_vision_model": core.store.get_setting("ai_vision_model", "") or "",
            "ai_text_model": core.store.get_setting("ai_text_model", "") or "",
            # The RAW setting, not the resolved map: this is the admin edit surface, and an
            # editor must show what is stored so a save round-trips. /config reports the
            # RESOLVED scope for everything that renders it — the two are different questions
            # and conflating them is how an editor starts overwriting what it never loaded.
            "scan_scope": core.store.get_setting("scan_scope", "") or ""}


@router.put("/settings")
def update_settings(body: SettingsUpdate, request: Request):
    """Admin: set platform settings. Persisted across restarts. Audited."""
    _require_admin(request)
    if body.drive_mirror_enabled is not None:
        core.store.set_drive_mirror_enabled(body.drive_mirror_enabled)
        core.store.log_decision(
            "admin", "settings.drive_mirror_enabled",
            detail=f"drive_mirror_enabled set to {body.drive_mirror_enabled}")
    if body.drive_mirror_folder is not None:
        folder = body.drive_mirror_folder.strip() or "Remediated"
        core.store.set_drive_mirror_folder(folder)
        core.store.log_decision(
            "admin", "settings.drive_mirror_folder",
            detail=f"drive_mirror_folder set to {folder}")
    # SCOPE. Validated BEFORE writing, and rejected with a reason rather than stored: a scope
    # that cannot be parsed fails open at read time (assessment_policy.parse_scope_setting), so
    # storing a broken one would leave the operator looking at a saved value the engine silently
    # ignores. That is precisely the failure /config's `error` key exists to surface, and it is
    # better never to create it. `""` is always legal — it clears the scope.
    if body.scan_scope is not None:
        from store import parse_scope_setting
        raw = (json.dumps(body.scan_scope) if isinstance(body.scan_scope, dict)
               else str(body.scan_scope).strip())
        if raw and raw != "{}":
            problem = parse_scope_setting(raw)[1]
            if problem:
                raise HTTPException(422, f"scan_scope: {problem}")
        else:
            raw = ""            # {} and "" both mean no restriction; store the simpler one
        core.store.set_setting("scan_scope", raw)
        core.store.log_decision("admin", "settings.scan_scope",
                                detail=f"scan_scope set to {raw or '(no restriction)'}")

    ai_updates = [(key, val.strip())
                  for key, val in (("ai_base_url", body.ai_base_url),
                                   ("ai_vision_model", body.ai_vision_model),
                                   ("ai_text_model", body.ai_text_model))
                  if val is not None]
    # Validate EVERY field before writing ANY of them — see _AI_VALIDATORS. All-or-nothing is
    # order-independent; the old single-pass loop was correct only by the accident of which field
    # carried the only rule.
    for key, val in ai_updates:
        validator = _AI_VALIDATORS.get(key)
        problem = validator(val) if validator else None
        if problem:
            raise HTTPException(422, problem)
    for key, val in ai_updates:
        core.store.set_setting(key, val)
        core.store.log_decision("admin", f"settings.{key}",
                                detail=f"{key} set to {val or '(deploy default)'} — takes effect "
                                       "on every replica within ~30s, no restart")
    if ai_updates:
        # This replica switches immediately; the others follow via the TTL refresh. Once for the
        # batch, not once per field — the refresh re-reads all three settings anyway.
        try:
            import ai as _ai
            _ai._override_checked["at"] = 0.0
            _ai._maybe_refresh_endpoint()
        except Exception:
            swallowed("routes.system.update_settings: refreshing the AI endpoint after a settings "
                      "update failed")
    if body.auto_apply_validated is not None:
        core.store.set_auto_apply_validated(body.auto_apply_validated)
        core.store.log_decision(
            "admin", "settings.auto_apply_validated",
            detail=f"auto_apply_validated set to {body.auto_apply_validated} — "
                   "cross-checked ungrounded vision drafts "
                   f"{'auto-apply' if body.auto_apply_validated else 'queue for one-click approval'}")
    if body.ai_enabled is not None:
        core.store.set_ai_enabled(body.ai_enabled)
        core.store.log_decision(
            "admin", "settings.ai_enabled",
            detail=f"ai_enabled set to {body.ai_enabled}")
    return get_settings()


# ── per-user scan-scope override (ADR 0035 stage 2 — the non-admin surface) ────────────
# The owner default is admin-gated above; this lets a SIGNED-IN USER set their OWN scan-scope
# override, keyed to their email, never able to write anyone else's. The override can only WIDEN the
# owner mandate — the widen-only union in active_scope keeps every owner criterion/format regardless
# of what is stored here — so this surface can never be used to skip a check the owner required.
class MyScopeUpdate(BaseModel):
    # Same shape the admin scan_scope accepts — a preset NAME or the scope as DATA. "" is a REAL
    # value here: the user opting into NO restriction (assess everything), which is distinct from
    # HAVING no override (to clear the override and fall back to the owner default, use DELETE).
    scan_scope: dict[str, list[str]] | str | None = None


def _require_user(request: Request) -> str:
    """The signed-in user's email, or 401. Per-user settings are keyed to identity, so — unlike the
    admin gate, which no-ops in local dev — this REQUIRES a stamped user: there is no per-user
    override without a user, and falling back to the shared 'demo' owner would let one user's
    override leak onto everyone on a shared-estate deployment."""
    email = (getattr(request.state, "user_email", None) or "").strip()
    if not email:
        raise HTTPException(401, "sign-in required for per-user settings")
    return email


@router.get("/settings/mine")
def get_my_settings(request: Request):
    """This signed-in user's OWN scan-scope override, plus the owner default it widens onto — both as
    the RAW stored values (the edit surface, mirroring GET /settings), so an editor round-trips.
    `scan_scope` is "" when the user has no override; the RESOLVED effective map is /config's job."""
    user = _require_user(request)
    return {
        "scan_scope": core.store.get_user_setting(user, "scan_scope") or "",
        "owner_default": core.store.get_setting("scan_scope", "") or "",
    }


@router.put("/settings/mine")
def update_my_settings(body: MyScopeUpdate, request: Request):
    """Set THIS user's own scan-scope override. Validated BEFORE writing — a malformed scope is a 422
    and is never stored (same discipline as the admin PUT), because a stored-but-unparseable override
    is silently ignored at read time. `{}` and "" both store as "" (no restriction)."""
    user = _require_user(request)
    if body.scan_scope is None:
        return {"scan_scope": core.store.get_user_setting(user, "scan_scope") or ""}
    from store import parse_scope_setting
    raw = (json.dumps(body.scan_scope) if isinstance(body.scan_scope, dict)
           else str(body.scan_scope).strip())
    if raw and raw != "{}":
        problem = parse_scope_setting(raw)[1]
        if problem:
            raise HTTPException(422, f"scan_scope: {problem}")
    else:
        raw = ""            # {} and "" both mean 'no restriction' — store the simpler one
    core.store.set_user_setting(user, "scan_scope", raw)
    core.store.log_decision(user, "settings.mine.scan_scope",
                            detail=f"per-user scan_scope set to {raw or '(no restriction)'}")
    return {"scan_scope": raw}


@router.delete("/settings/mine")
def clear_my_settings(request: Request):
    """Remove THIS user's override so their scans fall back to the owner default. Distinct from PUT
    with "" (a real override meaning 'no restriction'): DELETE means 'I have no preference, use the
    owner's'. Idempotent."""
    user = _require_user(request)
    core.store.clear_user_setting(user, "scan_scope")
    core.store.log_decision(user, "settings.mine.scan_scope", detail="per-user scan_scope cleared")
    return {"scan_scope": ""}


# ── AI provider gateway config (ADR 0019 §6, secret-ref design) ────────────────
class AIProviderUpdate(BaseModel):
    # extra='forbid' is a load-bearing security guard: the model has NO key/api_key field, so a
    # client that tries to submit a key value (rather than a secret reference NAME) is rejected
    # with 422 instead of the value being silently accepted. The key never transits this endpoint.
    model_config = ConfigDict(extra="forbid")
    provider: str
    enabled: bool | None = None
    endpoint: str | None = None
    deployment: str | None = None
    model: str | None = None
    key_secret_ref: str | None = None       # the NAME of an ops-provisioned env/Key-Vault secret


@router.get("/ai/providers")
def get_ai_providers(request: Request):
    """Admin: the configurable cloud AI providers as SAFE views — endpoint, model, whether the
    referenced secret is present, and who owns it — never a key value (ADR 0019 §6). Admin-gated:
    provider governance config isn't exposed to non-owners.

    `secret_write` tells the page whether THIS deployment can accept a pasted key at all (a Key
    Vault is configured and its SDK is installed). The field exists so the UI never renders an
    input that cannot work: without it the only way to discover an unconfigured vault is to type
    a live credential into a box and have it rejected."""
    _require_admin(request)
    import providers as _providers
    import secret_store as _secrets
    store = _secrets.active_secret_store()
    ok, reason = store.writable()
    return {"providers": _providers.list_provider_views(),
            "secret_write": {"available": ok, "kind": store.kind, "reason": reason}}


@router.put("/ai/providers")
def put_ai_provider(body: AIProviderUpdate, request: Request):
    """Admin: set ONE provider's non-secret config. The key itself is never submitted here — the
    admin's ops team provisions it as a container/Key-Vault secret and this stores only the secret's
    NAME (key_secret_ref). A value that looks like a key (not an env-var name) is rejected."""
    _require_admin(request)
    import providers as _providers
    provider = (body.provider or "").strip().lower()
    if provider not in _providers.CLOUD_PROVIDERS:
        raise HTTPException(422, f"unknown provider '{provider}' — one of {list(_providers.CLOUD_PROVIDERS)}")
    existing = core.store.get_ai_provider_config(provider) or {}
    endpoint = existing.get("endpoint")
    if body.endpoint is not None:
        endpoint = body.endpoint.strip() or None
        if endpoint and not endpoint.startswith(("http://", "https://")):
            raise HTTPException(422, "endpoint must be an http(s) URL")
    ref = existing.get("key_secret_ref")
    if body.key_secret_ref is not None:
        ref = body.key_secret_ref.strip() or None
        # Reject a pasted key: a secret reference is an env-var NAME, not the credential. This is
        # the guard that keeps a key out of the database even if an admin misunderstands the field.
        if ref and not _SECRET_REF_RE.match(ref):
            raise HTTPException(422, "key_secret_ref must be an environment-variable NAME "
                                     "(e.g. AZURE_OPENAI_API_KEY), not a key value")
    enabled = body.enabled if body.enabled is not None else bool(existing.get("enabled"))
    if enabled:
        # ENABLE ONLY WHAT CAN ACTUALLY RUN. Until this guard, enabling was unconditional: the row
        # stored enabled=true whatever else was blank, `_adapter_for` then returned None at call
        # time, and every document silently stayed on the local path. The Settings page said the
        # provider was on and nothing was ever sent to it. An enable switch that does nothing is
        # worse than one that refuses, because it reads as consent having been honoured.
        #
        # The would-be config is validated, not the stored one — an admin fills the fields and
        # ticks the box in a single save, so checking `existing` would refuse the first correct
        # save and accept nothing after it.
        candidate = {**existing, "provider": provider, "endpoint": endpoint,
                     "deployment": (body.deployment.strip() if body.deployment is not None
                                    else existing.get("deployment")) or None,
                     "model": (body.model.strip() if body.model is not None
                               else existing.get("model")) or None,
                     "key_secret_ref": ref}
        readiness = _providers.activation_readiness(provider, candidate)
        if not readiness["ready"]:
            # 422 with the reason, not a bare refusal: "missing model, key_secret_ref" is fixable
            # by the admin reading it, and "the environment secret named X is not present" is a
            # different person's job (ops provisions the value; this app never stores it).
            raise HTTPException(422, {"error": "cannot enable this provider yet",
                                      "provider": provider,
                                      "detail": readiness["detail"],
                                      "missing": readiness["missing"],
                                      "secret_resolves": readiness["secret_resolves"]})
    who = getattr(request.state, "user_email", None) or "admin"
    core.store.upsert_ai_provider_config(
        provider,
        enabled=enabled,
        endpoint=endpoint,
        deployment=(body.deployment.strip() if body.deployment is not None else existing.get("deployment")) or None,
        model=(body.model.strip() if body.model is not None else existing.get("model")) or None,
        key_secret_ref=ref,
        updated_by=who,
    )
    # Audit records the config change WITHOUT the key value (only the reference name).
    core.store.log_decision("admin", f"settings.ai_provider.{provider}",
                            detail=f"provider={provider} enabled={enabled} endpoint={endpoint or '—'} "
                                   f"key_secret_ref={ref or '—'} (key value never handled here)")
    return {"providers": _providers.list_provider_views()}


class AIProviderSecretWrite(BaseModel):
    value: str


@router.post("/ai/providers/{provider}/secret")
def put_ai_provider_secret(provider: str, body: AIProviderSecretWrite, request: Request):
    """Admin: set one provider's API key by writing it to the deployment's Key Vault.

    The one place in this product where a key VALUE is accepted, and it is accepted only to hand
    straight to the vault: nothing is written to the database except the resulting reference name
    (`keyvault:acp-ai-<provider>-key`), nothing is logged but that name, and no read path can
    return the value — `provider_view` has never carried it and still does not.

    A deployment with no vault configured REFUSES (422) rather than falling back to storing the
    value anywhere else. That refusal is the feature: it is what keeps "we could not do this
    safely" from turning into "we did it unsafely".

    The vault secret's name is derived from the provider, never supplied by the caller — a name
    over HTTP would let one admin overwrite another provider's secret, or something else in a
    shared vault, through a field that looks like a label.
    """
    _require_admin(request)
    import providers as _providers
    import secret_store as _secrets
    provider = (provider or "").strip().lower()
    if provider not in _providers.CLOUD_PROVIDERS:
        raise HTTPException(422, f"unknown provider '{provider}' — one of {list(_providers.CLOUD_PROVIDERS)}")
    try:
        ref = _secrets.write_provider_secret(provider, body.value)
    except ValueError:
        raise HTTPException(422, "the key value is empty")
    except RuntimeError as e:
        # "no vault is configured", or "the SDK is not installed in this image" — an operator's
        # fix, and one an admin cannot make from this page, so it is reported verbatim.
        raise HTTPException(422, {"error": "this deployment cannot store a key value", "detail": str(e)})
    except Exception as e:
        # A vault that refused the write (identity lacks secrets/set, network, throttling). The
        # TYPE and message are surfaced because "it did not work" sends someone to read code.
        raise HTTPException(502, {"error": "the key vault rejected the write",
                                  "detail": f"{type(e).__name__}: {e}"})

    existing = core.store.get_ai_provider_config(provider) or {}
    core.store.upsert_ai_provider_config(
        provider,
        enabled=bool(existing.get("enabled")),
        endpoint=existing.get("endpoint"),
        deployment=existing.get("deployment"),
        model=existing.get("model"),
        key_secret_ref=ref,
        updated_by=getattr(request.state, "user_email", None) or "admin",
    )
    # The audit row names the reference, never the value — same rule as the config route above.
    core.store.log_decision("admin", f"settings.ai_provider.{provider}.secret",
                            detail=f"provider={provider} key_secret_ref={ref} "
                                   f"(written to the key vault; value never stored or logged)")
    return {"providers": _providers.list_provider_views()}


@router.get("/decisions")
def decisions(scan_id: str | None = None, limit: int = 500):
    """Immutable decision audit log — every consequential action (scan mode, HITL
    review, settings change, auto-routing). Append-only; filter by scan_id."""
    return core.store.list_decisions(scan_id=scan_id, limit=limit)


@router.get("/jobs")
def jobs(request: Request, status: str | None = None, limit: int = 100):
    """Async job-queue visibility (ADR 0004): queue depth by status + recent jobs.
    Owner-scoped — a user sees only their OWN jobs (stats, list, dead-letters), so
    filenames in job payloads / error text never leak across tenants. The worker
    count is global (shared infra, not sensitive)."""
    owner = getattr(request.state, "user_email", None) or "demo"
    # worker_tier_status() is a strict superset of worker_tier_alive() — same freshness check,
    # plus the beat's own timestamp and age. Discover's processing panel already distinguishes
    # connection freshness (its SSE stream) from progress freshness (inventory last changing);
    # this is the third of the PRD's three timestamps — whether the ASSIGNED WORKER is still
    # alive — which nothing here exposed before. "alive" below is unchanged in shape (still a
    # bare bool at the same key), so this is additive, not a breaking change to the response.
    _wt = core.store.worker_tier_status()
    return {"workers": core.WORKERS,
            # Standalone worker container's heartbeat (#113) — in the split topology the
            # API's own pool is 0, so Monitor must show the tier that actually runs jobs.
            "worker_tier_alive": _wt["alive"],
            "worker_heartbeat_at": _wt["heartbeat_at"],
            "worker_heartbeat_age_s": _wt["age_s"],
            # The worker container's own core.WORKERS (its real concurrency, carried in the
            # heartbeat's JSON envelope) — None for an old bare-ISO beat or one that never
            # carried it. This is real "ACP-ready worker slots" capacity, unlike `workers`
            # above, which is this API container's OWN pool (0 in the split topology). Busy
            # vs. available within that slot count is NOT tracked here — it needs
            # instrumentation inside worker.py's pool itself — but a caller can already
            # approximate "busy" for free from `stats.running` below once this is non-None.
            "worker_tier_pool_size": _wt.get("pool_size"),
            # Conservative starting recommendation. Local AI workloads are memory- and
            # GPU-constrained, not CPU-constrained; 4 is a safe floor the user can raise.
            "suggested_workers": 4,
            "runtime_mode": core._RUNTIME_MODE,
            # Global like `workers`/`worker_tier_alive` above, not owner-scoped: the question
            # this answers ("is the shared worker tier actually draining its queue") is about the
            # tier, not this caller's own jobs — scoping it to owner would go dark the moment
            # THIS user has nothing queued, even while every other tenant's queue is stalled.
            # Only id/type/created_at are exposed — no payload, so no filenames cross tenants.
            "oldest_queued": core.store.oldest_queued_job(),
            "stats": core.store.job_stats(owner=owner),
            "dead_letters": core.store.dead_letter_breakdown(owner=owner),
            "jobs": core.store.list_jobs(status=status, limit=limit, owner=owner)}


def _admin_activity_snapshot() -> dict:
    wt = core.store.worker_tier_status()
    worker_roles = core.store.worker_roles_status()
    stats = core.store.job_stats(owner=None)
    runs = core.store.admin_live_activity()
    # The shared heartbeat is last-writer-wins. In production each dedicated service writes its
    # own role heartbeat, so summing the live role pools is the only honest total capacity.
    # Fall back to the legacy shared heartbeat for older/single-pool deployments.
    live_role_slots = sum(int(row.get("pool_size") or 0) for row in worker_roles.values()
                          if row.get("alive"))
    slots = live_role_slots or (wt.get("pool_size") if wt.get("pool_size") is not None
                                else core.WORKERS)
    running = sum(int(r.get("running") or 0) for r in runs)
    queued = sum(int(r.get("queued") or 0) for r in runs)
    by_stage: dict[str, dict] = {}
    for run in runs:
        stage = run.get("stage") or "unknown"
        stage_row = by_stage.setdefault(stage, {"runs": 0, "running": 0, "queued": 0,
                                                  "completed": 0, "total": 0})
        stage_row["runs"] += 1
        for field in ("running", "queued", "completed", "total"):
            stage_row[field] += int(run.get(field) or 0)
    # The queue's own composition and rates, for the Live Operations queue visualization. Guarded
    # because an older store may not carry it: the drawer renders a missing row as "Not reported"
    # rather than as zero, so degrading to absent is honest and degrading to {} would not be.
    composition = None
    _qc = getattr(core.store, "queue_composition", None)
    if callable(_qc):
        try:
            composition = _qc()
        except Exception:
            composition = None
    if queued and not wt.get("alive"):
        pressure = "stalled"
    elif queued and slots and running >= slots:
        pressure = "saturated"
    elif queued:
        pressure = "busy"
    else:
        pressure = "healthy"
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runs": runs,
        "summary": {
            "active_runs": sum(1 for r in runs if r.get("status") == "active"),
            "recent_runs": sum(1 for r in runs if r.get("status") == "recent"),
            "active_users": len({r.get("owner") for r in runs if r.get("owner")}),
            "waiting_users": len({r.get("owner") for r in runs if r.get("owner") and r.get("queued")}),
            "queued": queued,
            "running": running,
            "completed_jobs": int(stats.get("done") or 0),
            "worker_slots": slots,
            "available_slots": max(0, int(slots or 0) - running),
            "utilization_pct": min(100, round((running / slots) * 100)) if slots else None,
            "pressure": pressure,
            "scheduling_policy": "tenant_fair_least_loaded",
            "worker_tier_alive": bool(wt.get("alive")),
            "worker_roles": worker_roles,
            "by_stage": by_stage,
            # Absent, not empty, when the store cannot answer — see the guard above.
            **({"queue": composition} if composition else {}),
        },
    }


@router.get("/admin/activity")
def admin_activity(request: Request, response: Response):
    """Payload-sanitized cross-user processing topology for signed-in workspace users."""
    _require_user(request)
    response.headers["Cache-Control"] = "no-store"
    return _admin_activity_snapshot()


@router.get("/admin/activity/stream")
async def admin_activity_stream(request: Request):
    """Authenticated SSE snapshots for the live multi-user traffic map."""
    import asyncio

    _require_user(request)

    async def _gen():
        last = None
        idle = 0
        while not await request.is_disconnected():
            snapshot = await asyncio.to_thread(_admin_activity_snapshot)
            signature = json.dumps({"runs": snapshot["runs"], "summary": snapshot["summary"]},
                                   sort_keys=True, default=str)
            if signature != last:
                last = signature
                idle = 0
                yield f"event: activity\ndata: {json.dumps(snapshot, default=str)}\n\n"
            else:
                idle += 1
                if idle >= 5:
                    idle = 0
                    yield ": keep-alive\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(_gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-store",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })


@router.get("/jobs/{job_id}")
def queue_job(job_id: str, request: Request):
    """Status of one durable-queue job, owner-scoped via its scan — lets the UI show
    REAL progress for a single-file remediation (queued → running → done/dead)
    instead of a timed guess. Slim view only: payload can hold another tenant's
    filenames, so it is never returned.

    `phase` and `locked_at` (2026-08-22) round this out into what AssessRunner's deferred poll
    needed and didn't have: not just "queued vs running" but WHAT a running job is doing right
    now (phase, written by the handler as it works — same field the queue panel already reads)
    and WHEN a worker actually claimed it (locked_at), so "waiting for a worker" and "a worker
    has been on this for 40s" read as the different situations they are, instead of both showing
    an identical, silent 0%."""
    j = core.store.get_job(job_id)
    owner = getattr(request.state, "user_email", None) or "demo"
    if j is None or not j.get("scan_id") or core.store.get_scan(j["scan_id"], owner=owner) is None:
        raise HTTPException(404, "job not found")
    # `attempt`/`max_attempts` are named for the SSE frame, not the column (jobs.attempts), so a
    # reader has ONE name for this fact whichever way it arrived. Without them the retry and
    # interrupted cards could only ever say "attempt N" while a live event frame happened to be
    # in hand — a page reload dropped the number, and the card silently degraded to a card that
    # does not mention which attempt you are watching.
    #
    # Safe for the slim view: a counter is not tenant data. The payload stays excluded.
    return {"id": j["id"], "type": j["type"], "status": j["status"],
            "attempt": j.get("attempts"), "max_attempts": j.get("max_attempts"),
            "attempts": j.get("attempts"), "max_attempts": j.get("max_attempts"), "error": j.get("last_error"),
            "scan_id": j.get("scan_id"), "phase": j.get("phase"), "locked_at": j.get("locked_at")}


@router.post("/admin/jobs/clear-dead")
def clear_dead_jobs(request: Request):
    """Delete the caller's OWN unrecoverable dead-lettered jobs. Owner-scoped so a
    user can't purge another tenant's queue. Re-run the originating action to retry."""
    owner = getattr(request.state, "user_email", None) or "demo"
    return {"purged": core.store.purge_dead_jobs(owner=owner)}


class AIProviderTest(BaseModel):
    # Same extra='forbid' guard as the update model, and for the same reason: this endpoint has
    # no field that could carry a key, and a client that invents one is rejected rather than
    # having the value quietly ignored (or worse, logged with the request).
    model_config = ConfigDict(extra="forbid")
    provider: str


@router.post("/ai/providers/test")
def test_ai_provider(body: AIProviderTest, request: Request):
    """Admin: send a SYNTHETIC probe image to one provider and report what came back.

    NO CUSTOMER DOCUMENT IS SENT. The bytes are providers.probe_image_bytes() — a 64×64 black
    square on white, generated in-process from stdlib zlib. That is what makes this safe to press
    on a provider nobody has agreed to send documents to yet: it is how an admin learns whether
    the credential and the route work BEFORE any real content could go anywhere.

    Works on a provider that is NOT yet enabled, deliberately — testing before enabling is the
    whole point, and requiring the switch first would invert the order. It does require the
    configuration to be complete and the referenced secret to resolve, and says which of the two
    is missing when it is not.

    The response carries no secret: provider, model, zone, latency, outcome reason, real token
    counts and real cost. Never the key, never the value behind key_secret_ref, and not even the
    model's caption of the probe.
    """
    _require_admin(request)
    import providers as _providers
    provider = (body.provider or "").strip().lower()
    if provider not in _providers.CLOUD_PROVIDERS:
        raise HTTPException(422, f"unknown provider '{provider}' — one of {list(_providers.CLOUD_PROVIDERS)}")
    result = _providers.test_connection(provider)
    # Audited like any other admin action, and for a real reason beyond bookkeeping: this is the
    # one path that can make an outbound call to a third party from the Settings page, so who
    # pressed it and what came back belongs in the record. The detail names the outcome, never
    # a credential.
    core.store.log_decision(
        getattr(request.state, "user_email", None) or "admin",
        f"settings.ai_provider.{provider}.test",
        detail=f"connection test → ok={result.get('ok')} reason={result.get('reason')} "
               f"model={result.get('model') or '—'} zone={result.get('zone') or '—'} "
               f"latency_ms={result.get('latency_ms') or '—'} (synthetic probe image; "
               f"no customer document sent)")
    return result
