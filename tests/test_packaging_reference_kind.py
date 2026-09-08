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


def test_the_cluster_pins_a_kubernetes_version():
    """A reference cluster whose version nobody can name is not a reference. `kindest/node:latest`
    would move the version under the run."""
    cluster = yaml.safe_load(CLUSTER.read_text(encoding="utf-8"))
    image = cluster["nodes"][0]["image"]
    assert image.startswith("kindest/node:v"), image
    assert not image.endswith(":latest")


def test_the_workflow_installs_kind_from_a_script_this_repository_owns():
    installer = ROOT / "scripts" / "install_kind.sh"
    assert installer.exists()
    assert "scripts/install_kind.sh" in run_steps()
    steps = workflow()["jobs"]["install"]["steps"]
    third_party = {s["uses"].split("@")[0] for s in steps if "uses" in s}
    assert third_party <= {"actions/checkout", "actions/setup-python", "actions/setup-dotnet",
                           "actions/cache"}, third_party


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
    steps = [s.get("name", "") for s in workflow()["jobs"]["install"]["steps"]]
    assert steps.index("Data services") < steps.index("Install"), (
        "the namespace must carry the label before anything is installed into it")


def test_the_cluster_is_deleted_even_when_the_job_fails():
    steps = workflow()["jobs"]["install"]["steps"]
    teardown = [s for s in steps if s.get("name") == "Delete the cluster"]
    assert teardown and teardown[0].get("if") == "always()"
