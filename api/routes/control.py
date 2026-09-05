"""The control plane — the estate, aggregated, for one tenant.

"Filter by dept, user, Enterprise" from the v2 requirements. The data was always there:
`documents` carries department and owner, and #159 gave it its own tenant column so a filter
built on it can be scoped without borrowing a column that means something else.

WHY THE OWNER COMES FROM THE REQUEST, NEVER FROM A QUERY PARAM. `?owner_email=` would be a
tenant selector any caller could set, which is not a filter — it is the absence of isolation
wearing a filter's clothes. The `dept` and `owner` parameters below ARE filters: they narrow
within the caller's own estate and cannot widen past it, because the tenant is applied first and
separately by the store (`estate_by_department`'s docstring is explicit that owner_email is
required precisely so it cannot be forgotten).

The store excludes NULL-tenant rows rather than treating them as a wildcard, so an estate scanned
before #159 reports as empty here until it is backfilled. That is the intended direction: a
document nobody sees is recoverable, a document the wrong customer sees is not.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import core
from swallowed import swallowed

# Azure Container Apps replica control — optional; gracefully absent when env vars are unset.
# Required env vars: AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP, WORKER_APP_NAME. The
# container's managed identity must have Contributor on the worker app.
#
# WORKER_APP_NAME HAS NO DEFAULT, AND THAT IS THE FIX RATHER THAN AN OVERSIGHT. It used to
# default to "acp-worker", the single generic worker app that docs/worker-split.md records as
# RETIRED: production runs acp-discovery, acp-assess and acp-remediate, and NO deploy script in
# this repository sets WORKER_APP_NAME — so the default was what was in force, and it named an
# app that no longer exists.
#
# The failure was silent in the worst direction. A lookup against a missing app raises, the
# handler degrades to all-None, and the payload still reports `configured: true` — so Live
# Operations rendered a populated-looking panel of dashes, indistinguishable from "Azure Monitor
# has not reported yet". Nothing said the app name was wrong.
#
# There is deliberately no replacement default. Production has THREE worker apps and no single
# one of them is the right answer; picking one would restore the same class of quiet wrongness
# with a fresher name. Unset now means unconfigured, which the panel already states plainly.
_AZ_SUB  = os.environ.get("AZURE_SUBSCRIPTION_ID")
_AZ_RG   = os.environ.get("AZURE_RESOURCE_GROUP", "mdk-accessibility")
_AZ_APP  = os.environ.get("WORKER_APP_NAME") or None
# EVERY worker app, not one. Production runs acp-discovery (1 CPU / 2Gi), acp-assess and
# acp-remediate (2 CPU / 4Gi) — deploy/public/rightsize-production.sh — so one app's CPU, memory,
# replica count and restart count describe itself, possibly a same-sized sibling, and nothing
# else. Reading a single app is why Live Operations has to SUPPRESS those figures on two of the
# three worker services rather than show another app's numbers as theirs.
#
# WORKER_APP_NAMES is a comma-separated list and is optional: unset, this behaves exactly as
# before, reading only WORKER_APP_NAME. There is still no default app name — CLAUDE.md records
# the retired `acp-worker` default as a real incident, and a guessed list would repeat it three
# times over.
_AZ_APP_NAMES = tuple(n.strip() for n in (os.environ.get("WORKER_APP_NAMES") or "").split(",") if n.strip())


def _configured_apps() -> tuple[str, ...]:
    """The worker apps to read, resolved at CALL time rather than import time so a test (and a
    reconfigured process) sees the current values."""
    return _AZ_APP_NAMES or (_AZ_APP,)


_AZ_CONFIGURED = bool(_AZ_SUB and (_AZ_APP or _AZ_APP_NAMES))


def _az_client():
    from azure.identity import DefaultAzureCredential
    from azure.mgmt.appcontainers import ContainerAppsAPIClient
    return ContainerAppsAPIClient(DefaultAzureCredential(), _AZ_SUB)


def _monitor_client():
    """A second Azure management client, alongside _az_client() above — Azure Monitor metrics
    are a genuinely separate API surface from the Container Apps control plane, requiring a
    separate RBAC grant (the built-in "Monitoring Reader" role on the acp-worker resource or its
    resource group) on top of the Contributor grant _az_client() already needs. Deliberately
    azure-mgmt-monitor, not azure-monitor-query: that package's MetricsQueryClient was removed
    entirely in its 2.0.0 (2025-07-30) and split across two successor packages — this one predates
    that churn and follows the exact same DefaultAzureCredential + subscription_id constructor
    shape _az_client() already uses, so it's the more stable, more consistent choice."""
    from azure.identity import DefaultAzureCredential
    from azure.mgmt.monitor import MonitorManagementClient
    return MonitorManagementClient(DefaultAzureCredential(), _AZ_SUB)

router = APIRouter()


def _owner(request: Request) -> str:
    """Same helper as routes/scans.py, and deliberately the same value: the estate a person sees
    here must be the estate their scans wrote. Two different notions of "who is asking" across
    two routes is how one of them quietly stops matching."""
    return getattr(request.state, "user_email", None) or "demo"


@router.get("/control/estate")
def estate(request: Request, dept: str = "", owner: str = ""):
    """Documents per department for the caller's tenant, with an owner breakdown alongside.

    `dept` and `owner` narrow WITHIN the tenant. Empty means no narrowing — not "all tenants".
    """
    who = _owner(request)
    try:
        by_dept = core.store.estate_by_department(who, department=dept or None, owner=owner or None)
        owners = core.store.estate_owners(who)
    except Exception as e:  # noqa: BLE001 — a query failure is the caller's to see, not a 500 log
        raise HTTPException(502, f"estate query failed: {e}") from e

    total = sum(r["documents"] for r in by_dept)
    return {
        "tenant": who,
        "departments": by_dept,
        "owners": owners,
        "documents": total,
        # Stated, not implied. Every screen in this product that shows a total is expected to say
        # what the total counts (see ScopeBanner, #164), and a JSON surface is read by the same
        # people. `filtered` distinguishes "your estate is empty" from "your filter matched
        # nothing" — two very different things that look identical as a zero.
        "filters": {"department": dept or None, "owner": owner or None},
        "filtered": bool(dept or owner),
    }


# ---------------------------------------------------------------------------
# Worker replica control — scales the acp-worker Container App's minReplicas
# so the user can warm more workers before a large assessment run, then back
# off to save cost when idle.  Requires AZURE_SUBSCRIPTION_ID env var and a
# managed-identity Contributor grant on the acp-worker resource.
# ---------------------------------------------------------------------------

class ReplicaBody(BaseModel):
    min_replicas: int = Field(..., ge=1, le=5,
        description="Minimum warm replicas for the acp-worker Container App (1–5).")


@router.get("/control/workers/replicas")
def get_replicas():
    """Current min/max replica settings for the acp-worker Container App.

    Open to any authenticated user, deliberately — this is visibility into
    shared worker capacity (the "how many can pick up jobs" question every
    scan owner already sees a coarser version of via WorkerAvailability.jsx),
    not a control action. Only PATCH, below, is admin-gated: reading the
    replica count costs nothing and changing it spends real Azure money.

    Returns `configured: false` when AZURE_SUBSCRIPTION_ID is absent so the
    frontend can hide the control rather than showing a broken state.
    """
    if not _AZ_CONFIGURED:
        return {"configured": False, "min_replicas": None, "max_replicas": None}
    try:
        app = _az_client().container_apps.get(_AZ_RG, _AZ_APP)
        scale = app.properties.template.scale
        return {
            "configured": True,
            "min_replicas": scale.min_replicas,
            "max_replicas": scale.max_replicas,
            "app": _AZ_APP,
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"could not read replica config: {e}") from e


@router.patch("/control/workers/replicas")
def set_replicas(body: ReplicaBody, request: Request):
    """Set the minimum warm replicas for the acp-worker Container App.

    Admin-only and audited, matching PUT /workers' exact pattern (routes/system.py)
    — unlike GET above, this changes real Azure spend, the same class of action
    settings.worker_count already logs. Was unguarded until 2026-08-29: any
    authenticated user, not just an admin, could change the Azure replica count.

    Adjusts minReplicas only; maxReplicas stays at its current value so
    Azure's autoscaler ceiling is not affected. A higher min keeps workers
    warm before a large assessment; lower min reduces idle-container cost.
    """
    from .system import _require_admin
    _require_admin(request)
    if not _AZ_CONFIGURED:
        raise HTTPException(503, "AZURE_SUBSCRIPTION_ID not set — replica control is not available")
    try:
        client = _az_client()
        app = client.container_apps.get(_AZ_RG, _AZ_APP)
        app.properties.template.scale.min_replicas = body.min_replicas
        poller = client.container_apps.begin_create_or_update(_AZ_RG, _AZ_APP, app)
        updated = poller.result()
        scale = updated.properties.template.scale
        core.store.log_decision("admin", "settings.worker_replicas",
                                detail=f"Azure worker replicas (min) set to {scale.min_replicas}")
        return {
            "configured": True,
            "min_replicas": scale.min_replicas,
            "max_replicas": scale.max_replicas,
            "app": _AZ_APP,
        }
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"could not update replica config: {e}") from e


# ---------------------------------------------------------------------------
# Worker capacity evidence — what's actually happening on Azure right now, as
# distinct from the CONFIGURED min/max scale rule above. GET /control/workers/
# replicas answers "what is the warm floor set to"; this answers "how many
# replicas are actually up, and how loaded are they" — two different questions
# that this table's own PRD review (2026-08-29) found conflated in every
# existing surface. Needs the SAME Contributor grant as replica control, plus
# a SEPARATE "Monitoring Reader" role (or equivalent Microsoft.Insights/
# metrics/read permission) on the acp-worker resource for the metrics half.
# ---------------------------------------------------------------------------

# ── The Azure Monitor metric set ────────────────────────────────────────────────────────────
#
# REST API names, aggregations and units taken from Microsoft's own supported-metrics reference
# for Microsoft.App/containerApps (the 2026-07-31 revision of
# learn.microsoft.com/azure/azure-monitor/reference/supported-metrics/microsoft-app-containerapps-metrics),
# not from memory. That matters here more than usual: a wrong metric name is not an error — Azure
# Monitor simply returns nothing for it, which is indistinguishable from a metric that has no data
# yet, so a typo would present as "Azure has not reported this" forever.
#
# `agg` is the aggregation asked for AND the attribute the data point carries it in (Average →
# `dp.average`, Total → `dp.total`, Maximum → `dp.maximum`). Metrics are requested in ONE call per
# aggregation, because metrics.list takes a single aggregation for every name in the call.
#
# Deliberately NOT here: the Java (Jvm*) and Gpu categories. ACP's workers are Python and run no
# GPU, so those would be permanently empty rows — "not reported" is only useful when it describes
# something that could have been reported.
_AZ_METRICS = (
    # rest name,                   key,                 agg,       unit,     scale, label
    ("CpuPercentage",              "cpu_percent",       "Average", "%",      1,     "CPU utilization"),
    ("MemoryPercentage",           "memory_percent",    "Average", "%",      1,     "Memory utilization"),
    ("Replicas",                   "replicas",          "Average", "",       1,     "Replica count"),
    ("UsageNanoCores",             "cpu_cores_used",    "Average", " cores", 1e-9,  "CPU in use"),
    ("WorkingSetBytes",            "working_set_bytes", "Average", " B",     1,     "Memory working set"),
    ("ResponseTime",               "response_ms",       "Average", " ms",    1,     "Average response time"),
    ("TotalCoresQuotaUsed",        "reserved_cores",    "Maximum", " cores", 1,     "Reserved cores"),
    ("RestartCount",               "restarts",          "Total",   "",       1,     "Replica restarts"),
    ("Requests",                   "requests",          "Total",   "",       1,     "Requests"),
    ("RxBytes",                    "network_in_bytes",  "Total",   " B",     1,     "Network in"),
    ("TxBytes",                    "network_out_bytes", "Total",   " B",     1,     "Network out"),
    ("ResiliencyRequestRetries",   "retries",           "Total",   "",       1,     "Request retries"),
    ("ResiliencyConnectTimeouts",  "connect_timeouts",  "Total",   "",       1,     "Connection timeouts"),
    ("ResiliencyEjectedHosts",     "ejected_hosts",     "Total",   "",       1,     "Ejected hosts"),
)

