"""The release manifest: what one ACP release consists of, and how an install pins it.

WHY THIS IS A SECOND CONTRACT RATHER THAN A FIELD ON THE DEPLOYMENT DOCUMENT. The two answer
different questions and change on different cadences. An acp-deployment document is the
operator's record of ONE installation and lives in their repository; a release manifest is
produced by ACP's build, describes ONE release, and is the same file for every customer. Folding
digests into the deployment document would mean every operator hand-copying eight digests per
upgrade, which is how a "pinned" install comes to run whatever was pasted.

ONE COMPONENT PER BUILT ARTIFACT, NOT PER LOGICAL IMAGE. PRD S5.1 names eight images; the chart
renders four image references; `deploy/public/deploy.sh` builds one application image that serves
the API and all three worker roles. Those three counts are all correct about different things,
and before this contract existed they disagreed silently — `acpctl plan` named `acp-web-api` and
`acp-discovery-worker` while `helm template` deployed `acp` and `acp-worker`, and nothing built
any of the four. So a component here is an artifact that was actually built, and it declares:

  serves        which of PRD S5.1's logical images it provides  (inventory.IMAGES keys)
  chartImages   which of the chart's image components it backs  (acp.image lookup keys)

and the rules below require both sets to be covered exactly once. That is the check that would
have caught the divergence: a manifest cannot claim a release is complete while an image the plan
names, or one the chart pulls, has no artifact behind it.

WHAT THIS MODULE CANNOT DO, STATED SO IT IS NOT ASSUMED. It does not contact a registry, so it
cannot prove a digest exists, cannot verify a signature, and cannot confirm an SBOM is really at
the URI it names. It establishes that the release DECLARES those things and that the declarations
are internally consistent — an unsigned or mixed-revision release is refused before an install is
attempted rather than during one. Verifying signatures against the registry is `acpctl install`'s
job (PRD S13), and this module leaving that gap explicit is the point.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .inventory import IMAGES
from .jsonschema_mini import Validator
from .spec import Finding, load_document

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "acp-release.schema.json"

# The image components the chart's `acp.image` helper can be asked for. COPIED FROM THE CHART AND
# PINNED BY A TEST that reads the templates, for the reason inventory.LANE_JOB_TYPES is copied and
# pinned: acpctl must be able to run out of an air-gapped bundle without a Go template engine, and
# a copy nothing checks is how the two drift. A chart component missing from this tuple would be
# an image the release never pins and the install silently pulls by tag.
CHART_IMAGE_COMPONENTS = ("api", "worker", "ollama", "grafana")

# Reserved TLDs that cannot resolve (RFC 2606 / RFC 6761). A manifest published under one is an
# illustration, and saying so is cheaper than discovering it at `helm install`.
_UNRESOLVABLE_TLDS = (".invalid", ".example", ".test", ".localhost")


@dataclass
class Release:
    """A validated release manifest, reduced to the questions callers ask of it."""

    document: dict[str, Any]

    @property
    def version(self) -> str:
        return self.document["metadata"]["version"]

    @property
    def source_revision(self) -> str:
        return self.document["metadata"]["sourceRevision"]

    @property
    def registry(self) -> str:
        return self.document["metadata"]["registry"]

    @property
    def components(self) -> list[dict[str, Any]]:
        return self.document["components"]

    def component_for_image(self, logical: str) -> dict[str, Any] | None:
        """The artifact serving one of PRD S5.1's logical images (an inventory.IMAGES key)."""
        for component in self.components:
            if logical in component["serves"]:
                return component
        return None

    def component_for_chart(self, chart_component: str) -> dict[str, Any] | None:
        for component in self.components:
            if chart_component in component.get("chartImages", ()):
                return component
        return None

    def chart_digests(self) -> dict[str, str]:
        """`image.digests` for the Helm values — chart component -> digest.

        THE REGISTRY IS NOT INCLUDED, deliberately. A digest names the same bytes wherever the
        image was mirrored to, so the pull location stays the deployment document's
        `runtime.imageRegistry` and an air-gapped installation that copied the release into its
        own registry uses these digests unchanged.
        """
        return {
            name: component["digest"]
            for name in CHART_IMAGE_COMPONENTS
            if (component := self.component_for_chart(name)) is not None
        }

    def chart_repositories(self) -> dict[str, str]:
        """Chart component -> repository path, so the chart stops defaulting to names the build
        does not produce."""
        return {
            name: component["repository"]
            for name in CHART_IMAGE_COMPONENTS
            if (component := self.component_for_chart(name)) is not None
        }


