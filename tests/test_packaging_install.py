"""`acpctl install` — the refusals, the pinning rule, the verification, and the record it writes.

THE PATTERN IS THE ONE THE REST OF THE PACKAGING TESTS USE: take a working install, break exactly
one thing, assert the one refusal. What is different here is that the subject CHANGES A CLUSTER,
so two properties get tested that a read-only command does not need:

  * EVERY REFUSAL IS ALSO ASSERTED TO HAVE MUTATED NOTHING. A command that refuses after it has
    already created the namespace and half the release is not a refusal, and the exit code alone
    cannot tell the difference. `mutations()` reads the recorded argv through the same allow-list
    the guard uses, so a new kind of write is counted here by construction.
  * SUCCESS IS NEVER INFERRED FROM SILENCE. `test_an_install_that_cannot_be_verified_fails` and
    `test_an_interrupted_install_leaves_no_claim_of_success` are the load-bearing tests in this
    file: an installer that exits 0 because it observed nothing is the exact failure the whole
    packaging CLI is written against.

NO CLUSTER, NO HELM, NO NETWORK. Everything below runs against `FakeRunner`, an in-memory cluster
that answers the handful of helm and kubectl calls acpctl makes and records the exact argv. It is
modelled on tests/packaging_kubectl_fake.py and shares its reasoning: the interesting cases are
absences and failures — no release, an unreadable ConfigMap, helm dying halfway — and each is a
different cluster, so a fixture per shape covers them all where one real cluster covers one.

WHAT THAT DOES NOT PROVE, stated plainly: these are the answers helm and kubectl are DOCUMENTED to
give, not a recording of a specific cluster. The mitigation is the same as the kubectl fake's —
the parsed surface is tiny (a release status, a ConfigMap, a PVC list) and every field read is a
long-stable one. No acceptance run against a real cluster has happened; see
packaging/docs/lifecycle.md, which says so rather than implying otherwise.
"""
from __future__ import annotations

import copy
import json
import re

import pytest

from packaging_helpers import PACKAGING, load_example

EXAMPLE = PACKAGING / "examples" / "standard-production.acp-deployment.yaml"
RELEASE_EXAMPLE = PACKAGING / "examples" / "example.acp-release.yaml"
CHART = PACKAGING / "chart" / "acp"

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64
DIGEST_D = "sha256:" + "d" * 64


# ── the fake cluster ──────────────────────────────────────────────────────────

class FakeRunner:
    """An in-memory cluster behind the runner interface `helm.Helm` calls.

    STATEFUL ON PURPOSE. A stub that returned canned answers could not test idempotence at all:
    the second run has to see what the first one wrote, or "re-running changes nothing" is a
    claim about a fixture rather than about the code. So `helm upgrade` really does make the
    release deployed here, `kubectl apply` really does store the ConfigMap, and `helm uninstall`
    really does remove it — which is also what lets tests/test_packaging_uninstall.py reuse this
    class against an installation this one produced.

    `fail` maps a substring of the command line to the stderr it should fail with; `explode` maps
    one to an exception, which is how the interrupted-install path is reached — a runner that
    raises is a helm that was killed, a broken pipe, or a bug, and acpctl must not report success
    for any of them.
    """

    def __init__(self, *, namespace_exists=True, state=None, release=None, releases=(),
                 pvcs=(), manifest_text="", fail=None, explode=None, list_fails=False,
                 configmap_error=None):
        self.namespace_exists = namespace_exists
        self.state = json.loads(json.dumps(state)) if state else None
        self.release = dict(release) if release else None
        self.releases = list(releases)
        self.pvcs = list(pvcs)
        self.manifest_text = manifest_text
        self.fail = dict(fail or {})
        self.explode = dict(explode or {})
        self.list_fails = list_fails
        self.configmap_error = configmap_error
        self.log: list[list[str]] = []
        self.stdins: list[str | None] = []

    # -- helpers ------------------------------------------------------------
    def _result(self, argv, code=0, stdout="", stderr=""):
        from acpctl.helm import CommandResult
        return CommandResult(argv=list(argv), returncode=code, stdout=stdout, stderr=stderr)

    def _scripted(self, argv, line):
        for needle, message in self.explode.items():
            if needle in line:
                raise RuntimeError(message)
        for needle, message in self.fail.items():
            if needle in line:
                return self._result(argv, 1, stderr=message)
        return None

    def __call__(self, argv, *, stdin=None, timeout=None):
        self.log.append(list(argv))
        self.stdins.append(stdin)
        line = " ".join(argv)
        scripted = self._scripted(argv, line)
        if scripted is not None:
            return scripted
        tool = argv[0]
        args = [a for a in argv[1:]]
        if args[:1] in (["--kube-context"], ["--context"]):
            args = args[2:]
        return (self._helm(argv, args) if tool == "helm" else self._kubectl(argv, args, stdin))

    # -- helm ---------------------------------------------------------------
    def _helm(self, argv, args):
        verb = args[0]
        if verb == "status":
            if not self.release:
                return self._result(argv, 1, stderr="Error: release: not found")
            return self._result(argv, 0, stdout=json.dumps({
                "name": args[1], "version": self.release["revision"],
                "info": {"status": self.release["status"]},
                "chart": {"metadata": {"name": "acp"}}}))
        if verb == "list":
            if self.list_fails:
                return self._result(argv, 1, stderr="Error: query: forbidden")
            return self._result(argv, 0, stdout=json.dumps(self.releases))
        if verb == "get":
            return self._result(argv, 0, stdout=self.manifest_text)
        if verb == "upgrade":
            revision = (self.release or {}).get("revision", 0) + 1
            self.release = {"status": "deployed", "revision": revision}
            return self._result(argv, 0, stdout="release upgraded")
        if verb == "uninstall":
            self.release = None
            return self._result(argv, 0, stdout="release uninstalled")
        return self._result(argv, 1, stderr=f"fake helm: unscripted {verb}")

    # -- kubectl ------------------------------------------------------------
    def _kubectl(self, argv, args, stdin):
        verb = args[0]
        what = args[1] if len(args) > 1 else ""
        if verb == "get" and what == "namespace":
            if self.namespace_exists:
                return self._result(argv, 0, stdout=json.dumps({"metadata": {"name": args[2]}}))
            return self._result(
                argv, 1, stderr='Error from server (NotFound): namespaces "x" not found')
        if verb == "get" and what == "configmap":
            if self.configmap_error:
                return self._result(argv, 1, stderr=self.configmap_error)
            if self.state is None:
                return self._result(
                    argv, 1, stderr='Error from server (NotFound): configmaps "x" not found')
            from acpctl.helm import state_manifest
            return self._result(argv, 0, stdout=json.dumps(state_manifest("ns", self.state)))
        if verb == "get" and what == "pvc":
            return self._result(argv, 0, stdout=json.dumps(
                {"items": [{"metadata": {"name": n}} for n in self.pvcs]}))
        if verb == "create" and what == "namespace":
            self.namespace_exists = True
            return self._result(argv, 0, stdout="namespace created")
        if verb == "apply":
            payload = json.loads(stdin)
            self.state = json.loads(payload["data"]["installation.json"])
            return self._result(argv, 0, stdout="configmap configured")
        if verb == "delete" and what == "configmap":
            self.state = None
            return self._result(argv, 0, stdout="configmap deleted")
        if verb == "delete" and what == "pvc":
            self.pvcs = []
            return self._result(argv, 0, stdout="pvc deleted")
        return self._result(argv, 1, stderr=f"fake kubectl: unscripted {verb} {what}")


