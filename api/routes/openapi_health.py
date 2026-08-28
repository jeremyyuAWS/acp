"""A standalone, publicly-readable OpenAPI (Swagger) document for ACP's health, readiness,
heartbeat and monitoring surface — Discovery, Assessment/Remediation, and the platform as a
whole.

WHY A SEPARATE DOCUMENT, NOT FastAPI's OWN /docs. FastAPI already auto-generates a full
OpenAPI schema (every route, including admin, PII, and remediation endpoints) — but that
schema sits behind the same access gate as the routes it describes (core.is_public only
allow-lists specific paths; a bare "make /docs public" would publish the shape, and in some
cases the behaviour, of every admin and document-content endpoint in the product). Operators
and integrators who just want to wire a monitor or a status page don't need any of that; they
need the narrow slice that already exists for exactly this purpose (see ALWAYS_PUBLIC in
core.py: /healthz, /readyz, /monitor/estate, /ai/status, /alerts/webhook, /capability) plus the
owner-scoped progress/heartbeat endpoints (/jobs, /scans/{sid}/live, /scans/{sid}/status, …)
that a signed-in caller uses to watch a run.

This module owns that curated document and two routes to serve it:
  GET /openapi/health.json — the OpenAPI 3.0 document itself
  GET /docs/health         — a Swagger UI page rendering it

Both are added to core.ALWAYS_PUBLIC (see core.py) so they work unauthenticated even on a
gated deployment — the point of the document is to be reachable without a login.

Nothing here reads live state: the document is a static, hand-maintained description of the
response shapes those routes already return (see each route's own module for the source of
truth — this file must never drift into being that source of truth itself).
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter()

_HEARTBEAT_DESCRIPTION = """
# ACP Health, Readiness & Heartbeat API

Read-only endpoints for monitoring ACP's three pipeline stages — **Discovery**, **Assessment**,
and **Remediation** — plus the platform as a whole. This document covers only the
health/status/heartbeat surface; it is a curated subset of the full API, published so a
monitor, uptime check, or status page can be wired up without authenticating against the
product itself.

## Heartbeat mechanisms

ACP has no single "/heartbeat" endpoint. Instead there are three independent heartbeat
mechanisms, each with its own cadence, and each is *surfaced* through one or more of the
endpoints below rather than exposed directly:

| Heartbeat | Cadence | Written by | Read via |
|---|---|---|---|
| **Worker-tier heartbeat** | every scheduler tick (worker_main.py) | the standalone worker container, into the `worker_tier_heartbeat` setting | `GET /readyz` (`workers.heartbeat_at`, `workers.age_s`, `workers.alive`), `GET /jobs` (`worker_tier_alive`), `POST /discovery/preflight` (`workers` block) |
| **Job liveness heartbeat** | every 20s while a scan job runs (`core._JOB_HEARTBEAT_SECONDS`) | the scan's background thread, touching the job's `updated_at` | `GET /scans/{sid}/live`, `GET /jobs/{job_id}` (`locked_at`) — a stalled thread shows up as a stale `updated_at` even with no progress made |
| **Job lease heartbeat** | every 120s while a worker holds a job (`worker.HEARTBEAT_INTERVAL_S`) | the async worker, extending the job's lease so the stuck-job sweeper doesn't reclaim active work | indirectly — a job that stays `running` instead of being requeued as `dead` |
| **SSE keep-alive** | every 15s of silence (`_HEARTBEAT_EVERY` in routes/scans.py) | the `/scans/{sid}/events` and `/scans/{scan_id}/discover/stream` streams, as a `:` comment frame between real `data:` frames | consumed by the browser's EventSource, not polled directly |

## Pipeline stage → health endpoint

- **Discovery**: `POST /discovery/preflight` (pre-flight readiness for a specific source/scope),
  `GET /scans/active`, worker/queue fields on `GET /readyz`.
- **Assessment**: `GET /scans/{sid}/status` (Accessibility Status roll-up), `GET /scans/{sid}/live`
  and `GET /scans/{sid}/events` (live KPIs + worker/queue block while a run is in progress).
- **Remediation**: `GET /scans/{sid}/remediation-status` (in-flight jobs + current activity),
  `GET /scans/{sid}/source-status` (has the source file drifted since scan time).
