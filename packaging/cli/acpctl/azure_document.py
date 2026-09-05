"""Today's Azure deployment, written as a deployment document — derived, not transcribed.

PRD §21 phase 3 asks to "rebuild the current Azure deployment using the common contract". Slice 1
established what production runs and where it differs from the standard-production EXAMPLE. This
is the other half of the question, and the one that actually tests the contract:

    can the contract express what production runs AT ALL?

Not "should production change" — that is the decision `azure-parity.md` puts to the owner. This
asks whether a document exists that describes today's Azure faithfully, validates against the
schema, and renders to a Helm release that would reproduce it. If no such document exists, the
contract is not a portability layer for Azure yet, and every parity number computed against it is
a comparison with a target the deployment could not have hit.

THE ANSWER TURNED OUT TO BE "NOT QUITE", AND THAT IS THE FINDING. Everything about today's Azure
was expressible except one thing: the per-replica connection pool. `deploy/public/
rightsize-production.sh` pins `ACP_DB_MAX_CONN=2` on all three worker tiers (PR #1370) to hold the
fleet under Postgres's measured 150-connection ceiling. The contract had no vocabulary for it, so
the honest document — real replica ranges, the real 150-connection server — computed **384**
worst-case connections and read as 2.5x oversubscribed, while the deployment it described sits at
**82** and has never exhausted its pool. `tier.connectionPool` closes that, and
`inventory.pool_per_replica` mirrors `api/store.py`'s override semantics exactly.

Worth being precise about what that gap was: the contract was not WRONG about production, it was
UNABLE TO DESCRIBE IT. The arithmetic was right for a fleet with no pinned pools. The failure mode
is the quiet one — a plan that refuses a safe configuration teaches an operator to stop reading
plans.

DERIVED FROM THE SCRIPTS, LIKE THE BASELINE. Nothing here reads a live subscription; it reads
`azure_baseline`, which parses `deploy/public/*.sh`. Change a replica range in the script and this
document changes, or `scripts/gen_azure_current.py --check` fails. What the scripts cannot say —
the three items in `azure_parity.UNVERIFIABLE` — this cannot say either, and the generated file
carries that warning rather than reading as a complete description of the estate.
"""
from __future__ import annotations

from typing import Any

from . import presets
from .azure_baseline import baseline, secret_names

# Facts about today's Azure that this document states DIFFERENTLY from the deployment, or cannot
# state at all — each with why. Rendered into the generated report, because a derived document
# that silently smooths over what it could not express is the failure this whole exercise exists
# to prevent.
NOT_EXPRESSIBLE: dict[str, str] = {
    "secrets.provider": (
        "Production keeps its secrets in the CONTAINER APP's own secret store (`secretref:` in "
        "deploy.sh), which is not one of the six backends the contract offers. Recorded here as "
        "`azure-key-vault` because that is the adapter a rebuild would use — presets.py already "
        "says ACA is the legacy path the contract does not target, and no rebuild on AKS could "
        "carry the ACA secret store across anyway. So this one field describes the TARGET, not "
        "today, and it is the only field in this document that does."),
    "data.postgres.backupRetentionDays": (
        "`deploy/public/` does not provision the Postgres server — it is created outside these "
        "scripts — so backup retention is not derivable from them. Deliberately left unstated "
        "rather than guessed at Azure's default, which makes the document fail validation. That "
        "failure is the finding: the Azure adapter has to own server provisioning before this "
        "document can honestly claim a retention period."),
    "metadata.region": (
        "deploy.sh takes the region from its environment, so the scripts do not record one."),
}

# The Postgres server production actually runs. NOT the number that makes the arithmetic
# comfortable: `api/store.py`'s own docstring records 150 as confirmed live, the schema's
# `maxConnections` description repeats it, and #1370 exists because of it. The standard-production
# EXAMPLE declares 700, which is a plausible managed tier and not this server — one of the reasons
# a document describing today's Azure had to be derived rather than adapted from that example.
PRODUCTION_MAX_CONNECTIONS = 150

# cpu/memory -> preset. The contract sizes tiers by preset, not by free-form quantities, so a
# derived document has to land on one; an Azure app whose size matches no preset is a real finding
# (the contract cannot express it) rather than something to round to the nearest row.
_BY_SIZE = {(float(row["cpu"]), row["memory"]): name for name, row in presets.PRESETS.items()}

# What each worker tier's autoscaler watches, where the scripts give it a scale rule. Only
# remediate has one in this repository today (#1370's `remediation-queue`, a postgresql trigger on
# the lane's job types) — which is queue depth by any other name. Discovery's rule is referenced by
# rightsize-production.sh but applied outside these scripts, so it is NOT recorded here: see
# azure_parity.UNVERIFIABLE. Inventing a signal for it would put a guess in a generated document.
_SIGNALS = {"remediate": ["queue-depth"]}


class NotExpressible(Exception):
    """The scripts configure something the contract has no vocabulary for.

    Raised rather than approximated. A derived document that silently rounds an unrepresentable
    value is worse than no document: it reads as proof the contract fits, which is the exact claim
    this module exists to test.
    """