def mutations(runner: FakeRunner) -> list[list[str]]:
    """Every recorded command that could have changed something.

    Derived from `helm.Helm.mutations`, which reads the same allow-list the guard enforces, so a
    newly permitted write is counted here without anybody remembering to add it to a list in a
    test — a preview that quietly stopped noticing one class of mutation would be as wrong as one
    that performed it.
    """
    from acpctl.helm import Helm
    probe = Helm(runner=lambda *a, **k: None)
    probe.log = runner.log
    return probe.mutations()


def component(document: dict, name: str) -> dict:
    return next(c for c in document["components"] if c["name"] == name)


def release_document() -> dict:
    """A valid `ACPRelease` document, with this file's digests substituted in.

    BUILT FROM THE SHIPPED EXAMPLE RATHER THAN HAND-ROLLED, for the reason
    tests/test_packaging_release.py does the same. A fixture typed out to satisfy the schema from
    memory describes the contract on the day it was written and goes on passing after the
    contract moves; starting from packaging/examples/example.acp-release.yaml means a rule added
    to release.py is felt HERE too — which is now the point, because `install` refuses on exactly
    release.validate()'s rules and no longer has any of its own.

    ONE ARTIFACT BACKS TWO CHART IMAGES, and that is why `api` and `worker` share DIGEST_A rather
    than getting one each. `deploy/public/deploy.sh` builds a single application image that runs
    the API and every worker role; the old fixture here named `acp-web-api` and
    `acp-discovery-worker` as separate artifacts with separate digests, which is a release nobody
    has ever built. The manifest format exists to stop that fiction being representable.
    """
    from acpctl.release import load_manifest

    document = copy.deepcopy(load_manifest(RELEASE_EXAMPLE))
    for name, digest in (("app", DIGEST_A), ("ollama-gateway", DIGEST_C), ("grafana", DIGEST_D)):
        component(document, name)["digest"] = digest
    return document


def manifest_file(tmp_path, *, document=None, name="release.json", as_yaml=False):
    """Write a release manifest for `install` to read. A valid one, unless told otherwise."""
    payload = release_document() if document is None else document
    target = tmp_path / name
    if as_yaml:
        import yaml
        assert target.suffix in (".yaml", ".yml"), (
            "release.load_manifest picks its parser from the suffix, so YAML in a .json file "
            "would be read as JSON and fail for the wrong reason")
        target.write_text(yaml.safe_dump(payload), encoding="utf-8")
    else:
        target.write_text(json.dumps(payload), encoding="utf-8")
    return target


HEALTHY_PREFLIGHT = {"reachable": True, "ok": True, "namespace": "acp-production",
                     "checks": [], "blockers": 0, "warnings": 0, "unknown": 0}


def preflight_returning(report):
    def _preflight(values, *, namespace, context):
        return report
    return _preflight


def run_install(tmp_path, runner, **kwargs):
    """The real install(), against the fake cluster, with a healthy preflight by default."""
    from acpctl.helm import Helm
    from acpctl.install import install

    kwargs.setdefault("namespace", "acp-production")
    kwargs.setdefault("assume_yes", True)
    kwargs.setdefault("preflight", preflight_returning(HEALTHY_PREFLIGHT))
    # NOT setdefault(): its second argument is evaluated eagerly, so a default manifest would be
    # WRITTEN even when the caller passed its own — and to the same path, silently replacing it.
    # That turned a test of a manifest missing one component into a test of the complete one, and
    # it passed.
    if "release_manifest" not in kwargs:
        kwargs["release_manifest"] = str(manifest_file(tmp_path))
    kwargs.setdefault("chart_dir", CHART)
    lines: list[str] = []
    outcome = install(str(EXAMPLE), helm=Helm(runner=runner), echo=lines.append, **kwargs)
    outcome.messages = lines
    return outcome


def text(outcome) -> str:
    return "\n".join(outcome.messages) + "\n" + outcome.reason


# ── the allow-list: this is the file that may mutate, and only this far ───────

def test_the_read_only_allow_list_was_not_widened_to_make_this_work():
    """THE POINT OF PUTTING MUTATION IN ITS OWN MODULE.

    `cluster.run` is what makes `doctor` and `status` safe to run against production from a
    laptop, and the cheapest way to implement an installer would have been to add `apply` to its
    verb list — which would have retired that guarantee for every command at once. This asserts
    the read side is untouched, so a future edit cannot quietly take the shortcut.
    """
    from acpctl import cluster as cluster_mod
    assert cluster_mod.READ_VERBS == {"version", "api-resources", "get"}
    with pytest.raises(cluster_mod.ForbiddenVerb):
        cluster_mod.run(["apply", "-f", "acp.yaml"])


def test_the_helm_allow_list_is_the_documented_set():
    from acpctl import helm as helm_mod
    assert helm_mod.HELM_SUBCOMMANDS == {
        "install", "upgrade", "uninstall", "get", "status", "list", "template", "history"}


@pytest.mark.parametrize("subcommand", ["rollback", "delete", "push", "pull", "plugin",
                                        "dependency", "package", "registry", "repo", "create",
                                        "verify", "search"])
def test_a_helm_subcommand_outside_the_allow_list_is_refused(subcommand):
    """`rollback` is the instructive entry: it is a real helm subcommand acpctl will need in
    phase 5, and it is refused today. An allow-list that pre-authorises the verbs of features
    nobody has written is not an allow-list."""
    from acpctl import helm as helm_mod
    with pytest.raises(helm_mod.ForbiddenCommand):
        helm_mod.check_helm([subcommand, "acp", "-n", "acp-production"])


@pytest.mark.parametrize("verb", ["exec", "patch", "edit", "scale", "annotate", "label",
                                  "rollout", "drain", "cordon", "taint", "replace", "cp",
                                  "port-forward", "proxy", "attach", "debug", "set", "expose",
                                  "run", "apply-set"])
def test_a_kubectl_verb_outside_the_allow_list_is_refused(verb):
    from acpctl import helm as helm_mod
    with pytest.raises(helm_mod.ForbiddenCommand):
        helm_mod.check_kubectl([verb, "deployment/acp-api", "-n", "acp-production"])


@pytest.mark.parametrize("resource", ["deployment", "secret", "namespace", "pod", "statefulset",
                                      "service", "networkpolicy", "node"])
def test_deleting_an_arbitrary_resource_is_refused(resource):
    """`helm uninstall` removes what the release owns. A `kubectl delete` of anything else is a
    tool reaching outside the installation it was pointed at, and there is no undo."""
    from acpctl import helm as helm_mod
    with pytest.raises(helm_mod.ForbiddenCommand):
        helm_mod.check_kubectl(["delete", resource, "acp-api", "-n", "acp-production"])


