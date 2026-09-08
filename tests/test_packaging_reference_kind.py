"""The disposable reference cluster: does the bundle that CI installs still describe one thing?

WHAT THESE TESTS ARE FOR, AND WHAT THEY ARE NOT. They cannot tell you the install works — only
the workflow can, and that is the point of the workflow. What they can do is stop the four files
that describe the cluster from drifting apart, because every one of those drifts fails LATE: a
renamed secret key, a preset bump that no longer fits the runner, or a Postgres serving fewer
connections than the document declares all produce a twenty-minute job that dies on a Pending pod
or a CrashLoopBackOff, with an error that says nothing about the edit that caused it.

So each test here pins one pair of files that are really one fact written twice.
"""
from __future__ import annotations

import shutil
import subprocess

import pytest
import yaml

from packaging_helpers import PACKAGING, ROOT

REFERENCE = PACKAGING / "reference" / "kind"
SPEC = REFERENCE / "acp-deployment.yaml"
OVERRIDES = REFERENCE / "runner-resources.yaml"
DATA_SERVICES = REFERENCE / "data-services.yaml"
CLUSTER = REFERENCE / "cluster.yaml"
WORKFLOW = ROOT / ".github" / "workflows" / "packaging-kind.yml"
CHART = PACKAGING / "chart" / "acp"
HELM = shutil.which("helm")

needs_helm = pytest.mark.skipif(HELM is None, reason="helm is not installed")

# A GitHub-hosted `ubuntu-latest` runner, as the sizes GitHub documents. The ephemeral-storage
# figure is the one that bites first and the one nobody thinks about: the `small` preset requests
# 4Gi per pod, and five pods of that is more disk than the runner has.
RUNNER_CPU_MILLIS = 4000
RUNNER_MEMORY_MIB = 16 * 1024
RUNNER_DISK_GIB = 14


def document() -> dict:
    from acpctl.spec import load_document
    return load_document(SPEC)


def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def job_env() -> dict:
    return workflow()["jobs"]["install"]["env"]


def run_steps() -> str:
    return "\n".join(s["run"] for s in workflow()["jobs"]["install"]["steps"] if "run" in s)


