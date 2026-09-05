"""`acpctl init` — a deployment document that is valid the moment it is written.

WHAT MAKES THIS MORE THAN A TEMPLATE. The contract has 37 semantic rules on top of its schema, and
they interact: `regulated` requires local-only AI *and* local telemetry *and* customer-managed
keys *and* ≥30-day retention; `evaluation` is Compose-only and Compose has no managed data
services; which secret providers are legal depends on the platform; which secret refs are REQUIRED
depends on which data services are external and which connectors are enabled. An operator who
starts from a copied example meets those rules one validation error at a time.

So the defaults here are DERIVED FROM THE SAME POLICY TABLES THE VALIDATOR ENFORCES —
presets.PLATFORM_DATA_MODES, PLATFORM_SECRET_PROVIDERS, PROFILE_MIN_REPLICAS, SUPPORT_STATUS — and
never from a second copy of them. A generator with its own idea of what `regulated` means would
drift from the validator, and the failure would be a document that init produced and validate
rejects, which is the worst possible first experience of a tool.

THE INVARIANT, AND IT IS TESTED ACROSS THE WHOLE MATRIX: every document this module emits passes
`spec.validate` with no errors. tests/test_packaging_init.py runs every legal (profile, platform)
pair through init and then through the real validator. That test is also what makes hand-written
YAML safe here — see `render` below for why the output is authored as text rather than dumped.

IT INVENTS NO SECRET VALUES. Every credential is a REFERENCE to a vault entry, with a name the
operator must replace. PRD S13: values never appear in configuration output. A generator that
emitted a placeholder password would be a generator whose output gets committed with it.
"""
from __future__ import annotations

from typing import Any

from . import presets

PROFILES = ("evaluation", "standard", "regulated", "high-availability")
PLATFORMS = ("azure", "aws", "gcp", "kubernetes", "onprem", "compose")

# Which platforms each profile can run on. `evaluation` is Compose-only by contract (single
# machine, no HA), and the production profiles cannot run on Compose for the same reason read the
# other way round. Kept here so `init` REFUSES an impossible combination up front, naming the
# rule, rather than emitting a document that validate then rejects.
PROFILE_PLATFORMS: dict[str, tuple[str, ...]] = {
    "evaluation": ("compose",),
    "standard": ("azure", "aws", "gcp", "kubernetes", "onprem"),
    "regulated": ("azure", "aws", "gcp", "kubernetes", "onprem"),
    "high-availability": ("azure", "aws", "gcp", "kubernetes", "onprem"),
}

# Resource preset per tier, per profile. The assess and remediate tiers do the rasterisation, so
# they get the larger preset everywhere it is allowed; evaluation stays small because it is one
# machine.
_TIER_PRESETS: dict[str, dict[str, str]] = {
    "evaluation": {"api": "small", "discover": "small", "assess": "small", "remediate": "small"},
    "standard": {"api": "small", "discover": "small", "assess": "standard", "remediate": "standard"},
    "regulated": {"api": "small", "discover": "small", "assess": "standard", "remediate": "standard"},
    "high-availability": {"api": "standard", "discover": "small", "assess": "standard",
                          "remediate": "standard"},
}

# Headroom above the profile floor. A max equal to the min is a tier that cannot absorb a spike,
# which defeats the autoscaling the contract asks for; these are starting points an operator is
# expected to size properly, and the comment in the rendered document says so.
_HEADROOM = {"api": 2, "discover": 2, "assess": 7, "remediate": 7}

# EXCEPT ON A SINGLE MACHINE, WHERE HEADROOM IS A LIE. The evaluation profile runs on Compose,
# which has no autoscaler at all — so a replica ceiling above the floor describes capacity that
# nothing can ever reach, while still costing the deployment its full connection budget.
#
# The contract catches this: `data.connection-budget` computes the fleet's worst case from the
# MAXIMUM replicas (each pool is ACP_WORKERS + 16, per api/store.py), and the first draft's
# evaluation defaults needed 372 connections against an embedded Postgres declared at 100. The
# rule was right and the generator was wrong — the fix is not a bigger number, it is a ceiling
# that matches what a single machine can actually run.
_EVALUATION_HEADROOM = {"api": 0, "discover": 0, "assess": 0, "remediate": 0}

