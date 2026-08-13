"""System & meta endpoints: liveness, SPA auth config, schedule, hub landing page."""
from __future__ import annotations

import hmac
import json
import re

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict

import core

router = APIRouter()

# A secret REFERENCE is an environment-variable name (e.g. AZURE_OPENAI_API_KEY), never a key
# value. This shape is what keeps a pasted key out of the DB: a real key won't match it.
_SECRET_REF_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,64}$")


def _require_admin(request: Request) -> None:
    """Owner-only gate for platform-mutating admin endpoints. The SPA hides these
    behind the Platform Admin role, but the API must enforce it too — any
    allow-listed user could otherwise flip platform settings (AI mode, Drive
    mirror, worker pool, data reset) with a direct call. Admin = the protected
    OWNER_EMAIL, the same identity the allowlist can never drop (anti-lockout).
    No-op when no owner is configured (local dev without auth)."""
    if not core.OWNER_EMAIL:
        return
    email = (getattr(request.state, "user_email", None) or "").lower()
    if email != core.OWNER_EMAIL:
        raise HTTPException(403, "admin (owner) access required")


@router.post("/admin/reset")
def admin_reset(request: Request,
                scope: str = Query("all", pattern="^(all|grafana|langfuse)$"),
                confirm: bool = Query(False)):
    _require_admin(request)
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
            pass
    return {"received": len(alerts)}


@router.get("/admin/allowlist")
def get_allowlist():
    """Test users who can use the app: the editable list, the protected owner (can't be
    removed), and any always-allowed domains."""
    return {"emails": core.store.get_allowlist(),
            "owner": core.OWNER_EMAIL,
            "domains": core.ALLOWED_DOMAINS}


@router.put("/admin/allowlist")
def set_allowlist(body: dict, request: Request):
    """Replace the editable test-user list. The owner is always kept (anti-lockout)."""
    _require_admin(request)
    emails = body.get("emails", [])
    if not isinstance(emails, list):
        raise HTTPException(400, "emails must be a list of strings")
    if core.OWNER_EMAIL:
        emails = list(emails) + [core.OWNER_EMAIL]   # never drop the owner
    saved = core.store.set_allowlist(emails)
    core.store.log_decision("admin", "settings.allowlist",
                            detail=f"test-user list set to {len(saved)} email(s)")
    return {"emails": saved, "owner": core.OWNER_EMAIL}


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
    local_pool = int(getattr(core, "WORKERS", 0) or 0)
    # Either tier can man the queue: the split topology (#113) runs the pool in a standalone
    # worker container, the single-tier setup runs it in-process. Readiness is the OR — the
    # scan-start guard in routes/scans.py makes exactly the same call.
    can_run_scans = bool(local_pool) or workers["alive"]

    degraded: list[str] = []
    if not can_run_scans:
        degraded.append("no_workers" if workers["ever_seen"] else "worker_tier_never_started")
    pdf = pdf_engine_status()
    if not pdf["available"]:
        degraded.append("pdf_engine_missing")

    return {
        "ready": not degraded,
        "degraded": degraded,
        "workers": {**workers, "local_pool": local_pool, "can_run_scans": can_run_scans},
        "engines": {"pdf": pdf},
        "service": "acp",
    }


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

    scans = core.store.list_scans() or []
    pending = core.store.list_hitl_queue(status="pending") or []
    return {
        "service": "acp",
        "scans": {
            "total": len(scans),
            # Newest first, exactly as list_scans orders them (completed_at DESC).
            "recent_files": [int(s.get("files") or 0) for s in scans[:MONITOR_SCAN_WINDOW]],
        },
        "inbox": {"pending": len(pending)},
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
    return {"google_client_id": core.GOOGLE_CLIENT_ID,
            "drive_scope": core.DRIVE_SCOPES[0],
            # Entra app for the SharePoint/OneDrive connect — runtime so the tenant can be set per
            # deployment without rebuilding the SPA (the frontend falls back to VITE_AZURE_* only
            # when these are absent). Null when SharePoint isn't configured; the SPA hides the button.
            "azure_client_id": core.AZURE_CLIENT_ID,
            "azure_tenant_id": core.AZURE_TENANT_ID,
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
    scans = core.store.list_scans()
    cfg["last_at"] = scans[0]["completed_at"] if scans else None
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
            pass
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
    provider governance config isn't exposed to non-owners."""
    _require_admin(request)
    import providers as _providers
    return {"providers": _providers.list_provider_views()}


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
    who = getattr(request.state, "user_email", None) or "admin"
    core.store.upsert_ai_provider_config(
        provider,
        enabled=body.enabled if body.enabled is not None else bool(existing.get("enabled")),
        endpoint=endpoint,
        deployment=(body.deployment.strip() if body.deployment is not None else existing.get("deployment")) or None,
        model=(body.model.strip() if body.model is not None else existing.get("model")) or None,
        key_secret_ref=ref,
        updated_by=who,
    )
    # Audit records the config change WITHOUT the key value (only the reference name).
    core.store.log_decision("admin", f"settings.ai_provider.{provider}",
                            detail=f"provider={provider} enabled={body.enabled} endpoint={endpoint or '—'} "
                                   f"key_secret_ref={ref or '—'} (key value never handled here)")
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
    return {"workers": core.WORKERS,
            # Standalone worker container's heartbeat (#113) — in the split topology the
            # API's own pool is 0, so Monitor must show the tier that actually runs jobs.
            "worker_tier_alive": core.store.worker_tier_alive(),
            "stats": core.store.job_stats(owner=owner),
            "dead_letters": core.store.dead_letter_breakdown(owner=owner),
            "jobs": core.store.list_jobs(status=status, limit=limit, owner=owner)}


@router.get("/jobs/{job_id}")
def queue_job(job_id: str, request: Request):
    """Status of one durable-queue job, owner-scoped via its scan — lets the UI show
    REAL progress for a single-file remediation (queued → running → done/dead)
    instead of a timed guess. Slim view only: payload can hold another tenant's
    filenames, so it is never returned."""
    j = core.store.get_job(job_id)
    owner = getattr(request.state, "user_email", None) or "demo"
    if j is None or not j.get("scan_id") or core.store.get_scan(j["scan_id"], owner=owner) is None:
        raise HTTPException(404, "job not found")
    return {"id": j["id"], "type": j["type"], "status": j["status"],
            "attempts": j.get("attempts"), "error": j.get("last_error"),
            "scan_id": j.get("scan_id")}


@router.post("/admin/jobs/clear-dead")
def clear_dead_jobs(request: Request):
    """Delete the caller's OWN unrecoverable dead-lettered jobs. Owner-scoped so a
    user can't purge another tenant's queue. Re-run the originating action to retry."""
    owner = getattr(request.state, "user_email", None) or "demo"
    return {"purged": core.store.purge_dead_jobs(owner=owner)}