def render(extra: list[str] | None = None) -> list[dict]:
    from acpctl.values import render_values_yaml
    args = [HELM, "template", "acp", str(CHART), "-f", "-",
            "-f", str(OVERRIDES), *(extra or [])]
    proc = subprocess.run(args, input=render_values_yaml(document()),
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return [d for d in yaml.safe_load_all(proc.stdout) if d]


def deployments(manifests: list[dict]) -> list[dict]:
    return [d for d in manifests if d["kind"] == "Deployment"]


def _quantity_millis(value: str) -> int:
    return int(value[:-1]) if value.endswith("m") else int(float(value) * 1000)


def _quantity_mib(value: str) -> int:
    for suffix, factor in (("Gi", 1024), ("Mi", 1), ("Ti", 1024 * 1024)):
        if value.endswith(suffix):
            return int(float(value[: -len(suffix)]) * factor)
    raise AssertionError(f"unhandled quantity {value!r}")


# ── the document ──────────────────────────────────────────────────────────────
def test_the_reference_document_is_a_real_deployment_document():
    """Run by the REAL validator, not a fixture loader. This document is installed by CI, so a
    contract change that invalidates it has to fail here rather than in the cluster."""
    from acpctl.spec import validate
    result = validate(document())
    assert result.ok, [f.render() for f in result.errors]


def test_the_reference_document_asks_for_nothing_the_cluster_does_not_have():
    """kind gets no KEDA and no ingress controller, so the document must ask for neither. Stated
    as an assertion on the DOCUMENT because that is where the mistake would be made — adding an
    `autoscale` block to make the reference more production-like renders a ScaledObject that
    nothing reconciles, and the tier then sits at its floor with no error anywhere."""
    doc = document()
    assert doc["network"]["publicIngress"] is False
    assert doc["ai"]["ollama"]["enabled"] is False
    assert doc["observability"]["grafana"] is False
    for tier in (doc["api"], *doc["workers"].values()):
        assert "autoscale" not in tier, "an autoscale block needs KEDA, which this cluster has none of"


# ── the overrides ─────────────────────────────────────────────────────────────
def test_the_runner_overrides_touch_nothing_but_requests():
    """THE GUARD THAT KEEPS THIS FILE FROM BECOMING A SECOND DEPLOYMENT DOCUMENT.

    Lowering requests is a scheduling accommodation for a 4-CPU runner. Lowering a LIMIT would be
    a different install from the one the document describes, and the report would go on saying the
    document was what ran.
    """
    def walk(node, path=""):
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            here = f"{path}.{key}" if path else key
            if key == "resources":
                assert set(value) == {"requests"}, (
                    f"{here} sets {sorted(value)}; only `requests` may be overridden here")
            else:
                walk(value, here)

    walk(yaml.safe_load(OVERRIDES.read_text(encoding="utf-8")))


@needs_helm
def test_the_overrides_leave_every_limit_exactly_as_the_document_sets_it():
    """The other direction, rendered rather than read: what Kubernetes receives must carry the
    document's limits. A file that only mentions `requests` could still displace a limit if the
    chart rebuilt the block instead of merging it."""
    from acpctl.values import render_values_yaml
    plain = subprocess.run([HELM, "template", "acp", str(CHART), "-f", "-"],
                           input=render_values_yaml(document()), capture_output=True,
                           text=True, timeout=120)
    assert plain.returncode == 0, plain.stderr
    documented = {d["metadata"]["name"]: d["spec"]["template"]["spec"]["containers"][0]
                  ["resources"]["limits"]
                  for d in yaml.safe_load_all(plain.stdout) if d and d["kind"] == "Deployment"}
    assert documented, "nothing rendered; this test would pass vacuously"
    for deployment in deployments(render()):
        name = deployment["metadata"]["name"]
        limits = deployment["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"]
        assert limits == documented[name], name


@needs_helm
def test_the_installation_fits_the_runner_it_is_installed_on():
    """A preset bump that no longer fits fails HERE, in a second, rather than after a fifteen-
    minute image build — on a Pending pod whose message names cpu and says nothing about ACP.

    Ephemeral storage is the term that bites first and the one nobody thinks about: the `small`
    preset requests 4Gi per pod, and five pods of that is more disk than the runner has.
    """
    cpu = memory = disk = 0
    for deployment in deployments(render()):
        replicas = deployment["spec"].get("replicas", 1)
        requests = deployment["spec"]["template"]["spec"]["containers"][0]["resources"]["requests"]
        cpu += _quantity_millis(requests["cpu"]) * replicas
        memory += _quantity_mib(requests["memory"]) * replicas
        disk += _quantity_mib(requests["ephemeral-storage"]) * replicas
    # Two thirds of the runner, leaving room for Postgres, Redis, the kube system pods and the
    # image itself sitting in the node's containerd.
    assert cpu <= RUNNER_CPU_MILLIS * 2 // 3, f"{cpu}m CPU requested"
    assert memory <= RUNNER_MEMORY_MIB * 2 // 3, f"{memory}Mi memory requested"
    assert disk <= RUNNER_DISK_GIB * 1024 * 2 // 3, f"{disk}Mi ephemeral storage requested"


# ── the render ────────────────────────────────────────────────────────────────
@needs_helm
def test_the_reference_render_contains_only_objects_this_cluster_can_act_on():
    """Two of these are accepted by any API server and reconciled by nothing, which is why they
    are asserted absent rather than left to the install: a ScaledObject with no KEDA and an
    Ingress with no controller both apply cleanly and then do nothing at all."""
    kinds = {d["kind"] for d in render()}
    for absent in ("Ingress", "ScaledObject", "PersistentVolumeClaim", "HorizontalPodAutoscaler"):
        assert absent not in kinds, f"{absent} rendered, and nothing in this cluster reconciles it"
    assert {"Deployment", "Service", "Job", "ServiceAccount"} <= kinds


@needs_helm
def test_one_artifact_serves_every_tier_so_one_kind_load_is_enough():
    """`kind load` copies ONE image. A render naming two would install a second that the node does
    not have, and the pod would sit in ImagePullBackOff against a registry that has no such tag."""
    images = {c["image"]
              for d in render(["--set", "image.repository=acp-app",
                               "--set", "image.workerRepository=acp-app",
                               "--set", "image.tag=ci"])
              for c in d.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])}
    assert images == {"acp-app:ci"}, images


# ── the workflow, against everything else ─────────────────────────────────────
def test_the_workflow_installs_the_document_this_test_file_checks():
    env = job_env()
    assert env["SPEC"] == str(SPEC.relative_to(ROOT))
    assert env["NAMESPACE"] == document()["metadata"]["name"], (
        "acpctl defaults the namespace to metadata.name, so status and doctor would read an empty "
        "namespace and report nothing installed")


