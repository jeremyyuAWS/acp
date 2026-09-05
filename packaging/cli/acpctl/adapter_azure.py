"""What the Azure adapter must provision for a deployment document to be true.

PRD §21 phase 3: "rebuild the current Azure deployment using the common contract... add managed
service and private-network options". Slice 1 wrote down what production runs; slice 2 derived a
document that describes it and found two things the contract could not say. This is the third
question, and it is the one that decides whether either of those artifacts means anything:

    WHO MAKES THE DOCUMENT TRUE?

A document says `postgres.mode: managed` with a 150-connection ceiling and 35-day backups. Nothing
in this repository creates that server. It says `secrets.workloadIdentity: [object-storage]`, and
nothing creates the identity, the federated credential or the role assignment that make the
workload actually reach Blob Storage. `deploy/public/deploy.sh` is explicit about the gap in its
own comment — the role grant is "one-time infra setup (not this script's job)" — and equally
explicit about how the omission surfaces: "else remediation blob writes 403 from the worker tier".
After deploy. Under load. On the tier with no ingress to check it from.

THAT IS THE FAILURE SHAPE THIS MODULE EXISTS FOR. A declaration with no owner reads as a
configured fact on every screen that shows it, and slice 2 added one — `workloadIdentity` — that
had exactly this property. So each requirement here traces to the document field or derived
quantity that produced it, and the requirements for an identity are the THREE resources it takes,
not the one boolean that claims it.

DERIVED, NOT VALIDATED. The connection ceiling is the sharpest case. Today's contract has the
operator TYPE a `maxConnections` and checks the fleet against it; that catches a server too small
but cannot tell the adapter what to build. Here the demand is the input: this fleet needs N
connections, so provision a server that provides at least N. The document's declared value becomes
a claim to check rather than the source of truth.

WHAT THIS DOES NOT DO, and the boundary is deliberate:

  * It does not emit Terraform or Bicep. There is no `terraform`, `az` or `bicep` in the
    environment this was written in, so generated IaC could not be validated — and unvalidated
    infrastructure code that looks runnable is worse than a requirements list that admits it is
    one. What this produces is the specification an adapter author implements against.
  * It does not contact Azure, read a subscription, or touch production.
  * It does not invent vendor limits. Azure's max_connections varies by SKU; that table is not
    reproduced here from memory. Where a requirement depends on a vendor fact this repository
    cannot check, it is marked `VENDOR` and says what has to be looked up, rather than asserting a
    number that would read as verified.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Where a requirement comes from — and specifically, how much this repository can vouch for it.
DOCUMENT = "document"     # stated outright in the deployment document
DERIVED = "derived"       # computed from the document by code in this package
PROFILE = "profile"       # imposed by the profile the document declares (PRD S8)
VENDOR = "vendor"         # depends on an Azure fact this repository cannot verify offline

from .inventory import SERVER_RESERVED_CONNECTIONS


@dataclass
class Requirement:
    """One setting the adapter must provision, and where it came from."""

    resource: str
    setting: str
    value: Any
    because: str
    source: str = DERIVED

    def render(self) -> str:
        return f"{self.resource}.{self.setting} = {self.value!r}  ({self.source}: {self.because})"


# Settings the adapter MUST decide that this contract does not express. Named rather than left
# implicit: an adapter author reading only the requirements below would otherwise conclude the list
# is complete, and pick a SKU, a region and an address space by accident.
UNOWNED: dict[str, str] = {
    "compute SKU / tier": (
        "The contract sizes WORKLOADS by preset and says nothing about the node pool or database "
        "tier that has to fit them. An adapter must map the fleet's total requests to a node SKU "
        "and the connection ceiling to a Postgres tier — and the second is a vendor lookup: "
        "Azure's max_connections is a function of the server's SKU, and that table is not "
        "reproduced here from memory."),
    "region": (
        "`metadata.region` is optional and free text; the contract records a residency boundary "
        "and does not choose a datacentre."),
    "VNet address space": (
        "Private endpoints and a private control plane need a network the contract has no "
        "vocabulary for. Deliberately so: an address plan belongs to the customer's estate, not "
        "to an application's deployment document."),
    "backup destination and restore drill": (
        "Retention is a number the contract can carry; whether a restore has ever been "
        "PERFORMED is not, and PRD S16 wants both. An adapter that provisions 35-day backups has "
        "satisfied this list and not the requirement."),
}


def _postgres(doc: dict[str, Any], out: list[Requirement]) -> None:
    from .inventory import connection_budget

    postgres = doc["data"]["postgres"]
    mode = postgres["mode"]
    if mode != "managed":
        out.append(Requirement(
            "postgres", "provisioning", mode,
            f"the document asks for a {mode} Postgres, so the Azure adapter provisions no server; "
            f"the chart runs it in-cluster and the cluster's storage class becomes the durability "
            f"boundary", DOCUMENT))
        return

    budget = connection_budget(doc)
    demand = budget["worstCaseConnections"]
    required = demand + SERVER_RESERVED_CONNECTIONS

    out.append(Requirement(
        "postgres", "provisioning", "Azure Database for PostgreSQL Flexible Server",
        "data.postgres.mode is managed", DOCUMENT))
    out.append(Requirement(
        "postgres", "max_connections", f">= {required}",
        f"the fleet's worst case at maximum replicas is {demand} (acpctl.inventory."
        f"connection_budget, which mirrors api/store.py's db_max_conn per replica), plus "
        f"{SERVER_RESERVED_CONNECTIONS} the server keeps for itself", DERIVED))
    declared = postgres.get("maxConnections")
    if declared is not None and declared < required:
        # NOT the same check the validator already runs. `data.connection-budget` fails when the
        # fleet's demand EXCEEDS the declared ceiling; this fires in the band between the demand
        # and the demand plus the server's own reserve — where the document validates cleanly and
        # a real server still runs out, because the connections the fleet does not use are not all
        # spare. The symptom is the operator's own psql session being refused during the incident
        # they opened it to investigate.
        out.append(Requirement(
            "postgres", "max_connections.conflict", f"declared {declared} < required {required}",
            f"data.postgres.maxConnections is {declared}, which clears the fleet's {demand} and "
            f"leaves {declared - demand} for the server itself — fewer than the "
            f"{SERVER_RESERVED_CONNECTIONS} it needs. The document passes validation and the "
            f"server does not", DERIVED))
    out.append(Requirement(
        "postgres", "sku", "one whose max_connections reaches the value above",
        "Azure derives max_connections from the server's vCPU/memory tier, and this repository "
        "cannot check that table offline — so the requirement is stated as the number to satisfy "
        "rather than as a SKU name that would read as verified", VENDOR))

    retention = postgres.get("backupRetentionDays")
    if retention is None:
        out.append(Requirement(
            "postgres", "backup.retentionDays", "UNDECIDED",
            "the document states none. THIS IS THE GAP slice 2 could not close: deploy/public/ "
            "does not provision the server, so no artifact in this repository owned retention and "
            "the derived document had to leave it blank. The adapter owns it now, and an adapter "
            "that provisions a server without setting it has left the decision to Azure's "
            "default", DOCUMENT))
    else:
        out.append(Requirement(
            "postgres", "backup.retentionDays", retention,
            "data.postgres.backupRetentionDays", DOCUMENT))

    if postgres.get("highAvailability"):
        out.append(Requirement(
            "postgres", "highAvailability", "zone-redundant",
            "data.postgres.highAvailability is true; a same-zone standby survives a node failure "
            "and not the zone failure the profile is bought for", DOCUMENT))
    if postgres.get("storage"):
        out.append(Requirement(
            "postgres", "storage", postgres["storage"], "data.postgres.storage", DOCUMENT))


def _redis(doc: dict[str, Any], out: list[Requirement]) -> None:
    redis = doc["data"]["redis"]
    if redis["mode"] != "managed":
        return
    out.append(Requirement(
        "redis", "provisioning", "Azure Managed Redis",
        "data.redis.mode is managed", DOCUMENT))
    if redis.get("highAvailability"):
        out.append(Requirement(
            "redis", "highAvailability", "zone-redundant replication",
            "data.redis.highAvailability", DOCUMENT))


def _storage(doc: dict[str, Any], out: list[Requirement]) -> None:
    storage = doc["data"]["objectStorage"]
    if storage["mode"] != "managed":
        return
    out.append(Requirement(
        "blob", "provisioning", "Storage account + container",
        "data.objectStorage.mode is managed", DOCUMENT))
    if storage.get("encryption") == "customer-managed":
        out.append(Requirement(
            "blob", "encryption", "customer-managed key in Key Vault, with the account granted "
                                  "access to it",
            "data.objectStorage.encryption", DOCUMENT))
    if storage.get("retentionDays"):
        out.append(Requirement(
            "blob", "lifecycle.retentionDays", storage["retentionDays"],
            "data.objectStorage.retentionDays", DOCUMENT))


# Which Azure resource each workload-identity reference has to be granted on, and with what role.
# The role names are Azure's built-ins and the Blob one is the role `deploy/public/deploy.sh`
# already names for exactly this purpose.
_IDENTITY_TARGET: dict[str, tuple[str, str]] = {
    "object-storage": ("the storage account", "Storage Blob Data Contributor"),
    "database-url": ("the Postgres server", "an AAD administrator or a Postgres role mapped to "
                                           "the identity"),
    "redis-url": ("the Redis instance", "Redis Data Owner (or the narrowest data role that "
                                        "covers the queue's operations)"),
}


def _workload_identity(doc: dict[str, Any], out: list[Requirement]) -> None:
    """The three resources behind each declared identity — and why one boolean is not enough.

    `secrets.workloadIdentity: [object-storage]` is a claim that the workload can reach Blob
    Storage without a credential. Making it true on AKS takes a managed identity, a federated
    credential binding it to this exact (issuer, namespace, service account) triple, and a role
    assignment on the target resource. Any one of those missing produces a workload that starts
    cleanly, passes every readiness probe, and returns 403 the first time it writes — which is the
    failure `deploy.sh` predicts in its own comment for the ACA version of the same grant.

    Listing all three is the whole point. A requirements list that said "workload identity:
    enabled" would reproduce the declaration rather than decompose it.
    """
    names = doc["secrets"].get("workloadIdentity") or []
    if not names:
        return

    out.append(Requirement(
        "cluster", "oidcIssuer", "enabled",
        "secrets.workloadIdentity is non-empty; federated credentials are issued against the "
        "cluster's OIDC issuer URL and cannot exist without it", DERIVED))
    out.append(Requirement(
        "cluster", "workloadIdentity", "enabled",
        "the addon that projects the identity token into the pod. Without it the SDK falls back "
        "to whatever else it can find — often the node's identity, which usually has MORE access "
        "than intended and so fails silently in the permissive direction", DERIVED))

    for name in sorted(names):
        target, role = _IDENTITY_TARGET.get(
            name, ("the resource this reference names", "the narrowest data-plane role that "
                                                        "covers the operations it performs"))
        out.append(Requirement(
            f"identity:{name}", "userAssignedIdentity", "one per reference",
            f"secrets.workloadIdentity names {name}. One identity per reference rather than one "
            f"shared: a single identity holding every grant makes each workload as privileged as "
            f"the most privileged one", DOCUMENT))
        out.append(Requirement(
            f"identity:{name}", "federatedCredential",
            "subject = system:serviceaccount:<namespace>:<the chart's service account>",
            "the credential binds the identity to one service account in one namespace; a wrong "
            "subject is not an error at deploy time, it is a 403 at first use", DERIVED))
        out.append(Requirement(
            f"identity:{name}", "roleAssignment", f"{role} on {target}",
            f"deploy/public/deploy.sh already names this grant for the ACA deployment and calls "
            f"it \"one-time infra setup (not this script's job)\" — which is precisely why "
            f"nothing owned it", DERIVED if name == "object-storage" else VENDOR))


def _network(doc: dict[str, Any], out: list[Requirement]) -> None:
    net = doc["network"]
    managed = [name for name in ("postgres", "redis", "objectStorage")
               if doc["data"][name]["mode"] == "managed"]

    if net.get("privateDataServices"):
        out.append(Requirement(
            "network", "privateEndpoints", sorted(managed),
            "network.privateDataServices; every managed service the document uses, because an "
            "installation that reaches one privately and another over the internet has the "
            "posture of the weaker one", DOCUMENT))
        out.append(Requirement(
            "network", "publicNetworkAccess", "disabled on each of those services",
            "a private endpoint ADDS a private route; it does not remove the public one, and a "
            "service left publicly reachable behind a private endpoint is the most common way "
            "this is configured and not achieved", DOCUMENT))
        out.append(Requirement(
            "network", "privateDnsZones", "one per service type, linked to the cluster's VNet",
            "without the zone link the pods resolve the public name and take the public route, so "
            "the endpoint exists and nothing uses it", DERIVED))
    elif managed:
        out.append(Requirement(
            "network", "privateEndpoints", "none",
            "network.privateDataServices is not set, so the managed services keep public "
            "endpoints — which is what today's Azure runs, stated rather than left to be assumed "
            "either way", DOCUMENT))

    if net.get("privateControlPlane"):
        out.append(Requirement(
            "cluster", "apiServerAccess", "private",
            "network.privateControlPlane; reaching the API server then needs a jump host, a VPN "
            "or an authorized-IP range, and an adapter that makes it private without one of those "
            "has locked out the operator too", DOCUMENT))

    if net["publicIngress"]:
        out.append(Requirement(
            "network", "ingress", f"public endpoint for {doc['runtime'].get('publicUrl')}",
            "network.publicIngress with runtime.publicUrl", DOCUMENT))
    if net["privateWorkers"]:
        out.append(Requirement(
            "network", "workerIngress", "none",
            "network.privateWorkers (PRD S13). The chart renders no Service for the worker tiers, "
            "so this needs nothing from the adapter — recorded because a requirement satisfied by "
            "the application layer is easy to re-satisfy expensively in the infrastructure one",
            DOCUMENT))
    if net.get("allowedEgress") is not None:
        allowed = net["allowedEgress"]
        out.append(Requirement(
            "network", "egress", sorted(allowed) if allowed else "deny-all",
            "network.allowedEgress. Deny-all is a valid regulated posture and the contract "
            "already checks it against `sources` and `ai.mode`", DOCUMENT))


def _profile(doc: dict[str, Any], out: list[Requirement]) -> None:
    profile = doc["runtime"]["profile"]
    if profile in ("regulated", "high-availability"):
        out.append(Requirement(
            "cluster", "availabilityZones", ">= 3",
            f"the {profile} profile. A multi-replica tier in a single zone survives a node "
            f"failure and not a zone one, which is the failure the profile is bought for",
            PROFILE))


def requirements(doc: dict[str, Any]) -> list[Requirement]:
    """Everything the Azure adapter must provision for this document to be true."""
    out: list[Requirement] = []
    _postgres(doc, out)
    _redis(doc, out)
    _storage(doc, out)
    _workload_identity(doc, out)
    _network(doc, out)
    _profile(doc, out)
    return out


@dataclass
class Report:
    requirements: list[Requirement] = field(default_factory=list)
    unowned: dict[str, str] = field(default_factory=dict)

    @property
    def unverifiable(self) -> list[Requirement]:
        """Requirements that rest on an Azure fact this repository cannot check."""
        return [r for r in self.requirements if r.source == VENDOR]

    @property
    def undecided(self) -> list[Requirement]:
        return [r for r in self.requirements if r.value == "UNDECIDED"]

    @property
    def conflicts(self) -> list[Requirement]:
        """Where the document's own numbers disagree with what the adapter would have to build."""
        return [r for r in self.requirements if r.setting.endswith(".conflict")]


def report(doc: dict[str, Any]) -> Report:
    return Report(requirements=requirements(doc), unowned=dict(UNOWNED))
