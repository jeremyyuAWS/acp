"""Render Helm values for the shared ACP release from a deployment document.

THE PORTABILITY CLAIM, MADE CONCRETE. Kubernetes + Helm is the primary production packaging
layer; Azure, AWS and GCP are infrastructure ADAPTERS around the same release, and Docker Compose
is the evaluation option. That claim is only real if one function turns any platform's document
into one release's values — which is this module. If a platform needed its own renderer, the
clouds would have forked the application package, which is exactly what PRD S22 forbids.

WHAT THE PLATFORM ACTUALLY CHANGES, and it is a short list: whether a data service is provisioned
in-cluster or pointed at a provider service, which secret backend resolves a reference, and the
ingress/storage classes. Everything else — tiers, roles, replica ranges, resources, probes,
network posture — is identical across every platform, and this file is where a reviewer can see
that it is identical rather than take it on trust.

NOT A CHART, AND NOT AN INSTALL. This renders VALUES. The chart lands in phase 2, and nothing
here runs helm, contacts a cluster or reads a secret. `acpctl values` is read-only like the rest
of this release: its output is reviewable text, and generating it is the step before a chart
exists, not a substitute for one.
"""
from __future__ import annotations

from typing import Any

from . import presets
from .inventory import (
    API_HEADROOM_CONN,
    TIER_ROLE,
    build_inventory,
    connection_budget,
    worker_threads,
)

# Which data services the adapter points at a provider rather than provisioning in-cluster.
# `managed` is the only mode that leaves the cluster; self-hosted and embedded are both rendered
# as in-cluster workloads, differing in whether the profile permits them (see spec.py).
_EXTERNAL_MODES = frozenset({"managed"})

# Secret backends that resolve a reference through the External Secrets Operator rather than a
# native Kubernetes Secret. The chart mounts them identically; only the source differs.
_ESO_BACKENDS = {
    "azure-key-vault": "azurekv",
    "aws-secrets-manager": "secretsmanager",
    "gcp-secret-manager": "gcpsm",
    "external-secrets": "vault",
}


def _tier_values(tier: dict, *, role: str | None, threads: int) -> dict[str, Any]:
    row = presets.PRESETS[tier["resources"]["preset"]]
    values: dict[str, Any] = {
        "replicaCount": tier["replicas"]["min"],
        "autoscaling": {
            "enabled": bool(tier.get("autoscale")),
            "minReplicas": tier["replicas"]["min"],
            "maxReplicas": tier["replicas"]["max"],
        },
        "resources": {
            "requests": {
                "cpu": row["cpu"],
                "memory": row["memory"],
                "ephemeral-storage": row["ephemeralStorage"],
            },
            "limits": {
                "cpu": row["cpu"],
                "memory": row["memory"],
                "ephemeral-storage": row["ephemeralStorage"],
            },
        },
        "env": {"ACP_WORKERS": str(threads)},
    }
    if role:
        values["env"]["ACP_WORKER_ROLE"] = role
    auto = tier.get("autoscale")
    if auto:
        # KEDA where the signal is queue-based, HPA where it is not. PRD S11 makes queue depth
        # and oldest-job age the preferred signals precisely because CPU lags a batch workload.
        queue_signals = [s for s in auto["signals"] if s in ("queue-depth", "oldest-job-age")]
        values["autoscaling"]["scaler"] = "keda" if queue_signals else "hpa"
        values["autoscaling"]["triggers"] = list(auto["signals"])
        if "queueDepthTarget" in auto:
            values["autoscaling"]["queueDepthTarget"] = auto["queueDepthTarget"]
        if "oldestJobAgeSeconds" in auto:
            values["autoscaling"]["oldestJobAgeSeconds"] = auto["oldestJobAgeSeconds"]
    return values


