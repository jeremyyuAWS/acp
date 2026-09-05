"""Load an acp-deployment document and decide whether it describes a deployable installation.

Two layers, deliberately separate:

  STRUCTURE  packaging/schema/acp-deployment.schema.json, evaluated by jsonschema_mini. Says
             which fields exist and what shape they have.
  SEMANTICS  the rules below. Says whether a structurally valid document is one ACP will
             actually stand up — profile floors, preset availability per platform, the
             temporary-storage floor, the managed/embedded downgrade guard, secret references,
             and the egress allowlist.

The split matters because the schema is the PUBLISHED contract and has to stay readable by
non-ACP tooling, while the semantic rules encode PRD policy that no JSON Schema can express.
Every semantic rule names the PRD section it comes from so a reviewer can check the rule against
the requirement rather than against this file.

ERRORS vs WARNINGS. An error means the installation would be wrong or unsafe and `validate`
exits 1. A warning means the operator has chosen something legal but worth knowing — a preview
platform, an evaluation topology, an AI lane that is switched off. Warnings never fail; a check
that fails on a legitimate choice trains people to ignore it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import presets
from .jsonschema_mini import Validator

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "acp-deployment.schema.json"

WORKER_TIERS = ("discover", "assess", "remediate")
ALL_TIERS = ("api",) + WORKER_TIERS

# Secret-shaped VALUES, matched against every string in the document (PRD S13: "secrets never
# appear in generated manifests, logs, plans, or support bundles").
#
# THIS DETECTS VALUES, NOT KEY NAMES, and the distinction is the whole rule. A key-name check —
# reject any field called `password` — reads as the obvious implementation and CANNOT FIRE here:
# every object in the schema is `additionalProperties: false`, so a field by that name is already
# a structural error and the semantic rules never run. What the closed schema cannot prevent is a
# secret pasted into a field that legitimately accepts a string, which is the failure that has
# actually happened in this repo: deploy/public/deploy.sh carries a literal `pk-lf-655083d1…`
# Langfuse key as a default.
#
# Deliberately narrow. Each pattern is a shape that is a credential and is not something else;
# entropy heuristics are not used, because a false positive on a region name or a registry host
# would train people to work around this rule rather than fix the document.
_SECRET_VALUE_PATTERNS = (
    # A URI with inline credentials: postgres://user:password@host/db
    (re.compile(r"^[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@"), "a URI with inline credentials"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "a private key"),
    (re.compile(r"^sk-[A-Za-z0-9_-]{8,}"), "an API secret key"),
    (re.compile(r"^(pk|sk)-lf-[A-Za-z0-9]{8,}"), "a Langfuse key"),
    (re.compile(r"^gh[pousr]_[A-Za-z0-9]{16,}"), "a GitHub token"),
    (re.compile(r"^AKIA[0-9A-Z]{12,}"), "an AWS access key id"),
    (re.compile(r"^xox[abprs]-[A-Za-z0-9-]{10,}"), "a Slack token"),
    (re.compile(r"^ey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."), "a JWT"),
)
# Egress hosts each source needs. A source enabled without its host in the allowlist is a
# deployment that will fail at first use with a network error rather than at validation.
_SOURCE_EGRESS = {
    "google-drive": "googleapis.com",
    "sharepoint": "graph.microsoft.com",
}
# Secret references that must be present for a given configuration.
_ALWAYS_REQUIRED_SECRETS = ("database-url",)


@dataclass
class Finding:
    path: str
    message: str
    rule: str

    def render(self) -> str:
        where = self.path or "(document)"
        return f"{where}: {self.message}  [{self.rule}]"


@dataclass
class Result:
    spec: dict[str, Any] | None
    errors: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


# ── loading ───────────────────────────────────────────────────────────────────
def load_document(path: str | Path) -> dict[str, Any]:
    """Parse a .yaml/.yml/.json deployment document into plain Python.

    PyYAML is imported here rather than at module import so that the JSON path — and therefore
    `acpctl validate` on a JSON spec — works with the standard library alone. The air-gapped
    bundle (PRD S17) ships PyYAML; a bare checkout may not have it, and the failure should name
    the missing dependency instead of an ImportError at startup.
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix == ".json":
        return json.loads(text)
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise SystemExit(
            f"cannot read {p}: PyYAML is not installed. Install it, or supply the same document "
            f"as .json (acpctl reads JSON with no third-party dependency)."
        ) from exc
    loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise SystemExit(f"{p}: expected a mapping at the top level, got {type(loaded).__name__}")
    return loaded