def test_deleting_a_configmap_that_is_not_the_install_state_is_refused():
    from acpctl import helm as helm_mod
    with pytest.raises(helm_mod.ForbiddenCommand):
        helm_mod.check_kubectl(["delete", "configmap", "someone-elses-config", "-n", "acp"])
    helm_mod.check_kubectl(["delete", "configmap", "acp-installation", "-n", "acp"])


@pytest.mark.parametrize("args", [
    ["delete", "pvc", "data-acp-0", "-n", "acp"],            # by name: ownership asserted, not shown
    ["delete", "pvc", "--all", "-n", "acp"],                 # everything in the namespace
    ["delete", "pvc", "-n", "acp"],                          # no selector at all
])
def test_deleting_volumes_without_a_release_selector_is_refused(args):
    """A PVC holds the one thing an uninstall cannot put back, so the deletion has to be scoped
    by the label that proves the release owns it."""
    from acpctl import helm as helm_mod
    with pytest.raises(helm_mod.ForbiddenCommand):
        helm_mod.check_kubectl(args)


def test_deleting_volumes_by_release_selector_is_allowed():
    from acpctl import helm as helm_mod
    helm_mod.check_kubectl(["delete", "pvc", "-n", "acp", "-l",
                            "app.kubernetes.io/instance=acp-production"])


@pytest.mark.parametrize("resource", ["deployment", "secret", "job", "pvc"])
def test_creating_anything_but_a_namespace_or_the_state_configmap_is_refused(resource):
    from acpctl import helm as helm_mod
    with pytest.raises(helm_mod.ForbiddenCommand):
        helm_mod.check_kubectl(["create", resource, "acp", "-n", "acp"])


def test_apply_is_permitted_only_from_stdin():
    """The only thing acpctl pipes into apply is a manifest it built itself. Allowing `-f <path>`
    would make it a general-purpose applier of whatever a caller pointed it at."""
    from acpctl import helm as helm_mod
    helm_mod.check_kubectl(["apply", "-n", "acp", "-f", "-"])
    with pytest.raises(helm_mod.ForbiddenCommand):
        helm_mod.check_kubectl(["apply", "-n", "acp", "-f", "/tmp/anything.yaml"])


@pytest.mark.parametrize("args", [["--kube-context", "prod", "rollback", "acp"],
                                  ["-n", "acp", "uninstall"]])
def test_a_subcommand_hidden_behind_a_flag_is_refused(args):
    """`cluster.run` scans for the first non-flag argument, which a global flag's VALUE can
    impersonate. This module requires the verb to be first and refuses anything else outright."""
    from acpctl import helm as helm_mod
    with pytest.raises(helm_mod.ForbiddenCommand):
        helm_mod.check_helm(args)


def test_the_guard_runs_on_the_real_path_not_only_in_these_unit_tests(tmp_path):
    """A guard nothing calls is a comment. Reached through Helm.helm(), as install does."""
    from acpctl.helm import ForbiddenCommand, Helm
    runner = FakeRunner()
    with pytest.raises(ForbiddenCommand):
        Helm(runner=runner).helm(["rollback", "acp", "1"])
    assert runner.log == [], "the refused command still reached the runner"


# ── the release manifest: one reader, and it lives in release.py ─────────────

def test_install_carries_no_release_manifest_reader_of_its_own():
    """PRD S6: no parallel release-manifest formats, install-state formats or report schemas.

    `install.py` used to carry a narrow reader of its own — `ReleaseManifest`,
    `load_release_manifest`, `_parse_manifest_text`, `resolve_components`'s alias table — written
    while no format existed, against a shape agreed by message. release.py plus
    packaging/schema/acp-release.schema.json is now the format, so the second reader is deleted
    rather than kept "in case": a duplicate contract nothing else runs is one that drifts without
    failing, and the install is where the drift would have surfaced as a wrong digest.

    ASSERTED BY ABSENCE, which is the only way this stays true. Nothing imports these names any
    more, so a reintroduced copy would break no test — it would simply exist, and be believed.
    """
    from acpctl import install as install_mod

    for gone in ("ReleaseManifest", "load_release_manifest", "_parse_manifest_text",
                 "_disagreement", "_manifest_entries_for", "ManifestError", "COMPONENT_ALIASES",
                 "DIGEST_RE"):
        assert not hasattr(install_mod, gone), (
            f"install.{gone} is back: the release-manifest contract is release.py's, and a "
            f"second reader of it in this module is what PRD S6 forbids")


def test_the_manifest_is_read_as_json_or_yaml_and_installs_the_same_release(tmp_path):
    """Both forms, through the real install. The JSON path is the one that has to keep working
    with no PyYAML at all (PRD S17's air-gapped bundle), and it is release.load_manifest that
    owns that guarantee now — this asserts install actually goes through it."""
    as_json = run_install(tmp_path, FakeRunner(),
                          release_manifest=str(manifest_file(tmp_path, name="a.json")))
    as_yaml = run_install(tmp_path, FakeRunner(),
                          release_manifest=str(manifest_file(tmp_path, name="a.yaml",
                                                             as_yaml=True)))
    assert as_json.code == 0, as_json.reason
    assert as_yaml.code == 0, as_yaml.reason
    assert as_json.state["release"]["components"] == as_yaml.state["release"]["components"]


def test_a_mixed_revision_release_is_refused(tmp_path):
    """PRD workstream A's guarantee is that CI fails on a mixed-revision release. A consumer that
    installs one anyway makes that guarantee decorative — and the result is an API and a worker
    from different commits, which is a class of bug nobody can reproduce afterwards.

    The rule is release.py's (`release.mixed-revision`) rather than this module's, and that is the
    change: the refusal is now the same one `acpctl release verify` gives for the same file."""
    document = release_document()
    component(document, "ollama-gateway")["sourceRevision"] = "a" * 40
    runner = FakeRunner()
    outcome = run_install(tmp_path, runner, release_manifest=str(
        manifest_file(tmp_path, document=document, name="mixed.json")))
    assert outcome.code == 1
    assert "release.mixed-revision" in text(outcome)
    assert mutations(runner) == []


def test_a_release_that_is_not_the_documents_version_is_refused(tmp_path):
    """WHAT REPLACED "components declare different versions".

    The old reader read a `version` on every component and refused a manifest whose components
    disagreed, because the installation record states ONE version. An `ACPRelease` has a single
    `metadata.version` and cannot disagree with itself, so that refusal has no reachable case any
    more — but the fact it protected does: the record writes the DOCUMENT's version, so a release
    calling itself something else would make it a false statement about the running images. That
    check is `release.check_against_document`, and this asserts install runs it."""
    document = release_document()
    document["metadata"]["version"] = "2026.8"
    runner = FakeRunner()
    outcome = run_install(tmp_path, runner, release_manifest=str(
        manifest_file(tmp_path, document=document, name="other-version.json")))
    assert outcome.code == 1
    assert "release.version-mismatch" in text(outcome)
    assert mutations(runner) == []


