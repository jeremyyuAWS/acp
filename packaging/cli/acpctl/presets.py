"""Validated sizes, profile floors, and the platform support matrix.

Everything here is a POLICY table, kept apart from `spec.py` (which applies it) so that a
reviewer can read what ACP claims to support without reading the code that enforces it. Where a
number came from a measurement or an existing production baseline, the comment says so; where it
is a declared planning constant that has not yet been measured, the comment says that instead.
"""
from __future__ import annotations

import math

# ── Resource presets (PRD S11) ────────────────────────────────────────────────
# The four rows are the PRD's table verbatim. `standard` and `small` are also the shapes
# production already runs: deploy/public/rightsize-production.sh applies acp-app 1.0 CPU / 2Gi
# and acp-discovery 1.0 / 2Gi (= small), acp-assess and acp-remediate 2.0 / 4Gi (= standard).
# ephemeralStorage has no counterpart in that script — Container Apps does not expose it as a
# knob — so those figures are the PRD's, not an observed production setting.
PRESETS: dict[str, dict[str, str]] = {
    "small":    {"cpu": "1", "memory": "2Gi",  "ephemeralStorage": "4Gi"},
    "standard": {"cpu": "2", "memory": "4Gi",  "ephemeralStorage": "8Gi"},
    "large":    {"cpu": "4", "memory": "8Gi",  "ephemeralStorage": "16Gi"},
    "x-large":  {"cpu": "8", "memory": "16Gi", "ephemeralStorage": "32Gi"},
}

# Per-platform preset availability.
#
# HELM IS THE SUBSTRATE. Every platform except `compose` renders the SAME Helm release onto
# Kubernetes — AKS, EKS, GKE or a customer's own cluster — so the sizes available are the ones
# the cluster's nodes provide, not a per-cloud container-runtime limit. The platform selects the
# INFRASTRUCTURE ADAPTER (managed Postgres/Redis/object storage, the secret backend, the ingress
# and storage classes), never a different application package.
#
# That is why azure is not restricted here. The 8Gi ceiling recorded in deploy/ollama/Dockerfile
# — which OOM-killed a ~9.2GB model pair — is an Azure Container Apps CONSUMPTION limit, and ACA
# is not what this contract targets. The existing ACA deployment (deploy/public/) is the legacy
# path and stays untouched until the AKS adapter demonstrates parity (PRD S22).
#
# compose is capped because a single evaluation machine sized at x-large is not an evaluation.
PLATFORM_PRESETS: dict[str, tuple[str, ...]] = {
    "azure":      ("small", "standard", "large", "x-large"),
    "aws":        ("small", "standard", "large", "x-large"),
    "gcp":        ("small", "standard", "large", "x-large"),
    "kubernetes": ("small", "standard", "large", "x-large"),
    "onprem":     ("small", "standard", "large", "x-large"),
    "compose":    ("small", "standard"),
}

# What each platform's adapter supplies AROUND the shared Helm release. This table is the whole
# portability claim in one place: the differences between clouds are secret backends, managed
# data services and ingress — not application behaviour.
PLATFORM_ADAPTER: dict[str, str] = {
    "azure":      "AKS + Azure Database for PostgreSQL, Azure Managed Redis, Blob Storage, Key Vault",
    "aws":        "EKS + RDS PostgreSQL, ElastiCache, S3, Secrets Manager",
    "gcp":        "GKE + Cloud SQL PostgreSQL, Memorystore, Cloud Storage, Secret Manager",
    "kubernetes": "customer-managed cluster; customer supplies Postgres, Redis, S3-compatible storage and a secret backend",
    "onprem":     "customer-managed cluster or single server; self-hosted data services throughout",
    "compose":    "single-server Docker Compose; embedded data services, evaluation only",
}

# PRD S7's closing requirement, made machine-readable. "supported" means a reference deployment in
# THIS repository runs the contract suite against it. Nothing but Compose can honestly claim that
# today: deploy/compose/ exists and works, and every Kubernetes path — including azure — is the
# Helm chart at packaging/chart/acp. deploy/public/ deploys Azure Container Apps, which is a
# different topology from the AKS adapter named above, so it does not make `azure` supported here.
#
# This table is deliberately pessimistic. A "supported" that means "we wrote a module" is the
# claim PRD S20.10 exists to prevent.
SUPPORT_STATUS: dict[str, str] = {
    "compose":    "supported",
    "kubernetes": "planned",
    "azure":      "planned",
    "aws":        "planned",
    "gcp":        "planned",
    "onprem":     "planned",
}