def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


# ── validation ────────────────────────────────────────────────────────────────
def validate(document: dict[str, Any]) -> Result:
    result = Result(spec=document)
    for path, message in Validator(load_schema()).validate(document):
        result.errors.append(Finding(path, message, "schema"))
    if result.errors:
        # Semantic rules index into the document freely; running them over a structurally
        # invalid one produces KeyErrors dressed up as findings, which is worse than saying
        # "fix the structure first".
        return result
    for rule in _SEMANTIC_RULES:
        rule(document, result)
    return result


def _tiers(doc: dict) -> dict[str, dict]:
    tiers = {"api": doc["api"]}
    tiers.update({name: doc["workers"][name] for name in WORKER_TIERS})
    return tiers


def _tier_path(name: str) -> str:
    return "api" if name == "api" else f"workers.{name}"


def _rule_replica_bounds(doc: dict, out: Result) -> None:
    """min <= max, per tier."""
    for name, tier in _tiers(doc).items():
        lo, hi = tier["replicas"]["min"], tier["replicas"]["max"]
        if lo > hi:
            out.errors.append(Finding(
                f"{_tier_path(name)}.replicas",
                f"min ({lo}) is greater than max ({hi})", "replicas.bounds"))


def _rule_profile_replica_floor(doc: dict, out: Result) -> None:
    """PRD S8: each profile has a minimum replica count per tier."""
    profile = doc["runtime"]["profile"]
    floors = presets.PROFILE_MIN_REPLICAS[profile]
    for name, tier in _tiers(doc).items():
        floor = floors[name]
        actual = tier["replicas"]["min"]
        if actual < floor:
            out.errors.append(Finding(
                f"{_tier_path(name)}.replicas.min",
                f"profile '{profile}' requires at least {floor} replica(s) on this tier, got "
                f"{actual}", "profile.replica-floor"))


def _rule_preset_available(doc: dict, out: Result) -> None:
    """PRD S11: reject an unsupported size before deployment, not during it."""
    platform = doc["runtime"]["platform"]
    allowed = presets.PLATFORM_PRESETS[platform]
    for name, tier in _tiers(doc).items():
        preset = tier["resources"]["preset"]
        if preset not in allowed:
            out.errors.append(Finding(
                f"{_tier_path(name)}.resources.preset",
                f"preset '{preset}' is not available on platform '{platform}'; available: "
                f"{', '.join(allowed)}", "preset.platform"))


def _rule_preset_consistency(doc: dict, out: Result) -> None:
    """An explicit cpu/memory/ephemeralStorage must agree with the preset it sits beside.

    Stating both is allowed because a manifest that only says 'standard' is unreadable to
    someone sizing a cluster. Letting them DISAGREE is not: the adapters use the preset, so a
    hand-edited cpu figure would be silently discarded.
    """
    for name, tier in _tiers(doc).items():
        res = tier["resources"]
        row = presets.PRESETS[res["preset"]]
        for key in ("cpu", "memory", "ephemeralStorage"):
            stated = res.get(key)
            if stated is None:
                continue
            if key == "cpu":
                agrees = float(stated) == float(row[key])
            else:
                agrees = presets.parse_quantity_gib(stated) == presets.parse_quantity_gib(row[key])
            if not agrees:
                out.errors.append(Finding(
                    f"{_tier_path(name)}.resources.{key}",
                    f"is {stated}, but preset '{res['preset']}' is {row[key]}. The adapters use "
                    f"the preset, so the stated value would be ignored", "preset.consistency"))