@pytest.mark.parametrize("digest", ["2026.9", "sha256:abc", "sha256:" + "A" * 64,
                                    "sha1:" + "a" * 40, "@sha256:" + "a" * 64])
def test_anything_that_is_not_a_sha256_digest_is_refused(digest, tmp_path):
    """PRD S5.1: an immutable digest, and nothing that merely looks like one. Uppercase hex is
    refused too, because registries do not produce it and a digest acpctl "normalised" would be
    one the operator cannot grep for in their registry's UI."""
    document = release_document()
    component(document, "app")["digest"] = digest
    runner = FakeRunner()
    outcome = run_install(tmp_path, runner, release_manifest=str(
        manifest_file(tmp_path, document=document, name="bad-digest.json")))
    assert outcome.code == 1
    assert "digest" in text(outcome)
    assert mutations(runner) == []


@pytest.mark.parametrize("missing", ["name", "repository", "digest", "sourceRevision",
                                     "architectures", "serves"])
def test_a_component_missing_a_required_field_is_refused(missing, tmp_path):
    """A component acpctl cannot fully identify is one it cannot record as installed."""
    document = release_document()
    component(document, "app").pop(missing)
    runner = FakeRunner()
    outcome = run_install(tmp_path, runner, release_manifest=str(
        manifest_file(tmp_path, document=document, name=f"no-{missing}.json")))
    assert outcome.code == 1
    assert missing in text(outcome)
    assert mutations(runner) == []


@pytest.mark.parametrize("attestation,rule",
                         [("signature", "release.unsigned"), ("sbom", "release.no-sbom")])
def test_a_release_that_fails_validation_is_refused_rather_than_installed(attestation, rule,
                                                                         tmp_path):
    """THE GUARANTEE THE OLD READER COULD NOT HAVE GIVEN, and the reason this delegation is a
    strengthening rather than a shuffle.

    The narrow reader checked digest shape and revision/version agreement; signatures and SBOMs
    were not fields it read, so a release declaring neither passed it and installed. PRD S5.1
    requires both per image and PRD S13 requires the signature verified before deployment — and
    an unsigned image that reaches a cluster and is only noticed afterwards is precisely the
    failure a pre-install check exists to prevent. Refused before anything is contacted."""
    document = release_document()
    component(document, "app").pop(attestation)
    runner = FakeRunner()
    outcome = run_install(tmp_path, runner, release_manifest=str(
        manifest_file(tmp_path, document=document, name=f"no-{attestation}.json")))
    assert outcome.code == 1
    assert rule in text(outcome)
    assert mutations(runner) == []


def test_two_artifacts_claiming_the_same_chart_image_are_refused(tmp_path):
    """WHAT REPLACED "the three worker artifacts must agree on one digest".

    The chart installs ONE image per component, so two artifacts both claiming to back `worker`
    leaves no correct choice — picking one would deploy an assess worker built from a different
    image than the discovery worker, under a record claiming they matched. The old reader caught
    this by aliasing artifact names to chart roles and comparing digests; the manifest now states
    the mapping outright in `chartImages`, and release.py refuses the ambiguity."""
    document = release_document()
    component(document, "ollama-gateway")["chartImages"] = ["ollama", "worker"]
    runner = FakeRunner()
    outcome = run_install(tmp_path, runner, release_manifest=str(
        manifest_file(tmp_path, document=document, name="ambiguous.json")))
    assert outcome.code == 1
    assert "release.chart-image-ambiguous" in text(outcome)
    assert mutations(runner) == []


def test_only_the_components_this_render_enables_are_required():
    """A document with no Ollama and no Grafana renders neither, so demanding their digests would
    refuse an install over images the cluster will never pull — and the operator's fix would be
    --allow-unpinned, which switches pinning off for the components that DO matter."""
    from acpctl.install import required_components
    from acpctl.values import build_values

    doc = load_example("standard-production")
    assert set(required_components(build_values(doc))) == {"api", "worker", "ollama", "grafana"}
    doc["ai"]["ollama"]["enabled"] = False
    doc["observability"]["grafana"] = False
    assert required_components(build_values(doc)) == ["api", "worker"]


# ── digests, not tags ────────────────────────────────────────────────────────

def test_an_install_with_no_digests_is_refused(tmp_path):
    """PRD S5.1. A tag is a moving reference: two installs a week apart from the same values file
    can run different code, and an installation that cannot say what it ran is not auditable."""
    runner = FakeRunner()
    outcome = run_install(tmp_path, runner, release_manifest=None)
    assert outcome.code == 1
    assert "refusing to install unpinned" in outcome.reason
    assert mutations(runner) == []


@pytest.mark.parametrize("omitted", ["ollama", "worker"])
def test_a_manifest_missing_one_required_component_is_refused(omitted, tmp_path):
    """BOTH KINDS OF REQUIRED COMPONENT, because they are required for different reasons.

    `worker` is unconditional — every render deploys it. `ollama` is required only because THIS
    document enables it (`ai.ollama.enabled`), which is where `required_components` has an actual
    decision to make; the companion test above pins the other side of that decision, where a
    document with Ollama switched off does not demand its digest.

    The refusal names the component, so the operator's next move is to fix the manifest rather
    than to reach for --allow-unpinned, which would switch pinning off for everything.

    UNDER THE ACPRelease CONTRACT THE MISSING THING IS A `chartImages` ENTRY, not an absent
    stanza: one artifact can back several of the chart's images, so what makes an image unpinned
    is no artifact CLAIMING it. release.py refuses that outright (`release.chart-image-unpinned`)
    for every chart component, not only the enabled ones — which is stricter than this module's
    own rule and is left alone rather than relaxed. The enabled-only rule still governs the
    no-manifest path, which is the test above and `test_only_the_components_this_render_enables`.
    """
    document = release_document()
    holder = {"ollama": "ollama-gateway", "worker": "app"}[omitted]
    component(document, holder)["chartImages"] = [
        name for name in component(document, holder)["chartImages"] if name != omitted]
    runner = FakeRunner()
    path = manifest_file(tmp_path, document=document, name=f"without-{omitted}.json")
    outcome = run_install(tmp_path, runner, release_manifest=str(path))
    assert outcome.code == 1
    assert omitted in outcome.reason
    assert mutations(runner) == []


def test_the_same_manifest_with_that_digest_present_installs(tmp_path):
    """The bite check on the pair above: the refusal is about the MISSING DIGEST, not about the
    component being enabled at all. Without this, a bug that refused every install with Ollama
    switched on would pass both of them."""
    runner = FakeRunner()
    outcome = run_install(tmp_path, runner)
    assert outcome.code == 0, outcome.reason
    assert outcome.state["release"]["components"]["ollama"]["digest"] == DIGEST_C


def test_allow_unpinned_installs_but_shouts_and_is_recorded(tmp_path):
    runner = FakeRunner()
    outcome = run_install(tmp_path, runner, release_manifest=None, allow_unpinned=True)
    assert outcome.code == 0, outcome.reason
    assert "INSTALLING UNPINNED" in text(outcome)
    assert outcome.state["release"]["pinned"] is False
    assert outcome.state["flags"]["allowUnpinned"] is True