# Azure Monitor samples these at PT1M, so 15 one-minute points is the finest real history there is
# for a 15-minute strip. The window is REPORTED in the payload rather than assumed by the reader:
# the panel used to hardcode "last 5 min" next to a figure whose window lived only in this file.
_AZ_METRIC_WINDOW_MIN = 15
_AZ_METRIC_INTERVAL = "PT1M"


def _metric_points(metric, agg: str, scale: float) -> list[dict]:
    """One Azure metric's data points as [{at, value}], newest last.

    A point with no value for this aggregation is DROPPED rather than carried as a zero — Azure
    returns gaps for minutes it has no sample for, and a zero in a gap is a measurement nobody
    took. A point with no timestamp is kept for the average and left out of the series, because
    something has to place it on a time axis and nothing here may invent that.
    """
    attr = agg.lower()
    points = []
    for series in (getattr(metric, "timeseries", None) or []):
        for dp in (getattr(series, "data", None) or []):
            value = getattr(dp, attr, None)
            if value is None:
                continue
            stamp = getattr(dp, "time_stamp", None) or getattr(dp, "timestamp", None)
            points.append({"at": _iso(stamp) if stamp is not None else None,
                           "value": round(float(value) * scale, 4)})
    points.sort(key=lambda p: (p["at"] is None, p["at"] or ""))
    return points


def _dimension_value(series) -> str | None:
    """The dimension a split time series belongs to, e.g. "2xx" for a Requests series filtered by
    statusCodeCategory.

    Dual-path for the same reason `_rev_field` is: the two Azure monitor packages disagree about
    this attribute. `azure-mgmt-monitor` (what this module uses) documents `metadatavalues` as a
    list of MetadataValue with `.name.value` and `.value`, while the newer `azure-monitor-query`
    documents `metadata_values` as a plain dict. Trying both costs nothing and avoids a shape
    mismatch becoming a silently unsplit metric.
    """
    values = getattr(series, "metadatavalues", None)
    if values:
        for item in values:
            value = getattr(item, "value", None)
            if value:
                return str(value)
    mapping = getattr(series, "metadata_values", None)
    if isinstance(mapping, dict) and mapping:
        return str(next(iter(mapping.values())))
    return None


# Requests split by response class. Azure exposes `statusCodeCategory` as a DIMENSION on the
# Requests metric rather than as separate metrics, so this is one extra call with a filter rather
# than three more names in _AZ_METRICS.
_STATUS_CLASSES = ("2xx", "3xx", "4xx", "5xx")


def _metric_timespan(now: datetime) -> str:
    """Azure-safe UTC interval for the rolling metric window.

    `azure-mgmt-monitor` forwards a literal ``+`` in an ISO offset through a query-string path
    that Azure decodes as a space. Production then receives ``...13:24:59 00:00`` and rejects the
    entire metric request as an invalid interval. UTC's ``Z`` spelling is equivalent ISO 8601 and
    contains no query-string metacharacter, so it survives that transport unchanged.
    """
    end = now.astimezone(timezone.utc)
    start = end - timedelta(minutes=_AZ_METRIC_WINDOW_MIN)
    return f"{start.strftime('%Y-%m-%dT%H:%M:%S.%fZ')}/{end.strftime('%Y-%m-%dT%H:%M:%S.%fZ')}"


def _status_split(app_id: str, now: datetime) -> dict:
    """Requests per response class over the metric window, or {} when Azure does not answer.

    A class Azure does not report is ABSENT from the result rather than zero — an app serving no
    5xx and an app whose metrics have not arrived must not render alike, which is the same rule
    every other metric here follows.
    """
    timespan = _metric_timespan(now)
    try:
        answer = _monitor_client().metrics.list(
            app_id, metricnames="Requests", aggregation="Total", timespan=timespan,
            interval=_AZ_METRIC_INTERVAL, filter="statusCodeCategory eq '*'")
    except Exception:  # noqa: BLE001 — the unsplit Requests total is still reported by _gather_metrics.
        swallowed("routes.control._status_split: splitting Requests by status class failed")
        return {}
    out: dict = {}
    for metric in (getattr(answer, "value", None) or []):
        for series in (getattr(metric, "timeseries", None) or []):
            label = (_dimension_value(series) or "").lower()
            if label not in _STATUS_CLASSES:
                continue
            total = 0.0
            seen = False
            for dp in (getattr(series, "data", None) or []):
                value = getattr(dp, "total", None)
                if value is None:
                    continue
                total += float(value)
                seen = True
            if seen:
                out[label] = round(total, 2)
    return out


def _gather_metrics(app_id: str, now: datetime) -> tuple[dict, str | None]:
    """Every metric in _AZ_METRICS, with its per-minute series, or ({}, reason) on failure.

    One call per aggregation rather than one per metric: metrics.list accepts a comma-separated
    name list but a single aggregation, so three calls cover fourteen metrics. A group that fails
    degrades only its own metrics — the reason is recorded, the other groups still return.

    A metric Azure does not answer for is present in the result with `available: false` and null
    values, never absent and never zero. The distinction the UI needs is between "nothing is
    happening" and "nobody measured", and dropping the key would erase it.
    """
    timespan = _metric_timespan(now)
    out = {key: {"label": label, "unit": unit, "aggregation": agg, "azure_metric": rest,
                 "available": False, "latest": None, "average": None, "series": []}
           for rest, key, agg, unit, _scale, label in _AZ_METRICS}
    by_agg: dict[str, dict[str, tuple]] = {}
    for rest, key, agg, unit, scale, label in _AZ_METRICS:
        by_agg.setdefault(agg, {})[rest] = (key, scale)
    reason = None
    client = _monitor_client()
    for agg, group in by_agg.items():
        try:
            answer = client.metrics.list(
                app_id, metricnames=",".join(group), aggregation=agg,
                timespan=timespan, interval=_AZ_METRIC_INTERVAL)
        except Exception as e:  # noqa: BLE001 — this group degrades; the others still run.
            status = getattr(e, "status_code", None)
            # 401/403 is the one actionable case: the identity is missing the Monitoring Reader
            # role. Recorded once for the whole response rather than per group, since one missing
            # grant fails every group identically.
            reason = "permission" if status in (401, 403) else (reason or "error")
            continue
        for metric in (getattr(answer, "value", None) or []):
            name = getattr(getattr(metric, "name", None), "value", None)
            spec = group.get(name)
            # A name this group did not ask for: ignore it rather than mapping it into whichever
            # key happens to share the name under a different aggregation.
            if spec is None:
                continue
            key, scale = spec
            points = _metric_points(metric, agg, scale)
            if not points:
                continue
            values = [p["value"] for p in points]
            out[key].update(available=True, latest=values[-1],
                            average=round(sum(values) / len(values), 4),
                            series=[p for p in points if p["at"]])
    if reason is None and not any(m["available"] for m in out.values()):
        # The calls succeeded and came back empty. CpuPercentage and MemoryPercentage are
        # Microsoft Preview metrics and are simply unpopulated on a fresh or freshly-scaled
        # resource — "we asked and got nothing" wants a different operator response from
        # "we could not ask", so it keeps its own reason.
        reason = "no_data"
    return out, reason


def _empty_capacity(configured: bool, app_name: str | None = None) -> dict:
    return {
        "configured": configured, "current_replicas": None, "min_replicas": None,
        "max_replicas": None, "cpu_percent": None, "memory_percent": None,
        "cpu_cores_per_replica": None, "memory_per_replica": None,
        "ephemeral_storage_per_replica": None, "workload_profile_name": None,
        "active_revision_name": None, "worker_app_name": app_name or _AZ_APP,
        "metrics_available": False, "measured_at": None,
        "revision_health": None, "revision_provisioning_state": None, "draining_replicas": None,
        "revision_traffic_percent": None, "metrics_unavailable_reason": None,
        # Set when the Container App lookup itself fails. Without it, a renamed, deleted or
        # mistyped WORKER_APP_NAME is reported exactly like a healthy app with no metrics yet:
        # `configured: true` and every value None. The caller cannot tell the difference, which
        # is how a panel pointed at a retired app went unnoticed.
        "app_unavailable": False,
        # Per-metric detail with each metric's own 15-minute PT1M series. Present in every shape
        # (empty here) so a caller never has to test for the key's existence before the values.
        "metrics": {}, "metrics_window_minutes": _AZ_METRIC_WINDOW_MIN,
        "metrics_interval": _AZ_METRIC_INTERVAL,
        # Per-replica and per-revision lifecycle. Empty here rather than absent, for the same
        # reason as `metrics`: a caller should never have to test for the key before the values.
        "replicas": [], "revisions": [], "replica_lifecycle": None, "scale": None,
        "status_classes": {},
        # Alert rules watching this app and which are firing. Present (unqueried) in every
        # shape so a caller never tests for the key — and so "we did not ask" is
        # distinguishable from "we asked and nothing is firing", which an absent key is not.
        "alerts": {"queried": False, "rules_total": None, "rules_enabled": None,
                   "firing": [], "rules": [], "unavailable_reason": None},
        # The health transitions Azure reported for THIS app. Not a current status — see the
        # platform-health section. Present unqueried in every shape, same reason as `alerts`.
        "resource_health": _empty_resource_health(),
        # The deployment timeline, and the steps of a deployment Azure cannot see. Present in
        # every shape so the NAMED gaps (build, image publish, smoke test, system logs) are
        # readable even on a deployment with no Azure at all — they are gaps there too.
        "deployments": _empty_deployments(),
        "revision_comparison": None,
    }


def _revision_template(rev) -> dict:
    """`image`, `cpu` and `memory` for one revision, from its own template.

    ALLOCATION, NOT USE. This is what the revision asks Azure for, which is the only per-revision
    resource figure that exists — Azure Monitor collects CpuPercentage and the rest per CONTAINER
    APP, with no revision attribution this code has verified. A "CPU went up 12% in this revision"
    figure would therefore be app-wide data wearing a revision's name.

    `env` is deliberately not read. A container's environment carries connection strings, keys and
    tokens, and this response reaches a screen any signed-in workspace user can open.
    """
    out = {"image": None, "cpu": None, "memory": None}
    template = _rev_field(rev, "template")
    containers = getattr(template, "containers", None) or []
    if not containers:
        return out
    first = containers[0]
    out["image"] = getattr(first, "image", None)
    resources = getattr(first, "resources", None)
    if resources is not None:
        out["cpu"] = getattr(resources, "cpu", None)
        out["memory"] = getattr(resources, "memory", None)
    return out

def _rev_field(rev, name, default=None):
    """The published azure-mgmt-appcontainers docs describe Revision's fields (active, replicas,
    health_state, provisioning_state, ...) as living under a nested `.properties`, matching the
    `app.properties.template.scale` shape _az_client() callers already use elsewhere in this file
    — but a WebFetch of the SDK source to confirm that nesting definitively was inconclusive
    (truncated before the relevant class). Rather than guess and risk a silent AttributeError
    swallowed by the try/except below turning into an all-None response, try nested first and
    fall back to a flattened top-level attribute — costs nothing, and whichever shape Azure
    actually returns, this finds it."""
    props = getattr(rev, "properties", None)
    if props is not None and hasattr(props, name):
        return getattr(props, name)
    return getattr(rev, name, default)