- **Platform**: `GET /healthz` (liveness + build provenance), `GET /readyz` (functional
  readiness — workers, PDF/vision engines, source-adapter config), `GET /monitor/estate`
  (production-monitor aggregate counts, key-gated), `GET /schedule` (scheduled-sweep config +
  last outcome), `GET /ai/status`, `GET /jobs` (queue depth + worker heartbeat),
  `GET /control/estate`, `POST /alerts/webhook` (inbound Grafana alert receiver).

Endpoints marked **public** in this document work with no credential at all (they are
allow-listed in ACP's access gate). Endpoints marked **authenticated** require the same
sign-in the product UI uses; two of those (`/monitor/estate`, `/alerts/webhook`) are public
paths but require a separate shared-secret header/query param instead.
"""

_OK_HEADERS = {"Cache-Control": "no-store"}


def _get(summary: str, tag: str, description: str, response_schema: dict,
         security: list | None = None, params: list | None = None,
         responses_extra: dict | None = None) -> dict:
    op = {
        "summary": summary,
        "tags": [tag],
        "description": description,
        "responses": {
            "200": {
                "description": "OK",
                "content": {"application/json": {"schema": response_schema}},
            }
        },
    }
    if security is not None:
        op["security"] = security
    if params:
        op["parameters"] = params
    if responses_extra:
        op["responses"].update(responses_extra)
    return op


_NO_AUTH: list = []
_SESSION_AUTH = [{"sessionAuth": []}]
_MONITOR_KEY_AUTH = [{"monitorKey": []}]
_ALERT_KEY_AUTH = [{"alertKey": []}]

HEALTH_OPENAPI_SPEC: dict = {
    "openapi": "3.0.3",
    "info": {
        "title": "ACP — Health, Readiness & Heartbeat API",
        "version": "1.0.0",
        "description": _HEARTBEAT_DESCRIPTION,
    },
    "servers": [{"url": "/", "description": "This deployment"}],
    "tags": [
        {"name": "Platform", "description": "Liveness, readiness, build provenance, and platform-wide status."},
        {"name": "Monitoring", "description": "Aggregate, key-gated signals for external monitors and alerting."},
        {"name": "Discovery", "description": "Pre-flight and in-flight health for the Discover stage."},
        {"name": "Assessment", "description": "Live and roll-up health for the Assess stage."},
        {"name": "Remediation", "description": "Live progress and source-drift health for the Remediate stage."},
    ],
    "components": {
        "securitySchemes": {
            "sessionAuth": {
                "type": "http", "scheme": "bearer",
                "description": "The product's own sign-in session (Google/Microsoft bearer token, "
                                "or HTTP Basic when ACP_ACCESS_CODE is configured). Not required "
                                "on a local/dev deployment with neither configured.",
            },
            "monitorKey": {
                "type": "apiKey", "in": "header", "name": "X-Monitor-Key",
                "description": "Shared secret (ACP_MONITOR_KEY). Route is public but 401s without "
                                "the correct key, and 503s when the deployment has none configured.",
            },
            "alertKey": {
                "type": "apiKey", "in": "query", "name": "key",
                "description": "Shared secret (ACP_ALERT_KEY) for the inbound Grafana alert webhook.",
            },
        },
        "schemas": {
            "HealthzResponse": {
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean", "description": "False when this image was never stamped by deploy.sh (advisory, not a rollout gate)."},
                    "service": {"type": "string", "example": "acp"},
                    "rubric_hash": {"type": "string"},
                    "version": {"type": "string", "example": "2026.8.28.140501"},
                    "built_at": {"type": "string", "nullable": True, "format": "date-time"},
                    "version_stamped": {"type": "boolean"},
                },
            },
            "ReadyzResponse": {
                "type": "object",
                "properties": {
                    "ready": {"type": "boolean"},
                    "capacity_state": {"type": "string", "enum": ["ready", "starting", "unavailable"]},
                    "degraded": {"type": "array", "items": {"type": "string"},
                                 "description": "Machine-readable reasons, e.g. no_workers, worker_tier_never_started, pdf_engine_missing."},
                    "workers": {
                        "type": "object",
                        "properties": {
                            "alive": {"type": "boolean"},
                            "heartbeat_at": {"type": "string", "nullable": True, "format": "date-time",
                                              "description": "Worker-tier heartbeat — see the heartbeat table above."},
                            "age_s": {"type": "number", "nullable": True},
                            "ever_seen": {"type": "boolean"},
                            "local_pool": {"type": "integer"},
                            "can_run_scans": {"type": "boolean"},
                        },
                    },
                    "engines": {
                        "type": "object",
                        "properties": {
                            "pdf": {"type": "object", "properties": {
                                "available": {"type": "boolean"}, "path": {"type": "string"},
                                "reason": {"type": "string", "nullable": True}}},
                            "vision": {"type": "object", "properties": {
                                "ready": {"type": "boolean"}, "reason": {"type": "string", "nullable": True},
                                "model": {"type": "string", "nullable": True}, "zone": {"type": "string", "nullable": True}}},
                        },
                    },
                    "sources": {"type": "object", "description": "Informational, per-source-adapter readiness (e.g. smb) — never folds into `degraded`."},
                    "service": {"type": "string", "example": "acp"},
                },
            },
            "MonitorEstateResponse": {
                "type": "object",
                "properties": {
                    "service": {"type": "string", "example": "acp"},
                    "scans": {"type": "object", "properties": {
                        "total": {"type": "integer"},
                        "recent_files": {"type": "array", "items": {"type": "integer"},
                                          "description": "Newest-first file counts for up to the last 20 finished scans (Discover-only runs included)."}}},
                    "inbox": {"type": "object", "properties": {"pending": {"type": "integer"}}},
                    "sweep": {"type": "object", "description": "Added 2026-08-28 (#908/#909) so a scheduled sweep can't be mistaken for a real collapse.",
                              "properties": {
                                  "enabled": {"type": "boolean"},
                                  "interval_minutes": {"type": "integer", "nullable": True},
                                  "last_ok": {"type": "boolean", "nullable": True},
                                  "last_at": {"type": "string", "nullable": True, "format": "date-time"},
                                  "last_files": {"type": "integer", "nullable": True}}},
                },
            },
            "ScheduleResponse": {
                "type": "object",
                "properties": {
                    "enabled": {"type": "boolean"},
                    "interval_minutes": {"type": "integer"},
                    "next_at": {"type": "string", "nullable": True, "format": "date-time"},
                    "last_at": {"type": "string", "nullable": True, "format": "date-time",
                                "description": "Fixed 2026-08-28 (#908) to include Discover-only sweeps, not just fully-assessed scans."},
                    "last_sweep": {"type": "object", "nullable": True,
                                    "description": "The last scheduled sweep's OUTCOME (added #909) — distinguishes a failing sweep from a healthy one that simply hasn't run recently.",
                                    "properties": {"ok": {"type": "boolean"}, "at": {"type": "string", "format": "date-time"}, "files": {"type": "integer"}}},
                },
            },
            "AiStatusResponse": {
                "type": "object",
                "properties": {
                    "available": {"type": "boolean"},
                    "base_url": {"type": "string"},
                    "model": {"type": "string"},
                    "ai_enabled": {"type": "boolean"},
                    "backend": {"type": "string"},
                    "vision_available": {"type": "boolean"},
                    "vision_model": {"type": "string"},
                    "vision_unavailable_reason": {"type": "string", "nullable": True},
                    "model_available": {"type": "boolean"},
                    "cloud_enabled": {"type": "boolean"},
                    "cloud_provider": {"type": "string", "nullable": True},
                    "cloud_zone": {"type": "string", "nullable": True},
                    "config_source": {"type": "object"},
                },
            },
            "JobsResponse": {
                "type": "object",
                "properties": {
                    "workers": {"type": "integer", "description": "In-process worker pool size (0 in the split worker-tier topology)."},
                    "worker_tier_alive": {"type": "boolean", "description": "Worker-tier heartbeat, boolean form."},
                    "suggested_workers": {"type": "integer"},
                    "runtime_mode": {"type": "string"},
                    "stats": {"type": "object", "description": "Queue depth by status, scoped to the caller."},
                    "dead_letters": {"type": "object"},
                    "jobs": {"type": "array", "items": {"type": "object"}},
                },
            },
            "JobResponse": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"}, "type": {"type": "string"},
                    "status": {"type": "string", "enum": ["queued", "running", "done", "dead"]},
                    "attempts": {"type": "integer", "nullable": True},
                    "error": {"type": "string", "nullable": True},
                    "scan_id": {"type": "string", "nullable": True},
                    "phase": {"type": "string", "nullable": True, "description": "What a running job is doing right now."},
                    "locked_at": {"type": "string", "nullable": True, "format": "date-time",
                                   "description": "When a worker claimed this job — the job liveness heartbeat keeps this lease alive."},
                },
            },
            "DiscoveryPreflightResponse": {
                "type": "object",
                "properties": {
                    "verdict": {"type": "string", "enum": ["ready", "degraded", "blocked"]},
                    "capacity_state": {"type": "string", "enum": ["ready", "starting", "unavailable", "busy"]},
                    "blocked_reasons": {"type": "array", "items": {"type": "string"}},
                    "degraded_reasons": {"type": "array", "items": {"type": "string"}},
                    "source": {"type": "object", "description": "Credential/root-existence check for the selected source."},
                    "workers": {"type": "object"},
                    "queue": {"type": "object", "properties": {
                        "queued": {"type": "integer"}, "backlogged": {"type": "boolean"}, "threshold": {"type": "integer"}}},
                },
            },
            "ScanActiveResponse": {
                "type": "object",
                "description": "The caller's in-flight scan, or {} when none.",
            },
            "ScanAccessibilityStatusResponse": {
                "type": "object",
                "description": "ADR 0026 — always-200; {available:false, reason} when the scan/file is unknown or not yet certifiable.",
            },
            "ScanLiveSnapshotResponse": {
                "type": "object",
                "description": "Live Assessment Experience PRD §8 — reconciled file-outcome KPIs plus the worker/queue block, when present. Always 200 ({available:false} degrade).",
            },
            "RemediationStatusResponse": {
                "type": "object",
                "properties": {
                    "activity": {"type": "object", "nullable": True,
                                 "description": "The file, criterion, and action currently in flight, if any."},
                },
                "additionalProperties": True,
                "description": "Plus in-flight job counts from store.remediation_status().",
            },
            "SourceStatusResponse": {
                "type": "object",
                "properties": {
                    "scan_id": {"type": "string"},
                    "stale_count": {"type": "integer"},
                    "untracked_count": {"type": "integer"},
                    "unavailable_count": {"type": "integer"},
                    "files": {"type": "array", "items": {"type": "object"}},
                },
            },
            "ControlEstateResponse": {
                "type": "object",
                "properties": {
                    "tenant": {"type": "string"},
                    "departments": {"type": "array", "items": {"type": "object"}},
                    "owners": {"type": "array", "items": {"type": "object"}},
                    "documents": {"type": "integer"},
                    "filters": {"type": "object"},
                    "filtered": {"type": "boolean"},
                },
            },
            "CapabilityResponse": {
                "type": "object",
                "description": "The two-axis capability matrix (ADR 0023) — static, non-sensitive product metadata.",
            },
            "AlertWebhookResponse": {
                "type": "object",
                "properties": {"received": {"type": "integer"}},
            },
        },
    },
    "paths": {
        "/healthz": {
            "get": _get(
                "Liveness + build provenance", "Platform",
                "Is this the image deploy.sh actually stamped? No dependency checks — see /readyz "
                "for functional readiness. Not gated by a platform health probe (ACA runs none "
                "against this route); this is advisory.",
                {"$ref": "#/components/schemas/HealthzResponse"}, security=_NO_AUTH,
            ),
        },
        "/readyz": {
            "get": _get(
                "Functional readiness", "Platform",
                "Can this deployment actually do work right now — worker tier (with its heartbeat "
                "age), the PDF/vision engines, source-adapter config. Deliberately separate from "
                "/healthz: a worker-tier outage must never be treated as a reason to restart the "
                "API container.",
                {"$ref": "#/components/schemas/ReadyzResponse"}, security=_NO_AUTH,
            ),
        },
        "/monitor/estate": {
            "get": _get(
                "Production-monitor aggregate counts", "Monitoring",
                "Counts only — never records: recent per-scan file counts (newest first, Discover-"
                "only runs included), the pending HITL-review count, and (added 2026-08-28, #907-#909) "
                "whether the newest scan was a scheduled sweep, so a routine sweep can't be misread "
                "as a collapse. 503 when ACP_MONITOR_KEY is unset (fail closed); 401 on a wrong key.",
                {"$ref": "#/components/schemas/MonitorEstateResponse"}, security=_MONITOR_KEY_AUTH,
                responses_extra={
                    "401": {"description": "Missing or wrong X-Monitor-Key"},
                    "503": {"description": "ACP_MONITOR_KEY is not configured on this deployment"},
                },
            ),
        },
        "/schedule": {
            "get": _get(
                "Scheduled-sweep configuration + last outcome", "Monitoring",
                "Enabled/interval, next scheduled run, last completed scan (fixed 2026-08-28 (#908) "
                "to see Discover-only sweeps), and the last sweep's own success/failure outcome "
                "(added 2026-08-28, #909).",
                {"$ref": "#/components/schemas/ScheduleResponse"}, security=_SESSION_AUTH,
            ),
        },
        "/ai/status": {
            "get": _get(
                "AI backend + vision-model reachability", "Platform",
                "Is the local model backend reachable, is a vision model pulled (needed for genuine "
                "image alt text, WCAG 1.1.1), and is a governed cloud vision fallback configured.",
                {"$ref": "#/components/schemas/AiStatusResponse"}, security=_NO_AUTH,
            ),
        },
        "/jobs": {
            "get": _get(
                "Async job-queue visibility", "Monitoring",
                "Queue depth by status, the caller's own recent jobs, dead-letter breakdown, and the "
                "worker-tier heartbeat as a boolean (worker_tier_alive). Owner-scoped.",
                {"$ref": "#/components/schemas/JobsResponse"}, security=_SESSION_AUTH,
                params=[{"name": "status", "in": "query", "required": False, "schema": {"type": "string"}},
                        {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer", "default": 100}}],
            ),
        },
        "/jobs/{job_id}": {
            "get": _get(
                "Status of one durable-queue job", "Monitoring",
                "queued → running → done/dead, plus `phase` (what a running job is doing right now) "
                "and `locked_at` (when a worker claimed it — the job's lease is kept alive by the "
                "120s job-lease heartbeat in worker.py). Owner-scoped via the job's scan.",
                {"$ref": "#/components/schemas/JobResponse"}, security=_SESSION_AUTH,
                params=[{"name": "job_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                responses_extra={"404": {"description": "Job not found, or belongs to another owner"}},
            ),
        },
        "/discovery/preflight": {
            "post": _get(
                "Pre-flight readiness for a Discover scan", "Discovery",
                "Ready/degraded/blocked verdict for the SPECIFIC source + scope about to be scanned "
                "— credential validity, selected-root existence, worker/queue capacity. Read-only; "
                "safe to call repeatedly. Separate from /readyz, which knows nothing about the "
                "specific folder a user picked.",
                {"$ref": "#/components/schemas/DiscoveryPreflightResponse"}, security=_SESSION_AUTH,
                params=[{"name": "source", "in": "query", "required": True, "schema": {"type": "string", "enum": ["drive", "sharepoint", "local"]}},
                        {"name": "folder", "in": "query", "required": False, "schema": {"type": "string"}},
                        {"name": "folders", "in": "query", "required": False, "schema": {"type": "array", "items": {"type": "string"}}}],
            ),
        },
        "/scans/active": {
            "get": _get(
                "The caller's in-flight scan, if any", "Discovery",
                "Lets the UI reconnect to a running scan after a page reload — the durable fan-out "
                "keeps running server-side regardless. Owner-scoped.",
                {"$ref": "#/components/schemas/ScanActiveResponse"}, security=_SESSION_AUTH,
            ),
        },
        "/scans/{sid}/status": {
            "get": _get(
                "Accessibility Status roll-up for a scan", "Assessment",
                "ADR 0026 PR 3 — per-file Accessibility Status models summed and the state machine "
                "re-derived over the totals, so this can never disagree with the per-file cards. "
                "Always 200 ({available:false} degrade); ?prefix= narrows to a folder.",
                {"$ref": "#/components/schemas/ScanAccessibilityStatusResponse"}, security=_SESSION_AUTH,
                params=[{"name": "sid", "in": "path", "required": True, "schema": {"type": "string"}},
                        {"name": "prefix", "in": "query", "required": False, "schema": {"type": "string"}}],
            ),
        },
        "/scans/{sid}/live": {
            "get": _get(
                "Live-run snapshot for the Assess running screen", "Assessment",
                "Live Assessment Experience PRD §8 — reconciled file-outcome KPIs (from the same run "
                "summary the final certification uses) plus, when present, the live worker/queue "
                "block reflecting the job-liveness heartbeat. Always 200 ({available:false} degrade). "
                "See also GET /scans/{sid}/events for the pushed (SSE) equivalent, which adds a "
                "15s keep-alive comment frame between real updates.",
                {"$ref": "#/components/schemas/ScanLiveSnapshotResponse"}, security=_SESSION_AUTH,
                params=[{"name": "sid", "in": "path", "required": True, "schema": {"type": "string"}}],
            ),
        },
        "/scans/{sid}/remediation-status": {
            "get": _get(
                "Live remediation progress", "Remediation",
                "In-flight remediation job counts plus `activity` — the one line naming the file, "
                "criterion, and action currently in flight. Owner-scoped.",
                {"$ref": "#/components/schemas/RemediationStatusResponse"}, security=_SESSION_AUTH,
                params=[{"name": "sid", "in": "path", "required": True, "schema": {"type": "string"}}],
                responses_extra={"404": {"description": "Scan not found"}},
            ),
        },
        "/scans/{sid}/source-status": {
            "get": _get(
                "Has each file's source drifted since scan time?", "Remediation",
                "Compares each file's current Drive modifiedTime against the baseline captured at "
                "scan time. A file with no baseline, no Drive id, or a non-Drive source reports "
                "'untracked' rather than a false 'unchanged'; a 404/403 from Drive reports "
                "'unavailable', never 'stale'.",
                {"$ref": "#/components/schemas/SourceStatusResponse"}, security=_SESSION_AUTH,
                params=[{"name": "sid", "in": "path", "required": True, "schema": {"type": "string"}}],
                responses_extra={"404": {"description": "Scan not found"}},
            ),
        },
        "/control/estate": {
            "get": _get(
                "Tenant estate aggregate, by department/owner", "Monitoring",
                "Document counts for the caller's own tenant, optionally narrowed (never widened) "
                "by dept/owner query params.",
                {"$ref": "#/components/schemas/ControlEstateResponse"}, security=_SESSION_AUTH,
                params=[{"name": "dept", "in": "query", "required": False, "schema": {"type": "string"}},
                        {"name": "owner", "in": "query", "required": False, "schema": {"type": "string"}}],
            ),
        },
        "/capability": {
            "get": _get(
                "Remediation/assessment capability matrix", "Platform",
                "ADR 0023 — static, non-sensitive product metadata: which (format, WCAG criterion) "
                "pairs are auto/assisted/human for remediation, and auto/review/human for "
                "assessment. Not live state, but published here as the reference for what 'healthy' "
                "coverage looks like.",
                {"$ref": "#/components/schemas/CapabilityResponse"}, security=_NO_AUTH,
            ),
        },
        "/alerts/webhook": {
            "post": _get(
                "Inbound Grafana alert receiver", "Monitoring",
                "Public path, shared-secret gated (?key=ACP_ALERT_KEY). Each firing/resolved alert "
                "is appended to the immutable decision log and optionally forwarded to a downstream "
                "HITL webhook.",
                {"$ref": "#/components/schemas/AlertWebhookResponse"}, security=_ALERT_KEY_AUTH,
                responses_extra={"401": {"description": "Missing or wrong ?key="}},
            ),
        },
    },
}


@router.get("/openapi/health.json", include_in_schema=False)
def openapi_health_document() -> JSONResponse:
    """The OpenAPI 3.0 document above, served as-is. Public (see core.ALWAYS_PUBLIC) — this
    describes only already-public or intentionally-documented endpoints, never a secret."""
    return JSONResponse(HEALTH_OPENAPI_SPEC, headers=_OK_HEADERS)


_SWAGGER_UI_HTML = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>ACP — Health &amp; Heartbeat API</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css" />
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>
      window.onload = () => {
        window.ui = SwaggerUIBundle({
          url: "/openapi/health.json",
          dom_id: "#swagger-ui",
          presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
        });
      };
    </script>
  </body>
</html>
"""


@router.get("/docs/health", include_in_schema=False)
def swagger_ui_health() -> HTMLResponse:
    """Swagger UI rendering the health/heartbeat OpenAPI document, publicly reachable with no
    sign-in (see core.ALWAYS_PUBLIC)."""
    return HTMLResponse(_SWAGGER_UI_HTML, headers=_OK_HEADERS)
