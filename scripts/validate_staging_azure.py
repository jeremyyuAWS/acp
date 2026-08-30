#!/usr/bin/env python3
"""
Read-only cross-check: does ACP's own view of the staging worker Container App agree with
Azure's ground truth?

Two independent sources, same facts:
  * Azure side  — `azure.mgmt.appcontainers.ContainerAppsAPIClient` /
                   `azure.mgmt.monitor.MonitorManagementClient`, the exact SDK clients and
                   response-shape handling api/routes/control.py's `_az_client()` /
                   `_monitor_client()` already use (see `_rev_field()`/`_iso()` below, copied
                   from there on purpose — this script exists to compare against control.py's
                   own answer, so it reads Azure the same way control.py does).
  * ACP side    — `GET /control/workers/replicas`, `/capacity`, `/revisions` on ACP's own
                   staging deployment, authenticated with `x-e2e-key` (see
                   scripts/smoke_sse_discover.py's `_headers()` for the same mechanism).

Every call here is a GET/list/show. Nothing in this script or its callers may mutate Azure or
ACP state — see .github/workflows/validate-staging-azure.yml, which is the only caller, and
which is workflow_dispatch-only.

Usage:
    python3 scripts/validate_staging_azure.py \\
        --acp-url https://<STAGING_FQDN> \\
        --e2e-key "$ACP_E2E_KEY" \\
        --az-subscription "$AZURE_SUBSCRIPTION_ID" \\
        --az-resource-group mdk-accessibility \\
        --az-app acp-worker-staging \\
        --out report.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------------------------
# Safety guard — checked BEFORE any Azure or ACP call is made. The resource group
# (mdk-accessibility) is shared between the production and staging Container Apps — deploy.yml
# and deploy-staging.yml both default to it — so the group name cannot tell staging from
# production apart. The app name suffix is the only thing that actually does: staging's worker
# is `acp-worker-staging`, production's is `acp-worker`. This function is the one place that
# decision is made, so nothing downstream can accidentally read or (never, in this script) touch
# the production app.
# ---------------------------------------------------------------------------------------------

def is_staging_target(resource_group: str, app_name: str) -> bool:
    """True only when the resolved worker app name is unambiguously a staging name."""
    return bool(app_name) and app_name.strip().lower().endswith("-staging")


def assert_staging_target(resource_group: str, app_name: str) -> None:
    """Hard-fail if `app_name` doesn't look like a staging app. Call this first, before
    constructing any Azure client or making any HTTP call — a refusal here must cost nothing."""
    if not is_staging_target(resource_group, app_name):
        raise SystemExit(
            f"REFUSING to run: resolved app '{app_name}' in resource group '{resource_group}' "
            "does not look like a staging target (the app name must end in '-staging'). This "
            "guard exists to stop this script from ever being pointed at production."
        )


# ---------------------------------------------------------------------------------------------
# Redaction — every artifact this script writes goes through this before it touches disk.
# Explicit known-sensitive values (subscription/tenant/client id, the FQDN) are replaced with a
# stable, named placeholder first; a generic UUID/hostname pattern is a backstop for anything
# that leaks in through a raw SDK repr this script didn't anticipate (a revision's resource id,
# for instance, embeds the subscription id again).
# ---------------------------------------------------------------------------------------------

_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
# A conservative FQDN pattern: two or more dot-separated labels, final label alphabetic. Deliberately
# requires an all-alphabetic final label so it does not eat version strings like "5.0.0" or
# decimal data (final label would be numeric) — those are not hostnames and must survive redaction.
_HOSTNAME_RE = re.compile(
    r"\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}\b"
)


def redact(text: str, secrets: dict[str, str] | None = None) -> str:
    """Replace known-sensitive values with a stable placeholder, then sweep for anything that
    still looks like a UUID or a hostname.

    `secrets` maps a placeholder (e.g. "<subscription>") to the literal value to blank — pass
    every identifier this run actually resolved (subscription id, tenant id, client id, the
    staging FQDN) so an exact match is redacted even where the generic patterns below wouldn't
    catch it (a resource group name, an app name — neither looks like a UUID or a hostname, but
    both are worth blanking if the caller considers them sensitive enough to pass in).
    """
    out = text
    for placeholder, value in (secrets or {}).items():
        if value:
            out = out.replace(value, placeholder)
    out = _UUID_RE.sub("<uuid>", out)
    out = _HOSTNAME_RE.sub("<hostname>", out)
    return out


# ---------------------------------------------------------------------------------------------
# Azure side — mirrors api/routes/control.py's GET /control/workers/capacity and /revisions
# handlers field for field. `_rev_field`/`_iso` are copied from there verbatim: this script's
# whole point is comparing against control.py's own answer, so it must read the SDK response the
# same defensive way control.py does (nested-first-then-flat attribute lookup — see control.py's
# own docstring on `_rev_field` for why neither shape is assumed).
# ---------------------------------------------------------------------------------------------

def _rev_field(rev, name, default=None):
    props = getattr(rev, "properties", None)
    if props is not None and hasattr(props, name):
        return getattr(props, name)
    return getattr(rev, name, default)


def _iso(v):
    if v is None:
        return None
    isoformat = getattr(v, "isoformat", None)
    return isoformat() if callable(isoformat) else str(v)


def make_container_client(subscription_id: str):
    from azure.identity import DefaultAzureCredential
    from azure.mgmt.appcontainers import ContainerAppsAPIClient
    return ContainerAppsAPIClient(DefaultAzureCredential(), subscription_id)


def make_monitor_client(subscription_id: str):
    from azure.identity import DefaultAzureCredential
    from azure.mgmt.monitor import MonitorManagementClient
    return MonitorManagementClient(DefaultAzureCredential(), subscription_id)


def _empty_azure_facts() -> dict:
    return {
        "min_replicas": None, "max_replicas": None, "current_replicas": None,
        "active_revision": None, "revision_health": None, "revision_provisioning_state": None,
        "revision_traffic_percent": None, "draining_replicas": None,
        "cpu_percent": None, "memory_percent": None,
    }


def collect_azure_facts(container_client, monitor_client, resource_group: str, app_name: str) -> dict:
    """The Azure-side half of the comparison. `container_client`/`monitor_client` are injected
    (rather than built here) so tests can pass a stub with the same method surface as the real
    SDK clients — no network, no credentials, no live Azure account needed to exercise this."""
    facts = _empty_azure_facts()

    app = container_client.container_apps.get(resource_group, app_name)
    scale = app.properties.template.scale
    facts["min_replicas"] = scale.min_replicas
    facts["max_replicas"] = scale.max_replicas

    try:
        revision_name = app.properties.latest_ready_revision_name
        replicas = container_client.container_apps_revision_replicas.list_replicas(
            resource_group, app_name, revision_name)
        replica_list = getattr(replicas, "value", None)
        if replica_list is None:
            replica_list = list(replicas)
        facts["current_replicas"] = len(replica_list)
    except Exception:  # noqa: BLE001 — leave current_replicas None, same "honest unknown" rule
        pass           # control.py's own get_capacity() follows.

    active_revision_name = None
    try:
        revisions = container_client.container_apps_revisions.list_revisions(resource_group, app_name)
        rev_list = getattr(revisions, "value", None)
        if rev_list is None:
            rev_list = list(revisions)
        draining = 0
        for rev in rev_list:
            if _rev_field(rev, "active", False):
                facts["active_revision"] = _rev_field(rev, "name")
                facts["revision_health"] = _rev_field(rev, "health_state")
                facts["revision_provisioning_state"] = _rev_field(rev, "provisioning_state")
                active_revision_name = _rev_field(rev, "name")
            else:
                draining += _rev_field(rev, "replicas", 0) or 0
        facts["draining_replicas"] = draining
    except Exception:  # noqa: BLE001
        pass

    try:
        if active_revision_name:
            ingress = app.properties.configuration.ingress
            for t in (getattr(ingress, "traffic", None) or []):
                if getattr(t, "revision_name", None) == active_revision_name:
                    facts["revision_traffic_percent"] = getattr(t, "weight", None)
                    break
    except Exception:  # noqa: BLE001
        pass

    try:
        now = datetime.now(timezone.utc)
        metrics = monitor_client.metrics.list(
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
                facts["cpu_percent"] = avg
            elif metric_name == "MemoryPercentage":
                facts["memory_percent"] = avg
    except Exception:  # noqa: BLE001
        pass

    return facts


# ---------------------------------------------------------------------------------------------
# ACP side — the same three GET endpoints a human hitting the API directly would call. stdlib
# urllib, matching scripts/smoke_sse_discover.py's own style rather than adding a new HTTP
# dependency for one script.
# ---------------------------------------------------------------------------------------------

def _get_json(url: str, e2e_key: str, timeout: float) -> dict:
    req = urllib.request.Request(
        url, headers={"x-e2e-key": e2e_key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            detail = json.loads(body).get("detail", body.decode())
        except Exception:
            detail = body.decode(errors="replace")
        print(f"FAIL: GET {url} -> HTTP {e.code}: {detail}", file=sys.stderr)
        raise


def _empty_acp_facts() -> dict:
    facts = _empty_azure_facts()
    facts["metrics_unavailable_reason"] = None
    return facts


def collect_acp_facts(base_url: str, e2e_key: str, timeout: float = 20.0) -> dict:
    """The ACP-side half. Three plain GETs — no admin auth needed, these endpoints are open to
    any authenticated caller (see control.py's own docstrings on why)."""
    facts = _empty_acp_facts()
    base = base_url.rstrip("/")

    replicas = _get_json(f"{base}/control/workers/replicas", e2e_key, timeout)
    facts["min_replicas"] = replicas.get("min_replicas")
    facts["max_replicas"] = replicas.get("max_replicas")

    capacity = _get_json(f"{base}/control/workers/capacity", e2e_key, timeout)
    facts["current_replicas"] = capacity.get("current_replicas")
    facts["cpu_percent"] = capacity.get("cpu_percent")
    facts["memory_percent"] = capacity.get("memory_percent")
    facts["revision_health"] = capacity.get("revision_health")
    facts["revision_provisioning_state"] = capacity.get("revision_provisioning_state")
    facts["draining_replicas"] = capacity.get("draining_replicas")
    facts["revision_traffic_percent"] = capacity.get("revision_traffic_percent")
    facts["metrics_unavailable_reason"] = capacity.get("metrics_unavailable_reason")

    revisions = _get_json(f"{base}/control/workers/revisions", e2e_key, timeout)
    active = next((r for r in revisions.get("revisions", []) if r.get("active")), None)
    if active:
        facts["active_revision"] = active.get("name")

    return facts


# ---------------------------------------------------------------------------------------------
# Comparison — field-by-field verdict, plus a best-effort note on what kind of discrepancy it
# looks like. The classification is a heuristic, not a diagnosis: it exists to point a human at
# the right first guess (code / RBAC / config / missing-telemetry / Azure-data-latency), not to
# replace them looking.
# ---------------------------------------------------------------------------------------------

FIELDS = (
    "min_replicas", "max_replicas", "current_replicas", "active_revision",
    "revision_health", "revision_provisioning_state", "revision_traffic_percent",
    "draining_replicas", "cpu_percent", "memory_percent",
)

# Fields where a live sample can drift a little between the two calls (Azure metrics/replica
# counts are read moments apart, not atomically) without that drift meaning anything is wrong.
_LATENCY_TOLERANT = {"cpu_percent", "memory_percent"}
_LATENCY_TOLERANCE = 5.0  # percentage points


def _values_equal(field: str, azure_val, acp_val) -> bool:
    if field in _LATENCY_TOLERANT and isinstance(azure_val, (int, float)) and isinstance(acp_val, (int, float)):
        return abs(azure_val - acp_val) <= _LATENCY_TOLERANCE
    return azure_val == acp_val


def _reason_missing(field: str, side: str, acp_facts: dict) -> str:
    if field in ("cpu_percent", "memory_percent") and side == "acp":
        reason = acp_facts.get("metrics_unavailable_reason")
        if reason == "permission":
            return "rbac — ACP's identity likely lacks Monitoring Reader on the worker resource"
        if reason == "no_data":
            return "missing-telemetry — Azure Monitor has no data points yet for this metric"
        return "azure-data-latency — the Azure Monitor call likely failed transiently or timed out"
    if side == "acp":
        return "code — ACP's endpoint does not currently surface this field"
    return "config — Azure did not return this field for the resolved app/revision"


def _reason_disagree(field: str) -> str:
    if field in ("cpu_percent", "memory_percent", "current_replicas", "draining_replicas"):
        return "azure-data-latency — the two calls sampled Azure moments apart, not simultaneously"
    if field in ("active_revision", "revision_traffic_percent", "revision_health",
                 "revision_provisioning_state"):
        return "config — ACP and Azure disagree about which revision is active, healthy, or serving traffic"
    return "config — value mismatch"


def compare_fields(azure_facts: dict, acp_facts: dict) -> list[dict]:
    """Returns one row per field in FIELDS: {field, azure, acp, verdict, note}.
    verdict is one of: agree, disagree, acp-missing, azure-missing."""
    rows = []
    for field in FIELDS:
        av = azure_facts.get(field)
        cv = acp_facts.get(field)
        if av is None and cv is None:
            rows.append({"field": field, "azure": av, "acp": cv, "verdict": "agree",
                         "note": "neither side reports this field"})
        elif av is None:
            rows.append({"field": field, "azure": av, "acp": cv, "verdict": "azure-missing",
                         "note": _reason_missing(field, "azure", acp_facts)})
        elif cv is None:
            rows.append({"field": field, "azure": av, "acp": cv, "verdict": "acp-missing",
                         "note": _reason_missing(field, "acp", acp_facts)})
        elif _values_equal(field, av, cv):
            rows.append({"field": field, "azure": av, "acp": cv, "verdict": "agree", "note": ""})
        else:
            rows.append({"field": field, "azure": av, "acp": cv, "verdict": "disagree",
                         "note": _reason_disagree(field)})
    return rows


# ---------------------------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------------------------

def render_report(rows: list[dict], meta: dict) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1

    lines = [
        "# Staging Azure validation report",
        "",
        f"- app: `{meta.get('app_name')}`",
        f"- resource group: `{meta.get('resource_group')}`",
        f"- generated at: {meta.get('generated_at')}",
        "",
        "## Summary",
        "",
        f"agree={counts.get('agree', 0)}  disagree={counts.get('disagree', 0)}  "
        f"acp-missing={counts.get('acp-missing', 0)}  azure-missing={counts.get('azure-missing', 0)}",
        "",
        "## Fields",
        "",
        "| field | azure | acp | verdict | note |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['field']} | {row['azure']} | {row['acp']} | {row['verdict']} | {row['note']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Compare ACP's own Azure-facing worker endpoints against Azure ground truth "
                    "(read-only, staging only).")
    ap.add_argument("--acp-url", default=None, help="Base URL of ACP's staging API")
    ap.add_argument("--e2e-key", default=None, help="ACP_E2E_KEY value (x-e2e-key header)")
    ap.add_argument("--az-subscription", default=None, help="Azure subscription id")
    ap.add_argument("--az-resource-group", default="mdk-accessibility")
    ap.add_argument("--az-app", default="acp-worker-staging", help="Worker Container App name")
    ap.add_argument("--az-tenant", default=None, help="Azure tenant id — used only for redaction")
    ap.add_argument("--az-client-id", default=None, help="Azure client id — used only for redaction")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--out", default=None, help="Path to write the redacted Markdown report")
    # Two narrow, reusable modes so validate-staging-scale-test.yml (workflow 2) can share this
    # module's TESTED staging-safety-check and redaction logic instead of reimplementing either
    # as ad-hoc bash — see tests/test_validate_staging_azure.py for both functions' coverage.
    ap.add_argument("--check-staging-only", action="store_true",
                    help="Only run the staging-name safety check against --az-resource-group/"
                         "--az-app, then exit. Makes no Azure or ACP call.")
    ap.add_argument("--redact-file", default=None,
                    help="Redact this file with --secret pairs (and generic UUID/hostname "
                         "patterns), write the result to --out (or back to the same file), then "
                         "exit. Makes no Azure or ACP call.")
    ap.add_argument("--secret", action="append", default=[],
                    help="PLACEHOLDER=value pair to redact from --redact-file, e.g. "
                         "'<subscription>=1111...'. Repeatable.")
    args = ap.parse_args()

    if args.check_staging_only:
        assert_staging_target(args.az_resource_group, args.az_app)
        print(f"OK: '{args.az_app}' in '{args.az_resource_group}' is a staging target")
        return

    if args.redact_file:
        secrets = {}
        for pair in args.secret:
            if "=" not in pair:
                ap.error(f"--secret must be PLACEHOLDER=value, got: {pair!r}")
            placeholder, value = pair.split("=", 1)
            secrets[placeholder] = value
        text = Path(args.redact_file).read_text()
        out_path = Path(args.out) if args.out else Path(args.redact_file)
        out_path.write_text(redact(text, secrets))
        print(f"redacted {args.redact_file} -> {out_path}")
        return

    missing = [flag for flag, val in (
        ("--acp-url", args.acp_url), ("--e2e-key", args.e2e_key),
        ("--az-subscription", args.az_subscription),
    ) if not val]
    if missing:
        ap.error(f"the following arguments are required: {', '.join(missing)}")

    # Safety guard FIRST — before constructing any client or making any call.
    assert_staging_target(args.az_resource_group, args.az_app)

    print(f"Azure app:  {args.az_app}  (rg={args.az_resource_group})")
    print(f"ACP url:    {args.acp_url}")

    container_client = make_container_client(args.az_subscription)
    monitor_client = make_monitor_client(args.az_subscription)
    azure_facts = collect_azure_facts(container_client, monitor_client,
                                       args.az_resource_group, args.az_app)
    acp_facts = collect_acp_facts(args.acp_url, args.e2e_key, timeout=args.timeout)

    rows = compare_fields(azure_facts, acp_facts)

    fqdn = args.acp_url.split("//", 1)[-1].split("/", 1)[0]
    secrets = {
        "<subscription>": args.az_subscription,
        "<tenant>": args.az_tenant,
        "<client-id>": args.az_client_id,
        "<fqdn>": fqdn,
    }

    meta = {
        "app_name": args.az_app,
        "resource_group": args.az_resource_group,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    report = redact(render_report(rows, meta), secrets)

    print()
    print(report)

    if args.out:
        with open(args.out, "w") as f:
            f.write(report)
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