# Tiers that hold file bytes on scratch disk, and therefore carry the PRD S12 storage floor.
#
# `discover` is deliberately ABSENT, and this is a fact about the code rather than an assumption:
# ADR 0020 made metadata-only discovery the DEFAULT — api/handlers.py `_defer_analysis_to_assess`
# opens no file and downloads nothing, and the download plus WCAG analysis run at Assess time.
# Sizing the discovery tier for source bytes it never holds would inflate every plan.
#
# THE EXEMPTION HAS A SWITCH. That same function honours ACP_DEFER_ANALYSIS_TO_ASSESS=0, which
# restores the legacy immediate-analysis scan that DOES download at Discover time. Nothing in
# v1alpha1 models that setting, so an installation that sets it invalidates this exemption. When
# the contract grows a field for it, this tuple is what must change.
_STORAGE_BEARING_TIERS = ("assess", "remediate")


def _rule_ephemeral_floor(doc: dict, out: Result) -> None:
    """PRD S12: temporary worker storage is sized from the workload, and is disposable."""
    capacity = doc.get("capacity", {})
    max_mb = capacity.get("maxSourceFileSizeMb", presets.DEFAULT_MAX_SOURCE_FILE_MB)
    concurrent = capacity.get(
        "concurrentFilesPerWorker", presets.DEFAULT_CONCURRENT_FILES_PER_WORKER)
    floor = presets.minimum_ephemeral_gib(max_mb, concurrent)
    for name in _STORAGE_BEARING_TIERS:
        preset = doc["workers"][name]["resources"]["preset"]
        have = presets.parse_quantity_gib(presets.PRESETS[preset]["ephemeralStorage"])
        if have < floor:
            out.errors.append(Finding(
                f"workers.{name}.resources.preset",
                f"preset '{preset}' provides {have:g}Gi of temporary storage, below the {floor}Gi "
                f"floor for {concurrent} concurrent file(s) of up to {max_mb}MB per worker",
                "storage.ephemeral-floor"))


def _rule_data_mode_platform(doc: dict, out: Result) -> None:
    platform = doc["runtime"]["platform"]
    allowed = presets.PLATFORM_DATA_MODES[platform]
    for service in ("postgres", "redis", "objectStorage"):
        mode = doc["data"][service]["mode"]
        if mode not in allowed:
            out.errors.append(Finding(
                f"data.{service}.mode",
                f"mode '{mode}' is not available on platform '{platform}'; available: "
                f"{', '.join(allowed)}", "data.platform"))


def _rule_no_embedded_downgrade(doc: dict, out: Result) -> None:
    """PRD S22: do not silently downgrade from managed production services to embedded ones."""
    profile = doc["runtime"]["profile"]
    if profile not in presets.PRODUCTION_PROFILES:
        return
    for service in ("postgres", "redis", "objectStorage"):
        if doc["data"][service]["mode"] == "embedded":
            out.errors.append(Finding(
                f"data.{service}.mode",
                f"'embedded' runs {service} as a container inside this installation with no "
                f"durability or failover story, which profile '{profile}' cannot claim. Use "
                f"'managed' or 'self-hosted'", "data.no-downgrade"))


def _rule_profile_platform(doc: dict, out: Result) -> None:
    """evaluation and compose imply each other (PRD S8: Evaluation is one machine, Compose)."""
    profile, platform = doc["runtime"]["profile"], doc["runtime"]["platform"]
    if profile == "evaluation" and platform != "compose":
        out.errors.append(Finding(
            "runtime.platform",
            f"profile 'evaluation' is the single-machine Docker Compose topology; platform "
            f"'{platform}' is not that", "profile.platform"))
    if platform == "compose" and profile != "evaluation":
        out.errors.append(Finding(
            "runtime.profile",
            f"platform 'compose' is a single-server topology and cannot carry profile "
            f"'{profile}'. Docker Compose is not the recommended large-scale production "
            f"topology (PRD S5.2)", "profile.platform"))