def test_the_workflow_creates_exactly_the_secret_keys_the_document_references():
    """THE DRIFT THAT FAILS LATEST AND READS WORST. The chart projects each `secrets.refs` key as
    an uppercase env var, so a key the Secret does not carry becomes a pod stuck in
    CreateContainerConfigError — the one silent prerequisite that is at least loud, but loud in a
    place that says nothing about a renamed key in a YAML file."""
    script = run_steps()
    referenced = set(document()["secrets"]["refs"])
    created = {line.split("--from-literal=", 1)[1].split("=", 1)[0]
               for line in script.splitlines()
               if "--from-literal=" in line and "acp-reference-data" not in line}
    # The data-services credentials are a separate Secret and deliberately not in the document.
    created -= {"postgres-user", "postgres-password"}
    assert created == referenced, f"workflow creates {sorted(created)}, document wants {sorted(referenced)}"


def test_the_connection_strings_name_the_services_the_manifests_define():
    services = {d["metadata"]["name"] for d in yaml.safe_load_all(DATA_SERVICES.read_text())
                if d and d["kind"] == "Service"}
    script = run_steps()
    assert "acp-postgres" in services and "acp-redis" in services
    assert "@acp-postgres:5432" in script
    assert "redis://acp-redis:6379" in script


def test_postgres_serves_the_connection_count_the_document_declares():
    """`data.postgres.maxConnections` is not a note — `acpctl` checks the fleet's worst-case
    demand against it, and that rule was written after a production incident where a fleet
    comfortable at rest exhausted the server the first time it scaled out. A reference Postgres
    serving fewer than the document declares would make the check a fiction on the one cluster
    that could have caught it."""
    declared = document()["data"]["postgres"]["maxConnections"]
    args = [d for d in yaml.safe_load_all(DATA_SERVICES.read_text())
            if d and d["kind"] == "Deployment" and d["metadata"]["name"] == "acp-postgres"
            ][0]["spec"]["template"]["spec"]["containers"][0]["args"]
    assert f"max_connections={declared}" in args, args


def test_the_workflow_loads_the_image_it_installs():
    env = job_env()
    script = run_steps()
    assert 'kind load docker-image "$IMAGE"' in script
    assert "--set image.pullPolicy=Never" in script, (
        "without Never the node may reach for a registry that has no such tag")
    assert ":" in env["IMAGE"], "the tag is what pullPolicy Never resolves against"


def test_the_cluster_pins_a_kubernetes_version_and_the_bytes_behind_it():
    """A reference cluster whose version nobody can name is not a reference, and `kindest/node:v…`
    alone names a version rather than an image: a tag is a mutable pointer, so two runs a month
    apart can report the same Kubernetes version and have run different bytes.

    The digest was NOT here originally, deliberately — inventing one before any run had recorded
    which bytes it pulled would have been a pin to bytes nobody had seen, which is the failure the
    digest rule exists to prevent. The create step prints `docker image inspect`'s RepoDigest on
    every run, so this one came from a run.

    Both halves are asserted because they answer different questions: the tag is what a reader
    recognises and what `MINIMUM_KUBERNETES` is compared against, the digest is what decides which
    bytes run.
    """
    cluster = yaml.safe_load(CLUSTER.read_text(encoding="utf-8"))
    image = cluster["nodes"][0]["image"]
    assert image.startswith("kindest/node:v"), image
    assert not image.endswith(":latest")
    assert "@sha256:" in image, (
        "a tag is a mutable pointer; the create step prints the digest of what it pulled")
    tag, digest = image.split("@")
    assert len(digest) == len("sha256:") + 64, digest
    assert run_steps().count("RepoDigests") == 1, (
        "the run that records the digest is what makes pinning it honest rather than a lookup")


def test_the_workflow_installs_kind_from_a_script_this_repository_owns():
    installer = ROOT / "scripts" / "install_kind.sh"
    assert installer.exists()
    assert "scripts/install_kind.sh" in run_steps()
    steps = workflow()["jobs"]["install"]["steps"]
    third_party = {s["uses"].split("@")[0] for s in steps if "uses" in s}
    # FIRST-PARTY `actions/*` ONLY. The point is not the count but the origin: this job builds an
    # image and stands up a cluster, so a third-party action here runs arbitrary code next to
    # both. `upload-artifact` was added with the acceptance step and is the same first-party,
    # @v4-pinned family already used by ci.yml and four other workflows — adding a NON-`actions/`
    # entry to this set is a different decision and should not be made to get a job green.
    assert third_party <= {"actions/checkout", "actions/setup-python", "actions/setup-dotnet",
                           "actions/cache", "actions/upload-artifact"}, third_party