@router.get("/control/workers/capacity")
def get_capacity():
    """Azure-side capacity evidence for the worker Container Apps: how many replicas are actually
    running right now, their lifecycle, the scale rule, and recent Azure Monitor metrics — as
    opposed to GET /control/workers/replicas' CONFIGURED min/max scale rule, which says nothing
    about whether Azure has actually provisioned that many, or how loaded they are.

    Open to any authenticated user, same reasoning as GET /control/workers/replicas (#950) — this
    is read-only visibility, not a control action, and costs nothing to expose.

    READS EVERY CONFIGURED WORKER APP. `WORKER_APP_NAMES` (comma-separated) names them all;
    `WORKER_APP_NAME` remains the single-app path and the default when the list is unset. The
    top-level fields are the FIRST app's, unchanged in shape and meaning so every existing caller
    keeps working, and `apps` carries one block per app keyed by name. That is what lets each
    worker service in Live Operations show its OWN CPU, memory, replicas and restarts: production
    runs three differently sized worker apps, so a single reading is right for itself and wrong
    for the rest, which is why the UI has had to suppress those figures on two of three services.

    Graceful at every step, per app: `configured: false` when Azure isn't set up; a single
    unreachable app degrades to its own `app_unavailable` block rather than taking the others
    down; and within an app, `current_replicas` / `cpu_percent` / `revision_health` /
    `draining_replicas` individually stay None (never a fabricated 0) when their specific Azure
    call fails. UNVERIFIED against a live Azure account — the SDK response shapes here are built
    from Microsoft's published REST reference, not exercised against a real Container App; treat
    the first real deployment as this endpoint's actual proof.
    """
    if not _AZ_CONFIGURED:
        unconfigured = _empty_capacity(False)
        unconfigured["service_health"] = _empty_service_health()
        # Carried even here: the named gaps (no rate configured, no Cost Management) are gaps on
        # a deployment with no Azure too, and the rate note is how an operator learns the knob.
        unconfigured["cost"] = _cost_block({})
        return unconfigured
    # Every configured worker app, keyed by name. The top-level fields stay the FIRST app's, so
    # every existing caller of this endpoint is unaffected; `apps` is what lets each worker
    # service in Live Operations show its own figures instead of suppressing them.
    #
    # `apps` is omitted entirely when no app is NAMED — _AZ_CONFIGURED can be true in a test that
    # patches it directly, and a block keyed by a null name would be worse than none.
    apps = [name for name in _configured_apps() if name]
    blocks = {name: _capacity_for_app(name) for name in apps}
    primary = blocks.get(_AZ_APP) or (next(iter(blocks.values())) if blocks else _capacity_for_app(_AZ_APP))
    result = dict(primary)
    if blocks:
        result["apps"] = blocks
        result["worker_app_names"] = apps
    # Subscription-scoped, so it lives at the TOP LEVEL and never inside an app block: a regional
    # Azure incident is not a fault in any one worker service, and nesting it under one would read
    # as though it were. One call for the whole response, not one per app.
    result["service_health"] = _service_health(datetime.now(timezone.utc))
    # Subscription-wide too, and derived rather than measured: see the Tier 6 section. Computed
    # from the blocks already read, so it costs no extra Azure call.
    result["cost"] = _cost_block(blocks)
    return result


def _capacity_for_app(app_name: str) -> dict:
    """One container app's capacity, replicas, revisions, scale rule and metrics.

    Split out of get_capacity so the same reading can be taken for each worker app. Every failure
    mode it had is unchanged and per-app: one unreachable app degrades to its own
    `app_unavailable` block rather than taking the others down with it.

    The field-by-field contract this carries, unchanged from when it was get_capacity's own body:

        this is read-only visibility, not a control action, and costs nothing to expose.
    
        Also reports revision health: `revision_health`/`revision_provisioning_state` (the active
        revision's own Azure-reported state — "Healthy"/"Unhealthy"/"None" and "Provisioned"/
        "Provisioning"/"Failed"/etc.) and `draining_replicas` (replicas still up on OLD, non-active
        revisions — the practical signal that a rollout is mid-drain rather than done).
    
        And `revision_traffic_percent`: the active revision's own share of ingress traffic
        (`app.properties.configuration.ingress.traffic`, 0-100). This is a DIFFERENT question from
        revision_health — a revision can be perfectly Healthy and Provisioned while still receiving
        0% of traffic, which is exactly what a stuck blue-green rollout looks like (a real production
        incident on this app: the new revision came up healthy but ingress was never repointed at it,
        stranding it at 0% until someone noticed customer-facing requests were still hitting the old
        one). `active` in list_revisions() and "receiving traffic" are independently-tracked Azure
        states — this field is what closes that specific gap.
    
        And `metrics_unavailable_reason`, set whenever `metrics_available` is false: `"permission"`
        (the Azure Monitor call itself failed with a 401/403 — the identity is very likely missing
        the Monitoring Reader role this docstring already asks for), `"no_data"` (the call succeeded
        but came back with no data points — CpuPercentage/MemoryPercentage are Microsoft Preview
        metrics and can simply be unpopulated on a fresh or freshly-scaled resource, nothing wrong),
        or `"error"` (anything else — network, quota, a transient Azure fault). Before this field
        existed, all three looked identical: silence. `None` when `metrics_available` is true.
    
        Graceful at every step, matching the rest of this module: `configured: false` when Azure
        isn't set up; `current_replicas`/`cpu_percent`/`memory_percent`/`revision_health`/
        `draining_replicas` individually stay None (never a fabricated 0) if their specific Azure
        call fails — a missing Monitoring Reader grant on this identity, CpuPercentage/
        MemoryPercentage being unavailable (both are Microsoft Preview metrics as of 2026 and can be
        withdrawn or renamed), or any other partial failure degrades that one field rather than
        502ing the whole response and hiding the min/max data that DID come back. UNVERIFIED against
        a live Azure account as of this PR — the Azure SDK response shapes here are built from
        current published documentation, not exercised against a real Container App; treat the first
        real deployment as this endpoint's actual proof, not this code review.
    """
    now = datetime.now(timezone.utc)
    result = _empty_capacity(True, app_name)
    result["measured_at"] = now.isoformat()

    try:
        client = _az_client()
        app = client.container_apps.get(_AZ_RG, app_name)
        scale = app.properties.template.scale
        result["min_replicas"] = scale.min_replicas
        result["max_replicas"] = scale.max_replicas
        result["workload_profile_name"] = getattr(app.properties, "workload_profile_name", None)
        result["scale"] = _scale_block(app)
        result["active_revision_name"] = getattr(app.properties, "latest_ready_revision_name", None)
        containers = getattr(app.properties.template, "containers", None) or []
        if containers:
            resources = getattr(containers[0], "resources", None)
            if resources is not None:
                result["cpu_cores_per_replica"] = getattr(resources, "cpu", None)
                result["memory_per_replica"] = getattr(resources, "memory", None)
                result["ephemeral_storage_per_replica"] = getattr(resources, "ephemeral_storage", None)
    except Exception:  # noqa: BLE001 — can't even reach the Container App; nothing else to try
        # Say WHICH failure this is. Everything below stays None, but the caller now knows the
        # named app could not be read rather than assuming the metrics are merely late.
        result["app_unavailable"] = True
        return result

    try:
        revision = app.properties.latest_ready_revision_name
        replicas = client.container_apps_revision_replicas.list_replicas(_AZ_RG, _AZ_APP, revision)
        # Defensive about the exact collection shape: an OData-style `.value` list is the norm
        # for this SDK generation, but falling back to treating the result as directly iterable
        # costs nothing and avoids a shape mismatch turning into a silent None where a real count
        # was available.
        replica_list = getattr(replicas, "value", None)
        if replica_list is None:
            replica_list = list(replicas)
        result["current_replicas"] = len(replica_list)
    except Exception:  # noqa: BLE001 — current_replicas stays None: an honest "couldn't measure"
        # rather than a fabricated 0, same rule this codebase applies everywhere.
        swallowed("routes.control.get_capacity: listing the container-app revision replicas failed")

    try:
        metrics, reason = _gather_metrics(app.id, now)
        result["metrics"] = metrics
        # cpu_percent / memory_percent keep exactly the meaning they have always had — the AVERAGE
        # over the metric window — so every existing caller is unaffected. What changed is that
        # the window is now REPORTED (metrics_window_minutes) instead of living only in this file
        # while the panel next to the figure said "last 5 min" from a hardcoded string.
        # Requests by response class — a dimension on the Requests metric, so one extra filtered
        # call rather than three more metric names. Absent when Azure does not answer.
        result["status_classes"] = _status_split(app.id, now)
        result["cpu_percent"] = metrics["cpu_percent"]["average"]
        result["memory_percent"] = metrics["memory_percent"]["average"]
        result["metrics_available"] = result["cpu_percent"] is not None or result["memory_percent"] is not None
        # Unchanged in meaning: this flag and this reason are about UTILIZATION specifically. A
        # deployment where CPU/memory are unpopulated but Replicas and RestartCount are not is
        # real, and each metric carries its own `available` for exactly that case.
        result["metrics_unavailable_reason"] = None if result["metrics_available"] else reason
    except Exception as e:  # noqa: BLE001 — metrics_available stays False; min/max/current_replicas
        # `status_code` is the standard azure-core HttpResponseError attribute — checked via
        # getattr rather than an isinstance import, since this module only imports the Azure SDK
        # lazily inside _az_client()/_monitor_client() and every other except clause here follows
        # the same "no top-level Azure import" convention. 401/403 is the single most actionable
        # case: the identity is very likely missing the Monitoring Reader role this endpoint's
        # own module docstring already tells an operator to grant. Anything else (network, quota,
        # a genuinely transient Azure error) is not distinguishable this cheaply and stays "error"
        # rather than guessing at a category the exception doesn't actually support.
        status = getattr(e, "status_code", None)
        result["metrics_unavailable_reason"] = "permission" if status in (401, 403) else "error"
        # (already gathered above) are still returned rather than lost.

    try:
        revisions = client.container_apps_revisions.list_revisions(_AZ_RG, app_name)
        rev_list = getattr(revisions, "value", None)
        if rev_list is None:
            rev_list = list(revisions)
        draining = 0
        active_revision_name = None
        rows = []
        for rev in rev_list:
            active = bool(_rev_field(rev, "active", False))
            # "name" is a standard Azure Resource field (like id/type), not part of
            # RevisionProperties — _rev_field's nested-first lookup correctly falls through
            # to the flat rev.name here, same dual-path safety as the fields below.
            name = _rev_field(rev, "name")
            created = _rev_field(rev, "created_time")
            rows.append({
                "name": name, "active": active,
                "health": _rev_field(rev, "health_state"),
                "provisioning_state": _rev_field(rev, "provisioning_state"),
                # The platform's own error string for a Failed revision. This is where a
                # deployment failure actually surfaces — a failed replica is simply absent from
                # list_replicas, so without this a rollout that never came up reads as an app
                # that merely has fewer replicas than expected.
                "provisioning_error": _rev_field(rev, "provisioning_error"),
                "running_state": _rev_field(rev, "running_state"),
                "replicas": _rev_field(rev, "replicas"),
                "traffic_percent": _rev_field(rev, "traffic_weight"),
                "created_at": _iso(created) if created is not None else None,
                # When this revision last SERVED — the honest end of a drained revision's life,
                # and the only timestamp Azure gives for it. Absent on one that never took traffic.
                "last_active_at": _iso(_rev_field(rev, "last_active_time")),
                # The image, and the CPU/memory this revision ASKS FOR. Allocation, not use: the
                # per-revision figure Azure will actually answer for. `env` is deliberately not
                # read — a container's environment carries connection strings and keys, and this
                # lands on a screen any signed-in workspace user can open.
                **_revision_template(rev),
                # Elapsed since the revision was created. NOT a provisioning duration: Azure
                # reports when a revision was created and what state it is in now, but never when
                # it BECAME ready, so "how long did provisioning take" is not answerable from this
                # API and is not invented. For a revision still Provisioning this elapsed time is
                # the honest form of the question.
                "age_s": _age_seconds(created),
            })
            if active:
                result["revision_health"] = _rev_field(rev, "health_state")
                result["revision_provisioning_state"] = _rev_field(rev, "provisioning_state")
                active_revision_name = name
            else:
                draining += _rev_field(rev, "replicas", 0) or 0
        result["draining_replicas"] = draining
        result["revisions"] = rows
        # Per-replica lifecycle for the active revision, plus whatever is still draining on the
        # superseded ones — the two together are what "is capacity actually there" means during a
        # rollout, and the active revision alone would show a drain as though it were finished.
        replicas = []
        for row in rows:
            if row["active"] and row["name"]:
                replicas.extend(_replica_rows(client, row["name"], draining=False, app_name=app_name))
            elif row["name"] and (row["replicas"] or 0) > 0:
                replicas.extend(_replica_rows(client, row["name"], draining=True, app_name=app_name))
        result["replicas"] = replicas
        result["replica_lifecycle"] = _lifecycle_summary(replicas)
    except Exception:  # noqa: BLE001 — revision health stays None; everything gathered above
        pass           # is still returned rather than lost.
        active_revision_name = None

    try:
        # Own try/except: a separate field on `app` (already fetched above), but independently
        # absent-able — ingress can be null on a Container App with no external endpoint, and
        # the active revision's name might not have resolved above if that block partially failed.
        if active_revision_name:
            ingress = app.properties.configuration.ingress
            traffic = getattr(ingress, "traffic", None) or []
            for t in traffic:
                if getattr(t, "revision_name", None) == active_revision_name:
                    result["revision_traffic_percent"] = getattr(t, "weight", None)
                    break
    except Exception:  # noqa: BLE001 — revision_traffic_percent stays None; everything gathered
        # above is still returned rather than lost.
        swallowed("routes.control.get_capacity: reading a replica's capacity fields failed")

    # Alert rules watching this app, and which are firing. Last, and in its own block, because a
    # missing Alerts read must not cost the capacity figures that already came back — and because
    # `app.id` is what scopes it, so it needs the container-app lookup above to have succeeded.
    result["alerts"] = _alerts_for_app(getattr(app, "id", None))
    result["resource_health"] = _resource_health(getattr(app, "id", None), now)
    # Last, and after the revisions block above has run: the timeline merges Azure's own
    # operations with the revision milestones already read, so a failed activity-log call still
    # leaves a partial timeline rather than none.
    result["deployments"] = _deployments_for_app(getattr(app, "id", None), result["revisions"], now)
    # The system-log half, opt-in and off without a workspace. Scoped to the ACTIVE revision so a
    # rollout's failures are not mixed with the previous revision's.
    result["deployments"]["system_logs"] = _system_logs(app_name, result.get("active_revision_name"))
    result["revision_comparison"] = _revision_comparison(result["revisions"])

    return result