def _rule_regulated_posture(doc: dict, out: Result) -> None:
    """PRD S8 Regulated: the whole point of the profile is that these are not optional."""
    if doc["runtime"]["profile"] != "regulated":
        return
    if doc["ai"]["mode"] != "local-only":
        out.errors.append(Finding(
            "ai.mode", "profile 'regulated' requires 'local-only' — the profile exists so a "
            "deployment can state that no document content leaves it", "regulated.ai"))
    langfuse = doc["observability"].get("langfuse", {}).get("mode")
    if langfuse == "cloud":
        out.errors.append(Finding(
            "observability.langfuse.mode",
            "profile 'regulated' cannot send traces to hosted Langfuse; use 'self-hosted' or "
            "'disabled'", "regulated.telemetry"))
    exporter = doc["observability"].get("exporter", "local")
    if exporter != "local":
        out.errors.append(Finding(
            "observability.exporter",
            f"profile 'regulated' requires fully local collection (PRD S14); '{exporter}' sends "
            f"telemetry to a provider service", "regulated.telemetry"))
    if doc["data"]["objectStorage"].get("encryption") != "customer-managed":
        out.errors.append(Finding(
            "data.objectStorage.encryption",
            "profile 'regulated' requires customer-managed keys", "regulated.cmk"))
    retention = doc["data"]["postgres"].get("backupRetentionDays", 0)
    if retention < 30:
        out.errors.append(Finding(
            "data.postgres.backupRetentionDays",
            f"profile 'regulated' requires at least 30 days, got {retention}",
            "regulated.retention"))


def _rule_production_backup_retention(doc: dict, out: Result) -> None:
    profile = doc["runtime"]["profile"]
    if profile not in ("standard", "high-availability"):
        return
    retention = doc["data"]["postgres"].get("backupRetentionDays", 0)
    if retention < 7:
        out.errors.append(Finding(
            "data.postgres.backupRetentionDays",
            f"profile '{profile}' requires automatic backups of at least 7 days (PRD S8), got "
            f"{retention}", "production.retention"))


def _rule_ha_posture(doc: dict, out: Result) -> None:
    """PRD S8 HA / S22: do not claim high availability without the services that provide it."""
    if doc["runtime"]["profile"] != "high-availability":
        return
    for service in ("postgres", "redis"):
        if not doc["data"][service].get("highAvailability"):
            out.errors.append(Finding(
                f"data.{service}.highAvailability",
                f"profile 'high-availability' requires {service} high availability; leaving it "
                f"off would claim HA the installation does not have", "ha.data"))


def _rule_private_workers(doc: dict, out: Result) -> None:
    """PRD S13: workers have no public ingress. Explicit in the contract so it is auditable."""
    if not doc["network"]["privateWorkers"]:
        out.errors.append(Finding(
            "network.privateWorkers",
            "must be true — worker tiers have no ingress in any supported topology (PRD S13)",
            "network.private-workers"))


def _rule_public_url(doc: dict, out: Result) -> None:
    has_url = bool(doc["runtime"].get("publicUrl"))
    if doc["network"]["publicIngress"] and not has_url:
        out.errors.append(Finding(
            "runtime.publicUrl",
            "is required when network.publicIngress is true", "network.public-url"))
    if not doc["network"]["publicIngress"] and has_url:
        out.errors.append(Finding(
            "runtime.publicUrl",
            "is set but network.publicIngress is false; the URL would not resolve to this "
            "installation", "network.public-url"))


def _rule_egress_allowlist(doc: dict, out: Result) -> None:
    """PRD S17: an installation with controlled egress needs an explicit allowlist."""
    egress = doc["network"].get("allowedEgress", [])
    if doc["ai"]["mode"] != "local-only" and not egress:
        out.errors.append(Finding(
            "network.allowedEgress",
            f"is empty, but ai.mode is '{doc['ai']['mode']}' — an external AI provider cannot be "
            f"reached under deny-all egress", "egress.ai"))
    for source in doc.get("sources", []):
        host = _SOURCE_EGRESS.get(source)
        if host and not any(host in entry for entry in egress):
            out.errors.append(Finding(
                "network.allowedEgress",
                f"source '{source}' requires egress to {host}, which is not in the allowlist",
                "egress.source"))