def test_a_pinned_install_records_a_digest_for_every_enabled_component(tmp_path):
    runner = FakeRunner()
    outcome = run_install(tmp_path, runner)
    assert outcome.code == 0, outcome.reason
    assert outcome.state["release"]["pinned"] is True
    components = outcome.state["release"]["components"]
    assert set(components) == {"api", "worker", "ollama", "grafana"}
    for component, entry in components.items():
        assert re.match(r"^sha256:[0-9a-f]{64}$", entry["digest"]), component


def test_the_digests_reach_the_values_file_helm_is_given(tmp_path):
    """The pin has to reach the CHART, not just the record. A state file saying `pinned: true`
    over a values file with an empty `image.digests` would be a false statement in the one
    document written to be the record of what ran."""
    from acpctl.install import chart_repositories, render_values, resolve_components
    from acpctl.release import load_manifest, validate
    from acpctl.values import build_values

    doc = load_example("standard-production")
    release = validate(load_manifest(manifest_file(tmp_path))).release
    components, unpinned = resolve_components(
        release, ["api", "worker", "ollama", "grafana"],
        chart_repositories(build_values(doc), CHART))
    assert unpinned == []
    rendered = render_values(doc, release)
    for digest in (DIGEST_A, DIGEST_C, DIGEST_D):
        assert digest in rendered
    for component_ in ("api", "worker", "ollama", "grafana"):
        assert components[component_]["digest"] in rendered
    assert build_values(doc)["image"]["digests"] == {}, "build_values must stay digest-free"


def test_the_release_names_the_repositories_and_beats_the_charts_defaults(tmp_path):
    """#1797's finding, carried into the install. The chart's `image.repository` and
    `image.workerRepository` default to `acp` and `acp-worker` — names this repository's build
    does not produce — so an install that took them would record, and pull, an artifact nobody
    published. The release manifest names what was actually built (`acp-app`), and it wins.

    ASSERTED AGAINST THE CHART'S OWN DEFAULT rather than against a literal, so this cannot pass
    vacuously the day the chart is changed to agree."""
    from acpctl.install import chart_repositories
    from acpctl.values import build_values

    doc = load_example("standard-production")
    defaults = chart_repositories(build_values(doc), CHART)
    assert defaults["api"] != "acp-app", "the chart default and the release now agree — retire this"

    outcome = run_install(tmp_path, FakeRunner())
    assert outcome.code == 0, outcome.reason
    components = outcome.state["release"]["components"]
    assert components["api"]["repository"] == "acp-app"
    assert components["worker"]["repository"] == "acp-app"
    assert components["ollama"]["repository"] == "acp-ollama-gateway"


def test_an_unpinned_install_falls_back_to_the_chart_repositories(tmp_path):
    """The other side of the rule above: with no manifest there is nothing better than the name
    the chart would have used, and the record still has to say something. This is why
    `chart_repositories` survives the deletion of the manifest reader."""
    from acpctl.install import chart_repositories
    from acpctl.values import build_values

    outcome = run_install(tmp_path, FakeRunner(), release_manifest=None, allow_unpinned=True)
    assert outcome.code == 0, outcome.reason
    defaults = chart_repositories(build_values(load_example("standard-production")), CHART)
    for name, entry in outcome.state["release"]["components"].items():
        assert entry["digest"] is None
        assert entry["repository"] == defaults[name]


# ── preflight ────────────────────────────────────────────────────────────────

def test_a_preflight_blocker_refuses_the_install(tmp_path):
    runner = FakeRunner()
    outcome = run_install(tmp_path, runner, preflight=preflight_returning({
        "reachable": True, "ok": False, "blockers": 1, "warnings": 0, "unknown": 0,
        "namespace": "acp-production",
        "checks": [{"id": "keda.installed", "status": "fail", "severity": "blocker",
                    "detail": "KEDA is not installed", "remedy": ""}]}))
    assert outcome.code == 1
    assert "keda.installed" in text(outcome)
    assert mutations(runner) == []


def test_a_blocking_check_that_could_not_run_also_refuses(tmp_path):
    """doctor's third outcome, carried through to the install. The checks that cannot run are the
    ones guarding failures that are otherwise silent, so `unknown` on a blocker is not a softer
    case than `fail` — it is the same refusal with less information."""
    runner = FakeRunner()
    outcome = run_install(tmp_path, runner, preflight=preflight_returning({
        "reachable": True, "ok": False, "blockers": 0, "warnings": 0, "unknown": 1,
        "namespace": "acp-production",
        "checks": [{"id": "keda.installed", "status": "unknown", "severity": "blocker",
                    "detail": "could not list API resources", "remedy": ""}]}))
    assert outcome.code == 1
    assert mutations(runner) == []


def test_an_unreachable_cluster_exits_two_rather_than_one(tmp_path):
    """Retryable, and deliberately not a refusal — the same distinction doctor and status make."""
    runner = FakeRunner()
    outcome = run_install(tmp_path, runner, preflight=preflight_returning({
        "reachable": False, "ok": False, "blockers": 1, "warnings": 0, "unknown": 1,
        "namespace": "acp-production", "checks": []}))
    assert outcome.code == 2
    assert mutations(runner) == []


def test_skip_preflight_installs_and_records_that_it_was_skipped(tmp_path):
    runner = FakeRunner()
    outcome = run_install(tmp_path, runner, skip_preflight=True,
                          preflight=preflight_returning({"reachable": True, "ok": False,
                                                         "blockers": 9, "warnings": 0,
                                                         "unknown": 0, "checks": []}))
    assert outcome.code == 0, outcome.reason
    assert outcome.state["flags"]["skipPreflight"] is True
    assert "SKIPPED" in text(outcome)


def test_the_preflight_is_doctors_own_checks_and_not_a_second_copy(monkeypatch):
    """Imported rather than reimplemented, so a check added to doctor gates installs from that
    moment. Asserted by making the cluster unreachable and reading doctor's own finding id back
    out of the install's preflight report."""
    from acpctl import cluster as cluster_mod
    from acpctl import install as install_mod

    monkeypatch.setattr(cluster_mod, "gather", lambda **kw: cluster_mod.ClusterFacts(
        reachable=False, unreachable_reason="no cluster here"))
    report = install_mod.default_preflight({}, namespace="acp", context=None)
    assert report["reachable"] is False
    assert [c["id"] for c in report["checks"]] == ["cluster.reachable"]


# ── consent ──────────────────────────────────────────────────────────────────

def test_a_non_interactive_run_without_yes_exits_two_and_changes_nothing(tmp_path):
    """Silence is not consent. Exit 2 rather than 1 because nothing about the cluster or the
    document was wrong — the pipeline is missing a flag."""
    runner = FakeRunner()
    outcome = run_install(tmp_path, runner, assume_yes=False, confirm=lambda prompt: None)
    assert outcome.code == 2
    assert mutations(runner) == []


