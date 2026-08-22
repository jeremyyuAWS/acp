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
def set_replicas(body: ReplicaBody):
    """Set the minimum warm replicas for the acp-worker Container App.

    Adjusts minReplicas only; maxReplicas stays at its current value so
    Azure's autoscaler ceiling is not affected. A higher min keeps workers
    warm before a large assessment; lower min reduces idle-container cost.
    """
    if not _AZ_CONFIGURED:
        raise HTTPException(503, "AZURE_SUBSCRIPTION_ID not set — replica control is not available")
    try:
        client = _az_client()
        app = client.container_apps.get(_AZ_RG, _AZ_APP)
        app.properties.template.scale.min_replicas = body.min_replicas
        poller = client.container_apps.begin_create_or_update(_AZ_RG, _AZ_APP, app)
        updated = poller.result()
        scale = updated.properties.template.scale
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