def _rule_autoscale_signals(doc: dict, out: Result) -> None:
    """PRD S11: CPU may be a secondary signal but must not be the only one."""
    for name, tier in _tiers(doc).items():
        auto = tier.get("autoscale")
        if not auto:
            continue
        signals = auto["signals"]
        if signals == ["cpu"]:
            out.errors.append(Finding(
                f"{_tier_path(name)}.autoscale.signals",
                "cpu cannot be the only autoscaling signal; queue depth or oldest-job age is the "
                "preferred primary signal (PRD S11)", "autoscale.signals"))
        if name != "api" and "concurrent-requests" in signals:
            out.errors.append(Finding(
                f"{_tier_path(name)}.autoscale.signals",
                "'concurrent-requests' is an ingress signal and worker tiers have no ingress",
                "autoscale.signals"))


def _rule_secret_provider_platform(doc: dict, out: Result) -> None:
    platform = doc["runtime"]["platform"]
    provider = doc["secrets"]["provider"]
    allowed = presets.PLATFORM_SECRET_PROVIDERS[platform]
    if provider not in allowed:
        out.errors.append(Finding(
            "secrets.provider",
            f"'{provider}' cannot be resolved on platform '{platform}'; available: "
            f"{', '.join(allowed)}", "secrets.platform"))


def required_secret_names(doc: dict) -> list[str]:
    """Secret references this configuration cannot run without. Also used by the plan."""
    names = list(_ALWAYS_REQUIRED_SECRETS)
    if doc["data"]["redis"]["mode"] != "embedded":
        names.append("redis-url")
    if doc["data"]["objectStorage"]["mode"] != "embedded":
        names.append("object-storage")
    if doc["observability"].get("langfuse", {}).get("mode", "disabled") != "disabled":
        names.append("langfuse-secret-key")
    sources = doc.get("sources", [])
    if "google-drive" in sources:
        names.append("google-oauth-client-secret")
    if "sharepoint" in sources:
        names.append("microsoft-oauth-client-secret")
    if "smb" in sources:
        names.append("smb-credentials")
    if doc["ai"]["mode"] != "local-only":
        names.append("ai-provider-key")
    return names


def _rule_required_secrets(doc: dict, out: Result) -> None:
    """Every required reference must be satisfied — by a stored secret OR by workload identity.

    WORKLOAD IDENTITY SATISFIES A REQUIREMENT, it does not waive one. The requirement is that the
    installation can reach the service; a stored credential is one way and the platform's own
    identity is another, and the second is the better one — nothing to rotate, mount or leak.

    Before this accepted `workloadIdentity`, a document describing today's Azure had to declare an
    `object-storage` secret that does not exist: production's worker reaches Blob Storage through
    a managed identity granted Storage Blob Data Contributor (deploy/public/deploy.sh), holding no
    storage credential at all. A rule that fails the most secure configuration teaches operators
    to create a credential to satisfy it, which is the opposite of what it is for.
    """
    refs = doc["secrets"]["refs"]
    identity = set(doc["secrets"].get("workloadIdentity") or ())
    for name in required_secret_names(doc):
        if name not in refs and name not in identity:
            out.errors.append(Finding(
                f"secrets.refs.{name}",
                "is required by this configuration and is declared neither as a secret reference "
                "nor under secrets.workloadIdentity", "secrets.required"))


