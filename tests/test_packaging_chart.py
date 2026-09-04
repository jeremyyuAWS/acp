"""The chart renders, and what it renders is what ADR 0048 claims.

WHY THESE TESTS SHELL OUT TO `helm template` RATHER THAN PARSING THE TEMPLATES. A Helm template is
a Go text/template that happens to emit YAML; a test that reads the .yaml files and looks for
substrings is testing the source of a program, not its output. Every interesting property here —
what the manifest actually contains, whether `replicas` is present, whether two platforms produce
the same Deployment — is a property of the RENDER. So the render is what runs.

THE SKIP IS ITSELF TESTED. `helm` is not installed everywhere, and a test file that quietly skips
when it is missing is the shape CLAUDE.md records as indistinguishable from a check that passed —
a whole chart could rot behind a green suite. So `test_ci_has_helm` fails, rather than skips, when
CI is set and helm is absent: the skip is available to a developer on their laptop and unavailable
to the pipeline.
"""
from __future__ import annotations

import copy
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from packaging_helpers import PACKAGING, load_example

CHART = PACKAGING / "chart" / "acp"
HELM = shutil.which("helm")

needs_helm = pytest.mark.skipif(HELM is None, reason="helm is not installed (see test_ci_has_helm)")

# The profiles this chart can render. `evaluation` is Compose-only by contract and `regulated`
# ships asking for self-hosted data services, so both are covered by the fail-closed tests below
# rather than here — listing them as renderable would be asserting something untrue.
RENDERABLE = ("standard-production", "high-availability")