def test_the_office_analyser_is_built_before_the_image():
    """deploy/public/Dockerfile COPYs spike/dotnet/AcpScan.Cli/bin/Release/net10.0/, and bin/ is
    gitignored. Docker COPY of a missing directory is a hard build failure, so this is a
    prerequisite rather than an optimisation — and the ordering is the whole of it."""
    steps = [s.get("name", "") for s in workflow()["jobs"]["install"]["steps"]]
    assert steps.index("Build the Office analyser CLI") < steps.index("Build the application image")
    assert "spike/dotnet/AcpScan.Cli/AcpScan.Cli.csproj" in run_steps()


def test_the_reference_namespace_enforces_restricted_pod_security():
    """The job labels the namespace so the API SERVER decides whether the chart meets the
    restricted Pod Security Standard, rather than a test reading the YAML the chart produced. A
    pod that does not meet it is rejected at admission and the install fails — which is the whole
    difference between this job and `tests/test_packaging_chart.py`."""
    script = run_steps()
    assert "pod-security.kubernetes.io/enforce=restricted" in script
    assert "pod-security.kubernetes.io/enforce-version=latest" in script, (
        "without pinning the version the standard moves under the run")
    # Admission runs on the POD, so a violating Deployment is CREATED and merely never produces
    # one: the run dies three minutes later on a rollout timeout with nothing to describe, while
    # the message naming the missing fields went past as a warning on the apply. Promoting it is
    # what makes the standard fail where it is violated rather than where it is noticed.
    assert "--warnings-as-errors" in script, (
        "a PodSecurity violation arrives as a warning; unpromoted it becomes a rollout timeout")
    steps = [s.get("name", "") for s in workflow()["jobs"]["install"]["steps"]]
    assert steps.index("Data services") < steps.index("Install"), (
        "the namespace must carry the label before anything is installed into it")


def test_the_data_services_meet_the_standard_the_namespace_enforces():
    """THE LABEL APPLIES TO EVERYTHING IN THE NAMESPACE, INCLUDING THE SCAFFOLDING.

    Labelling the namespace `restricted` was added to prove the CHART meets the standard, and it
    rejected Postgres and Redis first — both images default to running as root, both were written
    before the label existed, and the deployments were accepted while their pods never appeared.
    The failure surfaces as a `rollout status` timeout with no pod to describe, twenty minutes
    before the install the label was added to check.

    The alternative was to exempt them, which would have made the enforcement selective and the
    claim it supports meaningless. So they meet the standard too, and this test says so in the
    same terms `tests/test_packaging_chart.py` uses for the chart's own pods.
    """
    services = [d for d in yaml.safe_load_all(DATA_SERVICES.read_text(encoding="utf-8"))
                if d and d["kind"] == "Deployment"]
    assert len(services) == 2, [d["metadata"]["name"] for d in services]
    for deployment in services:
        spec = deployment["spec"]["template"]["spec"]
        name = deployment["metadata"]["name"]
        pod_security = spec.get("securityContext", {})
        assert pod_security.get("runAsNonRoot") is True, name
        assert pod_security.get("runAsUser"), f"{name} must name a UID; the images default to root"
        assert pod_security.get("seccompProfile", {}).get("type") == "RuntimeDefault", name
        for container in spec["containers"]:
            container_security = container.get("securityContext", {})
            assert container_security.get("allowPrivilegeEscalation") is False, name
            assert container_security.get("capabilities", {}).get("drop") == ["ALL"], name
        # A non-root process cannot write to an emptyDir the kubelet has not handed it. Postgres
        # is the one with a volume and the one this bites: initdb creates PGDATA inside the mount.
        if spec.get("volumes"):
            assert pod_security.get("fsGroup") == pod_security.get("runAsGroup"), (
                f"{name} mounts a volume it will not be able to write to")