def _rule_workload_identity_is_live(doc: dict, out: Result) -> None:
    """A workloadIdentity entry that satisfies nothing is dead configuration, and reads as care.

    Same guard, same reason, as the acknowledged-difference check in azure_parity: an entry that
    outlives the requirement it answered still looks deliberate to the next reader. A warning
    rather than an error, because a name can legitimately arrive before the configuration that
    requires it — but it should not sit there unnoticed.
    """
    identity = doc["secrets"].get("workloadIdentity") or []
    required = set(required_secret_names(doc))
    for name in identity:
        if name not in required:
            out.warnings.append(Finding(
                f"secrets.workloadIdentity.{name}",
                "satisfies no reference this configuration requires — either a typo or left over "
                "from a configuration that has changed", "secrets.identity-unused"))
        elif name in doc["secrets"]["refs"]:
            out.warnings.append(Finding(
                f"secrets.workloadIdentity.{name}",
                "is also declared as a stored secret reference; the installation will have a "
                "credential it does not need", "secrets.identity-redundant"))


def _rule_no_literal_secrets(doc: dict, out: Result) -> None:
    """PRD S13: the contract carries secret REFERENCES, never values.

    Walks every string in the document rather than the secrets block, because the placement worth
    catching is a credential in a field that accepts free text — a connection string under
    `secrets.refs.database-url.name`, a registry host with a password in it, a token in `region`.
    """
    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else key)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]")
        elif isinstance(node, str):
            for pattern, what in _SECRET_VALUE_PATTERNS:
                if pattern.search(node):
                    out.errors.append(Finding(
                        path,
                        f"looks like {what}. This contract carries secret REFERENCES only — put "
                        f"the value in {doc['secrets']['provider']} and reference it under "
                        f"secrets.refs", "secrets.no-literals"))
                    return

    walk(doc, "")


def _rule_connection_budget(doc: dict, out: Result) -> None:
    """The fleet's worst-case Postgres pool demand must fit the server.

    NOT a theoretical check. api/store.py sizes every replica's pool at ACP_WORKERS +
    _API_HEADROOM_CONN and each replica holds its own, so demand is set by MAX replicas rather
    than by load — which is how a fleet that is comfortable at rest exhausts the server the first
    time it scales out. `psycopg2.pool.PoolError: connection pool exhausted`, 16-64 times per
    revision across five revisions, is what that looked like in production on 2026-08-30.

    An autoscaling range the database cannot support is a misconfiguration whether or not the
    fleet ever reaches it, so this is an error rather than a warning.
    """
    from .inventory import SERVER_RESERVED_CONNECTIONS, connection_budget
    budget = connection_budget(doc)
    demand, ceiling = budget["worstCaseConnections"], budget["serverMaxConnections"]

    # THE LEVERS, NAMED FROM THE DOCUMENT RATHER THAN FROM THE FORMULA. This message used to say
    # "each replica's pool is ACP_WORKERS + 16" and stop there, which stopped being the whole truth
    # when `tier.connectionPool` arrived: a document that pins pools is not using that formula at
    # all, and an operator sent to change ACP_WORKERS would be adjusting a lever with no effect.
    pinned = sorted(
        name for name, tier in [("api", doc["api"])] + sorted(doc["workers"].items())
        if tier.get("connectionPool"))
    # The lever DIRECTION matters as much as its name: demand is what has to come down here, so a
    # pinned pool must be LOWERED. Naming the right knob and the wrong direction is worse than
    # naming neither.
    lever = (f"lower `connectionPool` on {', '.join(pinned)} or the replica ceilings" if pinned
             else "lower the replica ceilings")

    if not budget["withinBudget"]:
        out.errors.append(Finding(
            "data.postgres.maxConnections",
            f"the fleet needs {demand} Postgres connections at maximum replicas "
            f"(acpctl.inventory.pool_per_replica, which mirrors api/store.py's db_max_conn), but "
            f"the server is declared at {ceiling}. Raise the server, {lever}, or put a pooler in "
            f"front of it",
            "data.connection-budget"))
    elif ceiling - demand < SERVER_RESERVED_CONNECTIONS:
        # The band where the document validates and a real server still runs out. Not an error:
        # what a server keeps for itself is a property of the server, and an operator who knows
        # theirs differs should not be blocked by this repository's estimate of it.
        out.warnings.append(Finding(
            "data.postgres.maxConnections",
            f"the fleet's {demand} connections fit under {ceiling}, but leave {ceiling - demand} "
            f"for the server itself — fewer than the {SERVER_RESERVED_CONNECTIONS} a Postgres "
            f"server typically spends on its own reservation, a migration job and an operator's "
            f"session. The first thing refused is usually the psql session opened to investigate "
            f"why things are being refused",
            "data.connection-reserve"))