# ── Scale rules ─────────────────────────────────────────────────────────────────────────────
#
# `app.properties.template.scale` carries the KEDA configuration: minReplicas, maxReplicas,
# pollingInterval, cooldownPeriod, and the rules themselves. A ScaleRule is one of azureQueue,
# custom, http or tcp, each with its own `metadata` map (Container Apps REST reference, Scale and
# ScaleRule definitions).
#
# WHICH RULE CAUSED A GIVEN SCALE IS NOT REPORTED. Azure exposes the rules that are configured and
# the replica count over time; it does not say "rule X fired at 14:31". So this names the rules
# that COULD be responsible and never claims one was — an operator can read the thresholds against
# the metrics beside them, which is the honest form of the question.
_SECRETISH = ("connection", "secret", "key", "token", "password", "sas", "credential")


def _scrub_metadata(metadata) -> dict:
    """A scale rule's metadata minus anything that looks like a credential.

    KEDA metadata is configuration — queue names, thresholds, poll intervals — and is genuinely
    useful next to the live metric it thresholds on. But it is a free-form map an operator fills
    in, so a key that reads like a credential is dropped rather than published on a screen any
    signed-in workspace user can open. Auth blocks (`auth`, `identity`) are never included at all;
    they are references, not values, and still name secrets.
    """
    if not isinstance(metadata, dict):
        try:
            metadata = dict(metadata or {})
        except (TypeError, ValueError):
            return {}
    return {k: v for k, v in metadata.items()
            if not any(marker in str(k).lower() for marker in _SECRETISH)}


# ── Tier 5: platform health ─────────────────────────────────────────────────────────────────────
#
# TWO DIFFERENT QUESTIONS, FROM ONE API, AND THEY MUST NOT BE MERGED.
#
#   · RESOURCE HEALTH is about THIS container app: has Azure reported it unavailable or degraded?
#   · SERVICE HEALTH is about AZURE: is there an incident in the region or a planned maintenance
#     window that would affect everything in the subscription?
#
# The first is per-app and the second is subscription-wide, so attributing a regional Azure
# incident to one worker service would read as that service being at fault. They are separate
# blocks for that reason.
#
# WHAT THE ACTIVITY LOG CAN AND CANNOT ANSWER — the constraint that shapes this whole section.
# `activity_logs.list` returns health TRANSITION EVENTS, not a current status. Azure's current
# resource health lives at Microsoft.ResourceHealth/availabilityStatuses/current, a different
# provider needing a package this repo does not install. So nothing here may say "this app is
# Available". It says "the last health transition Azure reported was Available, N hours ago",
# which is a weaker claim and the only one the data supports: an app that went unavailable ninety
# seconds ago has not had its event ingested yet, and reading the older event as a current status
# would show a broken service as healthy at exactly the moment that matters most.
_HEALTH_WINDOW_HOURS = 24

# Azure's documented resource health statuses, and how each should read. "Unknown" is Azure saying
# it cannot tell — kept as its own state rather than folded into either healthy or unhealthy.
_HEALTH_STATES = {
    "available": "ok", "unavailable": "bad", "degraded": "warn", "unknown": "warn",
}

# Service Health events come in kinds with very different urgency. An "Incident" is happening now;
# "Maintenance" is scheduled; "Informational" and "Security" are advisories.
_SERVICE_EVENT_KINDS = ("Incident", "Maintenance", "Informational", "Security", "ActionRequired")

_TAG_RE = None
_SPACE_BEFORE_PUNCT = None


def _strip_html(text) -> str | None:
    """Microsoft writes Service Health `communication` as HTML, and it reaches a page any
    signed-in workspace user can open.

    Tags are removed rather than escaped-and-rendered because this is operational prose, not
    layout worth preserving, and because handing markup from an external system to a renderer is
    the kind of decision that is only safe until somebody swaps the renderer. Entities are decoded
    after stripping so `&amp;` reads as `&` rather than as itself.
    """
    if not text:
        return None
    global _TAG_RE, _SPACE_BEFORE_PUNCT
    import re as _re  # noqa: PLC0415
    if _TAG_RE is None:
        _TAG_RE = _re.compile(r"<[^>]*>")
        # A tag becomes a SPACE, not nothing, or `<div>a</div><div>b</div>` reads as "ab". The
        # cost is a space before the punctuation that followed an inline tag — "investigating ." —
        # so it is taken back out afterwards rather than paid on screen.
        _SPACE_BEFORE_PUNCT = _re.compile(r"\s+([,.;:!?%)\]])")
    import html as _html  # noqa: PLC0415
    cleaned = _html.unescape(_TAG_RE.sub(" ", str(text)))
    cleaned = _SPACE_BEFORE_PUNCT.sub(r"\1", " ".join(cleaned.split()))
    return cleaned.strip() or None


def _localized(value) -> str | None:
    """An activity-log `category`/`operation_name`/`status` is a LocalizableString with `.value`
    and `.localized_value`; `level` is a plain string. Read whichever this is."""
    if value is None:
        return None
    inner = getattr(value, "value", None)
    return str(inner) if inner is not None else (str(value) or None)


def _activity_log(client, filter_str: str, limit: int = 50) -> list:
    """Activity-log events matching a filter, newest first, capped.

    Capped because `list` is a paged iterator over a subscription-wide log and a busy subscription
    would otherwise walk thousands of rows on a read path the live map polls.
    """
    rows = []
    for event in client.activity_logs.list(filter=filter_str):
        rows.append(event)
        if len(rows) >= limit:
            break
    rows.sort(key=lambda e: getattr(e, "event_timestamp", None) or datetime.min.replace(
        tzinfo=timezone.utc), reverse=True)
    return rows


def _health_filter(now: datetime, *, category: str, resource_id: str | None = None) -> str:
    """The OData filter activity_logs.list requires. `eventTimestamp` bounds are mandatory — the
    API rejects a filter without them — and a resource id narrows a subscription-wide log to one
    app."""
    start = (now - timedelta(hours=_HEALTH_WINDOW_HOURS)).isoformat()
    parts = [f"eventTimestamp ge '{start}'", f"eventTimestamp le '{now.isoformat()}'",
             f"category eq '{category}'"]
    if resource_id:
        parts.append(f"resourceId eq '{resource_id}'")
    return " and ".join(parts)


def _empty_resource_health() -> dict:
    return {"queried": False, "status": None, "tone": None, "previous": None, "cause": None,
            "reported_at": None, "summary": None, "transitions": [],
            "window_hours": _HEALTH_WINDOW_HOURS, "unavailable_reason": None}


def _resource_health(app_id: str, now: datetime) -> dict:
    """The health transitions Azure reported for THIS app in the last 24 hours.

    `status` is the status of the MOST RECENT transition and is named `reported_at` alongside, not
    "now": see the section docstring. A resource with no transitions in the window is the normal,
    healthy case and is reported as exactly that — no events — rather than as Available, because
    this API cannot distinguish "nothing went wrong" from "nothing was ingested".
    """
    block = _empty_resource_health()
    if not app_id:
        return block
    try:
        client = _monitor_client()
        events = _activity_log(client, _health_filter(now, category="ResourceHealth",
                                                      resource_id=app_id))
    except Exception as e:  # noqa: BLE001 — the health panel degrades; capacity figures stand
        status = getattr(e, "status_code", None)
        block["unavailable_reason"] = "permission" if status in (401, 403) else "error"
        swallowed("routes.control._resource_health: reading ResourceHealth activity events failed")
        return block

    block["queried"] = True
    for event in events:
        props = getattr(event, "properties", None) or {}
        current = (props.get("currentHealthStatus") or "").strip() or None
        block["transitions"].append({
            "at": _iso(getattr(event, "event_timestamp", None)),
            "status": current,
            "previous": (props.get("previousHealthStatus") or "").strip() or None,
            # PlatformInitiated vs UserInitiated is the difference between "Azure did this to you"
            # and "a deploy did this" — the two call for opposite responses.
            "cause": (props.get("cause") or "").strip() or None,
            "summary": _strip_html(props.get("title") or props.get("summary")),
        })
    if block["transitions"]:
        latest = block["transitions"][0]
        block["status"] = latest["status"]
        block["tone"] = _HEALTH_STATES.get((latest["status"] or "").lower())
        block["previous"] = latest["previous"]
        block["cause"] = latest["cause"]
        block["reported_at"] = latest["at"]
        block["summary"] = latest["summary"]
    return block


def _empty_service_health() -> dict:
    return {"queried": False, "active": [], "window_hours": _HEALTH_WINDOW_HOURS,
            "unavailable_reason": None}


