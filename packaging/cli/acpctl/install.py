"""`acpctl install` — put the document's release on a cluster, and record exactly what was put.

WHAT MAKES THIS DIFFERENT FROM `helm upgrade --install`, which an operator could run themselves in
one line. Five things, and each exists because of a way an install silently succeeds at the wrong
thing:

  * DIGESTS, NOT TAGS. PRD S5.1 requires cloud templates to reference digests. A tag is a moving
    reference: two installs a week apart from the same values file can run different code, and an
    installation that cannot say what it ran is not auditable. So this refuses to proceed unless
    every image component the render actually enables has a sha256 — `--allow-unpinned` is the
    escape hatch, it shouts, and it is written into the state as `pinned: false` so the next
    reader can tell an audited release from a hopeful one.
  * PREFLIGHT FIRST. `acpctl doctor`'s two silent failures — a ScaledObject with no KEDA, a
    NetworkPolicy under a CNI that ignores it — both apply cleanly and do nothing. An install that
    does not run those checks is one that reports success and leaves the worker tiers pinned at
    their floor. The checks are IMPORTED from doctor rather than repeated here, so a check added
    there gates installs from that moment.
  * NAMESPACE ISOLATION. Two helm releases with different names install side by side in one
    namespace without a word from helm, and the result is two ACP installations sharing PVC
    names, a NetworkPolicy and a Postgres connection budget computed for one of them.
  * VERIFICATION. `helm install` without `--wait` exits zero when the API server ACCEPTED the
    objects, not when the application came up. This waits, then asks helm what the release status
    actually is, and an install it could not verify exits NON-ZERO. Reporting success because
    nothing was observed is the failure mode the whole packaging CLI is written against.
  * A RECORD. PRD S20.12: every deployment produces a redacted, immutable installation manifest.
    See state.py.

IDEMPOTENCE IS A FEATURE, NOT AN ACCIDENT. `helm upgrade --install` is the same command for a
first install and a re-run, and re-running is a thing operators legitimately do — a CI job, a
network blip, uncertainty about whether the first attempt finished. So a second run with the same
document, the same release manifest and the same rendered values does NOTHING, exits 0, and does
not append a duplicate entry to the state history. An installer that appends an event per
invocation produces a history of things that did not happen.

THE RELEASE-MANIFEST READER BELOW IS A CONSUMER, NOT THE OWNER OF THAT FORMAT. The manifest is
produced by the release pipeline (PRD workstream A); this file reads the narrowest thing it can
work with and refuses anything it does not understand rather than guessing. It deliberately does
not define a schema, validate fields it does not use, or write manifests. If the pipeline's format
grows a field, nothing here needs to change; if it CONTRADICTS itself — components built from
different revisions — this refuses, because "CI fails on a mixed-revision release" is the property
the format exists to have and a consumer that installs one anyway makes that guarantee decorative.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import spec as spec_mod
from . import state as state_mod
from .helm import STATE_CONFIGMAP, CommandFailed, Helm, ToolUnavailable
from .plan import render as render_plan
from .values import build_values

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2

# packaging/cli/acpctl/install.py -> packaging/chart/acp
DEFAULT_CHART = Path(__file__).resolve().parents[2] / "chart" / "acp"

# PRD S5.1 again: an immutable digest, and nothing that merely looks like one. Uppercase hex is
# not accepted because registries do not produce it, and a digest this tool "normalised" would be
# one the operator cannot grep for in their registry's UI.
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

# The image components the CHART knows how to pin — `templates/_helpers.tpl` looks each up in
# `image.digests`. Not the same list as inventory.IMAGES: the API and the three worker tiers share
# two images in the chart (`api`, `worker`), because they differ by command and ACP_WORKER_ROLE
# rather than by artifact. Pinning a component the chart never reads would be a digest that
# resolves nothing.
CHART_COMPONENTS = ("api", "worker", "ollama", "grafana")

# What a release manifest may call each chart component. The pipeline names artifacts (PRD S5.1
# lists `acp-web-api`, `acp-discovery-worker`, …); the chart names ROLES. This is the only place
# the two vocabularies meet, and it is a tolerant read rather than a claim about the format: an
# unrecognised key in the manifest is ignored, a recognised one is used.
COMPONENT_ALIASES: dict[str, tuple[str, ...]] = {
    "api": ("api", "acp-web-api", "web-api", "acp-api"),
    # THREE WORKER ARTIFACTS, ONE CHART IMAGE. If a manifest carries all three they must agree,
    # because the chart has exactly one `worker` digest to install and picking one arbitrarily
    # would deploy an assess worker built from a different revision than the discovery worker,
    # under a state file claiming they matched.
    "worker": ("worker", "acp-worker", "acp-discovery-worker", "acp-assess-worker",
               "acp-remediate-worker", "discover", "assess", "remediate"),
    "ollama": ("ollama", "acp-ollama-gateway"),
    "grafana": ("grafana", "acp-grafana"),
}

# Fallback repositories, used only when the chart's values.yaml cannot be parsed (no PyYAML in an
# air-gapped bundle). They mirror packaging/chart/acp/values.yaml; the chart is the source of
# truth and is read first.
_FALLBACK_REPOSITORIES = {
    "api": "acp", "worker": "acp-worker",
    "ollama": "acp-ollama-gateway", "grafana": "acp-grafana",
}


class ManifestError(ValueError):
    """The release manifest is unusable. Always a refusal, never a warning: every one of these
    means acpctl cannot say which code it would be installing."""


@dataclass
class ReleaseManifest:
    path: str
    sha256: str
    revision: str
    version: str
    components: dict[str, dict[str, str]]


def load_release_manifest(path: str | Path) -> ReleaseManifest:
    """Read a release manifest. A NARROW CONSUMER — see this module's docstring.

    Accepts YAML or JSON, and either a top-level `components:` mapping or a bare top-level
    mapping of component name to entry. Both shapes are accepted because the format is owned
    elsewhere and this is the smallest set of assumptions that can still be checked; what is NOT
    accepted is anything ambiguous.

    Every entry must carry `digest`, `repository`, `revision` and `version`. The last two are not
    used to install anything — they are read solely so that a manifest whose components disagree
    can be refused, which is PRD workstream A's "CI fails on a mixed-revision release" enforced at
    the point where it would otherwise stop mattering.
    """
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    payload = _parse_manifest_text(text, target)

    if not isinstance(payload, dict):
        raise ManifestError(
            f"{target}: expected a mapping of component name to entry (optionally under a "
            f"top-level `components:` key); got {type(payload).__name__}")
    raw = payload.get("components", payload)
    if not isinstance(raw, dict) or not raw:
        raise ManifestError(f"{target}: no components found")

    components: dict[str, dict[str, str]] = {}
    revisions: dict[str, str] = {}
    versions: dict[str, str] = {}
    for name, entry in raw.items():
        if not isinstance(entry, dict):
            # A bare top-level mapping is one of the accepted shapes, so a scalar here is most
            # likely a top-level key of some LARGER manifest format (`apiVersion: …`) rather than
            # a broken component. Skipping it silently would mean reading half a document as if
            # it were the whole one.
            if name in ("components",):
                continue
            if isinstance(entry, (str, int, float, bool)) or entry is None:
                continue
            raise ManifestError(f"{target}: component {name!r} is not a mapping")
        missing = [f for f in ("digest", "repository", "revision", "version") if not entry.get(f)]
        if missing:
            raise ManifestError(
                f"{target}: component {name!r} is missing {', '.join(missing)}. A component "
                f"acpctl cannot fully identify is one it cannot record as installed.")
        digest = str(entry["digest"])
        if not DIGEST_RE.match(digest):
            raise ManifestError(
                f"{target}: component {name!r} has digest {digest!r}, which is not a sha256 "
                f"digest. PRD S5.1 requires immutable digests; a tag here would install "
                f"whatever that tag points at today.")
        components[str(name)] = {
            "repository": str(entry["repository"]),
            "digest": digest,
            "revision": str(entry["revision"]),
            "version": str(entry["version"]),
        }
        revisions[str(name)] = str(entry["revision"])
        versions[str(name)] = str(entry["version"])

    if not components:
        raise ManifestError(f"{target}: no components found")
    if len(set(revisions.values())) > 1:
        raise ManifestError(
            f"{target}: MIXED-REVISION RELEASE — components were built from different source "
            f"revisions ({_disagreement(revisions)}). PRD S5.1 requires every image in a release "
            f"to come from the same revision; installing this would deploy an API and a worker "
            f"from different commits, which is a class of bug nobody can reproduce afterwards.")
    if len(set(versions.values())) > 1:
        raise ManifestError(
            f"{target}: components declare different versions ({_disagreement(versions)}). The "
            f"installation records ONE version; recording either of these would make the state "
            f"file a false statement about half the release.")

    return ReleaseManifest(
        path=str(target), sha256=state_mod.sha256_file(target),
        revision=next(iter(revisions.values())), version=next(iter(versions.values())),
        components=components)


def _parse_manifest_text(text: str, target: Path) -> Any:
    """JSON first, then YAML. JSON is a subset, so trying it first means the reader works in an
    air-gapped bundle with no PyYAML for the format CI most naturally emits."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise ManifestError(
            f"{target} is not JSON and PyYAML is not installed, so it cannot be read as YAML"
        ) from exc
    try:
        return yaml.safe_load(text)
    except Exception as exc:  # yaml raises several types
        raise ManifestError(f"{target}: not valid YAML or JSON: {exc}") from exc