# Which data-service modes each platform can actually provide.
PLATFORM_DATA_MODES: dict[str, tuple[str, ...]] = {
    # The managed option is the point of the cloud adapters: the same Helm release, pointed at
    # the provider's Postgres/Redis/object storage instead of in-cluster ones.
    "azure":      ("managed", "self-hosted"),
    "aws":        ("managed", "self-hosted"),
    "gcp":        ("managed", "self-hosted"),
    "kubernetes": ("managed", "self-hosted"),
    # A customer-managed on-prem cluster has no provider service to point at.
    "onprem":     ("self-hosted",),
    "compose":    ("embedded",),
}

# Secret providers each platform can resolve a reference against.
PLATFORM_SECRET_PROVIDERS: dict[str, tuple[str, ...]] = {
    "azure":      ("azure-key-vault", "kubernetes", "external-secrets"),
    "aws":        ("aws-secrets-manager", "kubernetes", "external-secrets"),
    "gcp":        ("gcp-secret-manager", "kubernetes", "external-secrets"),
    "kubernetes": ("kubernetes", "external-secrets"),
    "onprem":     ("kubernetes", "external-secrets", "env-file"),
    "compose":    ("env-file",),
}

# ── Profile floors (PRD S8) ───────────────────────────────────────────────────
# Minimum replicas per tier, by profile. `standard` gets the PRD's "minimum two API replicas";
# `high-availability` gets "at least two replicas per critical tier".
PROFILE_MIN_REPLICAS: dict[str, dict[str, int]] = {
    "evaluation":         {"api": 1, "discover": 0, "assess": 1, "remediate": 1},
    "standard":           {"api": 2, "discover": 1, "assess": 1, "remediate": 1},
    "regulated":          {"api": 2, "discover": 1, "assess": 1, "remediate": 1},
    "high-availability":  {"api": 2, "discover": 2, "assess": 2, "remediate": 2},
}

# Profiles for which `embedded` data services are a silent downgrade rather than a choice
# (PRD S22: "do not silently downgrade from managed production services to embedded services").
PRODUCTION_PROFILES = frozenset({"standard", "regulated", "high-availability"})

# ── Temporary-storage floor (PRD S12) ─────────────────────────────────────────
# DECLARED PLANNING CONSTANTS, NOT MEASUREMENTS. Nothing in this repo has yet measured peak
# per-worker scratch use against source size, so these are stated openly as planning figures and
# the plan output labels them as such. The factors exist so the floor moves when someone does
# measure; they are not evidence that the floor is right.
RENDER_EXPANSION_FACTOR = 4.0   # Office/PDF rasterisation working set vs. source bytes
OUTPUT_FACTOR = 1.0             # remediated output held alongside the source
SAFETY_MARGIN = 1.5
MIN_EPHEMERAL_GIB = 4           # never below the `small` preset

DEFAULT_MAX_SOURCE_FILE_MB = 100
DEFAULT_CONCURRENT_FILES_PER_WORKER = 4


def parse_quantity_gib(text: str) -> float:
    """'8Gi' -> 8.0, '512Mi' -> 0.5, '1Ti' -> 1024.0."""
    for suffix, factor in (("Ti", 1024.0), ("Gi", 1.0), ("Mi", 1 / 1024.0)):
        if text.endswith(suffix):
            return float(text[: -len(suffix)]) * factor
    raise ValueError(f"not a storage quantity: {text!r}")


def minimum_ephemeral_gib(max_source_file_mb: int, concurrent_files: int) -> int:
    """The temporary-storage floor for one worker, in GiB, from the PRD S12 inputs.

    Rounded UP to a whole GiB and never below MIN_EPHEMERAL_GIB, because a floor that rounds
    down is not a floor.
    """
    per_file_mb = max_source_file_mb * (1.0 + RENDER_EXPANSION_FACTOR + OUTPUT_FACTOR)
    total_mb = per_file_mb * concurrent_files * SAFETY_MARGIN
    return max(MIN_EPHEMERAL_GIB, math.ceil(total_mb / 1024.0))


def preset_for(cpu: str, memory: str) -> str | None:
    """The preset name matching a cpu/memory pair, or None if it is not a validated size."""
    for name, row in PRESETS.items():
        if float(row["cpu"]) == float(cpu) and row["memory"] == memory:
            return name
    return None