def build_values(doc: dict[str, Any]) -> dict[str, Any]:
    """The Helm values for this document. A pure function of the document."""
    rt, data, ai, obs, net = (
        doc["runtime"], doc["data"], doc["ai"], doc["observability"], doc["network"])
    platform = rt["platform"]

    values: dict[str, Any] = {
        # Generated. Recorded so a cluster can be traced back to the document that produced it —
        # PRD S20.12 requires every deployment to produce an immutable installation manifest.
        "acpDeployment": {
            "name": doc["metadata"]["name"],
            "environment": doc["metadata"]["environment"],
            "profile": rt["profile"],
            "platform": platform,
            "adapter": presets.PLATFORM_ADAPTER[platform],
            "supportStatus": presets.SUPPORT_STATUS[platform],
        },
        "image": {
            "registry": rt.get("imageRegistry", ""),
            "tag": rt["version"],
            # PRD S5.1: templates reference digests, not mutable tags. `acpctl install` resolves
            # and verifies signatures; an empty map here is an honest "not yet resolved", not a
            # default that would deploy a tag.
            "digests": {},
            "pullPolicy": "IfNotPresent",
        },
        "api": _tier_values(doc["api"], role=None, threads=0),
        "workers": {
            name: _tier_values(
                doc["workers"][name],
                role=TIER_ROLE[name],
                threads=worker_threads(doc["workers"][name]["resources"]["preset"]),
            )
            for name in ("discover", "assess", "remediate")
        },
        "ingress": {
            "enabled": net["publicIngress"],
            "host": rt.get("publicUrl", "").removeprefix("https://"),
            "tls": True,
        },
        "networkPolicy": {
            # PRD S13: default-deny, with workers carrying no ingress at all.
            "enabled": True,
            "defaultDeny": True,
            "workerIngress": not net["privateWorkers"],
            "allowedEgress": list(net.get("allowedEgress", [])),
        },
        "podDisruptionBudget": {
            # A PDB whose minAvailable equals the replica count blocks every drain. Only tiers
            # that actually run more than one replica get one.
            "enabled": rt["profile"] == "high-availability",
            "minAvailable": 1,
        },
        "postgresql": _data_values(data["postgres"], in_cluster_chart="bitnami/postgresql"),
        "redis": _data_values(data["redis"], in_cluster_chart="bitnami/redis"),
        "objectStorage": _data_values(data["objectStorage"], in_cluster_chart="minio"),
        "secrets": _secret_values(doc),
        "ai": {
            "mode": ai["mode"],
            "ollama": {
                "enabled": ai.get("ollama", {}).get("enabled", False),
                "gpu": ai.get("ollama", {}).get("gpu", False),
                "modelVolumeSize": ai.get("ollama", {}).get("modelVolume", "200Gi"),
            },
            "externalProviders": list(ai.get("externalProviders", [])),
        },
        "observability": {
            "openTelemetry": {"enabled": obs.get("openTelemetry", False),
                              "exporter": obs.get("exporter", "local")},
            "grafana": {"enabled": obs.get("grafana", False)},
            "langfuse": {"mode": obs.get("langfuse", {}).get("mode", "disabled")},
        },
        "migrations": {
            # A Helm pre-install/pre-upgrade hook: it must complete before any application pod
            # starts, which is the ordering ADR 0045 depends on.
            "enabled": True,
            "hook": "pre-install,pre-upgrade",
            "backoffLimit": 0,
        },
        "preflight": {"enabled": True, "hook": "post-install,post-upgrade"},
    }

    budget = connection_budget(doc)
    values["postgresql"]["maxConnections"] = budget["serverMaxConnections"]
    values["postgresql"]["expectedWorstCaseConnections"] = budget["worstCaseConnections"]
    values["postgresql"]["connectionsPerReplicaHeadroom"] = API_HEADROOM_CONN
    return values


def _data_values(cfg: dict, *, in_cluster_chart: str) -> dict[str, Any]:
    mode = cfg["mode"]
    external = mode in _EXTERNAL_MODES
    out: dict[str, Any] = {
        "mode": mode,
        # `enabled` drives the in-cluster subchart. Managed means the adapter supplies the
        # endpoint and the subchart is off — the one structural difference between clouds.
        "enabled": not external,
        "chart": None if external else in_cluster_chart,
        "external": external,
    }
    if cfg.get("highAvailability"):
        out["architecture"] = "replication"
    if cfg.get("storage"):
        out["persistence"] = {"size": cfg["storage"]}
    if cfg.get("backupRetentionDays") is not None:
        out["backupRetentionDays"] = cfg["backupRetentionDays"]
    if cfg.get("encryption"):
        out["encryption"] = cfg["encryption"]
    if cfg.get("retentionDays"):
        out["retentionDays"] = cfg["retentionDays"]
    return out


def _secret_values(doc: dict) -> dict[str, Any]:
    provider = doc["secrets"]["provider"]
    backend = _ESO_BACKENDS.get(provider)
    return {
        "provider": provider,
        "externalSecrets": {
            "enabled": backend is not None,
            "backend": backend,
        },
        # References only. The chart mounts each as an env var sourced from a Secret; no value
        # passes through these values or through any generated manifest (PRD S13).
        "refs": {
            name: {"name": ref["name"], "key": ref["key"],
                   **({"version": ref["version"]} if "version" in ref else {})}
            for name, ref in doc["secrets"]["refs"].items()
        },
    }


def render_values_yaml(doc: dict[str, Any]) -> str:
    """`build_values` as a YAML document, with a header saying where it came from."""
    try:
        import yaml
    except ImportError:  # pragma: no cover - environment-dependent
        import json
        body = json.dumps(build_values(doc), indent=2)
        note = "# PyYAML is not installed; emitting JSON, which Helm accepts as valid YAML.\n"
    else:
        body = yaml.safe_dump(build_values(doc), sort_keys=False, default_flow_style=False)
        note = ""
    header = (
        "# GENERATED by `acpctl values` from an acp-deployment document. Do not hand-edit:\n"
        "# edit the deployment document and regenerate, or the two disagree and the document\n"
        "# stops being the record of what was installed.\n"
        f"# release {doc['runtime']['version']}  profile {doc['runtime']['profile']}  "
        f"platform {doc['runtime']['platform']}\n"
        "# Image digests are UNRESOLVED here — `acpctl install` resolves and verifies them.\n"
    )
    return header + note + body