# TAKEN FROM THE SCHEMA'S ENUM, not from what each cloud's telemetry product is called. The first
# draft guessed "aws-otel" and "otlp" from the shape of the names, and failed validation on 12 of
# the 16 combinations. The generator's entire promise is that its output is valid, so every value
# here is one the contract actually accepts — and the matrix test is what keeps that true.
_EXPORTERS = {"azure": "azure-monitor", "aws": "cloudwatch", "gcp": "google-cloud-monitoring"}

# PRD S14: the regulated profile keeps telemetry inside the boundary, and Compose has no cloud
# monitoring service to export to. `local` is the schema's name for that.
_LOCAL_EXPORTER = "local"

_VAULT_NAME = {"azure-key-vault": "acp-kv", "aws-secrets-manager": "acp/secrets",
               "gcp-secret-manager": "acp-secrets", "external-secrets": "acp-store",
               "kubernetes": "acp-secrets", "env-file": ".env"}


class InitError(ValueError):
    """A combination `init` will not generate, with the reason. Raised rather than emitted, so a
    document that cannot be valid is never written at all."""


def _data_mode(platform: str, profile: str) -> str:
    """The data-service mode for this platform, preferring managed where it exists.

    PRD S22 forbids silently downgrading a production profile to embedded services, and
    presets.PLATFORM_DATA_MODES already records what each platform can actually offer — so this
    takes the first mode that table lists rather than deciding independently. `onprem` has no
    provider to point at and gets self-hosted; `compose` gets embedded, which is why it is
    evaluation-only.
    """
    modes = presets.PLATFORM_DATA_MODES[platform]
    return "managed" if "managed" in modes else modes[0]


def _secret_provider(platform: str) -> str:
    """The first provider the platform supports, which is its native one by table order."""
    return presets.PLATFORM_SECRET_PROVIDERS[platform][0]


def _replicas(profile: str, tier: str) -> dict[str, int]:
    low = presets.PROFILE_MIN_REPLICAS[profile][tier]
    headroom = _EVALUATION_HEADROOM if profile == "evaluation" else _HEADROOM
    # The schema requires max >= 1 even where the floor is 0 — the evaluation profile lets the
    # discover tier idle at zero replicas, but a ceiling of zero would describe a tier that can
    # never run at all.
    return {"min": low, "max": max(low + headroom[tier], 1)}


