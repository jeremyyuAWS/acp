"""System & meta endpoints: liveness, SPA auth config, schedule, hub landing page."""
from __future__ import annotations

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


@router.get("/config")
def config():
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
            "auth": "gis" if core.GOOGLE_CLIENT_ID else "demo",
            **_build_info(),
            "ai": _ai.provenance(),
            "langfuse_trace_base": (f"{lf_host}/project/{lf_project}/traces" if lf_host else None)}


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


class SettingsUpdate(BaseModel):
    ai_enabled: bool | None = None
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
            "ai_text_model": core.store.get_setting("ai_text_model", "") or ""}


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
    for key, val in (("ai_base_url", body.ai_base_url),
                     ("ai_vision_model", body.ai_vision_model),
                     ("ai_text_model", body.ai_text_model)):
        if val is None:
            continue
        val = val.strip()
        if key == "ai_base_url" and val and not val.startswith(("http://", "https://")):
            raise HTTPException(422, "ai_base_url must be an http(s) URL (or empty to use the deploy default)")
        core.store.set_setting(key, val)
        core.store.log_decision("admin", f"settings.{key}",
                                detail=f"{key} set to {val or '(deploy default)'} — takes effect "
                                       "on every replica within ~30s, no restart")
        # This replica switches immediately; the others follow via the TTL refresh.
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