def test_the_doctor_step_asserts_its_findings_rather_than_printing_them():
    """`acpctl doctor` cannot exit 0 on this cluster, so the step runs it with `|| true` — and on
    its own that made the step DECORATIVE. It printed a report nothing read, so doctor could have
    stopped reporting anything at all and the job would have gone green.

    The comment it replaced was wrong in both directions: it named NetworkPolicy as the expected
    blocker when that check was UNKNOWN at WARNING severity, while the actual blocker —
    `capacity.floor` — went unmentioned. Installing Calico has since turned the NetworkPolicy
    check into a pass, so `capacity.floor` is the only finding left, and the expectation moved
    because the cluster did. That coupling is the point of asserting rather than describing.
    """
    script = run_steps()
    assert "acpctl doctor" in script and "--json" in script
    assert "capacity.floor" in script, (
        "the step must name the findings it expects, or it cannot tell a changed report from a "
        "report that stopped being produced")
    assert "networkpolicy.enforcement" not in script, (
        "the cluster enforces NetworkPolicy now, so doctor passes that check — expecting it to be "
        "UNKNOWN would assert the CNI is still kindnet")


def test_the_cluster_runs_a_cni_that_enforces_what_the_chart_renders():
    """THE CLAIM `templates/networkpolicy.yaml` SAYS IT CANNOT MAKE, made by the cluster instead.

    Its header: "Kubernetes silently ignores NetworkPolicy objects when the CNI does not implement
    them — no error, no event, no status field saying 'unenforced'." kindnet is such a CNI, so
    every run before this one installed four policies and established nothing about any of them.

    The concrete cost was `networkPolicy.egressPorts`. With nothing enforcing it, a missing port
    could not stop anything and the install passed either way — which is the shape this job exists
    to refuse. With Calico the install itself tests that list, because a worker that cannot reach
    Postgres or Redis does not come up.
    """
    config = yaml.safe_load(CLUSTER.read_text(encoding="utf-8"))
    assert config["networking"]["disableDefaultCNI"] is True, (
        "kindnet accepts NetworkPolicy objects and enforces none of them")
    assert config["networking"]["podSubnet"] == "192.168.0.0/16", (
        "Calico's default IPv4 pool; a mismatch here needs a CALICO_IPV4POOL_CIDR override")
    assert "CALICO_VERSION" in job_env(), "an unpinned CNI moves the cluster under the run"

    steps = [s.get("name", "") for s in workflow()["jobs"]["install"]["steps"]]
    cni = "A CNI that enforces the policies the chart renders"
    assert cni in steps, steps
    assert steps.index("Create the disposable cluster") < steps.index(cni) < steps.index("Install")
    script = run_steps()
    assert "kind create cluster --config packaging/reference/kind/cluster.yaml\n" in script, (
        "`kind create --wait` cannot succeed with no CNI: no node reaches Ready until Calico is "
        "running, so the wait belongs after the CNI, not on the create")


def test_the_enforcement_probe_can_tell_dropped_from_refused():
    """THE WHOLE DESIGN IS THE TARGET, and getting it wrong gives a check that cannot fail.

    Probing a Service port with no backend times out whether or not a policy exists, so it proves
    nothing. The step probes the POSTGRES POD IP: 5432 is in `egressPorts` and must connect, and a
    port that is not in the list, with nothing listening on it, must TIME OUT — because an enforced
    policy DROPS the packet while an unenforced one lets it reach the pod and come back REFUSED.

    So `refused` is the finding, and this asserts the step still distinguishes the two. Postgres
    pods carry none of this chart's labels, so no ingress policy applies to them and ACP's own
    egress policy is the only thing that can drop the packet — which is what makes the result a
    statement about that policy rather than about the cluster in general.
    """
    steps = [s.get("name", "") for s in workflow()["jobs"]["install"]["steps"]]
    probe = "Are the network policies enforced, or merely accepted?"
    assert probe in steps, steps
    assert steps.index("Install") < steps.index(probe)
    script = run_steps()
    assert "status.podIP" in script, (
        "probing a Service port with no backend times out regardless of policy and proves nothing")
    for token in ("refused", "timeout", "connected"):
        assert token in script, f"the probe cannot report {token}, so it cannot discriminate"
    assert "5432" in script and "12345" in script


