"""The target descriptor — what the suite is being run against, and what it is allowed to do there.

ONE FILE DESCRIBES ONE TARGET: an AKS cluster, a customer's on-prem Kubernetes, a Compose host.
The suite reads it and never writes it, and it is the only place a run learns anything about the
world. That matters for two reasons that pull in the same direction:

  * A scenario that cannot run must say WHY. "Skipped: this target declares no fault injection"
    is a fact about the target, and it belongs in the descriptor rather than in a flag somebody
    remembered to pass.
  * The mutating scenarios (restart a worker tier, scale it down, restore a backup) are
    destructive. Authorisation for them is a property of the target — "this is a certification
    cluster, break it" — not of the person running the command that afternoon.

CAPABILITIES ARE A GRANT, NOT A HINT. `capabilities` in the descriptor is both the answer to "can
this scenario run here" and the allow-list the execution backend is constructed with, so a
scenario cannot reach past what the descriptor granted even if its body tries. See
`backend.SubprocessBackend`, which refuses a mutating verb it was not granted.

CREDENTIALS NEVER REACH THE REPORT. The descriptor may carry a token, a kubeconfig path, a monitor
key — the suite needs them to talk to the target. `Target.as_report_block()` is an ALLOW-LIST of
five fields, not a copy with the secrets removed, because a blocklist silently ships the field
somebody added last week. `secret_values()` then feeds `report.assert_no_secrets`, which greps the
serialised report for every one of them and refuses to write a file that contains one. Redaction
you cannot verify is a promise; this one is checked, and tests/test_packaging_acceptance.py feeds
in a fake credential and asserts it is absent.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Every capability a scenario may require. Closed set, because a typo in a descriptor
# ("fault-injection" vs "faultinjection") would otherwise silently skip a MANDATORY scenario and
# the run would report "not eligible" for a reason nobody could find. `load_target` rejects an
# unknown name instead.
#
# Each entry is "what the target lets the suite do", never "what the target is".
CAPABILITIES: dict[str, str] = {
    "api": "the ACP API is reachable at the descriptor's baseUrl",
    "kubectl": "a kubeconfig context that can read the release's namespace",
    "helm": "helm can read (and, with upgrade, change) the release",
    "workload-restart": "the suite may restart worker pods — destructive, certification targets only",
    "scale-control": "the suite may change replica counts — destructive",
    "fault-injection": "the suite may take Redis/Postgres/object storage/the AI provider away",
    "previous-release": "a previous supported release exists and can be installed first",
    "backup-restore": "backup and restore jobs exist and may be run against real data",
}

# Capabilities whose exercise CHANGES the target. Constructing the backend with any of these is
# the moment the suite stops being read-only, so they are named in one place and the backend's
# verb allow-list is derived from this mapping rather than from scattered literals.
DESTRUCTIVE = frozenset({"workload-restart", "scale-control", "fault-injection",
                         "previous-release", "backup-restore"})


class TargetError(ValueError):
    """The descriptor is unusable. Raised rather than defaulted: a suite that invents a namespace
    runs against something nobody named, and the report would say it certified the wrong cluster."""


@dataclass(frozen=True)
class Release:
    """What is (or is about to be) installed, as the report must record it.

    `pinned` is not decoration. PRD §5.1 requires cloud templates to reference image digests
    rather than mutable tags, and a certification run against `:latest` certifies whatever was in
    the registry that afternoon — the report would name a release it cannot prove it ran. So the
    field is carried into the report and `upgrade-from-previous` reads it: an unpinned target
    cannot demonstrate the upgrade requirement in §15 ("deploy new API and workers by immutable
    digest") no matter how the upgrade behaves.
    """

    version: str = ""
    revision: int = 0
    pinned: bool = False
    # component -> {"repository": str, "digest": str}. The component names are the release images
    # from PRD §5.1 (acp-web-api, acp-discovery-worker, …); the suite does not police the list
    # because a target may legitimately run a subset (no ollama in a regulated install).
    components: dict[str, dict[str, str]] = field(default_factory=dict)
    previous_version: str = ""


@dataclass(frozen=True)
class Target:
    name: str
    platform: str = "kubernetes"
    distribution: str = ""          # aks | eks | gke | k3s | openshift | rke2 | compose | …
    kubernetes_version: str = ""
    namespace: str = "acp"
    kubeconfig_context: str = ""
    base_url: str = ""
    release_name: str = "acp"
    release: Release = field(default_factory=Release)
    capabilities: frozenset[str] = frozenset()
    # Secrets the suite needs to reach the target. Values are NEVER serialised; see the module
    # docstring. Kept as a plain dict so a descriptor can carry whatever a target needs
    # (bearer token, monitor key, basic auth) without this file growing a field per auth scheme.
    credentials: dict[str, str] = field(default_factory=dict)

    def has(self, capability: str) -> bool:
        return capability in self.capabilities

    def missing(self, required) -> list[str]:
        return sorted(c for c in required if c not in self.capabilities)

    def as_report_block(self) -> dict[str, str]:
        """The five fields the report contract defines for `target`, and only those.

        AN ALLOW-LIST, DELIBERATELY. Serialising the dataclass would put `credentials` and
        `kubeconfig_context` in every report the day someone adds a field, and the report is the
        artifact that gets attached to a support ticket.
        """
        return {
            "name": self.name,
            "platform": self.platform,
            "distribution": self.distribution,
            "kubernetesVersion": self.kubernetes_version,
            "namespace": self.namespace,
        }

    def secret_values(self) -> frozenset[str]:
        """Every literal that must not appear anywhere in a serialised report.

        Includes the kubeconfig context and the credential values. The context is not a secret in
        the cryptographic sense, but it routinely names a customer's cluster and subscription, and
        the report is a document that leaves the customer's control.
        """
        out = {str(v) for v in self.credentials.values() if str(v).strip()}
        if self.kubeconfig_context.strip():
            out.add(self.kubeconfig_context.strip())
        return frozenset(out)


def _require(mapping: dict, key: str, where: str) -> Any:
    if key not in mapping or mapping[key] in (None, ""):
        raise TargetError(f"{where}: {key!r} is required and is missing")
    return mapping[key]


def _expand(value: Any) -> Any:
    """`${ACP_ACCEPTANCE_TOKEN}` in a descriptor resolves from the environment.

    WHY THIS EXISTS AT ALL, given that the suite is careful never to print a credential: the
    alternative is operators pasting a real bearer token into a YAML file that then gets attached
    to a ticket alongside the report the suite was careful to redact. An unset variable is an
    ERROR rather than an empty string — a run that silently authenticates as nobody produces a
    page of `unknown` results whose real cause is one missing export.
    """
    if not isinstance(value, str) or not value.startswith("${") or not value.endswith("}"):
        return value
    name = value[2:-1]
    if name not in os.environ:
        raise TargetError(
            f"the descriptor references ${{{name}}} and that variable is not set. Export it, or "
            f"take the field out — an unset credential produces a run of 'unknown' results whose "
            f"cause is invisible in the report.")
    return os.environ[name]


def parse_target(doc: dict, *, source: str = "<dict>") -> Target:
    if not isinstance(doc, dict):
        raise TargetError(f"{source}: the descriptor must be a mapping, got {type(doc).__name__}")

    kind = doc.get("kind", "ACPAcceptanceTarget")
    if kind != "ACPAcceptanceTarget":
        raise TargetError(f"{source}: kind must be ACPAcceptanceTarget, got {kind!r}")

    caps = doc.get("capabilities") or []
    if not isinstance(caps, list):
        raise TargetError(f"{source}: capabilities must be a list")
    unknown = [c for c in caps if c not in CAPABILITIES]
    if unknown:
        raise TargetError(
            f"{source}: unknown capabilities {unknown}. Known: {sorted(CAPABILITIES)}. A "
            f"misspelled capability silently SKIPS the scenarios that need it, and a skipped "
            f"mandatory scenario fails the claim for a reason nobody can find.")

    rel = doc.get("release") or {}
    components = rel.get("components") or {}
    if not isinstance(components, dict):
        raise TargetError(f"{source}: release.components must be a mapping of component -> image")
    parsed_components = {}
    for name, entry in components.items():
        entry = entry or {}
        parsed_components[str(name)] = {
            "repository": str(entry.get("repository", "")),
            "digest": str(entry.get("digest", "")),
        }
    # PINNED IS DERIVED, NOT DECLARED. A descriptor that says `pinned: true` next to a component
    # with no digest would put a false claim in the report, and the report is what a support
    # decision is made from. Every component must carry a digest, and a release with no components
    # at all is not pinned — an empty set is not "all of them".
    pinned = bool(parsed_components) and all(
        c["digest"].startswith("sha256:") for c in parsed_components.values())

    creds = {str(k): str(_expand(v)) for k, v in (doc.get("credentials") or {}).items()}

    return Target(
        name=str(_require(doc, "name", source)),
        platform=str(doc.get("platform", "kubernetes")),
        distribution=str(doc.get("distribution", "")),
        kubernetes_version=str(doc.get("kubernetesVersion", "")),
        namespace=str(doc.get("namespace", "acp")),
        kubeconfig_context=str(_expand(doc.get("kubeconfigContext", "")) or ""),
        base_url=str(_expand(doc.get("baseUrl", "")) or "").rstrip("/"),
        release_name=str(doc.get("releaseName", "acp")),
        release=Release(
            version=str(rel.get("version", "")),
            revision=int(rel.get("revision", 0) or 0),
            pinned=pinned,
            components=parsed_components,
            previous_version=str(rel.get("previousVersion", "")),
        ),
        capabilities=frozenset(str(c) for c in caps),
        credentials=creds,
    )


def load_target(path) -> Target:
    """Read a descriptor from YAML. PyYAML's safe loader only — see the dependency budget."""
    import yaml  # imported here so `--self-test` works even where PyYAML is absent

    text = Path(path).read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    return parse_target(doc if doc is not None else {}, source=str(path))