def _service_health(now: datetime) -> dict:
    """Azure's own incidents and planned maintenance affecting this SUBSCRIPTION.

    Subscription-scoped on purpose and kept out of the per-app blocks: a regional Azure incident
    is not a fault in any one worker service, and showing it inside a service's panel would read
    as though it were.
    """
    block = _empty_service_health()
    try:
        client = _monitor_client()
        events = _activity_log(client, _health_filter(now, category="ServiceHealth"), limit=25)
    except Exception as e:  # noqa: BLE001
        status = getattr(e, "status_code", None)
        block["unavailable_reason"] = "permission" if status in (401, 403) else "error"
        swallowed("routes.control._service_health: reading ServiceHealth activity events failed")
        return block

    block["queried"] = True
    seen = set()
    for event in events:
        props = getattr(event, "properties", None) or {}
        tracking = (props.get("trackingId") or "").strip() or None
        # One incident emits an event per stage (Active, Updated, Resolved). Keyed by trackingId
        # so a single incident is one row at its LATEST stage, not three rows implying three
        # incidents — and because the events are already newest-first, the first one wins.
        if tracking and tracking in seen:
            continue
        if tracking:
            seen.add(tracking)
        stage = (props.get("stage") or "").strip() or None
        block["active"].append({
            "tracking_id": tracking,
            "kind": (props.get("incidentType") or "").strip() or None,
            "stage": stage,
            # Resolved incidents are KEPT rather than filtered out. An incident that resolved
            # twenty minutes ago is the explanation for the restarts still on the timeline, and
            # dropping it leaves an operator hunting for a cause that has already been published.
            "resolved": (stage or "").lower() in ("resolved", "complete", "completed"),
            "title": _strip_html(props.get("title")),
            "summary": _strip_html(props.get("communication")),
            "at": _iso(getattr(event, "event_timestamp", None)),
            "services": _impacted_services(props.get("impactedServices")),
        })
    return block


def _impacted_services(raw) -> list:
    """`impactedServices` is a JSON STRING inside a string-valued property map. Parsed here so the
    UI never has to, and degrading to [] rather than raising when Azure changes the encoding."""
    if not raw:
        return []
    try:
        import json as _json  # noqa: PLC0415
        parsed = _json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return []
    out = []
    for entry in (parsed if isinstance(parsed, list) else []):
        if not isinstance(entry, dict):
            continue
        name = entry.get("ServiceName") or entry.get("serviceName")
        regions = entry.get("ImpactedRegions") or entry.get("impactedRegions") or []
        names = [r.get("RegionName") or r.get("regionName") for r in regions
                 if isinstance(r, dict)]
        out.append({"service": name, "regions": [n for n in names if n]})
    return out


# ── Tier 4: Container Apps system logs (Log Analytics) ──────────────────────────────────────────
#
# The half of deployment transparency Azure Monitor's metrics cannot answer: WHY a revision failed
# to come up. Image-pull errors, failed volume mounts, container crash output and revision
# provisioning failures are written to a Log Analytics workspace as ContainerAppSystemLogs_CL, not
# to the activity log and not to any metric.
#
# THIS IS OPT-IN AND OFF BY DEFAULT, like tracing. No LOG_ANALYTICS_WORKSPACE_ID, no query, no
# egress, no bill. The Deployments panel already names the gap; this is what closes it when an
# operator provisions a workspace and sets the id.
#
# IT IS NOT LIVE, AND SAYS SO. Log Analytics ingestion for Container Apps runs roughly two to
# three minutes behind. Every row is stamped with that delay in the payload, so the panel cannot
# render a three-minute-old log line beside a two-second event stream as though they were the same
# freshness — which is exactly the confusion the provenance labels exist to prevent.
#
# THE QUERY IS PARAMETERISED, NOT INTERPOLATED. A revision name reaches this code from Azure, and
# a KQL query built by string-formatting an external value is an injection waiting for the day
# Azure returns something unexpected. `azure-monitor-query` has no bind-parameter API, so the one
# value that varies is validated against a strict pattern before it is used and the query is
# refused otherwise — refusing is the safe direction, since the panel already degrades honestly.
_LOG_WORKSPACE_ENV = "LOG_ANALYTICS_WORKSPACE_ID"
_LOG_WINDOW_HOURS = 6
_LOG_INGESTION_DELAY_S = 180

# What ACP asks the workspace for. Narrow on purpose: a system-log table carries every container's
# stdout, and this panel is about deployment failures, not application output.
_LOG_LEVELS_OF_INTEREST = ("error", "warning", "critical")

# A Container Apps revision name: the app name, two dashes, a suffix. Anchored and bounded so a
# value that is not one cannot reach the query text at all.
import re as _re  # noqa: E402,PLC0415 — module-scope by design; this pattern is compiled once
_REVISION_NAME_RE = _re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _log_workspace() -> str | None:
    value = (os.environ.get(_LOG_WORKSPACE_ENV) or "").strip()
    return value or None


def _empty_system_logs(reason: str | None = None) -> dict:
    return {
        "available": False,
        "configured": _log_workspace() is not None,
        "rows": [],
        "window_hours": _LOG_WINDOW_HOURS,
        # Carried so the UI cannot present a delayed row as a live one.
        "ingestion_delay_s": _LOG_INGESTION_DELAY_S,
        "reason": reason or (
            "Container Apps system logs (image-pull failures, volume mounts, crash output) need a "
            f"Log Analytics workspace. Set {_LOG_WORKSPACE_ENV} to enable them. Log Analytics also "
            "lags by about three minutes, so these are labelled delayed, never live."),
    }


def _safe_revision(name) -> str | None:
    """A revision name that is safe to place in a KQL query, or None.

    Validated rather than escaped: the set of legal Container Apps revision names is small and
    well defined, so anything outside it is far more likely to be a shape change or an injection
    attempt than a name worth querying for. Refusing costs one panel; interpolating an unchecked
    external string into a query language costs rather more.
    """
    if not name:
        return None
    text = str(name).strip().lower()
    return text if _REVISION_NAME_RE.match(text) else None


def _system_logs(app_name: str | None, revision_name: str | None = None) -> dict:
    """Recent system-log rows for one container app, or an honest account of why there are none.

    Never raises into the capacity payload: a workspace that is misconfigured, unreachable or
    missing the Log Analytics Reader grant degrades to `available: false` with the reason, exactly
    like every other Azure read in this module.
    """
    workspace = _log_workspace()
    if not workspace:
        return _empty_system_logs()
    if not app_name:
        return _empty_system_logs("No container app is configured, so there is nothing to query.")

    revision = _safe_revision(revision_name) if revision_name else None
    if revision_name and revision is None:
        # The revision came back in a shape this code will not put in a query. Say so rather than
        # querying the whole app and labelling the result as one revision's.
        return _empty_system_logs("The active revision name was not in the expected format, so "
                                  "the log query was not run.")

    try:
        from azure.identity import DefaultAzureCredential  # noqa: PLC0415
        from azure.monitor.query import LogsQueryClient, LogsQueryStatus  # noqa: PLC0415
    except Exception:  # noqa: BLE001 — the optional dependency is simply not installed
        swallowed("routes.control._system_logs: importing azure-monitor-query failed")
        return _empty_system_logs(
            "System logs need the azure-monitor-query package, which is not installed in this "
            "deployment.")

    levels = ", ".join(f'"{level}"' for level in _LOG_LEVELS_OF_INTEREST)
    where_revision = f'| where RevisionName_s == "{revision}"' if revision else ""
    query = (
        "ContainerAppSystemLogs_CL "
        f'| where TimeGenerated > ago({_LOG_WINDOW_HOURS}h) '
        f'| where ContainerAppName_s == "{app_name}" '
        f"{where_revision} "
        f"| where tolower(Log_s) has_any ({levels}) or tolower(Reason_s) has_any ({levels}) "
        "| project TimeGenerated, Reason_s, Type_s, Log_s, RevisionName_s, ReplicaName_s "
        "| order by TimeGenerated desc | take 50")

    try:
        client = LogsQueryClient(DefaultAzureCredential())
        response = client.query_workspace(
            workspace_id=workspace, query=query,
            timespan=timedelta(hours=_LOG_WINDOW_HOURS))
    except Exception as e:  # noqa: BLE001
        status = getattr(e, "status_code", None)
        swallowed("routes.control._system_logs: querying Log Analytics failed")
        return _empty_system_logs(
            "Azure refused the Log Analytics query — the identity is missing the Log Analytics "
            "Reader role." if status in (401, 403) else
            "The Log Analytics query failed, so system logs are not available.")

    # A PARTIAL result is a real Log Analytics outcome (the query timed out or hit a row cap) and
    # must not be presented as the whole picture.
    partial = getattr(response, "status", None) == getattr(LogsQueryStatus, "PARTIAL", "PARTIAL")
    tables = getattr(response, "tables", None) or getattr(response, "partial_data", None) or []
    rows = []
    for table in tables:
        columns = [str(c) for c in (getattr(table, "columns", None) or [])]
        for raw in (getattr(table, "rows", None) or []):
            record = dict(zip(columns, raw))
            rows.append({
                "at": _iso(record.get("TimeGenerated")),
                "reason": record.get("Reason_s") or None,
                "type": record.get("Type_s") or None,
                # Container stdout. Truncated, and never widened: this table carries whatever the
                # application logged, and the panel is about deployment failures.
                "message": _truncate(record.get("Log_s")),
                "revision": record.get("RevisionName_s") or None,
                "replica": record.get("ReplicaName_s") or None,
            })
            if len(rows) >= 50:
                break

    block = _empty_system_logs()
    block.update({
        "available": True,
        "configured": True,
        "rows": rows,
        "partial": partial,
        "reason": ("Log Analytics returned a partial result, so this is not the whole picture."
                   if partial else
                   f"Delayed by roughly {_LOG_INGESTION_DELAY_S // 60} minutes — Log Analytics "
                   f"ingestion lags. Never read these as live." if rows else
                   f"No errors or warnings in the last {_LOG_WINDOW_HOURS} hours."),
    })
    return block


_LOG_MESSAGE_MAX = 400


def _truncate(value) -> str | None:
    """One log line, bounded. A container can log a megabyte in a line, and this response is
    polled by the live map."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text if len(text) <= _LOG_MESSAGE_MAX else text[:_LOG_MESSAGE_MAX] + "…"


# ── Tier 6: cost and capacity ───────────────────────────────────────────────────────────────────
#
# THE RULE THIS SECTION IS BUILT AROUND, and it is the owner's, not an inference: Azure billing
# data is NOT real-time. Cost Management refreshes roughly every four hours and Microsoft advises
# against querying it more than daily. So nothing here is ever labelled "live cost". A figure is
# either "estimated from configured capacity" — derived, never measured — or "billing data, last
# updated <t>". Those are different claims and they never share a label.
#
# NO PRICE IS HARDCODED, and this is the deliberate part. Container Apps rates vary by region, by
# plan and over time; a rate baked into this file would be wrong somewhere on the day it was
# written and wrong everywhere within a year, while still rendering as a confident currency
# figure. So the QUANTITIES are computed exactly — vCPU-hours and GiB-hours follow from the
# configured replica count and per-replica resources with nothing invented — and money appears
# only when an operator supplies their own rate through the environment. Without one, the panel
# shows the resource quantities and says a rate is needed, which is a useful answer; a made-up
# currency figure is not.
#
# WHAT NEEDS COST MANAGEMENT AND IS NOT ATTEMPTED: month-to-date actuals, forecast, and budget
# consumption. Those are measurements of real spend and cannot be derived from capacity at all.
# They are named as unavailable, with the four-hour refresh caveat attached, so that when access
# does exist nobody expects the number to be current.
_COST_VCPU_HOUR_ENV = "ACP_COST_VCPU_HOUR"
_COST_GIB_HOUR_ENV = "ACP_COST_GIB_HOUR"
_COST_CURRENCY_ENV = "ACP_COST_CURRENCY"

# Microsoft's published guidance, carried in the payload so the UI cannot forget it.
_BILLING_REFRESH_NOTE = ("Azure Cost Management refreshes roughly every four hours, and Microsoft "
                         "advises against querying it more than daily. Actuals are never live.")


def _cost_rates() -> dict:
    """The operator's own rates, or None for each. Never a default: a default price is a wrong
    price rendered with the same confidence as a right one."""
    def _rate(name):
        raw = os.environ.get(name)
        if raw is None or not str(raw).strip():
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        # A negative or zero rate is a misconfiguration, not a free deployment.
        return value if value > 0 else None

    return {
        "vcpu_hour": _rate(_COST_VCPU_HOUR_ENV),
        "gib_hour": _rate(_COST_GIB_HOUR_ENV),
        "currency": (os.environ.get(_COST_CURRENCY_ENV) or "").strip() or None,
    }


def _memory_gib(value) -> float | None:
    """Container Apps reports memory as a string like "2Gi" or "512Mi". Parsed rather than
    assumed: reading "512Mi" as 512 would overstate a replica's memory by a thousand times, and
    the resulting cost estimate would be confidently absurd."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        for suffix, factor in (("Gi", 1.0), ("Mi", 1 / 1024), ("G", 1.0), ("M", 1 / 1024)):
            if text.endswith(suffix):
                return float(text[: -len(suffix)]) * factor
        return float(text)
    except (TypeError, ValueError):
        return None