def test_the_dry_run_covers_the_kinds_the_reference_install_never_creates():
    """THE PREMISE OF THAT STEP, ASSERTED, because it is a claim about two documents and either
    can change.

    The reference document deliberately turns most things off — no autoscaling, no public ingress,
    no Ollama, no Grafana — which is right for a one-node cluster and means whole templates are
    never submitted to an API server. The annotation-type defect found on 2026-09-08 was in six
    render sites and this install exercises three of them, so the same bug in `ollama.yaml` or
    `grafana.yaml` would have shipped.

    If the reference document ever renders everything standard-production does, the dry run adds
    nothing and this test says so. If it renders something standard-production does not, the dry
    run has a hole.
    """
    from acpctl.values import render_values_yaml
    from packaging_helpers import load_example

    def kinds(values: str) -> set[str]:
        proc = subprocess.run([HELM, "template", "acp", str(CHART), "-f", "-", "-f", str(OVERRIDES)],
                              input=values, capture_output=True, text=True, timeout=120)
        assert proc.returncode == 0, proc.stderr
        return {d["kind"] for d in yaml.safe_load_all(proc.stdout) if d}

    installed = kinds(render_values_yaml(document()))
    full = kinds(render_values_yaml(load_example("standard-production")))
    assert installed < full, (
        f"the reference document no longer renders strictly less than standard-production: "
        f"installed={sorted(installed)} full={sorted(full)}")
    uncovered = full - installed
    assert {"HorizontalPodAutoscaler", "Ingress"} <= uncovered, sorted(uncovered)
    script = run_steps()
    assert "--dry-run=server" in script and "--warnings-as-errors" in script, (
        "a dry run that does not run admission proves less than the install beside it")

    # THE THREE THAT USED TO BE SKIPPED. Their CRDs are installed now — the definitions only, not
    # the operators, because `--dry-run=server` validates a custom resource against its schema and
    # needs nothing else. The step must still NAME them: a render that stopped producing them
    # would otherwise leave it passing over a smaller set and reporting nothing about it.
    for kind in ("ExternalSecret", "ScaledObject", "TriggerAuthentication"):
        assert kind in script, (
            f"{kind} is one of the kinds the CRDs are installed for; the step must name it or a "
            f"render that stops producing it goes unnoticed")
    assert "keda" in script and "external-secrets" in script, (
        "without the CRDs those three kinds cannot be validated at all")
    for pin in ("KEDA_CRDS_VERSION", "ESO_CRDS_VERSION"):
        assert pin in job_env(), f"{pin} unpinned moves the schema under the run"
    assert "condition=established" in script, (
        "a CRD is not servable the instant it is created, and 'no matches for kind' reads as a "
        "broken manifest when it is a race")
    assert "-f /tmp/full.yaml" in script, (
        "the dry run must submit the whole render now that nothing needs skipping")


def test_the_ingress_probe_proves_its_own_mechanism_before_trusting_it():
    """"DID NOT CONNECT" IS ALSO WHAT A BROKEN PROBE LOOKS LIKE.

    The step checks that a pod carrying none of the release's labels cannot reach the API. No bash
    `/dev/tcp`, no DNS, no `timeout` — each would produce the same silence and read as a policy
    that works, which is the `cmd | grep X || echo clean` shape this repository already has a scar
    from.

    So it opens a socket to Postgres from the Postgres pod FIRST. That must succeed; when it does
    not, the step reports a broken mechanism rather than a passing check.
    """
    script = run_steps()
    assert "deploy/acp-postgres -- bash" in script, (
        "the probe must come from a pod carrying none of the chart's labels, or the API's ingress "
        "rule does not apply to it and the result says nothing")
    assert "/dev/tcp/acp-postgres/5432" in script, "the positive control is missing"
    assert "/dev/tcp/acp-api/80" in script
    control = script.index("/dev/tcp/acp-postgres/5432")
    probe = script.index("/dev/tcp/acp-api/80")
    assert control < probe, "the control has to run before the verdict it makes trustworthy"
    assert "meaningless" in script, (
        "a failed control must say the mechanism is broken, not that the policy holds")


def test_the_reference_cluster_upgrades_as_well_as_installs():
    """AN INSTALL THAT CANNOT BE UPGRADED IS A DEMO, and every way this chart could fail to
    upgrade is invisible to `helm template` and to a first install:

      - `spec.selector` is immutable, so a selector label that moves with the release installs
        perfectly and makes the first upgrade fail on a running installation.
      - A hook Job is a named object; without `before-hook-creation` the second release finds the
        first one's Job still there.
      - The migration hook is `pre-install,pre-upgrade`, so an upgrade runs it against a schema it
        has already applied.

    The step must change the POD TEMPLATE. `helm upgrade --wait` reports success for a release
    that replaced nothing, so an upgrade with identical values proves only that Helm accepted it —
    which is why the step sets an annotation and then looks for it on the running pods.
    """
    steps = [s.get("name", "") for s in workflow()["jobs"]["install"]["steps"]]
    assert "Can it be upgraded, or only installed?" in steps, steps
    assert steps.index("Install") < steps.index("Can it be upgraded, or only installed?")
    script = run_steps()
    assert "helm upgrade acp" in script
    assert "upgrade-probe" in script, (
        "an upgrade that does not change the pod template replaces nothing and passes vacuously")
    assert "helm -n \"$NAMESPACE\" status acp" in script and "REVISION" in script, (
        "`helm upgrade --wait` exits 0 for a release whose revision did not advance")


