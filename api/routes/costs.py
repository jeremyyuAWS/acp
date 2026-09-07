"""Read-only infrastructure cost transparency for Live Operations.

This endpoint reports a *configured-capacity estimate*, never an Azure invoice.  Azure Container
Apps billing depends on workload profile, active/idle time and negotiated pricing, so ACP only
calculates dollars when operations supplies an explicit per-service rate card.  Missing inputs
remain ``None`` and every response names its provenance and freshness.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from swallowed import swallowed

router = APIRouter()

_AZ_SUB = os.environ.get("AZURE_SUBSCRIPTION_ID")
_AZ_RG = os.environ.get("AZURE_RESOURCE_GROUP", "mdk-accessibility")

# ── Azure Cost Management: actual spend, never live ───────────────────────────────────────────
#
# WHY REST AND NOT AN SDK. Every other Azure surface here uses an azure-mgmt-* client, and the
# reason this one does not is that Cost Management is a single POST whose BODY IS THE SEMANTICS:
# the timeframe, the granularity and the aggregation decide what the number means. Wrapped in a
# client those become keyword arguments two files away from the value they describe, and
# azure-mgmt-costmanagement is not otherwise a dependency. azure-identity — already required for
# every other call in this package — supplies the token.
#
# WHY IT IS CACHED HARD. Microsoft's own guidance is not to query Cost Management more than
# daily, and it rate-limits aggressively (429 with Retry-After). The Live Operations cost panel
# polls this endpoint every 60 SECONDS. Querying per request would be abusive and would spend the
# subscription's Cost Management quota on a panel nobody is reading, so the answer is held for
# _BILLING_TTL_S and a throttle response is honoured rather than retried.
#
# WHAT THIS NUMBER IS NOT. It is not live and must never be labelled as such: Cost Management
# refreshes roughly every four hours, so month-to-date is a real measurement of a stale window.
# The block therefore carries `updated_at` — when ACP asked — and a label that says both.
_COST_API_VERSION = "2024-08-01"
_COST_SCOPE_HOST = "https://management.azure.com"
_COST_TOKEN_SCOPE = "https://management.azure.com/.default"
_BILLING_TTL_S = float(os.environ.get("ACP_BILLING_TTL_S") or 3600)
# A FAILURE IS NOT WORTH AN HOUR. The long TTL above exists because Cost Management rate-limits
# and Microsoft advises against querying it more than daily — but that reasoning applies to a
# SUCCESSFUL answer, which is stale-but-usable and costs a quota call to refresh. A failure is
# the opposite: it is almost always something an operator is actively fixing, and holding it for
# an hour means the panel keeps naming a missing role for fifty-nine minutes after the role was
# granted. Observed on 2026-09-06: the fix was to restart the revision, which is a blunt remedy
# for a cache this code chose.
#
# Not zero, either. An unconfigured or broken deployment would then re-query on every request
# from a panel that polls every 60 seconds, spending the quota fastest exactly when no answer is
# coming back.
_BILLING_FAILURE_TTL_S = float(os.environ.get("ACP_BILLING_FAILURE_TTL_S") or 60)
_BILLING_TIMEOUT_S = float(os.environ.get("ACP_BILLING_TIMEOUT_S") or 15)
_BILLING_REFRESH_NOTE = ("Azure Cost Management refreshes roughly every four hours; "
                         "month-to-date is a measurement, not a live figure.")
# Verbatim from #1580, which renders it as "Billing freshness: …". Kept as its own string rather
# than folded into the note above so that panel's line does not change wording under it.
_BILLING_DELAY_NOTE = "Azure Cost Management actuals can lag by about four hours."

# Held across requests: {"at": monotonic, "value": block, "blocked_until": monotonic}
_billing_cache: dict = {"at": 0.0, "value": None, "blocked_until": 0.0}


def _billing_unavailable(reason: str, label: str) -> dict:
    """The shape every failure returns. Never a zero: a subscription that could not be read has
    not spent nothing."""
    return {"configured": False, "actual_month_to_date_usd": None, "forecast_month_usd": None,
            "currency": None, "updated_at": None, "freshness_label": label,
            "unavailable_reason": reason, "refresh_note": _BILLING_REFRESH_NOTE,
            # #1580's key, kept on every shape so its "Billing freshness" line never blanks.
            "delay_note": _BILLING_DELAY_NOTE}


def _bearer_token():
    from azure.identity import DefaultAzureCredential  # noqa: PLC0415
    return DefaultAzureCredential().get_token(_COST_TOKEN_SCOPE).token


def _cost_post(path: str, body: dict, token: str) -> tuple[dict | None, str | None, float | None]:
    """POST one Cost Management query. Returns (payload, reason, retry_after_seconds).

    Distinguishes the cases an operator can act on: 401/403 is the Cost Management Reader role
    this endpoint's docstring names, 429 is throttling and carries how long to wait. Everything
    else is "error" rather than a category the response does not actually support.
    """
    request = urllib.request.Request(
        f"{_COST_SCOPE_HOST}{path}?api-version={_COST_API_VERSION}",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(request, timeout=_BILLING_TIMEOUT_S) as answer:
            return json.loads(answer.read().decode() or "{}"), None, None
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return None, "permission", None
        if e.code == 429:
            retry = e.headers.get("Retry-After") if e.headers else None
            try:
                return None, "throttled", float(retry)
            except (TypeError, ValueError):
                return None, "throttled", None
        return None, "error", None
    except Exception:  # noqa: BLE001 — network, DNS, timeout, a malformed body
        return None, "error", None


def _total_from(payload: dict | None) -> tuple[float | None, str | None]:
    """Pull (cost, currency) out of a Cost Management result BY COLUMN NAME.

    The response is columns plus rows, and the column order is not contractual. Reading row[0] as
    the cost is the mistake this exists to avoid: with a different aggregation the first column is
    the currency, and a currency string coerced through float() is not a number that fails loudly
    — it is a total that quietly disappears.
    """
    props = (payload or {}).get("properties") or {}
    columns = [str((column or {}).get("name") or "") for column in (props.get("columns") or [])]
    rows = props.get("rows") or []
    if not columns or not rows:
        return None, None
    lowered = [name.lower() for name in columns]
    cost_at = next((i for i, name in enumerate(lowered)
                    if name in ("cost", "pretaxcost", "costusd", "totalcost")), None)
    currency_at = next((i for i, name in enumerate(lowered)
                        if name in ("currency", "billingcurrency", "currencycode")), None)
    if cost_at is None:
        return None, None
    total = 0.0
    currency = None
    seen = False
    for row in rows:
        if cost_at >= len(row):
            continue
        try:
            total += float(row[cost_at])
            seen = True
        except (TypeError, ValueError):
            continue
        if currency is None and currency_at is not None and currency_at < len(row):
            currency = str(row[currency_at]) or None
    return (round(total, 2), currency) if seen else (None, None)


def _query_billing() -> dict:
    """One month-to-date actual, and one forecast, as two INDEPENDENT calls.

    Independent because the forecast endpoint is the more fragile of the two — it takes an
    explicit window and rejects more shapes — and losing a real month-to-date figure because a
    forecast 400'd would be trading the measurement for the projection.
    """
    scope = f"/subscriptions/{_AZ_SUB}/resourceGroups/{_AZ_RG}"
    try:
        token = _bearer_token()
    except Exception:  # noqa: BLE001
        swallowed("routes.costs: acquiring a management token for Cost Management failed")
        return _billing_unavailable(
            "credential", "Azure billing actuals unavailable: no managed identity token")

    payload, reason, retry_after = _cost_post(f"{scope}/providers/Microsoft.CostManagement/query", {
        "type": "ActualCost",
        "timeframe": "MonthToDate",
        "dataset": {"granularity": "None",
                    "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}}},
    }, token)
    if reason:
        block = _billing_unavailable(reason, {
            "permission": "Azure billing actuals unavailable: Cost Management Reader role needed",
            "throttled": "Azure billing actuals unavailable: Cost Management is throttling",
        }.get(reason, "Azure billing actuals unavailable: Cost Management query failed"))
        block["retry_after_s"] = retry_after
        return block

    actual, currency = _total_from(payload)
    if actual is None:
        # A query that answered with no rows is not a zero bill. Say so.
        return _billing_unavailable(
            "no_data", "Azure billing actuals unavailable: Cost Management returned no rows")

    now = datetime.now(timezone.utc)
    # The forecast window is the rest of THIS month, which is what "forecast_month_usd" means.
    last_day = (now.replace(day=28) + _timedelta_days(4)).replace(day=1) - _timedelta_days(1)
    forecast_payload, forecast_reason, _ = _cost_post(
        f"{scope}/providers/Microsoft.CostManagement/forecast", {
            "type": "ActualCost",
            "timeframe": "Custom",
            "timePeriod": {"from": now.strftime("%Y-%m-%dT00:00:00Z"),
                           "to": last_day.strftime("%Y-%m-%dT23:59:59Z")},
            "dataset": {"granularity": "None",
                        "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}}},
            "includeActualCost": True, "includeFreshPartialCost": False,
        }, token)
    forecast, _forecast_currency = (None, None) if forecast_reason else _total_from(forecast_payload)

    return {
        "configured": True,
        "actual_month_to_date_usd": actual,
        "forecast_month_usd": forecast,
        # Read from the answer, never assumed: a subscription billed in EUR must not have its
        # total relabelled as dollars by a hardcoded string.
        "currency": currency,
        "updated_at": now.isoformat(),
        # Never "live". This says WHEN ACP ASKED; the note says how stale Azure's own answer is.
        "freshness_label": "Azure billing data last updated",
        "unavailable_reason": None,
        "refresh_note": _BILLING_REFRESH_NOTE,
        "delay_note": _BILLING_DELAY_NOTE,
        # Stated rather than left to the reader: a null forecast is a call that did not answer,
        # not a forecast of nothing.
        "forecast_unavailable_reason": forecast_reason or (None if forecast is not None else "no_data"),
    }


def _timedelta_days(n):
    from datetime import timedelta  # noqa: PLC0415
    return timedelta(days=n)


def billing_block(*, now=None) -> dict:
    """The cached billing block. `now` is a seam for tests; production uses the monotonic clock."""
    if not _AZ_SUB:
        return _billing_unavailable("not_configured", "Azure billing feed not configured")
    clock = now() if now else time.monotonic()
    held = _billing_cache.get("value")
    # `configured` is the discriminator: only a query that came back with a number sets it, and
    # every failure shape from _billing_unavailable leaves it False.
    ttl = _BILLING_TTL_S if (held or {}).get("configured") else _BILLING_FAILURE_TTL_S
    if held is not None and clock - _billing_cache.get("at", 0.0) < ttl:
        return held
    # A throttle is honoured, not retried. Serving the LAST GOOD block through it is the honest
    # answer — it carries its own updated_at, so the panel says how old the figure is rather than
    # replacing a real measurement with an error.
    if clock < _billing_cache.get("blocked_until", 0.0):
        if held is not None:
            return held
        block = _billing_unavailable(
            "throttled", "Azure billing actuals unavailable: Cost Management is throttling")
        block["retry_in_s"] = max(0, round(_billing_cache["blocked_until"] - clock))
        return block

    block = _query_billing()
    if block.get("unavailable_reason") == "throttled":
        wait = block.get("retry_after_s")
        _billing_cache["blocked_until"] = clock + (wait if wait else _BILLING_TTL_S)
        if held is not None:
            return held
        # How long the hold has left, so the panel can name the retry time. Seconds from now, not
        # a timestamp: this clock is monotonic and means nothing to a browser.
        block["retry_in_s"] = max(0, round(_billing_cache["blocked_until"] - clock))
        return block
    _billing_cache["at"] = clock
    _billing_cache["value"] = block
    return block


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


def _billing_setup_row(billing: dict) -> dict:
    """The setup row's account of the billing feed: FOUR states, where one boolean used to do.

    On 2026-09-07 the panel read "Billing actuals — Not configured" while the tile beside it said
    "Cost Management is throttling". Both came from `configured: False`, which is what every
    failure shape sets — so a role that had just been granted and was working looked identical to
    a role that was missing. An operator reading "Not configured" goes to fix configuration; the
    only correct action for a throttle is to wait, and the row now says until when.

      connected       a figure came back; `configured` stays True for every existing reader
      throttled       Azure said back off — temporary, with `retry_at` when the hold lifts
      not_configured  no subscription on the API service; nothing was asked
      unavailable     asked and refused (a missing role, a bad token) — an operator's problem

    `configured` is kept as exactly `state == "connected"`, so nothing that reads the old
    boolean changes meaning. `reason` is the tile's own label, as before, so the two cannot
    disagree about why.
    """
    reason = billing.get("unavailable_reason")
    if billing.get("configured"):
        state = "connected"
    elif reason == "throttled":
        state = "throttled"
    elif reason == "not_configured":
        state = "not_configured"
    else:
        state = "unavailable"
    retry_at = None
    retry_in = billing.get("retry_in_s")
    if state == "throttled" and retry_in is not None:
        retry_at = (datetime.now(timezone.utc) + timedelta(seconds=int(retry_in))).isoformat()
    return {
        "configured": state == "connected",
        "state": state,
        "reason": None if state == "connected" else billing.get("freshness_label"),
        "retry_at": retry_at,
    }


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
    # Read BEFORE the `configured` gate below: a subscription with no WORKER_APP_NAMES has no
    # capacity estimate to make and still has a real bill.
    billing = billing_block()
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
        # Actual spend from Cost Management, cached hard and never called live.
        "billing": billing,
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
            # Derived from the query, not hardcoded: this row said "Azure Cost Management is
            # not connected" unconditionally, which is now a claim the code can actually check.
            # When it is NOT connected the reason is the billing block's own label, so the
            # setup row and the tile above it cannot disagree about why.
            "billing_actuals": _billing_setup_row(billing),
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