def _cost_for_app(block: dict) -> dict:
    """One app's capacity expressed as resource-hours, and as money only if a rate exists.

    EVERY QUANTITY HERE IS DERIVED FROM CONFIGURATION, not measured. `current_replicas` is what
    Azure reports running now, so the "running" figures follow the real replica count; the "floor"
    figures follow `min_replicas`, which is what the deployment pays for even when nothing is
    happening. The gap between them is the idle capacity question, and it is the one cost figure
    an operator can act on without any billing access at all.
    """
    rates = _cost_rates()
    cpu = _num_or_none(block.get("cpu_cores_per_replica"))
    gib = _memory_gib(block.get("memory_per_replica"))
    running = _num_or_none(block.get("current_replicas"))
    floor = _num_or_none(block.get("min_replicas"))
    ceiling = _num_or_none(block.get("max_replicas"))

    def _hours(replicas):
        if replicas is None:
            return {"vcpu_hours": None, "gib_hours": None}
        return {"vcpu_hours": None if cpu is None else round(replicas * cpu, 4),
                "gib_hours": None if gib is None else round(replicas * gib, 4)}

    def _money(hours):
        """Only with a rate for BOTH halves. A vCPU-only figure labelled as an hourly cost would
        silently omit memory, which is a large share of a Container Apps bill."""
        if rates["vcpu_hour"] is None or rates["gib_hour"] is None:
            return None
        if hours["vcpu_hours"] is None or hours["gib_hours"] is None:
            return None
        return round(hours["vcpu_hours"] * rates["vcpu_hour"]
                     + hours["gib_hours"] * rates["gib_hour"], 4)

    now_hours, floor_hours, ceiling_hours = _hours(running), _hours(floor), _hours(ceiling)
    hourly, floor_cost = _money(now_hours), _money(floor_hours)
    return {
        "app": block.get("worker_app_name"),
        "cpu_cores_per_replica": cpu,
        "memory_gib_per_replica": gib,
        "replicas_running": running,
        "replicas_floor": floor,
        "replicas_ceiling": ceiling,
        "running": now_hours,
        "floor": floor_hours,
        "ceiling": ceiling_hours,
        # Money, only with the operator's own rates. None is the honest answer otherwise.
        "estimated_hourly": hourly,
        "estimated_daily": None if hourly is None else round(hourly * 24, 4),
        "estimated_floor_hourly": floor_cost,
        # What is being paid for while nothing is happening. Derivable with no billing access.
        "idle_vcpu_hours": None if (floor_hours["vcpu_hours"] is None) else floor_hours["vcpu_hours"],
        "currency": rates["currency"],
        "rate_configured": rates["vcpu_hour"] is not None and rates["gib_hour"] is not None,
    }


def _num_or_none(value):
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _cost_block(blocks: dict) -> dict:
    """The whole subscription's estimate, per app and totalled, plus the actuals it cannot supply.

    `basis` and `billing_note` travel in the payload rather than living in the UI, so the caveat
    cannot be dropped by a frontend change and the label cannot drift from what it describes.
    """
    rates = _cost_rates()
    apps = [_cost_for_app(block) for block in (blocks or {}).values()]

    def _total(field, sub=None):
        values = [(a[field][sub] if sub else a[field]) for a in apps]
        present = [v for v in values if v is not None]
        # A total over a partial set would understate the bill while looking complete. All or
        # nothing, and the caller can see which apps are missing.
        return round(sum(present), 4) if present and len(present) == len(values) else None

    return {
        "apps": apps,
        "basis": "Estimated from configured capacity",
        "rate_configured": rates["vcpu_hour"] is not None and rates["gib_hour"] is not None,
        "rate_source": "environment" if (rates["vcpu_hour"] is not None) else None,
        "currency": rates["currency"],
        "rate_note": (None if (rates["vcpu_hour"] is not None and rates["gib_hour"] is not None)
                      else f"No rate is configured, so capacity is shown as resource-hours rather "
                           f"than money. Set {_COST_VCPU_HOUR_ENV} and {_COST_GIB_HOUR_ENV} (and "
                           f"optionally {_COST_CURRENCY_ENV}) to your own Container Apps rates — "
                           f"none is assumed, because a rate baked in here would be wrong for "
                           f"some region on the day it was written."),
        "total_vcpu_hours": _total("running", "vcpu_hours"),
        "total_gib_hours": _total("running", "gib_hours"),
        "total_floor_vcpu_hours": _total("floor", "vcpu_hours"),
        "estimated_hourly": _total("estimated_hourly"),
        "estimated_daily": _total("estimated_daily"),
        # NOT DERIVABLE. Real spend is a measurement, and capacity cannot stand in for it.
        "actuals": {
            "available": False,
            "reason": "Month-to-date spend, forecast and budget consumption come from Azure Cost "
                      "Management, which is not configured for this deployment.",
            "billing_note": _BILLING_REFRESH_NOTE,
            "month_to_date": None, "forecast": None, "budget_percent": None,
            "last_updated": None,
        },
        # ACP-side spend nobody instruments yet. Named so it is a known gap, not an oversight.
        "not_instrumented": [
            {"item": "AI cost per assessment or remediation",
             "reason": "Model spend is not metered per job in ACP, so a per-document AI figure "
                       "would be a guess divided by a count."},
            {"item": "Storage and network contribution",
             "reason": "Blob and egress charges are billed per subscription, not per worker app, "
                       "and are not attributable to a service from capacity alone."},
        ],
    }


# ── Tier 4: deployment transparency ─────────────────────────────────────────────────────────────
#
# WHAT THIS CAN AND CANNOT SEE, stated up front because the gaps are the honest part.
#
# Azure knows what it did to the platform: a revision was created at T, it took traffic, an old
# one drained, a write operation succeeded or failed. That is a real deployment timeline and it is
# what this section builds, from the Administrative activity log plus the revisions themselves.
#
# Azure does NOT know about the half of a deployment that happens before it:
#
#   · build started        · image published to the registry        · smoke test passed
#
# Those live in the CI workflow and the container registry. They are NAMED as not reported rather
# than omitted, because a timeline that silently begins at "revision created" reads as though the
# deployment began there — and the most common real failure (a build that never produced an image)
# would show up as no timeline at all, which is indistinguishable from no deployment.
#
# THE SYSTEM LOG FEED IS NOT HERE EITHER. Image-pull errors, failed volume mounts and container
# crash output live in Log Analytics (ContainerAppSystemLogs_CL), which needs a workspace, its own
# RBAC and carries roughly a three-minute ingestion delay. No workspace is configured, so the gap
# is reported as a gap.
_DEPLOY_WINDOW_HOURS = 24

# Activity-log operations worth a timeline row, mapped to what actually happened. Anything else
# under Administrative (a tag write, a diagnostic-setting change) is noise on a deployment
# timeline and is dropped rather than rendered as a deploy.
_DEPLOY_OPERATIONS = {
    "microsoft.app/containerapps/write": "Container app updated",
    "microsoft.app/containerapps/revisions/activate/action": "Revision activated",
    "microsoft.app/containerapps/revisions/deactivate/action": "Revision deactivated",
    "microsoft.app/containerapps/revisions/restart/action": "Revision restarted",
    "microsoft.app/containerapps/delete": "Container app deleted",
}

# The steps a Container Apps deployment has that Azure cannot report, and where each one lives.
# Carried in the payload rather than written into the UI so the reason travels with the gap.
_DEPLOY_STEPS_NOT_REPORTED = (
    {"step": "Build started",
     "reason": "Runs in the CI workflow, not in Azure. Container Apps sees a deployment only once "
               "an image already exists."},
    {"step": "Image published",
     "reason": "Happens in the container registry. The revision below names the image it runs, "
               "which is the same fact at the other end."},
    {"step": "Smoke test passed",
     "reason": "Runs in the CI workflow after the rollout. Azure reports whether the revision "
               "provisioned, never whether it works."},
)


def _empty_deployments() -> dict:
    return {"queried": False, "events": [], "window_hours": _DEPLOY_WINDOW_HOURS,
            "not_reported": list(_DEPLOY_STEPS_NOT_REPORTED),
            # ONE source for this block. It used to be written out here as well, and the two
            # copies had already drifted: this one had no `configured` flag, so an operator who
            # set the workspace would still be told it was not configured.
            "system_logs": _empty_system_logs(),
            "unavailable_reason": None}


def _deploy_events_from_activity(client, app_id: str, now: datetime) -> list:
    """Deployment operations Azure recorded against this app in the window.

    THE CALLER IS DELIBERATELY NOT INCLUDED. An activity-log `caller` is a person's UPN or a
    service principal id, and this response reaches a screen any signed-in workspace user can
    open. "What happened and when" is the operational question; "who did it" is an audit question
    with a different audience, and the activity log itself is where that belongs.
    """
    rows = []
    for event in _activity_log(client, _health_filter(now, category="Administrative",
                                                      resource_id=app_id), limit=60):
        operation = (_localized(getattr(event, "operation_name", None)) or "").lower()
        label = _DEPLOY_OPERATIONS.get(operation)
        if not label:
            continue
        status = _localized(getattr(event, "status", None))
        rows.append({
            "at": _iso(getattr(event, "event_timestamp", None)),
            "kind": "operation",
            "label": label,
            # Started / Accepted / Succeeded / Failed. A FAILED write is the row that matters most
            # on this timeline and is never filtered out.
            "status": status,
            "failed": (status or "").strip().lower() in ("failed", "failure"),
            "detail": _strip_html(_localized(getattr(event, "description", None))),
        })
    return rows


def _deploy_events_from_revisions(revisions: list) -> list:
    """Revision milestones, from the revisions already read for this app.

    Two timestamps per revision and no more, because those are the two Azure actually records.
    WHEN A REVISION BECAME READY IS NOT ONE OF THEM — Azure reports that a revision was created
    and what state it is in now, never when it finished provisioning. So "first replica ready" is
    absent from this timeline rather than approximated from created_time, which would report a
    slow rollout as an instant one.
    """
    rows = []
    for rev in revisions or []:
        name = rev.get("name")
        if rev.get("created_at"):
            rows.append({
                "at": rev["created_at"], "kind": "revision", "label": f"Revision {name} created",
                "status": rev.get("provisioning_state"),
                "failed": (rev.get("provisioning_state") or "").lower() == "failed",
                # The platform's own error string is where a failed rollout actually surfaces.
                "detail": rev.get("provisioning_error") or rev.get("image"),
            })
        # Only for a revision that is no longer active: on the live one this is "a moment ago" and
        # would sit on the timeline restating the present.
        if rev.get("last_active_at") and not rev.get("active"):
            rows.append({
                "at": rev["last_active_at"], "kind": "revision",
                "label": f"Revision {name} last served traffic",
                "status": None, "failed": False, "detail": None,
            })
    return rows


