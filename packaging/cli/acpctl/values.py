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

NOT AN INSTALL. This renders VALUES for the chart at packaging/chart/acp (added in phase 2).
Nothing here runs helm, contacts a cluster or reads a secret; the output is reviewable text that
an operator feeds to `helm template` or `helm install` themselves.

WHAT THE CHART REQUIRES OF THIS FILE, so a change here does not silently break a render: every
key the templates read must be present, and `queueJobTypes` in particular is what the worker
autoscaler builds its queue query from — the `jobs` table has no `role` column, so a scaler
written from the shape of this file rather than from that list queries a column that does not
exist and, KEDA being what it is, scales nothing while logging the error. tests/
test_packaging_chart.py renders the real chart against real output from here, so the two cannot
drift apart quietly.
"""
from __future__ import annotations

from typing import Any

from . import presets
from .inventory import (
    API_HEADROOM_CONN,
    GRAFANA_PORT,
    IMAGES,
    OLLAMA_PORT,
    LANE_JOB_TYPES,
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
    # A pinned pool has to reach the CONTAINER, not just the plan's arithmetic. If it stopped at
    # the budget calculation, the document would describe a fleet that fits its Postgres server
    # and the chart would deploy one that does not.
    if tier.get("connectionPool"):
        values["env"]["ACP_DB_MAX_CONN"] = str(int(tier["connectionPool"]))
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
        if queue_signals and role:
            # The chart builds its scaler query from THIS, rather than holding its own copy of
            # the lane lists in YAML where nothing can check them. See inventory.LANE_JOB_TYPES.
            values["autoscaling"]["queueJobTypes"] = list(LANE_JOB_TYPES[role])
    return values


def build_values(doc: dict[str, Any], release: Any = None) -> dict[str, Any]:
    """The Helm values for this document, optionally pinned to a release.

    A pure function of its inputs. `release` is an `acpctl.release.Release` when the caller has
    one; typed loosely so that values.py does not import release.py, which imports inventory and
    spec — the dependency would be circular for no gain, since the only thing needed here is two
    small mappings off the object.

    WITHOUT A RELEASE THIS IS UNCHANGED, and deliberately so: `digests` stays empty and the
    repository keys the chart defaults are left absent. An empty digest map is an honest
    "not resolved"; a default that pinned something would be a claim about bytes nobody
    looked up.
    """
    digests: dict[str, str] = {}
    repositories: dict[str, str] = {}
    if release is not None:
        digests = release.chart_digests()
        repositories = release.chart_repositories()
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
            # THE REGISTRY COMES FROM THE DOCUMENT, NOT THE RELEASE, even when a release is
            # given. A digest names the same bytes in any registry, so an installation that
            # mirrored the release into its own (an air-gapped one, PRD S17) pulls from its own
            # host with the release's digests unchanged. The manifest's registry records where
            # the build pushed; this is where this installation pulls.
            "registry": rt.get("imageRegistry", ""),
            "tag": rt["version"],
            # Named here rather than defaulted in the chart, so `acpctl plan` and `helm template`
            # cannot disagree about which artifact runs the models. inventory.IMAGES is the one
            # list of release images; taking it from there means adding an image to that table is
            # the whole change.
            #
            # A RELEASE OVERRIDES THESE, and that is the point of passing one. The chart's own
            # defaults are `acp` and `acp-worker`, which nothing in this repository builds; the
            # manifest names the artifact that was actually produced.
            "ollamaRepository": repositories.get("ollama", IMAGES["ollama"]),
            "grafanaRepository": repositories.get("grafana", IMAGES["grafana"]),
            # PRD S5.1: templates reference digests, not mutable tags. Empty until a release
            # manifest supplies them — an honest "not yet resolved", not a default that would
            # deploy a tag while reading as a pin.
            "digests": digests,
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
            # `modelVolumeSize` is deliberately NOT emitted, and its absence is the finding
            # rather than an omission. The document's `ai.ollama.modelVolume` (200-500Gi across
            # the examples) described storage that would keep models across a restart — and
            # deploy/ollama/Dockerfile bakes them into the image layer instead, serving from
            # /models precisely because a volume mounted at the base image's declared
            # `VOLUME /root/.ollama` SHADOWS them. So the value described a mount that, made,
            # would produce an Ollama with no models and no error. The chart renders no volume;
            # the schema still accepts the field for a deployment supplying its own runtime.
            "ollama": {
                "enabled": ai.get("ollama", {}).get("enabled", False),
                "gpu": ai.get("ollama", {}).get("gpu", False),
                "port": OLLAMA_PORT,
            },
            "externalProviders": list(ai.get("externalProviders", [])),
        },
        "observability": {
            "openTelemetry": {"enabled": obs.get("openTelemetry", False),
                              "exporter": obs.get("exporter", "local")},
            "grafana": {"enabled": obs.get("grafana", False), "port": GRAFANA_PORT},
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

    # The chart's own `image.repository` and `image.workerRepository` defaults are `acp` and
    # `acp-worker` — names nothing in this repository builds. A release manifest names the
    # artifact that WAS built, so it overrides them. With no release these keys stay ABSENT
    # rather than guessed: an emitted default here would be a second place for the chart's
    # defaults to live, and the two would drift without anything failing.
    for chart_component, key in (("api", "repository"), ("worker", "workerRepository")):
        if chart_component in repositories:
            values["image"][key] = repositories[chart_component]
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
    if cfg.get("account"):
        # objectStorage only. Carried through so the chart can wire the application's
        # remediated-output store; without it `api/blob.py` is a no-op and corrected documents
        # are produced and dropped.
        out["account"] = cfg["account"]
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


def render_values_yaml(doc: dict[str, Any], release: Any = None) -> str:
    """`build_values` as a YAML document, with a header saying where it came from."""
    try:
        import yaml
    except ImportError:  # pragma: no cover - environment-dependent
        import json
        body = json.dumps(build_values(doc, release), indent=2)
        note = "# PyYAML is not installed; emitting JSON, which Helm accepts as valid YAML.\n"
    else:
        body = yaml.safe_dump(build_values(doc, release), sort_keys=False,
                              default_flow_style=False)
        note = ""
    header = (
        "# GENERATED by `acpctl values` from an acp-deployment document. Do not hand-edit:\n"
        "# edit the deployment document and regenerate, or the two disagree and the document\n"
        "# stops being the record of what was installed.\n"
        f"# release {doc['runtime']['version']}  profile {doc['runtime']['profile']}  "
        f"platform {doc['runtime']['platform']}\n"
    )
    if release is None:
        header += (
            "# Image digests are UNRESOLVED here — supply a release manifest with\n"
            "# `acpctl values <doc> --release <manifest>` to pin them.\n")
    else:
        header += (
            f"# Pinned to release {release.version} built from "
            f"{release.source_revision[:12]}; images are referenced by digest.\n"
            "# Signatures are NOT verified by this command — that needs the registry, and is\n"
            "# `acpctl install`'s job.\n")
    return header + note + body