def build(*, profile: str, platform: str, name: str, environment: str, release: str,
          region: str | None = None, public_url: str | None = None,
          registry: str | None = None) -> dict[str, Any]:
    """The document as plain data. `render` turns it into commented YAML."""
    if profile not in PROFILES:
        raise InitError(f"unknown profile {profile!r}; choose from {', '.join(PROFILES)}")
    if platform not in PLATFORMS:
        raise InitError(f"unknown platform {platform!r}; choose from {', '.join(PLATFORMS)}")
    allowed = PROFILE_PLATFORMS[profile]
    if platform not in allowed:
        raise InitError(
            f"the {profile!r} profile cannot run on {platform!r} — it is defined for "
            f"{', '.join(allowed)}. (Rule `profile.platform`: the evaluation profile is "
            f"single-machine Docker Compose, and the production profiles need a cluster.)")

    regulated = profile == "regulated"
    ha = profile == "high-availability"
    compose = platform == "compose"
    mode = _data_mode(platform, profile)
    provider = _secret_provider(platform)
    vault = _VAULT_NAME[provider]

    workers = {}
    for tier in ("discover", "assess", "remediate"):
        block: dict[str, Any] = {
            "replicas": _replicas(profile, tier),
            "resources": {"preset": _TIER_PRESETS[profile][tier]},
        }
        if not compose:
            # Compose has no autoscaler, so declaring signals there would describe something that
            # cannot happen. Everywhere else the queue signals are the ones PRD S11 prefers,
            # because CPU lags a batch workload (see the chart's autoscaling template).
            block["autoscale"] = {
                "signals": ["queue-depth", "oldest-job-age"],
                "queueDepthTarget": 20 if tier == "discover" else 10,
                "oldestJobAgeSeconds": 300 if tier == "discover" else 180,
            }
        workers[tier] = block

    api: dict[str, Any] = {
        "replicas": _replicas(profile, "api"),
        "resources": {"preset": _TIER_PRESETS[profile]["api"]},
    }
    if not compose:
        api["autoscale"] = {"signals": ["concurrent-requests", "cpu"]}

    doc: dict[str, Any] = {
        "apiVersion": "packaging.acp.mova.io/v1alpha1",
        "kind": "ACPDeployment",
        "metadata": {"name": name, "environment": environment},
        "runtime": {
            "version": release,
            "profile": profile,
            "platform": platform,
            "publicUrl": public_url or f"https://acp.{name}.example.org",
        },
        "api": api,
        "workers": workers,
        "data": {
            "postgres": {
                "mode": mode,
                # Retention is a profile rule, not a preference: production needs a week,
                # regulated needs a month. Set from the profile so the generated document does
                # not have to be corrected to pass its own validation.
                "backupRetentionDays": 35 if regulated else 7 if profile != "evaluation" else 1,
                "storage": "256Gi" if profile != "evaluation" else "32Gi",
                "maxConnections": 700 if profile != "evaluation" else 100,
            },
            "redis": {"mode": mode},
            "objectStorage": {
                "mode": mode,
                # PRD S13: the regulated profile requires customer-managed keys.
                "encryption": "customer-managed" if regulated else "provider-managed",
                "retentionDays": 2555 if regulated else 365,
            },
        },
        # PRD S13 again: regulated means no document content leaves for a model. Defaulted to
        # local-only for EVERY profile rather than only where it is required — the safer setting
        # is the better default, and an operator who wants a cloud model is making a decision they
        # should make deliberately.
        "ai": {"mode": "local-only", "ollama": {"enabled": True, "modelVolume": "200Gi",
                                                "gpu": not compose}},
        "observability": {
            "openTelemetry": True,
            "exporter": _LOCAL_EXPORTER if (regulated or compose)
                        else _EXPORTERS.get(platform, _LOCAL_EXPORTER),
            "grafana": True,
            "langfuse": {"mode": "self-hosted" if not compose else "disabled"},
        },
        "network": {
            # PRD S13: workers hold document content and are reachable by nothing.
            "privateWorkers": True,
            "publicIngress": True,
            "allowedEgress": ["googleapis.com", "graph.microsoft.com"],
        },
        "secrets": {"provider": provider, "refs": {}},
        "sources": ["google-drive", "sharepoint", "local-upload"],
        "capacity": {
            "maxSourceFileSizeMb": presets.DEFAULT_MAX_SOURCE_FILE_MB,
            "concurrentFilesPerWorker": presets.DEFAULT_CONCURRENT_FILES_PER_WORKER,
            "expectedDocumentsPerDay": 20000 if profile != "evaluation" else 500,
        },
    }
    if region:
        doc["metadata"]["region"] = region
    if registry:
        doc["runtime"]["imageRegistry"] = registry
    if ha:
        doc["data"]["postgres"]["highAvailability"] = True
        doc["data"]["redis"]["highAvailability"] = True

    # WHICH REFS ARE REQUIRED IS DERIVED, NOT LISTED. spec.py decides from the document itself —
    # redis-url only when redis is not embedded, langfuse-secret-key only when langfuse is on,
    # a connector secret per enabled source. Rebuilding that logic here would be a second copy
    # that goes stale the first time a connector is added; this asks the same question of the
    # same document.
    doc["secrets"]["refs"] = {
        key: {"name": vault, "key": key} for key in _required_refs(doc)
    }
    return doc


def _required_refs(doc: dict) -> list[str]:
    """The secret names this document's own configuration makes mandatory.

    CALLS THE VALIDATOR'S OWN FUNCTION rather than restating the rule. `spec.required_secret_names`
    is what `validate` uses and what `plan` prints, so init cannot disagree with either about what
    a configuration needs — and a connector added later gets its secret into generated documents
    without anyone remembering this file exists.

    Imported directly, with no fallback. A defensive copy of the logic here would be a second
    implementation that goes stale silently; if the function is ever renamed, an ImportError names
    the problem immediately, which is the failure worth having.
    """
    from .spec import required_secret_names

    return list(required_secret_names(doc))


# ── rendering ─────────────────────────────────────────────────────────────────