def test_the_cluster_is_deleted_even_when_the_job_fails():
    steps = workflow()["jobs"]["install"]["steps"]
    teardown = [s for s in steps if s.get("name") == "Delete the cluster"]
    assert teardown and teardown[0].get("if") == "always()"


# ── the acceptance suite, run against this cluster ────────────────────────────
#
# WHY THESE EXIST. Everything above asks whether the chart installs. The acceptance step asks
# whether the INSTALLATION works, and it is the only place the portable suite meets a real API
# server, real workers and a real CNI — before it existed, "the suite passes" meant "the suite
# agrees with the fake we wrote alongside it". The tests here hold the wiring itself: that the
# step runs against the upgraded release, that its expectation covers every scenario rather than
# the ones somebody remembered, and that a green kind run can never read as a support claim.

ACCEPTANCE_STEP = "Does the installation pass the portable acceptance suite?"


def acceptance_target() -> dict:
    return yaml.safe_load(
        (PACKAGING / "reference" / "kind" / "acceptance-target.yaml").read_text(encoding="utf-8"))


def step_named(name: str) -> dict:
    return next(s for s in workflow()["jobs"]["install"]["steps"] if s.get("name") == name)


def expected_outcomes() -> dict[str, str]:
    """The EXPECTED table out of the step's own assertion script, parsed rather than duplicated.

    A copy here would drift from the workflow silently, and the drift would look like agreement.
    """
    import ast
    import re
    body = re.search(r"python - <<'PY'\n(.*?)\nPY\n", step_named(ACCEPTANCE_STEP)["run"], re.S)
    assert body, "the acceptance step's heredoc terminator is not flush-left; it would not run"
    tree = ast.parse(body.group(1))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "EXPECTED":
            return ast.literal_eval(node.value)
    raise AssertionError("the acceptance step no longer declares an EXPECTED table")


def test_the_acceptance_target_describes_this_cluster_and_not_another():
    target = acceptance_target()
    assert target["kind"] == "ACPAcceptanceTarget"
    assert target["distribution"] == "kind"
    assert target["namespace"] == job_env()["NAMESPACE"], (
        "the descriptor and the job install into different namespaces, so the suite would be "
        "asking a namespace with nothing in it")


def test_the_acceptance_target_declares_no_release_so_it_cannot_read_as_pinned():
    """`pinned` is DERIVED from component digests. This cluster loads a local tag with
    `pullPolicy: Never` and has no registry, so there is no digest — and declaring one to make the
    report look certified is the false pin PRD §5.1 exists to prevent."""
    assert "release" not in acceptance_target(), (
        "the kind descriptor grew a release block; if it carries component digests the report "
        "will claim a pinned release this cluster cannot have")


def test_the_acceptance_target_withholds_the_capabilities_this_job_cannot_honour():
    granted = set(acceptance_target()["capabilities"])
    assert "workload-restart" in granted, (
        "mid-job worker restart is the MVP's hardest requirement and the cluster is disposable; "
        "withholding it skips the one scenario `rollout status` cannot substitute for")
    forbidden = {"fault-injection", "scale-control", "previous-release", "backup-restore"}
    assert not (granted & forbidden), (
        f"the descriptor grants {sorted(granted & forbidden)}. Each is withheld for a reason "
        f"stated in the file — fault injection would take down data services shared with every "
        f"other step in this job, and nothing here builds a previous release to upgrade from.")


def test_the_suite_runs_against_the_upgraded_release_not_the_first_install():
    """A suite that only ever sees a first install certifies the easy half."""
    names = [s.get("name", "") for s in workflow()["jobs"]["install"]["steps"]]
    assert names.index("Can it be upgraded, or only installed?") < names.index(ACCEPTANCE_STEP)
    assert names.index(ACCEPTANCE_STEP) < names.index("Delete the cluster")


