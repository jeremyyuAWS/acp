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

THERE IS ONE RELEASE-MANIFEST READER AND IT IS NOT IN THIS FILE. `--release-manifest` is parsed
and validated by release.py against packaging/schema/acp-release.schema.json (kind `ACPRelease`) —
the same call `acpctl release verify`, `acpctl plan --release` and `acpctl values --release` make.
This module asks the loaded release three questions (its chart digests, its chart repositories,
its version) and holds no opinion at all about the format.

WHY THAT REPLACED A READER THAT WORKED. This file was written while no release-manifest format
existed, so it carried its own: a tolerant mapping of component name to `{digest, repository,
revision, version}`, checked for digest shape and for revision/version agreement. That reader was
not wrong; it was a SECOND definition of somebody else's contract. PRD S6 forbids exactly that —
"do not allow parallel work to create multiple release-manifest formats" — for the reason two
definitions always give: they drift, and the copy nothing else runs drifts SILENTLY. A manifest
the pipeline emits and `acpctl release verify` passes would have been read here by different
rules, and the first time the two disagreed, the install is where it would have surfaced.

THE GUARANTEE WENT UP, NOT SIDEWAYS, which is worth stating because delegating usually weakens
something. The old reader checked two things: digest shape, and that the components agreed on a
revision and a version. release.validate() checks those and, in addition: one source revision
across the whole release, a signature declared per artifact, an SBOM declared per artifact, amd64
on every artifact, arm64 recorded per image rather than claimed release-wide, component-name
uniqueness, every logical image `acpctl plan` names served by exactly one artifact, and every
image the CHART pulls backed by exactly one artifact. A manifest failing ANY of those is refused
here, before the cluster is contacted — so an unsigned release is now never installed and then
reported, which is the case the old reader had no way to see.

