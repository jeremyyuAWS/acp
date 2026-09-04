"""The normalized service inventory: one deployment document -> the services an adapter creates.

This is the seam the whole packaging contract exists to create. Today the answer to "what does a
production ACP installation consist of?" is spread across deploy/public/deploy.sh,
deploy/public/redeploy.sh, deploy/public/rightsize-production.sh and deploy/compose/
docker-compose.yml, in bash and YAML, per platform. A second platform means reading all of it and
guessing which parts were Azure and which were ACP.

The inventory answers that question ONCE, from the spec, in plain data. The Azure/AWS/GCP/Helm/
Compose adapters consume this list; none of them re-derives it, and none of them is where a
service's identity, ingress posture or secret set is decided. Nothing here reaches a cloud, reads
a credential or renders a template — it is a pure function of the document, which is what makes
`acpctl plan` safe to run against production before anything exists.

GROUNDED IN THE RUNNING SYSTEM, NOT INVENTED. The tier names, roles and topology are the ones
production runs today: acp-app with ACP_WORKERS=0 plus acp-discovery / acp-assess / acp-remediate
restricted by ACP_WORKER_ROLE (docs/worker-split.md, deploy/public/rightsize-production.sh). The
connection arithmetic is api/store.py's own (db_max_conn = ACP_WORKERS + _API_HEADROOM_CONN),
which tests/test_packaging_inventory.py pins to the real constant so this file cannot drift from
it silently.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import presets

# api/store.py's `_API_HEADROOM_CONN`: concurrent DB-touching HTTP handlers a replica may serve,
# independent of its worker-thread count. Duplicated here rather than imported because packaging
# must not depend on the application package (PRD S22: provider differences live in adapters, and
# the CLI ships in an installer bundle without api/). tests/test_packaging_inventory.py asserts
# the two are equal, so a change to store.py fails this file rather than silently outdating it.
API_HEADROOM_CONN = 16

# In-process worker THREADS per replica, per CPU. Taken from the one place in this repo that
# states the ratio and its reasoning: deploy/compose/docker-compose.yml sets ACP_WORKERS=8 and
# explains it as "enough to assess 8 documents in parallel on a 4-core host (each worker is
# I/O-bound on the vision HTTP call, not CPU-bound)" — two threads per CPU.
#
# It is a RATIO CARRIED OVER, not a measurement of the deployed tiers, and the number it feeds is
# consequential: `connection_budget` below multiplies it out across max replicas, and an
# over-subscribed pool is the 2026-08-30 production incident. Measuring the real per-tier
# concurrency is the follow-up that should replace this constant.
WORKER_THREADS_PER_CPU = 2

# The release images (PRD S5.1). acp-web-api and the three workers are the SAME image with a
# different command and role today; they are listed as distinct artifacts because the PRD
# requires separately-scannable, separately-signed images and because a worker image should not
# have to carry the built SPA.
IMAGES = {
    "api": "acp-web-api",
    "discover": "acp-discovery-worker",
    "assess": "acp-assess-worker",
    "remediate": "acp-remediate-worker",
    "ollama": "acp-ollama-gateway",
    "migrations": "acp-migrations",
    "preflight": "acp-preflight",
}

# ACP_WORKER_ROLE values api/core.py accepts: mixed, discovery, assess, remediate, processing.
# The spec's tier names and the role names are NOT the same strings ('discover' vs 'discovery'),
# which is exactly the kind of mismatch that turns into a worker that claims every job.
TIER_ROLE = {"discover": "discovery", "assess": "assess", "remediate": "remediate"}


@dataclass
class Service:
    """One deployable unit. Platform-neutral: an adapter maps it to an ACA app, a Deployment,
    an ECS service or a Compose service without deciding anything this record does not say."""

    name: str
    kind: str                     # "service" | "job" | "dependency"
    ingress: str                  # "public" | "internal" | "none"
    image: str | None = None
    image_version: str | None = None
    role: str | None = None       # ACP_WORKER_ROLE, worker tiers only
    replicas: tuple[int, int] | None = None
    resources: dict[str, str] | None = None
    ports: tuple[int, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    secret_refs: tuple[str, ...] = ()
    volumes: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    provisioning: str = "in-cluster"   # "in-cluster" | "managed" | "external"
    db_connections_max: int = 0        # worst case across max replicas
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        out = {
            "name": self.name,
            "kind": self.kind,
            "ingress": self.ingress,
            "provisioning": self.provisioning,
        }
        if self.image:
            out["image"] = f"{self.image}:{self.image_version}"
        if self.role:
            out["role"] = self.role
        if self.replicas:
            out["replicas"] = {"min": self.replicas[0], "max": self.replicas[1]}
        if self.resources:
            out["resources"] = dict(self.resources)
        if self.ports:
            out["ports"] = list(self.ports)
        if self.env:
            out["env"] = dict(self.env)
        if self.secret_refs:
            out["secretRefs"] = list(self.secret_refs)
        if self.volumes:
            out["volumes"] = list(self.volumes)
        if self.depends_on:
            out["dependsOn"] = list(self.depends_on)
        if self.db_connections_max:
            out["dbConnectionsMax"] = self.db_connections_max
        if self.notes:
            out["notes"] = self.notes
        return out


def worker_threads(preset: str) -> int:
    return int(float(presets.PRESETS[preset]["cpu"]) * WORKER_THREADS_PER_CPU)


def _resources(tier: dict) -> dict[str, str]:
    return dict(presets.PRESETS[tier["resources"]["preset"]])


def build_inventory(doc: dict[str, Any]) -> list[Service]:
    """Every service, job and dependency this document describes, in deployment order."""
    version = doc["runtime"]["version"]
    data, ai, obs, net = doc["data"], doc["ai"], doc["observability"], doc["network"]
    services: list[Service] = []

    # ── dependencies first: everything else waits on them ──────────────────────
    services.append(_data_dependency(
        "postgres", data["postgres"], port=5432,
        notes="Durable application state. The only authoritative store; PRD S12 forbids any "
              "authoritative output living on ephemeral disk."))
    services.append(_data_dependency(
        "redis", data["redis"], port=6379,
        notes="Scan progress, worker leases and live events. Reconstructable, so it is not a "
              "backup target on its own (PRD S16)."))
    services.append(_data_dependency(
        "object-storage", data["objectStorage"], port=None,
        notes="Remediated files and artifacts (ADR 0010). Authoritative output lives here."))

    # ── jobs ───────────────────────────────────────────────────────────────────
    services.append(Service(
        name="acp-migrations", kind="job", ingress="none",
        image=IMAGES["migrations"], image_version=version,
        secret_refs=("database-url",), depends_on=("postgres",),
        notes="Runs to completion before any application container starts. ADR 0045: migrations "
              "are additive (expand/contract), so a deploy rollback needs no schema rollback."))
    services.append(Service(
        name="acp-preflight", kind="job", ingress="none",
        image=IMAGES["preflight"], image_version=version,
        secret_refs=tuple(_preflight_secrets(doc)),
        depends_on=("postgres", "redis", "object-storage"),
        notes="Verifies connectivity and reports every enabled external data path (PRD S13) "
              "before traffic is admitted. Reports PASS/WARN/FAIL and never prints a secret."))

    # ── the API tier ───────────────────────────────────────────────────────────
    api_tier = doc["api"]
    api_max = api_tier["replicas"][1] if isinstance(api_tier["replicas"], tuple) else api_tier["replicas"]["max"]
    services.append(Service(
        name="acp-web-api", kind="service",
        ingress="public" if net["publicIngress"] else "internal",
        image=IMAGES["api"], image_version=version,
        replicas=(api_tier["replicas"]["min"], api_tier["replicas"]["max"]),
        resources=_resources(api_tier), ports=(8077,),
        # ACP_WORKERS=0 is the split topology, not a tuning choice: it is what stops an API
        # deploy from restarting a running scan (docs/worker-split.md, #113).
        env={"ACP_WORKERS": "0", "PORT": "8077"},
        secret_refs=tuple(_api_secrets(doc)),
        depends_on=("acp-migrations", "postgres", "redis", "object-storage"),
        db_connections_max=api_max * API_HEADROOM_CONN,
        notes="Serves the SPA and the API. Claims no jobs."))

    # ── the three worker tiers ─────────────────────────────────────────────────
    for tier_name in ("discover", "assess", "remediate"):
        tier = doc["workers"][tier_name]
        threads = worker_threads(tier["resources"]["preset"])
        lo, hi = tier["replicas"]["min"], tier["replicas"]["max"]
        depends = ["acp-migrations", "postgres", "redis", "object-storage"]
        if ai.get("ollama", {}).get("enabled"):
            depends.append("acp-ollama-gateway")
        services.append(Service(
            name=f"acp-{TIER_ROLE[tier_name]}", kind="service", ingress="none",
            image=IMAGES[tier_name], image_version=version,
            role=TIER_ROLE[tier_name], replicas=(lo, hi), resources=_resources(tier),
            env={"ACP_WORKERS": str(threads), "ACP_WORKER_ROLE": TIER_ROLE[tier_name]},
            secret_refs=tuple(_worker_secrets(doc)),
            volumes=(f"scratch:{presets.PRESETS[tier['resources']['preset']]['ephemeralStorage']}",),
            depends_on=tuple(depends),
            db_connections_max=hi * (threads + API_HEADROOM_CONN),
            notes="No ingress in any topology (PRD S13). Scratch volume is disposable — nothing "
                  "authoritative may exist only there."))

    # ── the AI lane ────────────────────────────────────────────────────────────
    if ai.get("ollama", {}).get("enabled"):
        services.append(Service(
            name="acp-ollama-gateway", kind="service", ingress="internal",
            image=IMAGES["ollama"], image_version=version,
            replicas=(1, 1), ports=(11434,),
            resources=dict(presets.PRESETS["large"]),
            env={"OLLAMA_MAX_LOADED_MODELS": "2"},
            volumes=(f"models:{ai['ollama'].get('modelVolume', '200Gi')}",),
            notes="Local model serving. Internal ingress only; the model volume is persistent so "
                  "a restart does not re-pull multi-GB models."))

    # ── observability ──────────────────────────────────────────────────────────
    if obs.get("openTelemetry"):
        exporter = obs.get("exporter", "local")
        services.append(Service(
            name="acp-otel-collector", kind="service", ingress="internal", ports=(4317, 4318),
            image=None, provisioning="in-cluster",
            notes=f"Portable instrumentation layer (PRD S14). Exporter: {exporter}."
                  + (" Collection stays entirely inside the installation."
                     if exporter == "local" else "")))
    if obs.get("grafana"):
        services.append(Service(
            name="acp-grafana", kind="service", ingress="internal", ports=(3000,),
            depends_on=("postgres",),
            notes="Dashboards. Upstream image, referenced not rebuilt."))
    langfuse_mode = obs.get("langfuse", {}).get("mode", "disabled")
    if langfuse_mode == "self-hosted":
        services.append(Service(
            name="acp-langfuse", kind="service", ingress="internal", ports=(3000,),
            depends_on=("postgres",), secret_refs=("langfuse-secret-key",),
            notes="Self-hosted LLM tracing. PRD S13: no raw customer document content in "
                  "centralized vendor telemetry."))
    elif langfuse_mode == "cloud":
        services.append(Service(
            name="langfuse", kind="dependency", ingress="none", provisioning="external",
            secret_refs=("langfuse-secret-key",),
            notes="Hosted Langfuse. Traces leave the installation boundary."))

    return services


def _data_dependency(name: str, cfg: dict, port: int | None, notes: str) -> Service:
    mode = cfg["mode"]
    provisioning = {"managed": "managed", "self-hosted": "in-cluster", "embedded": "in-cluster"}[mode]
    extra = ""
    if mode == "embedded":
        extra = " Runs as a container in this installation: single node, no failover."
    if cfg.get("highAvailability"):
        extra += " High availability requested."
    return Service(
        name=name, kind="dependency" if mode == "managed" else "service",
        ingress="internal", provisioning=provisioning,
        ports=(port,) if port else (),
        volumes=(f"data:{cfg['storage']}",) if cfg.get("storage") else (),
        notes=(notes + extra).strip())


def _api_secrets(doc: dict) -> list[str]:
    from .spec import required_secret_names
    # The API never needs the SMB credential: SMB is walked by the discovery worker.
    return [n for n in required_secret_names(doc) if n != "smb-credentials"]


def _worker_secrets(doc: dict) -> list[str]:
    from .spec import required_secret_names
    return list(required_secret_names(doc))


def _preflight_secrets(doc: dict) -> list[str]:
    from .spec import required_secret_names
    return list(required_secret_names(doc))


def connection_budget(doc: dict[str, Any]) -> dict[str, Any]:
    """Worst-case Postgres connection demand across the fleet, against the server's ceiling.

    Worst case, not typical: api/store.py sizes each replica's pool at ACP_WORKERS +
    _API_HEADROOM_CONN and every replica holds its own pool, so demand is set by MAX replicas.
    The 2026-08-30 production incident (`connection pool exhausted`) is what this number is for.
    """
    demand = sum(s.db_connections_max for s in build_inventory(doc))
    ceiling = doc["data"]["postgres"].get("maxConnections", 150)
    return {
        "worstCaseConnections": demand,
        "serverMaxConnections": ceiling,
        "headroom": ceiling - demand,
        "withinBudget": demand <= ceiling,
    }


def inventory_as_dict(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "release": doc["runtime"]["version"],
        "profile": doc["runtime"]["profile"],
        "platform": doc["runtime"]["platform"],
        "supportStatus": presets.SUPPORT_STATUS[doc["runtime"]["platform"]],
        "services": [s.as_dict() for s in build_inventory(doc)],
        "connectionBudget": connection_budget(doc),
    }