def _deployments_for_app(app_id: str, revisions: list, now: datetime) -> dict:
    """The deployment timeline: Azure's own operations merged with revision milestones.

    Merged and sorted newest-first so one list answers "what changed here recently", rather than
    making a reader interleave two. Revision milestones survive an activity-log failure, because
    they come from a call that already succeeded — a partial timeline that says so beats none.
    """
    block = _empty_deployments()
    block["events"] = _deploy_events_from_revisions(revisions)
    if not app_id:
        # Revision milestones still stand: they came from the revisions list, not from this call.
        block["events"].sort(key=lambda r: r["at"] or "", reverse=True)
        return block
    try:
        client = _monitor_client()
        block["events"].extend(_deploy_events_from_activity(client, app_id, now))
        block["queried"] = True
    except Exception as e:  # noqa: BLE001 — the revision milestones above are still returned
        status = getattr(e, "status_code", None)
        block["unavailable_reason"] = "permission" if status in (401, 403) else "error"
        swallowed("routes.control._deployments_for_app: reading Administrative activity events "
                  "failed")
    block["events"].sort(key=lambda r: r["at"] or "", reverse=True)
    return block


def _revision_comparison(revisions: list) -> dict:
    """Current versus the one before it, and whether a rollback target exists.

    WHAT IS COMPARED IS WHAT AZURE ATTRIBUTES PER REVISION: the image, the CPU and memory the
    revision ASKS FOR, its replica count, its traffic share and its health.

    WHAT IS NOT, and this is the point. Error rate, latency and actual CPU or memory USE are
    collected by Azure Monitor per CONTAINER APP. This code does not attempt to split them by
    revision, and the reason is not that the split is hard: a dimension filter that Azure ignored
    rather than rejected would return app-wide data wearing one revision's name — a regression
    attributed to a deploy that did not cause it, which is worse than no comparison. So those are
    named as not compared, with the reason, and the metrics panel above keeps showing them for
    the app as a whole, which is what they actually describe.
    """
    rows = [r for r in (revisions or []) if r.get("name")]
    current = next((r for r in rows if r.get("active")), None)
    # Newest first among the rest. `created_at` is an ISO string, so a lexical sort is a
    # chronological one — and a revision with no timestamp sorts last rather than first.
    others = sorted([r for r in rows if r is not current],
                    key=lambda r: r.get("created_at") or "", reverse=True)
    previous = others[0] if others else None

    changes = []
    if current and previous:
        for field, label in (("image", "Image"), ("cpu", "CPU requested"),
                             ("memory", "Memory requested")):
            before, after = previous.get(field), current.get(field)
            if before != after:
                changes.append({"field": field, "label": label,
                                "from": before, "to": after})

    # A rollback target is a revision that still EXISTS and provisioned successfully. A Failed one
    # is not a way back, and saying it is would send an operator to a revision that never ran.
    rollback = None
    for candidate in others:
        if (candidate.get("provisioning_state") or "").lower() == "provisioned":
            rollback = {"name": candidate["name"], "image": candidate.get("image"),
                        "created_at": candidate.get("created_at"),
                        "replicas": candidate.get("replicas")}
            break

    return {
        "current": current, "previous": previous, "changes": changes,
        "rollback": rollback,
        "rollback_reason": None if rollback else (
            "No earlier revision is still provisioned, so there is nothing to roll back to from "
            "the platform's side." if rows else
            "No revisions were read for this app."),
        "not_compared": [
            {"field": "error_rate", "label": "Error rate",
             "reason": "Azure Monitor collects requests per container app, not per revision."},
            {"field": "latency", "label": "Response time",
             "reason": "Collected per container app. A per-revision figure would be app-wide "
                       "data under one revision's name."},
            {"field": "cpu_used", "label": "CPU actually used",
             "reason": "Per app, not per revision. The CPU compared above is what the revision "
                       "requests, not what it consumes."},
            {"field": "memory_used", "label": "Memory actually used",
             "reason": "Per app, not per revision, for the same reason."},
        ],
    }


# ── Tier 5: active alerts ───────────────────────────────────────────────────────────────────────
#
# Azure severity is an integer 0-4 and reads backwards to most people: 0 is the WORST. Rendered as
# a bare number next to a rule name it is routinely misread as a priority where higher means more
# urgent, so it never leaves this module without its word.
_ALERT_SEVERITY = {0: "Critical", 1: "Error", 2: "Warning", 3: "Informational", 4: "Verbose"}

# Azure reports a metric alert's current state as one of these strings. Anything else — including
# a state Azure adds later — is carried through as-is rather than being coerced into "resolved",
# because the safe direction to be wrong in is "I don't know", never "it's fine".
_ALERT_FIRING = "fired"
_ALERT_RESOLVED = "resolved"


def _alert_rules(client, app_id: str) -> list:
    """Metric alert rules in the resource group whose scopes include this container app.

    Scoped by resource id rather than by name: a rule can be written against the subscription or
    the resource group and still cover this app, and a rule named after this app can be scoped
    somewhere else entirely. The id is the only thing that says what a rule actually watches.
    """
    wanted = (app_id or "").lower()
    rules = []
    for rule in client.metric_alerts.list_by_resource_group(_AZ_RG):
        scopes = [str(s).lower() for s in (getattr(rule, "scopes", None) or [])]
        if wanted and wanted in scopes:
            rules.append(rule)
    return rules


def _alert_state(client, rule_name: str) -> tuple[str | None, str | None]:
    """(state, since) for one rule — "fired", "resolved", whatever else Azure says, or None.

    None means the status call did not answer, which is NOT the same as resolved and must not be
    rendered as one; the caller keeps it as "unknown".
    """
    try:
        collection = client.metric_alerts_status.list(_AZ_RG, rule_name)
    except Exception:  # noqa: BLE001 — one rule's status failing must not hide the other rules
        swallowed(f"routes.control._alert_state: reading the status of metric alert "
                  f"{rule_name!r} failed")
        return None, None
    rows = getattr(collection, "value", None) or []
    # A rule split by dimensions has one status row per dimension combination. FIRING WINS: if any
    # one combination is fired the rule is firing, because a rule that is fired for a single worker
    # app and resolved for four others is a live incident, and taking the first row (or the last)
    # would report it as whichever happened to be ordered first.
    state, since = None, None
    for row in rows:
        props = getattr(row, "properties", None)
        row_state = getattr(props, "status", None) if props is not None else None
        row_at = _iso(getattr(props, "timestamp", None)) if props is not None else None
        if row_state is None:
            continue
        if str(row_state).strip().lower() == _ALERT_FIRING:
            return str(row_state).strip().lower(), row_at
        if state is None:
            state, since = str(row_state).strip().lower(), row_at
    return state, since


def _alert_condition(rule) -> str | None:
    """A one-line reading of what the rule thresholds on, or None when the criteria shape is one
    this does not recognise. Never invented: an unrecognised criteria block yields None and the
    UI says the condition is not reported rather than describing a threshold nobody can confirm."""
    criteria = getattr(rule, "criteria", None)
    all_of = getattr(criteria, "all_of", None) or []
    parts = []
    for c in all_of:
        metric = getattr(c, "metric_name", None)
        op = getattr(c, "operator", None)
        threshold = getattr(c, "threshold", None)
        agg = getattr(c, "time_aggregation", None)
        if metric is None or threshold is None:
            continue
        lead = f"{agg} {metric}" if agg else str(metric)
        parts.append(f"{lead} {op or '?'} {threshold}")
    return " and ".join(parts) or None


def _alerts_for_app(app_id: str) -> dict:
    """Which alert rules watch this app, and which of them are firing right now.

    THE DISTINCTION THIS BLOCK EXISTS TO PRESERVE: an empty firing list means "nothing is firing"
    only when something is actually watching. With no rules configured — which is this deployment's
    state today — an empty list means "nobody is watching", and the two must never render alike.
    A green panel over an unmonitored service is worse than no panel, because it answers the
    question the operator actually asked ("is this healthy?") with evidence that does not exist.
    So `rules_total` is reported beside `firing`, and 0 is a finding rather than a pass.

    Every field degrades to None rather than to a number nobody measured, matching the rest of
    this module.
    """
    block = {
        "queried": False,
        "rules_total": None,
        "rules_enabled": None,
        "firing": [],
        "rules": [],
        "unavailable_reason": None,
    }
    if not app_id:
        return block
    try:
        client = _monitor_client()
        rules = _alert_rules(client, app_id)
    except Exception as e:  # noqa: BLE001 — the alerts panel degrades; the rest of capacity stands
        status = getattr(e, "status_code", None)
        block["unavailable_reason"] = "permission" if status in (401, 403) else "error"
        swallowed("routes.control._alerts_for_app: listing metric alert rules failed")
        return block

    block["queried"] = True
    block["rules_total"] = len(rules)
    block["rules_enabled"] = sum(1 for r in rules if getattr(r, "enabled", None) is not False)
    for rule in rules:
        name = getattr(rule, "name", None)
        enabled = getattr(rule, "enabled", None)
        severity = getattr(rule, "severity", None)
        # A DISABLED rule is not asked for its status. Azure keeps returning the last status a
        # disabled rule had, so a rule switched off while fired would keep reporting "fired"
        # forever — an alert nobody can clear, on a condition nobody is evaluating.
        state, since = (_alert_state(client, name) if (name and enabled is not False) else (None, None))
        row = {
            "name": name,
            "description": getattr(rule, "description", None) or None,
            "severity": severity,
            "severity_label": _ALERT_SEVERITY.get(severity),
            "enabled": enabled,
            "state": state or "unknown",
            "since": since,
            "condition": _alert_condition(rule),
            "window": str(getattr(rule, "window_size", None) or "") or None,
            "frequency": str(getattr(rule, "evaluation_frequency", None) or "") or None,
        }
        block["rules"].append(row)
        if row["state"] == _ALERT_FIRING:
            block["firing"].append(row)
    # Worst first: severity 0 is Critical, so a plain ascending sort puts the thing to look at
    # first. A rule with no severity sorts last rather than as 0, which would promote an unknown
    # to the top of the list.
    block["firing"].sort(key=lambda r: (r["severity"] is None, r["severity"]))
    return block


def _scale_block(app) -> dict | None:
    """The scale rule as configured, or None when it cannot be read."""
    try:
        scale = app.properties.template.scale
    except AttributeError:
        return None
    rules = []
    for rule in (getattr(scale, "rules", None) or []):
        # One of these four is populated per rule; the populated one names the trigger type.
        for kind in ("azure_queue", "custom", "http", "tcp"):
            body = getattr(rule, kind, None)
            if body is None:
                continue
            rules.append({
                "name": getattr(rule, "name", None),
                "type": getattr(body, "type", None) or kind.replace("_", ""),
                "metadata": _scrub_metadata(getattr(body, "metadata", None)),
                # A queue rule carries its threshold as a field rather than in metadata.
                "queue_length": getattr(body, "queue_length", None),
                "queue_name": getattr(body, "queue_name", None),
            })
            break
    return {
        "min_replicas": getattr(scale, "min_replicas", None),
        "max_replicas": getattr(scale, "max_replicas", None),
        "polling_interval_s": getattr(scale, "polling_interval", None),
        "cooldown_period_s": getattr(scale, "cooldown_period", None),
        "rules": rules,
        # Named rather than omitted: an empty rules list means the app scales only between min and
        # max with no trigger, which is a real configuration and a different answer from "the
        # rules could not be read".
        "rules_reported": True,
        # Azure reports the rules and the replica count over time, never which rule fired when.
        "attribution": "Azure Container Apps does not report which scale rule caused a given "
                       "change; the rules below are the ones that could be responsible.",
    }