def _rule_version_consistency(doc: dict, out: Result) -> None:
    """PRD S5.1: every image in a release carries the same version.

    The inventory derives every image tag from runtime.version, so the only way to break this is
    to pin something by hand. Nothing in v1alpha1 allows that yet — this rule exists so the
    contract test has a rule to hold, and so a future per-image override cannot be added without
    a reviewer meeting this requirement.
    """
    version = doc["runtime"]["version"]
    from .inventory import build_inventory  # local import: inventory imports spec for secrets
    for service in build_inventory(doc):
        if service.image_version and service.image_version != version:
            out.errors.append(Finding(
                f"runtime.version",
                f"service '{service.name}' would run image version {service.image_version}, but "
                f"the release is {version}", "release.version-consistency"))


# ── warnings ──────────────────────────────────────────────────────────────────
def _warn_platform_support(doc: dict, out: Result) -> None:
    platform = doc["runtime"]["platform"]
    status = presets.SUPPORT_STATUS[platform]
    if status != "supported":
        out.warnings.append(Finding(
            "runtime.platform",
            f"platform '{platform}' is {status}: no reference deployment in this repository runs "
            f"the contract suite against it yet", "support.status"))


def _warn_evaluation(doc: dict, out: Result) -> None:
    if doc["runtime"]["profile"] == "evaluation":
        out.warnings.append(Finding(
            "runtime.profile",
            "evaluation is a single-machine topology with no high availability and is not a "
            "supported production posture", "profile.evaluation"))


def _warn_ai_off(doc: dict, out: Result) -> None:
    if doc["ai"]["mode"] == "local-only" and not doc["ai"].get("ollama", {}).get("enabled"):
        out.warnings.append(Finding(
            "ai.ollama.enabled",
            "is false under ai.mode 'local-only', so this installation has no AI lane at all. "
            "Assessment still runs; AI-drafted remediation content does not", "ai.no-lane"))


def _warn_capacity_defaults(doc: dict, out: Result) -> None:
    if "capacity" not in doc:
        out.warnings.append(Finding(
            "capacity",
            f"is not stated, so the temporary-storage floor was computed from the defaults "
            f"({presets.DEFAULT_CONCURRENT_FILES_PER_WORKER} concurrent files of up to "
            f"{presets.DEFAULT_MAX_SOURCE_FILE_MB}MB per worker)", "capacity.defaults"))


def _warn_no_backups(doc: dict, out: Result) -> None:
    if doc["data"]["postgres"].get("backupRetentionDays", 0) == 0:
        out.warnings.append(Finding(
            "data.postgres.backupRetentionDays",
            "is 0 — this installation keeps no database backups", "backup.none"))


_SEMANTIC_RULES = (
    _rule_replica_bounds,
    _rule_profile_replica_floor,
    _rule_preset_available,
    _rule_preset_consistency,
    _rule_ephemeral_floor,
    _rule_data_mode_platform,
    _rule_no_embedded_downgrade,
    _rule_profile_platform,
    _rule_regulated_posture,
    _rule_production_backup_retention,
    _rule_ha_posture,
    _rule_private_workers,
    _rule_public_url,
    _rule_egress_allowlist,
    _rule_autoscale_signals,
    _rule_secret_provider_platform,
    _rule_required_secrets,
    _rule_workload_identity_is_live,
    _rule_no_literal_secrets,
    _rule_connection_budget,
    _rule_version_consistency,
    _warn_platform_support,
    _warn_evaluation,
    _warn_ai_off,
    _warn_capacity_defaults,
    _warn_no_backups,
)