@dataclass
class Result:
    release: Release | None
    errors: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def load_manifest(path: str | Path) -> dict[str, Any]:
    """Parse a release manifest. Same loader as the deployment document, same JSON-without-PyYAML
    guarantee for the air-gapped bundle (PRD S17)."""
    return load_document(path)


def validate(document: dict[str, Any]) -> Result:
    result = Result(release=None)
    for path, message in Validator(load_schema()).validate(document):
        result.errors.append(Finding(path, message, "schema"))
    if result.errors:
        # Same reason as spec.validate: semantic rules index into the document freely, and running
        # them over a structurally invalid one produces KeyErrors dressed up as findings.
        return result
    for rule in _RULES:
        rule(document, result)
    result.release = Release(document)
    return result


# ── rules ─────────────────────────────────────────────────────────────────────
def _rule_one_source_revision(doc: dict, out: Result) -> None:
    """PRD S5.1: 'Images must use the same source revision'.

    This is the rule the acceptance criterion calls a mixed-revision release, and it is worth
    stating why it is an error rather than a warning: a release whose API and workers came from
    different commits can pass every smoke test and still be a combination nobody built, tested,
    or can reproduce from a tag.
    """
    expected = doc["metadata"]["sourceRevision"]
    for index, component in enumerate(doc["components"]):
        actual = component["sourceRevision"]
        if actual != expected:
            out.errors.append(Finding(
                f"components[{index}].sourceRevision",
                f"component '{component['name']}' was built from {actual[:12]} but the release "
                f"declares {expected[:12]}; PRD S5.1 requires one source revision per release",
                "release.mixed-revision"))


def _rule_component_names_unique(doc: dict, out: Result) -> None:
    seen: dict[str, int] = {}
    for index, component in enumerate(doc["components"]):
        name = component["name"]
        if name in seen:
            out.errors.append(Finding(
                f"components[{index}].name",
                f"'{name}' is already used by components[{seen[name]}]; component names are the "
                f"keys the rest of the manifest is read by",
                "release.duplicate-component"))
        else:
            seen[name] = index


def _rule_signed(doc: dict, out: Result) -> None:
    """PRD S5.1: images are cryptographically signed; PRD S13: signatures are verified before
    deployment. An unsigned component cannot be verified later, so it is refused here."""
    for index, component in enumerate(doc["components"]):
        if not component.get("signature"):
            out.errors.append(Finding(
                f"components[{index}]",
                f"component '{component['name']}' declares no signature; PRD S5.1 requires every "
                f"release image to be signed and PRD S13 requires it verified before deployment",
                "release.unsigned"))


def _rule_sbom(doc: dict, out: Result) -> None:
    """PRD S5.1: every image includes an SBOM."""
    for index, component in enumerate(doc["components"]):
        if not component.get("sbom"):
            out.errors.append(Finding(
                f"components[{index}]",
                f"component '{component['name']}' declares no SBOM; PRD S5.1 requires one per "
                f"release image",
                "release.no-sbom"))


def _rule_serves_every_logical_image(doc: dict, out: Result) -> None:
    """Every image `acpctl plan` names has an artifact behind it, and only one.

    THIS IS THE RULE THAT CATCHES THE DIVERGENCE THIS CONTRACT EXISTS FOR. `acpctl plan` prints
    one line per inventory.IMAGES entry. Before there was a manifest, six of those eight names
    were built by nothing at all and the plan said so to a reviewer as if they were artifacts.
    """
    providers: dict[str, list[str]] = {key: [] for key in IMAGES}
    for component in doc["components"]:
        for logical in component["serves"]:
            providers[logical].append(component["name"])
    for logical, names in providers.items():
        if not names:
            out.errors.append(Finding(
                "components",
                f"no component serves the '{logical}' image ({IMAGES[logical]}), which "
                f"`acpctl plan` names for every deployment; a release that does not build it "
                f"cannot install it",
                "release.image-unserved"))
        elif len(names) > 1:
            out.errors.append(Finding(
                "components",
                f"the '{logical}' image is served by {len(names)} components "
                f"({', '.join(sorted(names))}); an installation would have no way to choose",
                "release.image-ambiguous"))


