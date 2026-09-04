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
_AZ_CONFIGURED = bool(_AZ_SUB and _AZ_APP)


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


def _gather_metrics(app_id: str, now: datetime) -> tuple[dict, str | None]:
    """Every metric in _AZ_METRICS, with its per-minute series, or ({}, reason) on failure.

    One call per aggregation rather than one per metric: metrics.list accepts a comma-separated
    name list but a single aggregation, so three calls cover fourteen metrics. A group that fails
    degrades only its own metrics — the reason is recorded, the other groups still return.

    A metric Azure does not answer for is present in the result with `available: false` and null
    values, never absent and never zero. The distinction the UI needs is between "nothing is
    happening" and "nobody measured", and dropping the key would erase it.
    """
    timespan = (f"{(now - timedelta(minutes=_AZ_METRIC_WINDOW_MIN)).isoformat()}"
                f"/{now.isoformat()}")
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


def _empty_capacity(configured: bool) -> dict:
    return {
        "configured": configured, "current_replicas": None, "min_replicas": None,
        "max_replicas": None, "cpu_percent": None, "memory_percent": None,
        "cpu_cores_per_replica": None, "memory_per_replica": None,
        "ephemeral_storage_per_replica": None, "workload_profile_name": None,
        "active_revision_name": None, "worker_app_name": _AZ_APP,
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
        "replicas": [], "revisions": [], "replica_lifecycle": None,
    }


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
    """Azure-side capacity evidence for the acp-worker Container App: how many replicas are
    actually running right now, and recent CPU/memory utilization — as opposed to
    GET /control/workers/replicas' CONFIGURED min/max scale rule, which says nothing about
    whether Azure has actually provisioned that many, or how loaded they are.

    Open to any authenticated user, same reasoning as GET /control/workers/replicas (#950) —
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
    if not _AZ_CONFIGURED:
        return _empty_capacity(False)

    now = datetime.now(timezone.utc)
    result = _empty_capacity(True)
    result["measured_at"] = now.isoformat()

    try:
        client = _az_client()
        app = client.container_apps.get(_AZ_RG, _AZ_APP)
        scale = app.properties.template.scale
        result["min_replicas"] = scale.min_replicas
        result["max_replicas"] = scale.max_replicas
        result["workload_profile_name"] = getattr(app.properties, "workload_profile_name", None)
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
        revisions = client.container_apps_revisions.list_revisions(_AZ_RG, _AZ_APP)
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
                replicas.extend(_replica_rows(client, row["name"], draining=False))
            elif row["name"] and (row["replicas"] or 0) > 0:
                replicas.extend(_replica_rows(client, row["name"], draining=True))
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

    return result


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


def _replica_rows(client, revision_name: str, draining: bool = False) -> list[dict]:
    """Per-replica lifecycle rows for one revision. Never raises: a revision whose replicas cannot
    be listed contributes nothing rather than failing the whole reading."""
    try:
        answer = client.container_apps_revision_replicas.list_replicas(_AZ_RG, _AZ_APP, revision_name)
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