_SECTION_NOTES: dict[str, str] = {
    "metadata": "Who this deployment is. `name` also defaults the namespace acpctl reads.",
    "runtime": (
        "`version` is the ACP release. `profile` and `platform` are enforced, not decorative:\n"
        "changing either changes what the contract requires of everything below."),
    "api": (
        "The request tier. It scales on request load, which an HPA can see natively — unlike the\n"
        "worker tiers below."),
    "workers": (
        "One tier per stage, scaled independently. They scale on QUEUE DEPTH and the age of the\n"
        "oldest job rather than on CPU: a worker chewing through a large PDF is at 100% CPU\n"
        "whether the queue holds one job or four hundred, so CPU would scale up when documents\n"
        "are hard and not when they are numerous.\n"
        "\n"
        "The replica ceilings are STARTING POINTS. Size them against your own throughput — and\n"
        "note they drive the Postgres connection budget, which `acpctl validate` checks."),
    "data": (
        "Postgres, Redis and object storage. `mode: managed` points the release at the provider\'s\n"
        "services; the application package is identical either way (ADR 0048). The Helm chart does\n"
        "NOT provision in-cluster data services — see packaging/README.md."),
    "ai": (
        "`local-only` keeps document content inside the boundary. It is the default for every\n"
        "profile here, not only where the contract requires it: sending customer documents to a\n"
        "hosted model should be a decision somebody makes, not one they inherit."),
    "observability": "Telemetry. The regulated profile keeps it local by rule, not by preference.",
    "network": (
        "Workers hold document content and are reached by nothing — `privateWorkers` says so.\n"
        "`allowedEgress` records intent: hostname egress cannot be enforced by a Kubernetes\n"
        "NetworkPolicy (it matches on IP), so a FQDN-aware policy engine or an egress proxy is\n"
        "what actually enforces it. `acpctl doctor` reports what your cluster can enforce."),
    "secrets": (
        "REFERENCES ONLY. No value ever appears in this document, in rendered Helm values, or in\n"
        "a support bundle. Replace the vault name and keys with your own; `acpctl validate`\n"
        "refuses a document that inlines a literal."),
    "sources": "Connectors to enable. Each one needing a credential adds a required secret ref.",
    "capacity": (
        "Planning inputs. `maxSourceFileSizeMb` and `concurrentFilesPerWorker` set the temporary\n"
        "storage floor per worker — the factors behind it are declared planning constants, not\n"
        "measurements, and `acpctl plan` says so."),
}

_HEADER = """\
# ACP deployment document — generated by `acpctl init`.
#
# THIS IS THE RECORD OF WHAT WAS INSTALLED. Everything downstream reads it: `acpctl validate`
# checks it against the contract, `plan` explains it, `values` renders the Helm values from it,
# `doctor` checks that a cluster can run it, and `status` compares it against what is actually
# running. Edit this file and regenerate — do not hand-edit the values, or the two disagree and
# this file stops being the record.
#
# It is valid as generated, but the defaults are STARTING POINTS and three things below are
# placeholders you are expected to replace:
#
#   runtime.publicUrl      the hostname ACP is served on
#   runtime.imageRegistry  where your images are pulled from
#   secrets.refs.*         the vault entries holding your credentials
#
# Check it before installing:   python -m acpctl validate {path}
"""


def render(doc, *, path_hint: str = "<this file>") -> str:
    """The document as commented YAML.

    AUTHORED AS TEXT, NOT DUMPED, because the comments are the point. A `yaml.safe_dump` of the
    dict is a wall of keys, and this file is the one an operator reads, edits and keeps — the note
    explaining why a worker scales on queue depth rather than CPU is worth more than the key it
    sits above.

    The risk of hand-assembled YAML is malformed output, and the mitigation is structural: each
    section\'s BODY is dumped by PyYAML, so indentation and quoting are the library\'s problem
    rather than mine, and only the comments BETWEEN sections are authored. What closes the gap
    entirely is tests/test_packaging_init.py, which parses the rendered text back and requires it
    to equal the dict it came from — so a formatting error is a test failure rather than a
    support ticket.
    """
    import yaml

    out = [_HEADER.format(path=path_hint)]
    for key, value in doc.items():
        note = _SECTION_NOTES.get(key)
        if note:
            out.append("\n" + "\n".join(f"# {line}" if line else "#"
                                         for line in note.split("\n")))
        body = yaml.safe_dump({key: value}, sort_keys=False, default_flow_style=False,
                              width=100, allow_unicode=True)
        out.append(body.rstrip("\n"))
    return "\n".join(out) + "\n"
