"""System & meta endpoints: liveness, SPA auth config, schedule, hub landing page."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

import core

router = APIRouter()


@router.post("/admin/reset")
def admin_reset(scope: str = Query("all", pattern="^(all|grafana|langfuse)$"),
                confirm: bool = Query(False)):
    """Reset demo data so the charts start fresh (admin, audited).
    scope=grafana → clear the ACP Postgres analytics tables (Grafana + in-app
    charts); scope=langfuse → delete the project's Langfuse traces; all → both.
    Settings (worker count, AI mode, schedule, rubric) are preserved."""
    if not confirm:
        raise HTTPException(400, "confirmation required — pass confirm=true")
    cleared: list[str] = []
    lf_deleted = 0
    if scope in ("all", "grafana"):
        cleared = core.store.reset_analytics()
    if scope in ("all", "langfuse"):
        lf_deleted = core.reset_langfuse_traces()
    # Logged AFTER the wipe so the reset itself is recorded.
    core.store.log_decision("admin", "demo.reset",
                            detail=f"scope={scope} · tables={len(cleared)} · langfuse_traces={lf_deleted}")
    return {"scope": scope, "cleared_tables": cleared, "langfuse_traces_deleted": lf_deleted}


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


@router.put("/workers")
def set_workers(count: int = Query(..., ge=0, le=16)):
    """Admin: live-scale the in-process worker pool (0–16). Persisted + audited.
    Scaled-down workers finish their current job before exiting."""
    new = core.set_worker_count(count)
    core.store.log_decision("admin", "settings.worker_count",
                            detail=f"worker pool scaled to {new}")
    return {"workers": new}


@router.get("/healthz")
def healthz():
    return {"ok": True, "service": "acp", "rubric_hash": core.active_rubric().hash}


@router.get("/config")
def config():
    """Tells the SPA how to authenticate: GIS per-user (client id present) vs demo."""
    return {"google_client_id": core.GOOGLE_CLIENT_ID,
            "drive_scope": core.DRIVE_SCOPES[0],
            "auth": "gis" if core.GOOGLE_CLIENT_ID else "demo"}


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
def update_schedule(body: ScheduleUpdate):
    core.store.save_schedule(body.enabled, body.interval_minutes)
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


@router.get("/settings")
def get_settings():
    """Platform settings. ai_enabled=false → deterministic-only mode platform-wide
    (overrides per-scan ?ai=true and blocks /ai/explain)."""
    return {"ai_enabled": core.store.get_ai_enabled()}


@router.put("/settings")
def update_settings(body: SettingsUpdate):
    """Admin: set platform settings. Persisted across restarts. Audited."""
    if body.ai_enabled is not None:
        core.store.set_ai_enabled(body.ai_enabled)
        core.store.log_decision(
            "admin", "settings.ai_enabled",
            detail=f"ai_enabled set to {body.ai_enabled}")
    return get_settings()


@router.get("/decisions")
def decisions(scan_id: str | None = None, limit: int = 500):
    """Immutable decision audit log — every consequential action (scan mode, HITL
    review, settings change, auto-routing). Append-only; filter by scan_id."""
    return core.store.list_decisions(scan_id=scan_id, limit=limit)


@router.get("/jobs")
def jobs(status: str | None = None, limit: int = 100):
    """Async job-queue visibility (ADR 0004): queue depth by status + recent jobs.
    Feeds the Grafana queue panel and live UI."""
    return {"workers": core.WORKERS,
            "stats": core.store.job_stats(),
            "dead_letters": core.store.dead_letter_breakdown(),
            "jobs": core.store.list_jobs(status=status, limit=limit)}


@router.post("/admin/jobs/clear-dead")
def clear_dead_jobs():
    """Delete unrecoverable dead-lettered jobs (gated — signed-in admins only).
    Dead-letters are terminal failures; clearing them just removes the noise from
    the queue. Re-run the originating action (e.g. remediate) to retry the work."""
    return {"purged": core.store.purge_dead_jobs()}