def _rule_backs_every_chart_image(doc: dict, out: Result) -> None:
    """Every image the chart pulls is pinned by exactly one artifact.

    A chart component with no backing artifact is the failure that matters most here, because it
    is SILENT: `acp.image` falls back to the tag when `image.digests` has no entry, so the install
    succeeds and is simply not pinned — which is the state PRD S5.1 exists to prevent.
    """
    backers: dict[str, list[str]] = {name: [] for name in CHART_IMAGE_COMPONENTS}
    for component in doc["components"]:
        for chart_component in component.get("chartImages", ()):
            backers[chart_component].append(component["name"])
    for chart_component, names in backers.items():
        if not names:
            out.errors.append(Finding(
                "components",
                f"no component backs the chart's '{chart_component}' image, so nothing pins it "
                f"and the chart would fall back to the tag — an install that reports success "
                f"while running whatever that tag points at today",
                "release.chart-image-unpinned"))
        elif len(names) > 1:
            out.errors.append(Finding(
                "components",
                f"the chart's '{chart_component}' image is backed by {len(names)} components "
                f"({', '.join(sorted(names))}); image.digests holds one digest per component",
                "release.chart-image-ambiguous"))


def _rule_architectures_are_not_claimed_release_wide(doc: dict, out: Result) -> None:
    """PRD S5.1 supports ARM64 'where all analysis engines permit it' — a per-image fact.

    A WARNING, not an error: a release whose components differ on arm64 is legitimate and common,
    and this is the finding that stops it being SUMMARISED as an arm64 release in a support matrix.
    """
    arm = sorted(c["name"] for c in doc["components"] if "arm64" in c["architectures"])
    if arm and len(arm) != len(doc["components"]):
        without = sorted(c["name"] for c in doc["components"] if "arm64" not in c["architectures"])
        out.warnings.append(Finding(
            "components",
            f"arm64 is built for {', '.join(arm)} but not for {', '.join(without)}, so this "
            f"release is not an arm64 release; state the support per image",
            "release.partial-arm64"))
    for index, component in enumerate(doc["components"]):
        if "amd64" not in component["architectures"]:
            out.errors.append(Finding(
                f"components[{index}].architectures",
                f"component '{component['name']}' does not build amd64; PRD S5.1 requires it on "
                f"every release image",
                "release.no-amd64"))


def _rule_registry_is_reachable_in_principle(doc: dict, out: Result) -> None:
    """A WARNING that the manifest is an illustration.

    Nothing here contacts a registry, so this cannot say a registry exists — what it can say is
    that a host in a reserved TLD can never exist (RFC 2606, RFC 6761). That is what the shipped
    example uses, so copying it produces a manifest that fails at pull time rather than one that
    installs somebody else's digests.
    """
    registry = doc["metadata"]["registry"]
    host = registry.split("/", 1)[0].split(":", 1)[0]
    if any(host.endswith(tld) for tld in _UNRESOLVABLE_TLDS):
        out.warnings.append(Finding(
            "metadata.registry",
            f"'{registry}' is in a reserved TLD that cannot resolve, so this manifest is an "
            f"illustration and no install can pull from it",
            "release.illustrative"))


_RULES = (
    _rule_one_source_revision,
    _rule_component_names_unique,
    _rule_signed,
    _rule_sbom,
    _rule_serves_every_logical_image,
    _rule_backs_every_chart_image,
    _rule_architectures_are_not_claimed_release_wide,
    _rule_registry_is_reachable_in_principle,
)


# ── using a release against a deployment document ─────────────────────────────
def check_against_document(release: Release, doc: dict[str, Any]) -> list[Finding]:
    """Errors that only exist when a release and a deployment document are used together."""
    findings: list[Finding] = []
    wanted = doc["runtime"]["version"]
    if release.version != wanted:
        findings.append(Finding(
            "metadata.version",
            f"this release is {release.version} but the deployment document asks for {wanted}; "
            f"installing one while the document records the other is how the document stops "
            f"being the record of what was installed",
            "release.version-mismatch"))
    return findings


def describe_component(release: Release, logical: str) -> str:
    """One line for `acpctl plan`: which artifact serves a logical image, and its digest."""
    component = release.component_for_image(logical)
    if component is None:                                  # pragma: no cover - validate refuses it
        return "<no component serves this image>"
    arches = "/".join(component["architectures"])
    return f"{component['digest']}  (artifact {component['repository']}, {arches})"