def test_answering_no_at_the_prompt_refuses_and_changes_nothing(tmp_path):
    runner = FakeRunner()
    outcome = run_install(tmp_path, runner, assume_yes=False, confirm=lambda prompt: False)
    assert outcome.code == 1
    assert "cancelled" in outcome.reason
    assert mutations(runner) == []


def test_answering_yes_at_the_prompt_installs(tmp_path):
    runner = FakeRunner()
    outcome = run_install(tmp_path, runner, assume_yes=False, confirm=lambda prompt: True)
    assert outcome.code == 0, outcome.reason


def test_the_plan_is_printed_before_the_prompt(tmp_path):
    """PRD S10: the tool generates configuration but does not provision until the plan is
    reviewed. A confirmation prompt with nothing above it is a dialog box, not a review."""
    seen: list[str] = []
    runner = FakeRunner()

    def confirm(prompt):
        seen.append("\n".join(printed))
        return True

    printed: list[str] = []
    from acpctl.helm import Helm
    from acpctl.install import install
    install(str(EXAMPLE), namespace="acp-production", helm=Helm(runner=runner),
            release_manifest=str(manifest_file(tmp_path)), chart_dir=CHART,
            preflight=preflight_returning(HEALTHY_PREFLIGHT), confirm=confirm,
            echo=printed.append)
    assert seen, "the prompt was never reached"
    assert "ACP deployment plan" in seen[0]
    assert "8. Destructive changes" in seen[0]


def test_the_tty_confirm_helper_says_it_could_not_ask_rather_than_no(monkeypatch):
    """Three answers, not two: `None` is "there was nobody to ask", which the caller turns into
    exit 2. Collapsing it into False would report a scripted install as a decision somebody made."""
    import sys as sys_mod

    from acpctl.install import tty_confirm

    class NotATty:
        def isatty(self):
            return False

    monkeypatch.setattr(sys_mod, "stdin", NotATty())
    assert tty_confirm("install?") is None


# ── namespace isolation ──────────────────────────────────────────────────────

def test_a_missing_namespace_is_created(tmp_path):
    runner = FakeRunner(namespace_exists=False)
    outcome = run_install(tmp_path, runner)
    assert outcome.code == 0, outcome.reason
    assert any(argv[1:3] == ["create", "namespace"] for argv in runner.log)


def test_an_unestablished_namespace_is_not_installed_into(tmp_path):
    runner = FakeRunner(fail={"get namespace": "Error: connection refused"})
    outcome = run_install(tmp_path, runner)
    assert outcome.code == 1
    assert "could not establish" in outcome.reason
    assert mutations(runner) == []


def test_a_namespace_holding_a_different_release_is_refused(tmp_path):
    """Two helm releases with different names install side by side without a word from helm, and
    the result is two ACP installations sharing PVC names, a NetworkPolicy and a Postgres
    connection budget computed for one of them."""
    runner = FakeRunner(state=_installed_state(release_name="acp-other"))
    outcome = run_install(tmp_path, runner)
    assert outcome.code == 1
    assert "acp-other" in outcome.reason
    assert mutations(runner) == []


def test_a_namespace_holding_a_different_document_is_refused(tmp_path):
    runner = FakeRunner(state=_installed_state(document_name="acp-staging"))
    outcome = run_install(tmp_path, runner)
    assert outcome.code == 1
    assert "acp-staging" in outcome.reason
    assert mutations(runner) == []


def test_adopt_takes_over_the_namespace_and_records_it(tmp_path):
    runner = FakeRunner(state=_installed_state(release_name="acp-other"))
    outcome = run_install(tmp_path, runner, adopt=True)
    assert outcome.code == 0, outcome.reason
    assert outcome.state["flags"]["adopted"] is True


def test_a_foreign_acp_helm_release_in_the_namespace_is_refused(tmp_path):
    """The state ConfigMap is not the only evidence: an installation put there by helm directly
    has no record, and only `helm list` can see it."""
    runner = FakeRunner(releases=[{"name": "acp-legacy", "chart": "acp-0.1.0"}])
    outcome = run_install(tmp_path, runner)
    assert outcome.code == 1
    assert "acp-legacy" in outcome.reason
    assert mutations(runner) == []


def test_an_unreadable_installation_record_refuses_rather_than_assuming_empty(tmp_path):
    """"I could not read the record" and "there is no record" are opposite conclusions from the
    same empty result, and only one of them means it is safe to install."""
    runner = FakeRunner(configmap_error="Error from server (Forbidden): configmaps is forbidden")
    outcome = run_install(tmp_path, runner)
    assert outcome.code == 1
    assert "not an empty namespace" in outcome.reason
    assert mutations(runner) == []


def test_an_unlistable_namespace_refuses_rather_than_installing_over_an_unknown(tmp_path):
    runner = FakeRunner(list_fails=True)
    outcome = run_install(tmp_path, runner)
    assert outcome.code == 1
    assert mutations(runner) == []


# ── verification: success is never inferred from silence ─────────────────────

def test_an_install_that_cannot_be_verified_fails(tmp_path):
    """THE LOAD-BEARING TEST. `helm upgrade` succeeded and `helm status` then said nothing usable,
    so acpctl did not observe a working release. Exiting 0 there is the failure mode the whole
    packaging CLI is written against, and it is the one an installer falls into most easily
    because everything it ran returned zero."""
    runner = FakeRunner(fail={"status": "Error: query failed"})
    outcome = run_install(tmp_path, runner)
    assert outcome.code == 1
    assert "could NOT be verified" in outcome.reason


def test_a_release_that_lands_in_a_failed_state_is_reported_as_failed(tmp_path):
    runner = FakeRunner()
    original = runner._helm

    def helm(argv, args):
        result = original(argv, args)
        if args[0] == "upgrade":
            runner.release = {"status": "failed", "revision": 1}
        return result

    runner._helm = helm
    outcome = run_install(tmp_path, runner)
    assert outcome.code == 1
    assert "'failed'" in outcome.reason
    assert runner.state["history"][-1]["result"] == "failed"


def test_a_failing_helm_upgrade_is_a_failure_with_no_ok_history(tmp_path):
    runner = FakeRunner(fail={"upgrade": "Error: timed out waiting for the condition"})
    outcome = run_install(tmp_path, runner)
    assert outcome.code == 1
    assert "the install failed" in outcome.reason
    assert [e["result"] for e in runner.state["history"]] == ["failed"]


def test_an_interrupted_install_leaves_no_claim_of_success(tmp_path):
    """The runner raises mid-command: helm was killed, the pipe broke, the process died. acpctl
    did not observe the result, so the one thing it must not do is write a record saying it
    worked."""
    runner = FakeRunner(explode={"upgrade": "killed"})
    outcome = run_install(tmp_path, runner)
    assert outcome.code == 1
    assert "interrupted" in outcome.reason
    assert outcome.state is None
    assert runner.state is not None, "the attempt should still be recorded"
    assert all(entry["result"] == "failed" for entry in runner.state["history"])
    assert json.dumps(runner.state).count('"ok"') == 0