def render(doc: dict, *, extra: list[str] | None = None) -> list[dict]:
    """Deployment document -> acpctl values -> helm template -> parsed manifests."""
    from acpctl.values import render_values_yaml
    values = render_values_yaml(doc)
    proc = subprocess.run(
        [HELM, "template", "acp", str(CHART), "-f", "-", *(extra or [])],
        input=values, capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        raise AssertionError(f"helm template failed:\n{proc.stderr}")
    return [d for d in yaml.safe_load_all(proc.stdout) if d]


def render_error(doc: dict) -> str:
    """The stderr of a render that MUST fail. Asserting it failed is half the test; the other
    half is that the message says why, since an operator sees only this."""
    from acpctl.values import render_values_yaml
    proc = subprocess.run(
        [HELM, "template", "acp", str(CHART), "-f", "-"],
        input=render_values_yaml(doc), capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode != 0, "expected the render to fail, and it succeeded"
    return proc.stderr


def of_kind(manifests: list[dict], kind: str) -> list[dict]:
    return [m for m in manifests if m.get("kind") == kind]


def named(manifests: list[dict], kind: str, suffix: str) -> dict:
    matches = [m for m in of_kind(manifests, kind) if m["metadata"]["name"].endswith(suffix)]
    assert len(matches) == 1, f"expected one {kind} ending {suffix!r}, got {len(matches)}"
    return matches[0]


# ── the environment this file needs ───────────────────────────────────────────

def test_ci_has_helm():
    """The skip guard's guard.

    Without this, a CI runner that loses helm turns every test below into a skip, the suite stays
    green, and the chart is unverified from that day on with nothing reporting it. CLAUDE.md has
    this exact story twice — a check that cannot fail is indistinguishable from one that passed.
    """
    if not os.environ.get("CI"):
        pytest.skip("not CI; a developer without helm may still run the rest of the suite")
    assert HELM is not None, (
        "helm is not on PATH in CI, so every chart test below would silently skip. "
        "Install it in the workflow (see .github/workflows/ci.yml) rather than removing this test."
    )


def test_the_chart_exists_where_acpctl_says_it_does():
    assert (CHART / "Chart.yaml").is_file(), f"no chart at {CHART}"
    assert (CHART / "values.yaml").is_file()


# ── it renders, and what it renders is valid ──────────────────────────────────

@needs_helm
@pytest.mark.parametrize("profile", RENDERABLE)
def test_every_renderable_profile_renders(profile):
    manifests = render(load_example(profile))
    kinds = {m["kind"] for m in manifests}
    assert {"Deployment", "Service", "ServiceAccount", "Job"} <= kinds, kinds
    # One API tier plus one Deployment per worker role, and nothing else claiming to be a
    # workload — a count rather than a membership check, so a duplicated template is caught.
    assert len(of_kind(manifests, "Deployment")) == 4


@needs_helm
def test_helm_lint_passes():
    proc = subprocess.run([HELM, "lint", str(CHART)], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr


@needs_helm
def test_the_bare_chart_does_not_render_a_deployment_with_no_database():
    """`helm install acp ./acp` with no values at all.

    The default values name no secret refs, so this must fail rather than produce an API
    Deployment whose DATABASE_URL is absent — a pod that starts, fails, and reads as an ACP bug.
    """
    proc = subprocess.run([HELM, "template", "acp", str(CHART)],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode != 0, "the bare chart rendered a deployment with no connection details"
    assert "database-url" in proc.stderr


# ── the fail-closed boundary ──────────────────────────────────────────────────

@needs_helm
@pytest.mark.parametrize("profile,mode", [("regulated", "self-hosted"), ("evaluation", "embedded")])
def test_asking_for_in_cluster_data_services_fails_the_render(profile, mode):
    """THE POINT OF THE BOUNDARY. This chart does not provision Postgres, Redis or object storage.

    The tempting behaviour is to render the application anyway and mention the gap in NOTES.txt.
    That installs an ACP that cannot start and reports success: the API comes up, fails readiness
    against a database that was never created, and the operator reads a CrashLoop as a bug in ACP
    rather than as a chart that did not provision what it was asked for.
    """
    stderr = render_error(load_example(profile))
    assert "does not provision in-cluster data services" in stderr
    assert mode in stderr, "the error must name the mode that was asked for"
    assert "postgresql" in stderr


@needs_helm
def test_the_documented_escape_path_actually_works():
    """The control, and the thing that keeps the test above from being a wall.

    A regulated operator who runs Postgres in their own cluster — their own operator, CloudNativePG,
    whatever — is a legitimate and common case. The boundary is about who PROVISIONS it, not about
    where it runs, so `external: true` plus an endpoint in secrets.refs has to render. Without this
    test the guard above could be satisfied by a chart that simply refuses the regulated profile
    outright, which would be a different and much worse product.
    """
    manifests = render(load_example("regulated"), extra=[
        "--set", "postgresql.external=true",
        "--set", "redis.external=true",
        "--set", "objectStorage.external=true",
    ])
    assert len(of_kind(manifests, "Deployment")) == 4


@needs_helm
def test_a_missing_connection_secret_fails_the_render_naming_the_key():
    doc = load_example("standard-production")
    del doc["secrets"]["refs"]["redis-url"]
    stderr = render_error(doc)
    assert "redis-url" in stderr


# ── PRD S22 / ADR 0048: one application package ───────────────────────────────

# What the platform adapter owns, and therefore what may differ between clouds. Everything else
# in a workload must match. Kept as an explicit list rather than a diff-and-eyeball, because the
# whole value of the claim is that the exceptions are enumerable.
ADAPTER_OWNED = (
    "metadata.labels.acp.mova.io/platform",
    "spec.template.spec.containers[].image",          # registry only; repository and tag may not vary
    "spec.template.spec.containers[].env[ACP_PLATFORM]",
)


def _normalise_workload(obj: dict) -> dict:
    """Strip the adapter-owned fields so what remains is the application half.

    NORMALISING IS HOW AN IDENTITY TEST GOES VACUOUS, so each removal below is an IDENTIFIER —
    something that records which cloud this is — and never a behaviour. The distinction is the
    whole test: two clouds may label their objects differently and must not run different code.
    `test_acp_platform_is_provenance_not_a_switch` is what keeps the ACP_PLATFORM removal honest.
    """
    out = copy.deepcopy(obj)
    out["metadata"].get("labels", {}).pop("acp.mova.io/platform", None)
    spec = out.get("spec", {}).get("template", {}).get("spec", {})
    for container in spec.get("containers", []):
        # The registry is the adapter's (ACR, ECR, Artifact Registry); the repository and tag are
        # the release's. Splitting on the last "/" keeps the part that must not vary.
        container["image"] = container["image"].rsplit("/", 1)[-1]
        container["env"] = [e for e in container.get("env", []) if e["name"] != "ACP_PLATFORM"]
    return out


def test_acp_platform_is_provenance_not_a_switch():
    """The normalisation above removes ACP_PLATFORM from the comparison. That is only legitimate
    while nothing branches on it.

    The moment application code reads this variable, two clouds running "the same" Deployment
    behave differently and the identity test above would keep passing — it would be normalising
    away the very fork it exists to catch. So the variable's status as a label is asserted, not
    assumed: it exists for telemetry and support bundles, and if it ever needs to change
    behaviour, that belongs in the values as an explicit application setting where the identity
    test can see it.
    """
    import sys
    root = Path(__file__).resolve().parent.parent
    hits = []
    for path in (root / "api").rglob("*.py"):
        if "ACP_PLATFORM" in path.read_text(encoding="utf-8"):
            hits.append(path.relative_to(root))
    assert not hits, (
        f"application code now reads ACP_PLATFORM ({hits}) — it is no longer provenance, and "
        "_normalise_workload is hiding a real per-cloud behaviour difference")


@needs_helm
def test_the_same_workloads_render_on_every_cloud():
    """ADR 0048's central claim, checked on the RENDERED OBJECTS.

    tests/test_packaging_values.py already checks that the application half of the VALUES is
    identical across platforms. That is a claim about the renderer. This is the claim an operator
    cares about: that the Deployments, Jobs and Services which actually reach four different
    clusters are the same objects — that Azure did not get an extra sidecar, or a different
    probe, or one more replica, because somebody special-cased a cloud in a template.

    A template CAN special-case a platform (`if eq .Values.acpDeployment.platform "azure"`), and
    nothing in the values tests would notice. This is what would.
    """
    base = load_example("standard-production")
    rendered = {}
    for platform, provider, registry in (
        ("azure", "azure-key-vault", "acr.example.org/acp"),
        ("aws", "aws-secrets-manager", "123456789012.dkr.ecr.us-east-1.amazonaws.com/acp"),
        ("gcp", "gcp-secret-manager", "us-docker.pkg.dev/acp/acp"),
        ("kubernetes", "external-secrets", "registry.internal.example.org/acp"),
    ):
        doc = copy.deepcopy(base)
        doc["runtime"]["platform"] = platform
        doc["runtime"]["imageRegistry"] = registry
        doc["secrets"]["provider"] = provider
        rendered[platform] = render(doc)

    reference = rendered["kubernetes"]
    for platform, manifests in rendered.items():
        for kind in ("Deployment", "Job"):
            want = sorted((_normalise_workload(m) for m in of_kind(reference, kind)),
                          key=lambda m: m["metadata"]["name"])
            got = sorted((_normalise_workload(m) for m in of_kind(manifests, kind)),
                         key=lambda m: m["metadata"]["name"])
            assert got == want, (
                f"{platform} renders different {kind} objects than the reference — the "
                f"application package has forked per cloud, which PRD S22 forbids")


@needs_helm
def test_the_adapter_half_really_does_differ():
    """The control for the test above, and it is not a formality.

    Identity is trivially satisfiable by a chart that ignores the platform entirely — which would
    pass the test above while producing an installation that cannot authenticate to any cloud's
    secret store. So the adapter half must be shown to VARY: same application, different
    infrastructure, which is the actual claim rather than half of it.
    """
    base = load_example("standard-production")
    seen = set()
    for platform, provider in (("azure", "azure-key-vault"), ("aws", "aws-secrets-manager")):
        doc = copy.deepcopy(base)
        doc["runtime"]["platform"] = platform
        doc["secrets"]["provider"] = provider
        manifests = render(doc)
        external = of_kind(manifests, "ExternalSecret")
        assert external, f"{platform} rendered no ExternalSecret"
        seen.add(yaml.safe_dump(external[0]["spec"]["secretStoreRef"], sort_keys=True))
    # Both point at a store, and the platform decides which — asserted by the labels differing.
    labels = set()
    for platform in ("azure", "aws"):
        doc = copy.deepcopy(base)
        doc["runtime"]["platform"] = platform
        labels.add(render(doc)[0]["metadata"]["labels"]["acp.mova.io/platform"])
    assert labels == {"azure", "aws"}, "the rendered objects do not record which platform they are for"


# ── the autoscaler, which is where a wrong guess is invisible ─────────────────

def test_the_queue_lanes_match_the_application():
    """acpctl's copy of the worker lane lists against api/core.py's own tuples.

    acpctl deliberately does not import core (that module pulls in the store, the worker pool and
    the connectors; a packaging CLI that needs a database is not a packaging CLI), so the lists
    are duplicated — and this is what stops the duplicate drifting. A lane added to core and not
    here means the scaler for that role counts the wrong jobs, forever, silently.
    """
    import sys
    root = Path(__file__).resolve().parent.parent
    if str(root / "api") not in sys.path:
        sys.path.insert(0, str(root / "api"))
    import core

    from acpctl.inventory import LANE_JOB_TYPES
    assert LANE_JOB_TYPES["discovery"] == core.DISCOVERY_LANE_JOB_TYPES
    assert LANE_JOB_TYPES["assess"] == core.ASSESS_LANE_JOB_TYPES
    assert LANE_JOB_TYPES["remediate"] == core.REMEDIATE_LANE_JOB_TYPES


def test_every_lane_job_type_is_a_real_handler():
    """A typo in a job type is a scaler that counts zero jobs forever — so the tier never scales
    up and nothing anywhere reports why. Checked against the handler registry rather than against
    a second list, because two lists is how the first one goes stale."""
    import sys
    root = Path(__file__).resolve().parent.parent
    if str(root / "api") not in sys.path:
        sys.path.insert(0, str(root / "api"))
    # Importing `worker` alone gives an EMPTY registry: @handler decorators live in
    # api/handlers.py and only run when that module is imported. Asserting against the empty dict
    # would have failed loudly here, but the same mistake inside a lazy check elsewhere would
    # read as "no handlers exist" and pass.
    import handlers  # noqa: F401  — imported for its registration side effects
    from worker import HANDLERS
    assert HANDLERS, "the handler registry is empty; importing handlers did not register anything"

    from acpctl.inventory import LANE_JOB_TYPES
    for role, types in LANE_JOB_TYPES.items():
        unknown = [t for t in types if t not in HANDLERS]
        assert not unknown, f"{role} names job types no handler serves: {unknown}"


@needs_helm
def test_the_queue_scaler_filters_on_the_column_the_table_actually_has():
    """`jobs` has `type`; it has no `role` column.

    The first draft of the template wrote `WHERE role = '<role>'`, inferred from the shape of the
    values file. KEDA answers a Postgres error by logging it and scaling nothing, so the tier sits
    at its floor while the queue grows — the failure has no symptom except autoscaling that never
    happens, which is exactly the kind nobody finds by looking.
    """
    manifests = render(load_example("standard-production"))
    scaled = of_kind(manifests, "ScaledObject")
    assert len(scaled) == 3, "expected one ScaledObject per worker role"
    for obj in scaled:
        for trigger in obj["spec"]["triggers"]:
            query = trigger["metadata"]["query"]
            assert "type IN (" in query, query
            assert "role =" not in query, f"queries a column the jobs table does not have: {query}"


@needs_helm
def test_each_role_scales_on_its_own_backlog_only():
    """Three tiers sharing one depth query would scale all of them on any one tier's backlog —
    and the assess tier is the expensive one, so that is a real bill."""
    manifests = render(load_example("standard-production"))
    queries = {}
    for obj in of_kind(manifests, "ScaledObject"):
        role = obj["metadata"]["labels"]["acp.mova.io/worker-role"]
        queries[role] = obj["spec"]["triggers"][0]["metadata"]["query"]
    assert len(set(queries.values())) == 3, "worker roles share a scaler query"
    assert "remediate_file" in queries["remediate"]
    assert "remediate_file" not in queries["assess"]
    assert "scan_discover" in queries["discover"]


@needs_helm
def test_an_autoscaled_tier_does_not_also_pin_its_replica_count():
    """Setting both means every `helm upgrade` resets replicas to the floor and the autoscaler
    climbs back — a scale-down at the exact moment a deploy is already adding load."""
    manifests = render(load_example("standard-production"))
    for deployment in of_kind(manifests, "Deployment"):
        assert "replicas" not in deployment["spec"], (
            f"{deployment['metadata']['name']} pins replicas while an autoscaler owns them")


# ── the profile guarantees, on the rendered objects ───────────────────────────

@needs_helm
def test_high_availability_gets_a_disruption_budget_and_standard_does_not():
    """Anti-affinity is a preference; a PodDisruptionBudget is what survives a node drain. The
    profile's name is a promise about behaviour, so it is checked on the object that delivers it
    rather than on the values that requested it."""
    ha = render(load_example("high-availability"))
    assert of_kind(ha, "PodDisruptionBudget"), "the HA profile rendered no PDB"

    standard = render(load_example("standard-production"))
    assert not of_kind(standard, "PodDisruptionBudget")


@needs_helm
def test_private_workers_render_a_policy_that_admits_nothing():
    doc = load_example("standard-production")
    assert doc["network"]["privateWorkers"] is True
    manifests = render(doc)
    policy = named(manifests, "NetworkPolicy", "-worker-no-ingress")
    assert policy["spec"]["ingress"] == [], "worker ingress policy is not empty"


@needs_helm
def test_local_only_ai_is_visible_on_the_workload():
    """The regulated profile's central promise is that document content does not leave the cluster
    for a model. A promise nobody can read off the running Deployment is one nobody can audit."""
    manifests = render(load_example("regulated"), extra=[
        "--set", "postgresql.external=true", "--set", "redis.external=true",
        "--set", "objectStorage.external=true",
    ])
    api = named(manifests, "Deployment", "-api")
    env = {e["name"]: e.get("value") for e in api["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env.get("ACP_AI_LOCAL_ONLY") == "1"


@needs_helm
def test_workers_get_no_http_probes():
    """Workers do not listen. A readiness probe on a port nothing serves fails forever; a liveness
    probe on one restarts a healthy worker every failureThreshold."""
    manifests = render(load_example("standard-production"))
    for deployment in of_kind(manifests, "Deployment"):
        if not deployment["metadata"]["name"].endswith("-api"):
            container = deployment["spec"]["template"]["spec"]["containers"][0]
            assert "readinessProbe" not in container, deployment["metadata"]["name"]
            assert "livenessProbe" not in container, deployment["metadata"]["name"]


@needs_helm
def test_the_api_gets_both_probes_and_they_are_not_the_same_endpoint():
    """/readyz reports on dependencies and should remove a pod from the load balancer; /healthz
    reports on the process and should restart it. Pointing both at one endpoint means a database
    outage restarts every pod, which moves the outage around instead of shedding it."""
    api = named(render(load_example("standard-production")), "Deployment", "-api")
    container = api["spec"]["template"]["spec"]["containers"][0]
    assert container["readinessProbe"]["httpGet"]["path"] == "/readyz"
    assert container["livenessProbe"]["httpGet"]["path"] == "/healthz"


@needs_helm
def test_the_migration_runs_before_the_new_code_and_does_not_retry():
    """ADR 0045: migrations are additive, so running first is safe and a failure must stop the
    release rather than re-run DDL against a half-changed database while nobody is watching."""
    job = named(render(load_example("standard-production")), "Job", "-migrate")
    hooks = job["metadata"]["annotations"]["helm.sh/hook"]
    assert "pre-install" in hooks and "pre-upgrade" in hooks
    assert job["spec"]["backoffLimit"] == 0
    assert "hook-failed" not in job["metadata"]["annotations"]["helm.sh/hook-delete-policy"], (
        "deleting the failed migration Job deletes the only record of why it failed")


@needs_helm
def test_the_preflight_check_runs_after_and_does_not_gate():
    """A post-install hook that fails rolls back a deployment that is already serving, so a broken
    check would take down a working install."""
    job = named(render(load_example("standard-production")), "Job", "-preflight")
    hooks = job["metadata"]["annotations"]["helm.sh/hook"]
    assert "post-install" in hooks and "post-upgrade" in hooks


# ── what must never be in the chart ───────────────────────────────────────────

def test_the_chart_contains_no_secret_values():
    """A chart that can hold a credential is one whose values file becomes a secret store — and
    values files get committed, pasted into tickets and attached to support bundles. The chart
    holds REFERENCES; the only `kind: Secret` it may produce is one the External Secrets Operator
    fills in.
    """
    for path in CHART.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        assert "stringData:" not in text, f"{path.name} writes a literal secret value"
        for marker in ("BEGIN RSA PRIVATE KEY", "BEGIN PRIVATE KEY", "AKIA"):
            assert marker not in text, f"{path.name} contains what looks like a credential"


@needs_helm
def test_no_rendered_object_carries_a_literal_credential():
    manifests = render(load_example("standard-production"))
    for obj in manifests:
        assert obj.get("kind") != "Secret", (
            "the chart rendered a Secret directly; connection details must arrive through the "
            "External Secrets Operator or an existing Secret the operator manages")
    text = yaml.safe_dump_all(manifests)
    assert "stringData" not in text