def test_the_expectation_covers_every_registered_scenario():
    """THE GUARD WITH THE MOST TEETH. A scenario added to the suite and not to this table would
    run on the reference cluster and have its outcome ignored — and the step would still pass,
    because a comparison over a smaller set is a comparison that succeeded."""
    import sys
    if str(PACKAGING / "acceptance") not in sys.path:
        sys.path.insert(0, str(PACKAGING / "acceptance"))
    from acp_acceptance.scenarios import REGISTRY
    assert set(expected_outcomes()) == set(REGISTRY), (
        f"the acceptance step's EXPECTED table and the scenario registry disagree. "
        f"only in the table: {sorted(set(expected_outcomes()) - set(REGISTRY))}; "
        f"only in the registry: {sorted(set(REGISTRY) - set(expected_outcomes()))}")


def test_every_expected_outcome_is_a_state_the_report_can_carry():
    assert set(expected_outcomes().values()) <= {"pass", "fail", "skip", "unknown"}


def test_no_scenario_is_expected_to_fail():
    """`fail` here would mean shipping a known defect with a test that asserts it stays. An
    outcome that cannot be reached is `unknown` or `skip`; a real failure gets fixed."""
    failing = sorted(k for k, v in expected_outcomes().items() if v == "fail")
    assert not failing, (
        f"{failing} are expected to FAIL on the reference cluster. Fix them, or establish that "
        f"the question cannot be asked here and record that as `unknown` with the reason.")


def test_the_scenarios_expected_to_skip_are_exactly_the_ones_without_capabilities():
    """A skip must come from a withheld capability, not from a scenario quietly not running."""
    import sys
    if str(PACKAGING / "acceptance") not in sys.path:
        sys.path.insert(0, str(PACKAGING / "acceptance"))
    from acp_acceptance.scenarios import REGISTRY
    granted = set(acceptance_target()["capabilities"])
    derived = {sid for sid, scn in REGISTRY.items() if not scn.requires <= granted}
    declared = {k for k, v in expected_outcomes().items() if v == "skip"}
    assert declared == derived, (
        f"the table expects {sorted(declared)} to skip, but the descriptor's capabilities imply "
        f"{sorted(derived)}. A scenario expected to skip for any other reason is one that stopped "
        f"measuring something without anybody deciding to.")


def test_a_green_kind_run_can_never_read_as_a_support_claim():
    """PRD §7/§9: `verified` needs acceptance evidence from a target somebody will certify. kind
    is not one, so the step asserts the report refuses both claims — otherwise a green job is one
    copy-paste away from being a status update that says MVP eligible."""
    run = step_named(ACCEPTANCE_STEP)["run"]
    assert 'report["synthetic"] is False' in run, (
        "nothing asserts the run actually met the cluster; a fake-backend run would pass this "
        "step with ten green scenarios")
    assert 'claim["mvpEligible"]' in run and 'claim["supportedEligible"]' in run


def test_the_acceptance_report_is_kept_even_when_the_step_fails():
    upload = step_named("Keep the acceptance report")
    assert upload["if"] == "always()", (
        "a failed acceptance step whose report was thrown away costs a whole run to reproduce, "
        "and the report is the entire output of the step")
    assert upload["uses"].startswith("actions/upload-artifact@")


def test_the_image_is_stamped_so_the_installation_can_name_itself():
    """`api-readiness` fails on `version_stamped: false`, and the Dockerfile defaults
    BUILD_VERSION to `dev` — which is the exact value /healthz reads as unstamped. A bare
    `docker build` therefore produces an image no acceptance run can pass, and PRD §5.1 requires
    build version metadata on every image anyway."""
    build = step_named("Build the application image")["run"]
    assert "--build-arg BUILD_VERSION=" in build
    assert "--build-arg BUILD_SHA=" in build
    assert "dev" not in build.split("BUILD_VERSION=")[1].split("\n")[0], (
        "BUILD_VERSION is stamped as `dev`, which /healthz reports as version_stamped: false")


def test_the_port_forward_is_proved_usable_before_the_suite_runs():
    """A suite pointed at a port that never opened produces ten `unknown` results whose cause is
    a race in this step, not a fact about the target."""
    run = step_named(ACCEPTANCE_STEP)["run"]
    assert "port-forward" in run and "/healthz" in run
    assert "the port-forward never became usable" in run