def test_a_state_write_failure_does_not_report_a_clean_install(tmp_path):
    """The release is up but nothing in the cluster can trace it back to a document. Reported as
    a failure with the record printed, because a namespace holding an untraceable ACP is a
    problem somebody has to fix now, not at the next upgrade."""
    runner = FakeRunner(fail={"apply": "Error from server (Forbidden): configmaps is forbidden"})
    outcome = run_install(tmp_path, runner)
    assert outcome.code == 1
    assert "could NOT be written" in outcome.reason
    assert outcome.state is not None


# ── idempotence ──────────────────────────────────────────────────────────────

def test_a_second_identical_run_is_a_no_op_that_still_exits_zero(tmp_path):
    """`install` is `helm upgrade --install`, and re-running is a thing operators legitimately do
    — a CI job, a network blip, uncertainty about whether the first attempt finished."""
    runner = FakeRunner()
    first = run_install(tmp_path, runner)
    assert first.code == 0, first.reason
    before = len(runner.log)

    second = run_install(tmp_path, runner)
    assert second.code == 0, second.reason
    assert second.changed is False
    assert mutations(FakeRunner()) == []
    assert not [argv for argv in runner.log[before:] if "upgrade" in argv], \
        "the second run re-ran helm upgrade"
    assert len(runner.state["history"]) == 1, "the re-run appended a duplicate history entry"


def test_a_changed_document_is_not_a_no_op(tmp_path):
    """The other direction, so the no-op path cannot pass vacuously by never installing anything."""
    import yaml

    runner = FakeRunner()
    assert run_install(tmp_path, runner).code == 0

    doc = load_example("standard-production")
    doc["metadata"]["environment"] = "staging"
    changed = tmp_path / "changed.acp-deployment.yaml"
    changed.write_text(yaml.safe_dump(doc), encoding="utf-8")

    from acpctl.helm import Helm
    from acpctl.install import install
    outcome = install(str(changed), namespace="acp-production", helm=Helm(runner=runner),
                      release_manifest=str(manifest_file(tmp_path)), chart_dir=CHART,
                      assume_yes=True, preflight=preflight_returning(HEALTHY_PREFLIGHT),
                      echo=lambda line: None)
    assert outcome.code == 0, outcome.reason
    assert outcome.changed is True
    assert len(runner.state["history"]) == 2


def test_a_rerun_after_a_failed_attempt_is_not_treated_as_identical(tmp_path):
    """The hashes match and the last attempt did not land. Re-running is the whole point."""
    runner = FakeRunner(fail={"upgrade": "Error: timed out"})
    assert run_install(tmp_path, runner).code == 1
    runner.fail = {}
    outcome = run_install(tmp_path, runner)
    assert outcome.code == 0, outcome.reason
    assert [e["result"] for e in runner.state["history"]] == ["failed", "ok"]


def test_a_changed_release_manifest_is_not_a_no_op(tmp_path):
    """The document is identical and the images are not. A comparison on the document alone would
    call a re-pinned release unchanged and skip the install that was the point of running it."""
    runner = FakeRunner()
    assert run_install(tmp_path, runner).code == 0
    rebuilt = release_document()
    component(rebuilt, "app")["digest"] = DIGEST_B
    moved = manifest_file(tmp_path, document=rebuilt, name="moved.json")
    outcome = run_install(tmp_path, runner, release_manifest=str(moved))
    assert outcome.code == 0, outcome.reason
    assert outcome.changed is True


# ── the record ───────────────────────────────────────────────────────────────

def test_the_install_state_matches_the_shared_contract(tmp_path):
    """The format is consumed by more than this command, so its shape is asserted field by field
    rather than "some JSON was written"."""
    runner = FakeRunner()
    state = run_install(tmp_path, runner).state
    assert state["apiVersion"] == "packaging.acp.mova.io/v1alpha1"
    assert state["kind"] == "ACPInstallation"
    assert set(state["installation"]) == {"name", "namespace", "releaseName", "profile",
                                          "platform", "environment", "version"}
    assert set(state["document"]) == {"path", "sha256"}
    assert set(state["release"]) == {"revision", "version", "pinned", "components",
                                     "manifestSha256"}
    assert set(state["chart"]) == {"name", "version", "appVersion", "valuesSha256"}
    assert set(state["flags"]) == {"skipPreflight", "adopted", "allowUnpinned"}
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", state["recordedAt"])
    assert state["acpctlVersion"]
    assert state["installation"]["namespace"] == "acp-production"
    assert state["chart"]["name"] == "acp"
    entry = state["history"][-1]
    assert entry["action"] == "install" and entry["result"] == "ok"
    assert entry["helmRevision"] == 1


def test_the_record_is_stored_as_the_shared_configmap(tmp_path):
    """Named, not derived from the release, because status and uninstall have to find it in a
    namespace without already knowing which release wrote it."""
    from acpctl.helm import STATE_CONFIGMAP, STATE_KEY
    runner = FakeRunner()
    run_install(tmp_path, runner)
    applied = [json.loads(s) for s in runner.stdins if s]
    assert applied, "nothing was applied"
    manifest = applied[-1]
    assert manifest["kind"] == "ConfigMap"
    assert manifest["metadata"]["name"] == STATE_CONFIGMAP
    assert manifest["metadata"]["namespace"] == "acp-production"
    assert json.loads(manifest["data"][STATE_KEY])["kind"] == "ACPInstallation"


def test_no_secret_reference_or_connection_string_reaches_the_record(tmp_path):
    """PRD S13/S20.6. The record is a ConfigMap, readable by anything with `get configmaps` in
    the namespace — a credential arriving here would be published to a wider audience than the
    Secret it came from, by the tool whose whole job is to be the auditable record."""
    runner = FakeRunner()
    state = run_install(tmp_path, runner).state
    blob = json.dumps(state)
    document = load_example("standard-production")
    for name, ref in document["secrets"]["refs"].items():
        assert ref["name"] not in blob, f"{name}'s secret name reached the state"
        assert ref["key"] not in blob, f"{name}'s secret key reached the state"
    for marker in ("postgres://", "redis://", "AccountKey=", "hunter2", "-----BEGIN"):
        assert marker not in blob


def test_the_leak_check_actually_fires_when_something_leaks():
    """A BITE CHECK ON THE CHECK ABOVE. `secret_leaks` returning [] on a clean state proves
    nothing unless it returns something on a dirty one — a guard that cannot fail is
    indistinguishable from one that passed."""
    from acpctl.state import secret_leaks
    document = load_example("standard-production")
    clean = {"installation": {"name": "acp-production"}}
    assert secret_leaks(clean, document) == []
    leaky = {"installation": {"name": "acp-production"},
             "oops": document["secrets"]["refs"]["database-url"]["name"]}
    assert secret_leaks(leaky, document)