def _preset_for(cpu: float | None, memory: str | None, *, app: str) -> str:
    if cpu is None or memory is None:
        raise NotExpressible(f"{app}: the scripts do not state cpu/memory")
    key = (cpu, memory)
    if key not in _BY_SIZE:
        raise NotExpressible(
            f"{app}: {cpu} cpu / {memory} matches no preset in acpctl.presets — the contract "
            f"sizes tiers by preset, so this app cannot be described without adding one")
    return _BY_SIZE[key]


def _tier(app, tier_name: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "replicas": {"min": app.min_replicas, "max": app.max_replicas},
        "resources": {"preset": _preset_for(app.cpu, app.memory, app=app.name)},
    }
    # `autoscaled` is min < max, deliberately: a tier pinned at 5-5 does not scale whatever rules
    # are attached to it, and recording an autoscale block for one would misdescribe the warm pool
    # the operator chose. Signals come from the scripts, never from what the tier "should" watch.
    if app.autoscaled and tier_name in _SIGNALS:
        out["autoscale"] = {"signals": list(_SIGNALS[tier_name])}
    if app.db_pool:
        out["connectionPool"] = app.db_pool
    return out


def derive(*, version: str, name: str = "acp-production") -> dict[str, Any]:
    """The document that describes today's Azure. A pure function of the parsed scripts."""
    apps = baseline()
    by_tier = {app.tier: app for app in apps.values() if app.tier}
    missing = [t for t in ("api", "discover", "assess", "remediate") if t not in by_tier]
    if missing:
        raise NotExpressible(
            f"the scripts configure no app for {', '.join(missing)} — either the deployment "
            f"changed shape or azure_baseline's parse went short")

    ollama = apps.get("acp-ollama")
    return {
        "apiVersion": "packaging.acp.mova.io/v1alpha1",
        "kind": "ACPDeployment",
        "metadata": {
            "name": name,
            "environment": "production",
            # The scripts do not state a region — `deploy.sh` takes it from the environment — so
            # this is deliberately absent rather than guessed. `region` is optional in the schema
            # for exactly this kind of fact.
        },
        "runtime": {
            "version": version,
            # STANDARD, not high-availability: production runs one API replica at its floor and
            # the HA profile requires more. Recording the profile it MEETS rather than the one it
            # aspires to is the difference between a description and a wish.
            "profile": "standard",
            "platform": "azure",
            "publicUrl": "https://acp.example.com",
        },
        "api": _tier(by_tier["api"], "api"),
        "workers": {t: _tier(by_tier[t], t) for t in ("discover", "assess", "remediate")},
        "data": {
            # Azure Database for PostgreSQL, Azure Managed Redis and Blob Storage — the adapter
            # services in presets.PLATFORM_ADAPTER, all provider-run.
            "postgres": {"mode": "managed", "maxConnections": PRODUCTION_MAX_CONNECTIONS},
            "redis": {"mode": "managed"},
            "objectStorage": {"mode": "managed"},
        },
        "ai": {
            "mode": "local-only",
            "ollama": {"enabled": ollama is not None, "gpu": "acp-ollama-gpu" in apps},
        },
        "observability": {
            "openTelemetry": True,
            "exporter": "azure-monitor",
            "grafana": "acp-grafana" in apps,
        },
        "network": {
            # Every worker app is created without ingress and only acp-app is external — which is
            # read from the scripts below rather than asserted, so a script that opened a worker
            # to the internet would change this document instead of being papered over.
            "privateWorkers": all(
                by_tier[t].ingress in (None, "internal")
                for t in ("discover", "assess", "remediate")),
            "publicIngress": by_tier["api"].ingress == "external",
        },
        "secrets": _secrets(),
    }


# The contract's required-reference names, and the ACA secret whose presence proves the deployment
# holds a credential for it. Only names the scripts actually wire are mapped: `object-storage` is
# deliberately absent, because there is no storage secret to map — see `_secrets`.
_REF_FROM_ACA_SECRET = {"database-url": "database-url", "redis-url": "redis-url"}


def _secrets() -> dict[str, Any]:
    """The secret posture, read from the scripts rather than assumed.

    THE INTERESTING ENTRY IS THE ONE THAT IS NOT A SECRET. `deploy.sh` wires `secretref:` values
    for the database and Redis URLs, so those are stored credentials and are declared as
    references. It wires NOTHING for Blob Storage: the worker's managed identity is granted
    Storage Blob Data Contributor and reaches the account with no credential at all. Before
    `secrets.workloadIdentity` existed, describing that honestly was impossible — the contract
    required an `object-storage` reference, and the only way to pass validation was to claim a
    credential the deployment does not have.
    """
    present = secret_names()
    refs = {
        ref: {"name": aca, "key": "value"}
        for ref, aca in sorted(_REF_FROM_ACA_SECRET.items()) if aca in present
    }
    return {
        "provider": "azure-key-vault",   # the rebuild target; see NOT_EXPRESSIBLE
        "refs": refs,
        "workloadIdentity": ["object-storage"],
    }
