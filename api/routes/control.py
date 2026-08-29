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
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import core

# Azure Container Apps replica control — optional; gracefully absent when env vars are unset.
# Required env vars: AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP, WORKER_APP_NAME (defaults
# to "acp-worker"). The container's managed identity must have Contributor on the worker app.
_AZ_SUB  = os.environ.get("AZURE_SUBSCRIPTION_ID")
_AZ_RG   = os.environ.get("AZURE_RESOURCE_GROUP", "mdk-accessibility")
_AZ_APP  = os.environ.get("WORKER_APP_NAME", "acp-worker")
_AZ_CONFIGURED = bool(_AZ_SUB)


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

def _empty_capacity(configured: bool) -> dict:
    return {
        "configured": configured, "current_replicas": None, "min_replicas": None,
        "max_replicas": None, "cpu_percent": None, "memory_percent": None,
        "metrics_available": False, "measured_at": None,
        "revision_health": None, "revision_provisioning_state": None, "draining_replicas": None,
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
    except Exception:  # noqa: BLE001 — can't even reach the Container App; nothing else to try
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
        pass           # rather than a fabricated 0, same rule this codebase applies everywhere.

    try:
        metrics = _monitor_client().metrics.list(
            app.id, metricnames="CpuPercentage,MemoryPercentage", aggregation="Average",
            timespan=f"{(now - timedelta(minutes=5)).isoformat()}/{now.isoformat()}",
            interval="PT1M")
        for m in metrics.value:
            points = [dp.average for ts in (m.timeseries or []) for dp in ts.data
                      if dp.average is not None]
            if not points:
                continue
            avg = round(sum(points) / len(points), 1)
            metric_name = getattr(m.name, "value", None)
            if metric_name == "CpuPercentage":
                result["cpu_percent"] = avg
            elif metric_name == "MemoryPercentage":
                result["memory_percent"] = avg
        result["metrics_available"] = result["cpu_percent"] is not None or result["memory_percent"] is not None
    except Exception:  # noqa: BLE001 — metrics_available stays False; min/max/current_replicas
        pass           # (already gathered above) are still returned rather than lost.

    try:
        revisions = client.container_apps_revisions.list_revisions(_AZ_RG, _AZ_APP)
        rev_list = getattr(revisions, "value", None)
        if rev_list is None:
            rev_list = list(revisions)
        draining = 0
        for rev in rev_list:
            if _rev_field(rev, "active", False):
                result["revision_health"] = _rev_field(rev, "health_state")
                result["revision_provisioning_state"] = _rev_field(rev, "provisioning_state")
            else:
                draining += _rev_field(rev, "replicas", 0) or 0
        result["draining_replicas"] = draining
    except Exception:  # noqa: BLE001 — revision health stays None; everything gathered above
        pass           # is still returned rather than lost.

    return result