def test_the_history_is_appended_not_replaced(tmp_path):
    import yaml
    runner = FakeRunner()
    run_install(tmp_path, runner)
    doc = load_example("standard-production")
    doc["metadata"]["environment"] = "staging"
    changed = tmp_path / "changed.yaml"
    changed.write_text(yaml.safe_dump(doc), encoding="utf-8")

    from acpctl.helm import Helm
    from acpctl.install import install
    install(str(changed), namespace="acp-production", helm=Helm(runner=runner),
            release_manifest=str(manifest_file(tmp_path)), chart_dir=CHART, assume_yes=True,
            preflight=preflight_returning(HEALTHY_PREFLIGHT), echo=lambda line: None)
    assert [e["action"] for e in runner.state["history"]] == ["install", "install"]
    assert [e["helmRevision"] for e in runner.state["history"]] == [1, 2]


# ── the document itself ──────────────────────────────────────────────────────

def test_an_invalid_document_is_refused_before_anything_is_contacted(tmp_path):
    import yaml
    doc = load_example("standard-production")
    doc["network"]["privateWorkers"] = False          # a rule, not a typo
    bad = tmp_path / "bad.acp-deployment.yaml"
    bad.write_text(yaml.safe_dump(doc), encoding="utf-8")

    from acpctl.helm import Helm
    from acpctl.install import install
    runner = FakeRunner()
    outcome = install(str(bad), namespace="acp-production", helm=Helm(runner=runner),
                      release_manifest=str(manifest_file(tmp_path)), chart_dir=CHART,
                      assume_yes=True, preflight=preflight_returning(HEALTHY_PREFLIGHT),
                      echo=lambda line: None)
    assert outcome.code == 1
    assert runner.log == [], "an invalid document reached the cluster"


def test_a_missing_document_is_a_usage_error(tmp_path):
    from acpctl.helm import Helm
    from acpctl.install import install
    runner = FakeRunner()
    outcome = install(str(tmp_path / "nope.yaml"), namespace="acp-production",
                      helm=Helm(runner=runner), allow_unpinned=True, chart_dir=CHART,
                      assume_yes=True, preflight=preflight_returning(HEALTHY_PREFLIGHT),
                      echo=lambda line: None)
    assert outcome.code == 2


def test_a_namespace_is_required(tmp_path):
    from acpctl.helm import Helm
    from acpctl.install import install
    outcome = install(str(EXAMPLE), namespace="", helm=Helm(runner=FakeRunner()),
                      chart_dir=CHART, echo=lambda line: None)
    assert outcome.code == 2


# ── the command ──────────────────────────────────────────────────────────────

def cli(monkeypatch, runner, argv, *, preflight=None):
    """`acpctl install …` through argparse and the real exit-code path, on the fake cluster."""
    from acpctl import install as install_mod
    from acpctl.cli import main
    from acpctl.helm import Helm

    monkeypatch.setattr(install_mod, "Helm", lambda **kwargs: Helm(runner=runner))
    monkeypatch.setattr(install_mod, "default_preflight",
                        preflight or preflight_returning(HEALTHY_PREFLIGHT))
    return main(argv)


def test_the_command_exits_zero_and_prints_the_state_as_json(tmp_path, monkeypatch, capsys):
    runner = FakeRunner()
    code = cli(monkeypatch, runner, [
        "install", str(EXAMPLE), "-n", "acp-production", "--yes",
        "--release-manifest", str(manifest_file(tmp_path)), "--chart", str(CHART), "--json"])
    out = capsys.readouterr()
    assert code == 0, out.err
    assert json.loads(out.out)["kind"] == "ACPInstallation"


def test_the_command_exits_one_on_a_refusal(tmp_path, monkeypatch, capsys):
    runner = FakeRunner()
    code = cli(monkeypatch, runner, [
        "install", str(EXAMPLE), "-n", "acp-production", "--yes", "--chart", str(CHART)])
    assert code == 1
    assert "unpinned" in capsys.readouterr().err
    assert mutations(runner) == []


def test_the_command_exits_two_when_the_cluster_is_unreachable(tmp_path, monkeypatch, capsys):
    runner = FakeRunner()
    code = cli(monkeypatch, runner, [
        "install", str(EXAMPLE), "-n", "acp-production", "--yes", "--chart", str(CHART),
        "--release-manifest", str(manifest_file(tmp_path))],
        preflight=preflight_returning({"reachable": False, "ok": False, "blockers": 1,
                                       "warnings": 0, "unknown": 1, "checks": []}))
    assert code == 2
    capsys.readouterr()


def test_the_command_requires_a_namespace(capsys):
    """No default from the document, unlike doctor and status. Those read; this one creates, and
    "installed into the wrong namespace" is not a mistake a read-only command can make."""
    from acpctl.cli import main
    with pytest.raises(SystemExit) as exc:
        main(["install", str(EXAMPLE), "--yes"])
    assert exc.value.code == 2
    capsys.readouterr()


def test_install_is_no_longer_advertised_as_unimplemented():
    from acpctl.cli import NOT_YET_IMPLEMENTED, build_parser
    assert "install" not in NOT_YET_IMPLEMENTED
    sub = next(a for a in build_parser()._actions if hasattr(a, "choices") and a.choices)
    assert "install" in sub.choices


def test_upgrade_and_rollback_are_still_refused():
    """The phase boundary, asserted rather than trusted. `install` landing must not have quietly
    switched on the phase-5 commands, whose stubs are what stop an operator believing a backup
    ran.

    support-bundle WAS in this set and has been removed from it, because it is implemented now
    (PRD S5.D.6) — not because the assertion was in the way. The distinction matters: the four
    named below are the ones that would silently mislead if stubbed out badly, and a `backup`
    that exits 0 having done nothing is the specific failure this guards. support-bundle now has
    its own tests; leaving it here would assert that a working command is broken.
    """
    from acpctl.cli import NOT_YET_IMPLEMENTED
    assert {"upgrade", "rollback", "backup", "restore"} <= set(NOT_YET_IMPLEMENTED)
    assert "support-bundle" not in NOT_YET_IMPLEMENTED


# ── fixtures ─────────────────────────────────────────────────────────────────

def _installed_state(*, release_name="acp-production", document_name="acp-production"):
    """A prior installation record, as `install` would have written one."""
    return {
        "apiVersion": "packaging.acp.mova.io/v1alpha1",
        "kind": "ACPInstallation",
        "installation": {"name": document_name, "namespace": "acp-production",
                         "releaseName": release_name, "profile": "standard",
                         "platform": "azure", "environment": "production", "version": "2026.9"},
        "document": {"path": str(EXAMPLE), "sha256": "sha256:" + "0" * 64},
        "release": {"revision": 1, "version": "2026.9", "pinned": True, "components": {},
                    "manifestSha256": "sha256:" + "0" * 64},
        "chart": {"name": "acp", "version": "0.1.0", "appVersion": "2026.9",
                  "valuesSha256": "sha256:" + "0" * 64},
        "recordedAt": "2026-09-01T00:00:00Z",
        "acpctlVersion": "0.1.0-alpha",
        "flags": {"skipPreflight": False, "adopted": False, "allowUnpinned": False},
        "history": [{"action": "install", "at": "2026-09-01T00:00:00Z", "helmRevision": 1,
                     "result": "ok"}],
    }