# ── Replica lifecycle ───────────────────────────────────────────────────────────────────────
#
# WHAT AZURE ACTUALLY REPORTS, which is less than the lifecycle a reader wants.
#
# `Replica.properties.runningState` is a three-value enum — Running, NotRunning, Unknown
# (ContainerAppReplicaRunningState in azure-mgmt-appcontainers). It does not distinguish a replica
# that is allocating from one that is starting from one that is serving. What DOES distinguish
# them is the container level: each `ReplicaContainer` carries `started` and `ready` booleans plus
# `restartCount` and a `runningStateDetails` string. So the finer states below are DERIVED from
# those two booleans and named for what they are, rather than read off a field that does not
# exist.
#
# Two states in the operator's wish list are NOT derivable here and are not faked:
#
#   · REQUESTED — the gap between a scale rule asking for a replica and a replica existing. Azure
#     exposes no pending-replica list; an unsatisfied request is visible only as replicas < the
#     scale rule's target, which is a different statement and is reported separately.
#   · FAILED — a replica that failed and was removed is simply absent from list_replicas. What IS
#     reported is the REVISION's provisioningState ("Failed") and its provisioningError string,
#     which is where a failure actually surfaces, so that is what the revision rows carry.
#
# Verified against Microsoft's Container Apps REST reference (Revision and Replica definitions,
# 2025-01-01 and later) rather than assumed — the same reason _AZ_METRICS names are quoted from
# the metrics reference.
_REPLICA_STATES = ("ready", "starting", "allocating", "not_running", "draining", "unknown")


def _replica_state(replica, draining: bool) -> tuple[str, str | None]:
    """(state, detail) for one replica, derived from what Azure reports about its containers."""
    running = str(_rev_field(replica, "running_state", "") or "").strip().lower()
    detail = _rev_field(replica, "running_state_details")
    containers = _rev_field(replica, "containers", None) or []
    # A replica still up on a superseded revision is draining, whatever its own running state:
    # that is the practical signal a rollout is mid-drain rather than done, and it is a fact about
    # which revision it belongs to, not about the replica's health.
    if draining:
        return "draining", detail
    if running in ("notrunning", "not_running"):
        return "not_running", detail
    if running == "unknown" or not running:
        return "unknown", detail
    if containers:
        # `ready` is the container reporting it can take work; `started` is only that the process
        # launched. Started-but-not-ready is the startup window a reader is looking for when they
        # ask why capacity has not arrived yet.
        if all(bool(_rev_field(c, "ready", False)) for c in containers):
            return "ready", detail
        if any(bool(_rev_field(c, "started", False)) for c in containers):
            return "starting", detail
        return "allocating", detail
    return "ready", detail


def _replica_rows(client, revision_name: str, draining: bool = False,
                  app_name: str | None = None) -> list[dict]:
    """Per-replica lifecycle rows for one revision. Never raises: a revision whose replicas cannot
    be listed contributes nothing rather than failing the whole reading."""
    try:
        answer = client.container_apps_revision_replicas.list_replicas(
            _AZ_RG, app_name or _AZ_APP, revision_name)
    except Exception:  # noqa: BLE001
        swallowed("routes.control._replica_rows: listing replicas for a revision failed")
        return []
    replicas = getattr(answer, "value", None)
    if replicas is None:
        try:
            replicas = list(answer)
        except Exception:  # noqa: BLE001
            return []
    rows = []
    for replica in replicas:
        state, detail = _replica_state(replica, draining)
        created = _rev_field(replica, "created_time")
        containers = _rev_field(replica, "containers", None) or []
        # Summed across containers, because a replica's restarts are its containers' restarts and
        # a reader asking "has this replica been crashing" means the pod, not one process in it.
        restarts = [int(_rev_field(c, "restart_count", 0) or 0) for c in containers]
        rows.append({
            "name": getattr(replica, "name", None) or _rev_field(replica, "name"),
            "revision": revision_name,
            "state": state,
            "state_detail": detail,
            "created_at": _iso(created) if created is not None else None,
            "age_s": _age_seconds(created),
            "restarts": sum(restarts) if restarts else None,
            "containers_ready": sum(1 for c in containers if _rev_field(c, "ready", False)),
            "containers": len(containers),
            # The image the replica is actually running, which is the version question a
            # deployment reader is really asking. Absent when Azure does not report it.
            "image": next((_rev_field(c, "image", None) for c in containers
                           if _rev_field(c, "image", None)), None),
        })
    return rows


def _age_seconds(value) -> int | None:
    """Seconds since an Azure timestamp, or None. Tolerates a datetime, an ISO string, or a
    malformed value — never raises and never returns a fabricated 0."""
    if value is None:
        return None
    try:
        if isinstance(value, str):
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            stamp = value
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - stamp).total_seconds()))
    except (AttributeError, TypeError, ValueError):
        return None


def _lifecycle_summary(replicas: list[dict]) -> dict:
    """The replica counts by state, with the two states Azure does not report named rather than
    silently missing — a reader counting six states and seeing four should be told why."""
    counts = {state: 0 for state in _REPLICA_STATES}
    for row in replicas:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    return {
        "counts": counts,
        "total": len(replicas),
        # Not zero: Azure exposes no pending-replica list and a failed replica is simply absent
        # from list_replicas. Reported as unavailable so the UI can say so instead of showing a
        # confident 0 for states it never measured.
        "unreported_states": ["requested", "failed"],
        "unreported_reason": "Azure Container Apps does not list pending or removed replicas; a "
                             "failure surfaces on the revision's provisioningState and "
                             "provisioningError instead.",
    }


# ── One Azure reading, shared by every SSE client ───────────────────────────────────────────
#
# The live map's SSE stream builds a frame every two seconds, and there is one stream per open
# Live Operations tab. Calling Azure Monitor on that cadence, per client, would be both slow (the
# metrics API is a network round trip on the critical path of a frame) and a good way to meet its
# rate limit; it also answers PT1M metrics, so asking more than once a minute cannot return
# anything new anyway.
#
# So the reading is taken at most once per TTL and shared. `measured_at` inside the payload says
# when it was actually taken, which is what lets the UI label the value's freshness honestly
# rather than implying the age of the frame it arrived in.
_CAPACITY_TTL_S = float(os.environ.get("WORKER_CAPACITY_TTL_S") or 30)
_capacity_lock = threading.Lock()
_capacity_cache: dict = {"at": 0.0, "value": None}


def cached_capacity(ttl_s: float | None = None) -> dict | None:
    """The most recent Azure capacity reading, refreshed at most once per `ttl_s`.

    Returns None only if the read itself raised — callers treat that as "no Azure block this
    frame" and keep whatever they last had, rather than replacing a real reading with an empty
    one. An UNCONFIGURED deployment is not that case: it returns the ordinary
    `configured: false` payload, because "Azure is not set up" is an answer the UI shows.

    Thread-safe because the SSE route calls it from asyncio.to_thread, so several event loops can
    land here at once. The lock is held across the refresh deliberately: the alternative lets N
    clients each start their own Azure call on the same expiry.
    """
    ttl = _CAPACITY_TTL_S if ttl_s is None else ttl_s
    now = time.monotonic()
    with _capacity_lock:
        cached = _capacity_cache["value"]
        if cached is not None and (now - _capacity_cache["at"]) < ttl:
            return cached
        try:
            value = get_capacity()
        except Exception:  # noqa: BLE001 — never take the live map down for a capacity read.
            swallowed("routes.control.cached_capacity: refreshing the Azure capacity reading failed")
            return cached
        _capacity_cache.update(at=now, value=value)
        return value


def _iso(v):
    """`created_time` on a Revision is documented as a datetime by the Container Apps REST API
    schema, but this module's own `_rev_field` docstring above already flags that the SDK's exact
    attribute shapes here are unverified against a live account — so accept either a datetime
    (call .isoformat()) or something already string-shaped, rather than assume one and let an
    AttributeError turn a working field into a silently-empty one."""
    if v is None:
        return None
    isoformat = getattr(v, "isoformat", None)
    return isoformat() if callable(isoformat) else str(v)


@router.get("/control/workers/revisions")
def get_revisions():
    """The FULL revision history for the acp-worker Container App — every revision
    list_revisions() returns, not just the active one GET /control/workers/capacity extracts a
    handful of fields from. Answers "what got deployed, when, and is it healthy" — currently
    invisible anywhere in the app; an operator has to open the Azure portal to see it.

    Open to any authenticated user, same reasoning as the other /control/workers/* endpoints —
    read-only visibility, not a control action.

    Each entry in `revisions`: `name`, `active` (bool — is this the one new traffic defaults to),
    `health_state`/`provisioning_state`/`running_state` (Azure's own per-revision status strings),
    `replicas` (how many are up on THIS revision specifically — draining old revisions show a
    nonzero count here after a rollout, the same signal `draining_replicas` on the capacity
    endpoint sums across all of them), `traffic_percent` (this revision's own share of ingress,
    from the SAME `app.properties.configuration.ingress.traffic` list GET /control/workers/
    capacity reads — but matched against every revision here, not just the active one, since a
    canary or blue-green rollout can split traffic across two revisions at once and that split is
    exactly what this view exists to show), and `created_time` (ISO 8601, or null if the SDK
    field is absent — see _iso() above).

    Sorted newest-first by created_time; revisions Azure returns with no created_time (should not
    happen in practice, but nothing here assumes it can't) sort last rather than crash the sort.

    Graceful at every step, matching the rest of this module: `configured: false` when Azure
    isn't set up; an empty `revisions: []` (never a fabricated entry) if the Container App or the
    revision list itself can't be reached; a per-revision `traffic_percent` of null if ingress
    data is unavailable, rather than losing the whole revision. UNVERIFIED against a live Azure
    account, same caveat as GET /control/workers/capacity — treat the first real deployment as
    this endpoint's actual proof.
    """
    if not _AZ_CONFIGURED:
        return {"configured": False, "revisions": []}

    try:
        client = _az_client()
        app = client.container_apps.get(_AZ_RG, _AZ_APP)
    except Exception:  # noqa: BLE001 — can't even reach the Container App; nothing else to try
        return {"configured": True, "revisions": []}

    traffic_by_revision = {}
    try:
        ingress = app.properties.configuration.ingress
        for t in (getattr(ingress, "traffic", None) or []):
            name = getattr(t, "revision_name", None)
            if name:
                traffic_by_revision[name] = getattr(t, "weight", None)
    except Exception:  # noqa: BLE001 — every revision's traffic_percent stays None below;
        # the revision list itself is unaffected.
        swallowed("routes.control.get_revisions: reading a revision's fields failed")

    try:
        # _AZ_APP, not app_name: this endpoint reads the single named app, unlike get_capacity
        # which reads every app in _configured_apps(). It briefly said `app_name` — a global
        # rename that reached a scope with no such variable — and the NameError landed in the
        # except below as an empty revision list. A bare except turns a typo into "Azure returned
        # nothing", which is why the tests below assert the CONTENT and not just the status.
        revisions = client.container_apps_revisions.list_revisions(_AZ_RG, _AZ_APP)
        rev_list = getattr(revisions, "value", None)
        if rev_list is None:
            rev_list = list(revisions)
    except Exception:  # noqa: BLE001 — no revision list to report; configured stays true so the
        return {"configured": True, "revisions": []}  # caller can tell "asked, got nothing" from
                                                        # "never asked" (same as capacity's fields).

    out = []
    for rev in rev_list:
        name = _rev_field(rev, "name")
        out.append({
            "name": name,
            "active": bool(_rev_field(rev, "active", False)),
            "health_state": _rev_field(rev, "health_state"),
            "provisioning_state": _rev_field(rev, "provisioning_state"),
            "running_state": _rev_field(rev, "running_state"),
            "replicas": _rev_field(rev, "replicas"),
            "traffic_percent": traffic_by_revision.get(name),
            "created_time": _iso(_rev_field(rev, "created_time")),
        })
    out.sort(key=lambda r: r["created_time"] or "", reverse=True)
    return {"configured": True, "revisions": out}
