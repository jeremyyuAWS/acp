"""Read-only infrastructure cost transparency for Live Operations.

This endpoint reports a *configured-capacity estimate*, never an Azure invoice.  Azure Container
Apps billing depends on workload profile, active/idle time and negotiated pricing, so ACP only
calculates dollars when operations supplies an explicit per-service rate card.  Missing inputs
remain ``None`` and every response names its provenance and freshness.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter()

_AZ_SUB = os.environ.get("AZURE_SUBSCRIPTION_ID")
_AZ_RG = os.environ.get("AZURE_RESOURCE_GROUP", "mdk-accessibility")


def _app_names() -> list[str]:
    return [name.strip() for name in os.environ.get("WORKER_APP_NAMES", "").split(",") if name.strip()]


def _rate_card() -> tuple[dict, str | None]:
    raw = os.environ.get("ACP_AZURE_CAPACITY_RATES_JSON", "")
    if not raw:
        return {}, None
    try:
        card = json.loads(raw)
        return (card, os.environ.get("ACP_AZURE_RATE_SOURCE") or "Operations-configured rate card") if isinstance(card, dict) else ({}, None)
    except (TypeError, ValueError):
        return {}, None


def _az_client():
    from azure.identity import DefaultAzureCredential
    from azure.mgmt.appcontainers import ContainerAppsAPIClient
    return ContainerAppsAPIClient(DefaultAzureCredential(), _AZ_SUB)


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def estimate_service(app_name: str, replicas, cpu, memory_gib, rate: dict | None) -> dict:
    """Build one honest service line from measured allocation and explicit rates."""
    replicas_n, cpu_n, memory_n = _number(replicas), _number(cpu), _number(memory_gib)
    vcpu_rate = _number((rate or {}).get("vcpu_hour"))
    memory_rate = _number((rate or {}).get("gib_hour"))
    hourly = None
    if None not in (replicas_n, cpu_n, memory_n, vcpu_rate, memory_rate):
        hourly = replicas_n * ((cpu_n * vcpu_rate) + (memory_n * memory_rate))
    capacity_available = None not in (replicas_n, cpu_n, memory_n)
    rate_available = None not in (vcpu_rate, memory_rate)
    return {
        "app": app_name,
        "replicas": int(replicas_n) if replicas_n is not None else None,
        "cpu_cores_per_replica": cpu_n,
        "memory_gib_per_replica": memory_n,
        "vcpu_hour_rate_usd": vcpu_rate,
        "gib_hour_rate_usd": memory_rate,
        "estimated_hourly_usd": round(hourly, 4) if hourly is not None else None,
        "estimated_daily_usd": round(hourly * 24, 2) if hourly is not None else None,
        "status": "estimated" if hourly is not None else "not_reported",
        "capacity_available": capacity_available,
        "rate_configured": rate_available,
        "allocated_vcpu": round(replicas_n * cpu_n, 2) if capacity_available else None,
        "allocated_memory_gib": round(replicas_n * memory_n, 2) if capacity_available else None,
        "unavailable_reason": (None if hourly is not None else
                               "Azure capacity could not be read" if not capacity_available else
                               "No rate card is configured for this worker service"),
    }


def _memory_gib(value):
    if value is None:
        return None
    text = str(value).strip().lower()
    try:
        if text.endswith("gi"):
            return float(text[:-2])
        if text.endswith("mi"):
            return float(text[:-2]) / 1024
        return float(text)
    except ValueError:
        return None


@router.get("/control/costs")
def get_costs():
    """Configured-capacity estimate plus an explicit placeholder for delayed billing actuals."""
    measured_at = datetime.now(timezone.utc).isoformat()
    apps = _app_names()
    rates, rate_source = _rate_card()
    capacity_configured = bool(_AZ_SUB and apps)
    missing_rate_apps = [name for name in apps
                         if None in (_number((rates.get(name) or {}).get("vcpu_hour")),
                                     _number((rates.get(name) or {}).get("gib_hour")))]
    rate_configured = bool(apps and rate_source and not missing_rate_apps)
    response = {
        "configured": capacity_configured,
        "currency": "USD",
        "estimate_kind": "configured_capacity",
        "estimate_label": "Estimated from running replicas and an operations-configured rate card",
        "measured_at": measured_at,
        "rate_source": rate_source,
        "services": [],
        "estimated_hourly_usd": None,
        "estimated_daily_usd": None,
        "billing": {
            "configured": False, "actual_month_to_date_usd": None,
            "forecast_month_usd": None, "updated_at": None,
            "freshness_label": "Azure billing feed not configured",
            "delay_note": "Azure Cost Management actuals can lag by about four hours.",
        },
        "setup": {
            "capacity": {
                "configured": capacity_configured,
                "available": False,
                "reason": (None if capacity_configured else
                           "Azure subscription access is not configured on the API service" if not _AZ_SUB else
                           "Worker service names are not configured on the API service"),
            },
            "rate_card": {
                "configured": rate_configured,
                "reason": (None if rate_configured else
                           "No operations-approved rate card is configured" if not rates else
                           "Rates are missing for: " + ", ".join(missing_rate_apps)),
            },
            "billing_actuals": {
                "configured": False,
                "reason": "Azure Cost Management is not connected",
            },
        },
    }
    if not response["configured"]:
        return response

    try:
        client = _az_client()
    except Exception:
        response["services"] = [
            estimate_service(app_name, None, None, None, rates.get(app_name))
            for app_name in apps
        ]
        response["setup"]["capacity"]["reason"] = "Azure capacity could not be read with the API service identity"
        return response
    for app_name in apps:
        try:
            app = client.container_apps.get(_AZ_RG, app_name)
            revision = app.properties.latest_ready_revision_name
            listed = client.container_apps_revision_replicas.list_replicas(_AZ_RG, app_name, revision)
            replicas = getattr(listed, "value", None)
            replicas = list(listed) if replicas is None else replicas
            containers = getattr(app.properties.template, "containers", None) or []
            resources = getattr(containers[0], "resources", None) if containers else None
            response["services"].append(estimate_service(
                app_name, len(replicas), getattr(resources, "cpu", None),
                _memory_gib(getattr(resources, "memory", None)), rates.get(app_name)))
        except Exception:  # one Azure app must not erase the other services' evidence
            response["services"].append(estimate_service(app_name, None, None, None, rates.get(app_name)))

    unavailable_apps = [line["app"] for line in response["services"]
                        if not line["capacity_available"]]
    response["setup"]["capacity"]["available"] = not unavailable_apps
    response["setup"]["capacity"]["reason"] = (None if not unavailable_apps else
                                                  "Capacity could not be read for: " +
                                                  ", ".join(unavailable_apps))

    hourly = [line["estimated_hourly_usd"] for line in response["services"] if line["estimated_hourly_usd"] is not None]
    if hourly and len(hourly) == len(response["services"]):
        response["estimated_hourly_usd"] = round(sum(hourly), 4)
        response["estimated_daily_usd"] = round(sum(hourly) * 24, 2)
    return response