WHAT IT STILL CANNOT DO, so it is not assumed: nothing here contacts a registry, so a declared
signature is not a verified one and a digest is not proven to exist. release.py says the same
about itself in its own docstring; verifying against the registry is future work (PRD S13) and
the gap is deliberately left visible rather than papered over by the word "verified".
"""
from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import release as release_mod
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

# THE CHART'S IMAGE COMPONENTS ARE release.CHART_IMAGE_COMPONENTS, not a tuple of this module's
# own. That copy is pinned to the chart's templates by a test that reads them, and a second copy
# here would be the same drift this file's docstring is about, one scope smaller: the day the
# chart grows a fifth image, a private list would go on refusing to pin it with nothing failing.

# Fallback repositories, used only when the chart's values.yaml cannot be parsed (no PyYAML in an
# air-gapped bundle). They mirror packaging/chart/acp/values.yaml; the chart is the source of
# truth and is read first.
_FALLBACK_REPOSITORIES = {
    "api": "acp", "worker": "acp-worker",
    "ollama": "acp-ollama-gateway", "grafana": "acp-grafana",
}


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
    """Which repository each chart component pulls from, as the chart itself would resolve it.

    THE FALLBACK, NOT THE ANSWER. When a release manifest was given it names the artifacts the
    build actually produced and those win (see resolve_components); this reads the chart's own
    defaults, which are what an unpinned install has and nothing better. It is kept for exactly
    that path: `--allow-unpinned` with no manifest still has to write SOME repository into the
    installation record, and "the name the chart would have used" is the only honest one.
    """
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


def resolve_components(release: Any | None, wanted: list[str],
                       chart_defaults: dict[str, str]) -> tuple[dict[str, dict[str, str]], list[str]]:
    """The `release.components` map for the state, and the components with no digest.

    The second half of the return is the point: a caller that only took the map would install an
    unpinned release without noticing, which is exactly what `--allow-unpinned` exists to make
    into a deliberate act.

    THE MANIFEST'S REPOSITORY BEATS THE CHART'S DEFAULT, and that is a correctness rule rather
    than a preference. The chart's `image.repository` and `image.workerRepository` default to
    `acp` and `acp-worker`, which are names this repository's build does not produce (#1797); the
    release manifest names the artifact that WAS built. So where the manifest speaks it wins, and
    the chart-derived value below is the fallback for the no-manifest path — where the
    alternative is not a better name but no name at all.

    WITH A VALID RELEASE THE UNPINNED LIST IS ALWAYS EMPTY, because release.validate() refuses a
    manifest that does not back every one of the chart's four image components. That is stricter
    than this function's own rule — a digest per ENABLED component — and the weaker rule is kept
    rather than deleted because it still governs the path where NO manifest was given, which is
    the path `--allow-unpinned` exists for and the one whose message names components.
    """
    digests = release.chart_digests() if release is not None else {}
    repositories = release.chart_repositories() if release is not None else {}
    resolved: dict[str, dict[str, str]] = {}
    unpinned: list[str] = []
    for component in wanted:
        digest = digests.get(component)
        resolved[component] = {
            "repository": repositories.get(component) or chart_defaults[component],
            "digest": digest,
        }
        if not digest:
            unpinned.append(component)
    return resolved, unpinned


def render_values(document: dict, release: Any | None) -> str:
    """The chart values for this install, pinned to `release` when there is one.

    BUILT BY values.build_values, WHICH ALREADY TAKES A RELEASE. The digests and the repository
    overrides come from the same function `acpctl values --release` runs, so the file helm is
    handed here is the file an operator can reproduce with that command and diff. An installer
    that assembled its own pinned values would be a third opinion about what a pinned values file
    looks like, and the one nobody can print.

    A RELEASE PINS ALL FOUR CHART COMPONENTS, INCLUDING ONES THIS RENDER DISABLES. That is not an
    oversight: `image.digests` is a lookup table the chart consults only for the images it
    actually renders, so an entry for a Deployment that does not exist installs nothing — and
    hashing the whole release into `chart.valuesSha256` means switching Ollama on later is
    correctly seen as a change rather than as the same installation.

    THE DIGESTS GO IN THE VALUES FILE, NOT ON `--set`. Two reasons, and the second is the one that
    bites: the values file is what gets hashed into the state as `chart.valuesSha256`, so a
    digest that moved must change that hash or the idempotence check would call a different
    release "identical"; and `--set` values are invisible in `helm get values` output read later
    by somebody trying to work out what is running.
    """
    values = build_values(document, release)
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


def load_release(path: str | Path, document: dict, *, echo: Callable[[str], None]
                 ) -> tuple[Any | None, str | None, Outcome | None]:
    """The validated release for `--release-manifest`: (release, its sha256, a refusal or None).

    A NON-NONE THIRD ELEMENT MEANS STOP, and stopping is the whole point of this function. An
    unusable release manifest must never degrade into the unpinned path: the operator asked to
    pin, and an install that quietly fell back to tags would either refuse for a reason that
    reads as "you forgot --release-manifest" or install and record `pinned: false` under a
    command line that says otherwise.

    VALIDATION IS RUN HERE RATHER THAN TRUSTED FROM `acpctl release verify`. It is the same call,
    and running it again costs one schema parse — against the assumption that somebody ran the
    other command against THIS file, on this machine, since it was last edited. Assumptions like
    that are how an unsigned release gets installed by a tool that "already checked".

    WARNINGS ARE PRINTED AND DO NOT REFUSE. release.py's warnings are facts about the release
    that are legitimate (`arm64 on some images only`) or that the operator has to see rather than
    be stopped by (`this registry is a reserved TLD, so it is an illustration`). Turning them
    into refusals would make the shipped example uninstallable and teach people to pass a flag
    that switches off the errors too.
    """
    try:
        payload = release_mod.load_manifest(path)
    except FileNotFoundError:
        return None, None, Outcome(EXIT_USAGE, reason=f"no such release manifest: {path}")
    except OSError as exc:
        return None, None, Outcome(EXIT_USAGE, reason=f"could not read {path}: {exc}")
    except Exception as exc:  # noqa: BLE001 - json, yaml and load_document raise several types
        # NOT A USAGE ERROR. The path resolved and the bytes were readable; what failed is the
        # file's claim to be a manifest, and a pipeline should stop rather than retry.
        return None, None, Outcome(EXIT_REFUSED, reason=(
            f"refusing to install: {path} could not be parsed as a release manifest ({exc!r}). "
            f"It must be the YAML or JSON of an ACPRelease document — see "
            f"packaging/examples/example.acp-release.yaml."))

    result = release_mod.validate(payload)
    for finding in result.warnings:
        echo(f"  release manifest: {finding.render()}")
    if not result.ok:
        for finding in result.errors:
            echo(f"  {finding.render()}")
        return None, None, Outcome(EXIT_REFUSED, reason=(
            f"refusing to install: {path} is not a valid release manifest "
            f"({len(result.errors)} error(s)):\n"
            + "\n".join(f"  {finding.render()}" for finding in result.errors)
            + f"\nA release that fails its own contract is how an unsigned image, or an API and "
              f"a worker built from different commits, reaches a cluster under an installation "
              f"record saying the release was checked. Run `acpctl release verify {path}` to see "
              f"these findings again without contacting anything."))

    # THE RELEASE AND THE DOCUMENT MUST AGREE ON THE VERSION. The installation record writes ONE
    # version — the document's — so installing a release that calls itself something else makes
    # the record a false statement about the images that are running. This replaces the old
    # reader's "components declare different versions" refusal: under the ACPRelease contract a
    # manifest has a single metadata.version and cannot disagree with itself, so the only
    # disagreement left to catch is this one, between the release and the document installing it.
    mismatches = release_mod.check_against_document(result.release, document)
    if mismatches:
        for finding in mismatches:
            echo(f"  {finding.render()}")
        return None, None, Outcome(EXIT_REFUSED, reason=(
            f"refusing to install: {path} cannot be used with this document:\n"
            + "\n".join(f"  {finding.render()}" for finding in mismatches)))

    # HASHED FROM A SECOND READ, which is a real if narrow gap: a manifest rewritten between the
    # parse above and this call would be recorded under a hash of bytes that were not installed.
    # Closing it means a loader that returns the text as well as the document — a second reader,
    # which is the thing this module was rewritten to stop having. The window is microseconds; a
    # wrong hash here is detectable later, a duplicated contract is not.
    return result.release, state_mod.sha256_file(path), None


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

    # ── the release, before anything is contacted ─────────────────────────────
    # READ AND VALIDATED BY release.py, never by this file (see the module docstring). A manifest
    # that fails release.validate() is REFUSED here — unsigned, no SBOM, mixed revisions, an
    # image the chart pulls that nothing backs — rather than installed and described afterwards.
    pinned_release: Any | None = None
    manifest_sha256: str | None = None
    if release_manifest:
        pinned_release, manifest_sha256, refusal = load_release(
            release_manifest, document, echo=echo)
        if refusal is not None:
            return refusal

    values = build_values(document, pinned_release)
    wanted = required_components(values)
    components, unpinned = resolve_components(
        pinned_release, wanted, chart_repositories(values, chart_dir))

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

    values_yaml = render_values(document, pinned_release)

    candidate = state_mod.build(
        document, namespace=namespace, release_name=release,
        document_path=str(document_path), document_sha256=state_mod.sha256_file(document_path),
        values_sha256=state_mod.sha256_text(values_yaml),
        chart=state_mod.chart_metadata(chart_dir), components=components,
        pinned=not unpinned, manifest_sha256=manifest_sha256,
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
    # THE PLAN IS RENDERED AGAINST THE RELEASE, so the digests in the record are the digests the
    # operator was shown before consenting. A consent screen that named images without saying
    # which bytes they resolve to would ask for agreement to something it did not display.
    echo(render_plan(document, result.warnings, pinned_release))
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