def _disagreement(values: dict[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in sorted(values.items()))


def required_components(values: dict) -> list[str]:
    """The chart image components THIS render actually deploys.

    Only the enabled ones, and that is the difference between a check people keep and one they
    turn off. A document with `ai.mode: external` renders no Ollama Deployment, so demanding an
    ollama digest would refuse an install over an image the cluster will never pull — and the
    operator's fix would be `--allow-unpinned`, which switches off the pinning requirement for
    every component including the ones that matter.
    """
    components = ["api", "worker"]
    if ((values.get("ai") or {}).get("ollama") or {}).get("enabled"):
        components.append("ollama")
    if ((values.get("observability") or {}).get("grafana") or {}).get("enabled"):
        components.append("grafana")
    return components


def chart_repositories(values: dict, chart_dir: str | Path) -> dict[str, str]:
    """Which repository each chart component pulls from, as the chart itself would resolve it."""
    image = dict(values.get("image") or {})
    defaults = dict(_FALLBACK_REPOSITORIES)
    try:
        import yaml
    except ImportError:  # pragma: no cover - environment-dependent
        chart_values: dict[str, Any] = {}
    else:
        try:
            chart_values = yaml.safe_load(
                (Path(chart_dir) / "values.yaml").read_text(encoding="utf-8")) or {}
        except OSError:
            chart_values = {}
    chart_image = dict((chart_values.get("image") or {}))
    keys = {"api": "repository", "worker": "workerRepository",
            "ollama": "ollamaRepository", "grafana": "grafanaRepository"}
    return {component: str(image.get(key) or chart_image.get(key) or defaults[component])
            for component, key in keys.items()}


def resolve_components(manifest: ReleaseManifest | None, wanted: list[str],
                       repositories: dict[str, str]) -> tuple[dict[str, dict[str, str]], list[str]]:
    """The `release.components` map for the state, and the components with no digest.

    The second half of the return is the point: a caller that only took the map would install an
    unpinned release without noticing, which is exactly what `--allow-unpinned` exists to make
    into a deliberate act.
    """
    resolved: dict[str, dict[str, str]] = {}
    unpinned: list[str] = []
    for component in wanted:
        entries = _manifest_entries_for(manifest, component)
        digests = {entry["digest"] for entry in entries}
        if len(digests) > 1:
            raise ManifestError(
                f"the release manifest gives component {component!r} more than one digest "
                f"({', '.join(sorted(digests))}). The chart installs ONE image for it, so there "
                f"is no correct choice to make here.")
        if entries:
            entry = entries[0]
            resolved[component] = {"repository": entry.get("repository") or repositories[component],
                                   "digest": entry["digest"]}
        else:
            resolved[component] = {"repository": repositories[component], "digest": None}
            unpinned.append(component)
    return resolved, unpinned


def _manifest_entries_for(manifest: ReleaseManifest | None, component: str) -> list[dict]:
    if manifest is None:
        return []
    names = COMPONENT_ALIASES.get(component, (component,))
    return [entry for name, entry in sorted(manifest.components.items()) if name in names]


def render_values_with_digests(document: dict, digests: dict[str, str]) -> str:
    """The chart values for this install, with the resolved digests in them.

    THE DIGESTS GO IN THE VALUES FILE, NOT ON `--set`. Two reasons, and the second is the one that
    bites: the values file is what gets hashed into the state as `chart.valuesSha256`, so a
    digest that moved must change that hash or the idempotence check would call a different
    release "identical"; and `--set` values are invisible in `helm get values` output read later
    by somebody trying to work out what is running.
    """
    values = build_values(document)
    values["image"]["digests"] = {k: v for k, v in digests.items() if v}
    header = (
        "# GENERATED by `acpctl install` from an acp-deployment document. Do not hand-edit:\n"
        "# edit the deployment document and reinstall, or the two disagree and the document\n"
        "# stops being the record of what was installed.\n"
        f"# release {document['runtime']['version']}  profile {document['runtime']['profile']}  "
        f"platform {document['runtime']['platform']}\n"
        f"# digests: {'resolved' if values['image']['digests'] else 'NONE — installed unpinned'}\n"
    )
    try:
        import yaml
    except ImportError:  # pragma: no cover - environment-dependent
        return header + json.dumps(values, indent=2)
    return header + yaml.safe_dump(values, sort_keys=False, default_flow_style=False)


def default_preflight(values: dict, *, namespace: str, context: str | None) -> dict:
    """`acpctl doctor`, run as the install's gate.

    IMPORTED, NOT REIMPLEMENTED. doctor's value is in the two checks whose failures are silent,
    and a second copy of them here would be one that stops matching the day somebody adds a third.
    The report format is doctor's own, so `--json` output from an install carries findings an
    operator has already learned to read.
    """
    from . import cluster as cluster_mod
    from . import doctor as doctor_mod

    facts = cluster_mod.gather(namespace=namespace, context=context)
    return doctor_mod.diagnose(values, facts, namespace=namespace)


def tty_confirm(prompt: str) -> bool | None:
    """y/N on a terminal. `None` means the question COULD NOT BE ASKED.

    THREE ANSWERS, NOT TWO, for the same reason doctor has three outcomes. "The operator said no"
    and "there was nobody to ask" are different facts: the first is a refusal (exit 1), the second
    is a usage error (exit 2) telling a pipeline to pass `--yes`. Collapsing them into False would
    report a scripted install with a missing flag as a decision somebody made.

    Silence is never consent. An installer that reads an empty stdin as agreement is one that
    installs on the strength of a cron job saying nothing.
    """
    if not sys.stdin.isatty():
        return None
    try:
        answer = input(f"{prompt} [y/N] ").strip().lower()
    except EOFError:
        return None
    return answer in ("y", "yes")


@dataclass
class Outcome:
    """What the command did, in a form the CLI prints and a test can assert on."""

    code: int
    state: dict | None = None
    reason: str = ""
    changed: bool = False
    preflight: dict | None = None
    messages: list[str] = field(default_factory=list)


def install(document_path: str, *, namespace: str, release_name: str | None = None,
            release_manifest: str | None = None, allow_unpinned: bool = False,
            adopt: bool = False, skip_preflight: bool = False, assume_yes: bool = False,
            context: str | None = None, chart_dir: str | Path = DEFAULT_CHART,
            helm: Helm | None = None,
            preflight: Callable[..., dict] | None = None,
            confirm: Callable[[str], bool] | None = None,
            echo: Callable[[str], None] = print) -> Outcome:
    """Install (or re-install) the release this document describes. See module docstring."""
    helm = helm if helm is not None else Helm(context=context)
    preflight = preflight if preflight is not None else default_preflight
    confirm = confirm if confirm is not None else tty_confirm

    if not namespace:
        return Outcome(EXIT_USAGE, reason="a namespace is required (-n/--namespace)")

    # ── the document ──────────────────────────────────────────────────────────
    try:
        document = spec_mod.load_document(document_path)
    except (OSError, ValueError) as exc:
        return Outcome(EXIT_USAGE, reason=f"could not read {document_path}: {exc}")

    result = spec_mod.validate(document)
    if not result.ok:
        for finding in result.errors:
            echo(f"  {finding.render()}")
        return Outcome(EXIT_REFUSED,
                       reason=f"refusing to install: {document_path} is invalid "
                              f"({len(result.errors)} error(s))")

    release = release_name or (document.get("metadata") or {}).get("name") or "acp"
    values = build_values(document)

    # ── digests, before anything is contacted ─────────────────────────────────
    manifest: ReleaseManifest | None = None
    if release_manifest:
        try:
            manifest = load_release_manifest(release_manifest)
        except FileNotFoundError:
            return Outcome(EXIT_USAGE, reason=f"no such release manifest: {release_manifest}")
        except OSError as exc:
            return Outcome(EXIT_USAGE, reason=f"could not read {release_manifest}: {exc}")
        except ManifestError as exc:
            return Outcome(EXIT_REFUSED, reason=str(exc))

    wanted = required_components(values)
    try:
        components, unpinned = resolve_components(
            manifest, wanted, chart_repositories(values, chart_dir))
    except ManifestError as exc:
        return Outcome(EXIT_REFUSED, reason=str(exc))

    if unpinned and not allow_unpinned:
        return Outcome(EXIT_REFUSED, reason=(
            "refusing to install unpinned. No sha256 digest is available for: "
            f"{', '.join(unpinned)}.\n"
            "PRD S5.1 requires releases to deploy by immutable digest — a tag is a moving "
            "reference, and an installation that cannot say exactly which code it ran cannot be "
            "audited or reproduced.\n"
            "Pass --release-manifest <path> with the digests for this release, or "
            "--allow-unpinned to install from tags anyway and have that recorded."))
    if unpinned:
        echo("")
        echo("  !!  INSTALLING UNPINNED  !!")
        echo(f"  No digest for: {', '.join(unpinned)}. These will be pulled by TAG "
             f"({values['image'].get('tag')}), which is a moving reference: what installs today "
             f"is not necessarily what installs tomorrow, and this release cannot be reproduced "
             f"from its record.")
        echo("  Recorded in the installation state as pinned: false.")
        echo("")

    values_yaml = render_values_with_digests(
        document, {c: components[c]["digest"] for c in components})

    candidate = state_mod.build(
        document, namespace=namespace, release_name=release,
        document_path=str(document_path), document_sha256=state_mod.sha256_file(document_path),
        values_sha256=state_mod.sha256_text(values_yaml),
        chart=state_mod.chart_metadata(chart_dir), components=components,
        pinned=not unpinned, manifest_sha256=manifest.sha256 if manifest else None,
        helm_revision=None,
        flags={"skipPreflight": skip_preflight, "adopted": adopt, "allowUnpinned": allow_unpinned})

    leaks = state_mod.secret_leaks(candidate, document)
    if leaks:
        return Outcome(EXIT_REFUSED, reason=(
            f"refusing to install: the installation record would contain {', '.join(leaks)}. "
            f"That record is written to a ConfigMap readable by anything with `get configmaps` "
            f"in the namespace (PRD S13/S20.6). This is a bug in acpctl — please report it."))

    # ── preflight ─────────────────────────────────────────────────────────────
    report: dict | None = None
    if skip_preflight:
        echo("  preflight SKIPPED (--skip-preflight). Recorded in the installation state.")
        echo("  The checks skipped include the two whose failures are silent: a ScaledObject with "
             "no KEDA, and a NetworkPolicy under a CNI that ignores it. Both apply cleanly and "
             "do nothing.")
    else:
        try:
            report = preflight(values, namespace=namespace, context=context)
        except ToolUnavailable as exc:
            return Outcome(EXIT_USAGE, reason=str(exc))
        if not report.get("reachable"):
            return Outcome(EXIT_USAGE, preflight=report, reason=(
                "the cluster could not be reached, so NOTHING was established and nothing was "
                "installed. Retryable — this is not a refusal."))
        if not report.get("ok"):
            for check in report.get("checks", []):
                if check["status"] in ("fail", "unknown") and check["severity"] == "blocker":
                    echo(f"  [{check['status'].upper():>4}] {check['id']}: {check['detail']}")
            return Outcome(EXIT_REFUSED, preflight=report, reason=(
                f"refusing to install: preflight found {report.get('blockers', 0)} blocker(s) and "
                f"{report.get('unknown', 0)} check(s) that could not be run. A check that could "
                f"not run has established nothing — and the checks that cannot run are the ones "
                f"guarding failures that are otherwise silent.\n"
                f"Fix them, or pass --skip-preflight to install anyway and have that recorded."))
        echo(f"  preflight: no blockers ({report.get('warnings', 0)} warning(s))")

    # ── is this namespace already somebody's? ─────────────────────────────────
    try:
        prior, unreadable = helm.read_state(namespace)
    except ToolUnavailable as exc:
        return Outcome(EXIT_USAGE, reason=str(exc))
    if unreadable:
        return Outcome(EXIT_REFUSED, reason=(
            f"could not read the installation state in {namespace!r}: {unreadable}. "
            f"Refusing to install into a namespace whose contents could not be established — "
            f"an unreadable check is not an empty namespace."))

    conflict = state_mod.occupant_conflict(
        prior, release_name=release, document_name=(document.get("metadata") or {}).get("name", ""))
    if conflict and not adopt:
        return Outcome(EXIT_REFUSED, reason=(
            f"refusing to install into {namespace!r}: {conflict}.\n"
            f"Two ACP installations in one namespace share PVC names, a NetworkPolicy and a "
            f"Postgres connection budget that was computed for one of them, and neither helm nor "
            f"Kubernetes objects to it.\n"
            f"Install into a different namespace, or pass --adopt to take over this one "
            f"(recorded in the installation state)."))

    releases = helm.releases(namespace)
    if releases is None and not adopt:
        return Outcome(EXIT_REFUSED, reason=(
            f"could not list helm releases in {namespace!r}, so whether something is already "
            f"installed there is unknown. Refusing rather than installing over an unknown."))
    foreign = [r["name"] for r in (releases or [])
               if r.get("name") != release and str(r.get("chart", "")).startswith("acp-")]
    if foreign and not adopt:
        return Outcome(EXIT_REFUSED, reason=(
            f"refusing to install into {namespace!r}: it already holds ACP helm release(s) "
            f"{', '.join(foreign)}, and this install would create {release!r} alongside them. "
            f"Pass --adopt if that is genuinely what you want."))

    # ── already installed, identically? ───────────────────────────────────────
    live = helm.release_state(release, namespace)
    if state_mod.same_installation(prior, candidate) and live.exists and live.status == "deployed":
        echo(f"  {release} in {namespace} is already at this exact document, release manifest and "
             f"rendered values (helm revision {live.revision}).")
        echo("  Nothing to do. No history entry recorded — a re-run is not an event.")
        return Outcome(EXIT_OK, state=prior, changed=False, preflight=report,
                       reason="already installed and identical")

    # ── the plan, and consent ─────────────────────────────────────────────────
    echo(render_plan(document, result.warnings))
    echo("")
    echo(f"  release   {release}")
    echo(f"  namespace {namespace}")
    echo(f"  chart     {chart_dir}")
    for component in sorted(components):
        digest = components[component]["digest"]
        echo(f"  image     {components[component]['repository']} "
             f"{digest if digest else '(UNPINNED — tag ' + str(values['image'].get('tag')) + ')'}")
    echo("")

    if not assume_yes:
        decision = confirm(f"Install {release} into {namespace}?")
        if decision is None:
            return Outcome(EXIT_USAGE, reason=(
                "refusing to install without confirmation, and there was nobody to ask: stdin is "
                "not a terminal, so the y/N prompt cannot be answered. Pass --yes to confirm in "
                "advance. This is a usage error rather than a refusal — nothing about the "
                "cluster or the document was wrong."))
        if not decision:
            return Outcome(EXIT_REFUSED, reason="cancelled — nothing was changed")

    # ── mutate ────────────────────────────────────────────────────────────────
    try:
        exists = helm.namespace_exists(namespace)
        if exists is None:
            return Outcome(EXIT_REFUSED, reason=(
                f"could not establish whether namespace {namespace!r} exists. Refusing rather "
                f"than creating one that may already hold something."))
        if not exists:
            echo(f"  creating namespace {namespace}")
            helm.create_namespace(namespace)

        with tempfile.TemporaryDirectory(prefix="acpctl-install-") as workdir:
            values_path = Path(workdir) / "values.yaml"
            values_path.write_text(values_yaml, encoding="utf-8")
            echo(f"  helm upgrade --install {release} (waiting for the release to become ready)")
            helm.upgrade_install(release, namespace, str(chart_dir),
                                 values_path=str(values_path))
    except CommandFailed as exc:
        _record_failure(helm, namespace, candidate, prior, echo)
        return Outcome(EXIT_REFUSED, preflight=report, reason=(
            f"the install failed: {exc.result.summary()}\n"
            f"helm was run with --atomic, so the release was rolled back to its previous state "
            f"rather than left half-applied. Run `acpctl status {document_path} -n {namespace}` "
            f"to see what is there now."))
    except ToolUnavailable as exc:
        _record_failure(helm, namespace, candidate, prior, echo)
        return Outcome(EXIT_USAGE, preflight=report, reason=str(exc))
    except Exception as exc:  # an interrupted runner: a broken pipe, a killed helm, a bug
        # NO CLAIM OF SUCCESS SURVIVES THIS PATH. Whatever went wrong, acpctl did not observe a
        # working release, so it must not write one into the record — the best it can honestly
        # do is record the attempt as failed and say what it does not know.
        _record_failure(helm, namespace, candidate, prior, echo)
        return Outcome(EXIT_REFUSED, preflight=report, reason=(
            f"the install was interrupted: {exc!r}\n"
            f"acpctl cannot say what state the release is in — it did not observe the result. "
            f"Run `acpctl status {document_path} -n {namespace}` before retrying."))

    # ── verify, then record ───────────────────────────────────────────────────
    verified = helm.release_state(release, namespace)
    if verified.exists is not True or verified.status != "deployed":
        detail = (f"helm reports status {verified.status!r}" if verified.exists
                  else f"helm could not confirm the release exists ({verified.reason})")
        _record_failure(helm, namespace, candidate, prior, echo,
                        revision=verified.revision)
        return Outcome(EXIT_REFUSED, preflight=report, reason=(
            f"the install command returned success but the result could NOT be verified: "
            f"{detail}.\n"
            f"This is reported as a failure on purpose. An installer that exits 0 because it "
            f"observed nothing is the failure this command set is written against."))

    final = dict(candidate)
    final["release"] = {**candidate["release"], "revision": verified.revision}
    final["history"] = list((prior or {}).get("history") or [])
    final = state_mod.with_history(final, state_mod.history_entry(
        state_mod.ACTION_INSTALL, helm_revision=verified.revision,
        result=state_mod.RESULT_OK))

    try:
        helm.write_state(namespace, final)
    except (CommandFailed, ToolUnavailable) as exc:
        return Outcome(EXIT_REFUSED, state=final, changed=True, preflight=report, reason=(
            f"the release is installed and healthy, but the installation record could NOT be "
            f"written to the cluster: {exc}\n"
            f"The state is printed below/with --json — keep it. Without it the namespace holds "
            f"an ACP installation that nothing in the cluster can trace back to a document."))

    echo(f"  installed: helm revision {verified.revision}, status {verified.status}")
    echo(f"  recorded in configmap/{STATE_CONFIGMAP} in namespace {namespace}")
    return Outcome(EXIT_OK, state=final, changed=True, preflight=report,
                   reason=f"{release} installed into {namespace}")


def _record_failure(helm: Helm, namespace: str, candidate: dict, prior: dict | None,
                    echo: Callable[[str], None], *, revision: int | None = None) -> None:
    """Best-effort: write a `failed` history entry, and never anything that reads as success.

    BEST-EFFORT IS THE HONEST DESIGN HERE. The install just failed, quite possibly because the
    cluster is unreachable, so this write may fail too — and a failure to record a failure must
    not turn into a traceback that hides the original error. What it must never do is leave an
    `ok` entry behind, which is why the record written here is built from the FAILED entry rather
    than from the success path's state.
    """
    try:
        record = dict(candidate)
        record["release"] = {**candidate["release"], "revision": revision}
        record["history"] = list((prior or {}).get("history") or [])
        record = state_mod.with_history(record, state_mod.history_entry(
            state_mod.ACTION_INSTALL, helm_revision=revision, result=state_mod.RESULT_FAILED))
        helm.write_state(namespace, record)
        echo("  the failed attempt was recorded in the installation state")
    except Exception as exc:  # noqa: BLE001 - see docstring
        echo(f"  (the failed attempt could not be recorded in the cluster: {exc})")
