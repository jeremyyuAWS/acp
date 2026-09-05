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
import re
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
    # TWO, not three: the example pins assess warm at 5-5 with no autoscale block (the owner's
    # 2026-09-05 parity decision), so it gets no scaler. Asserted as the exact SET of roles rather
    # than a count, because the loop below passes vacuously on an empty list — a chart that
    # rendered no ScaledObject at all would otherwise read as a chart with no bad queries in it.
    roles = {obj["metadata"]["labels"]["acp.mova.io/worker-role"] for obj in scaled}
    assert roles == {"discover", "remediate"}, roles
    for obj in scaled:
        for trigger in obj["spec"]["triggers"]:
            query = trigger["metadata"]["query"]
            assert "type IN (" in query, query
            assert "role =" not in query, f"queries a column the jobs table does not have: {query}"


@needs_helm
def test_each_role_scales_on_its_own_backlog_only():
    """Tiers sharing one depth query would scale all of them on any one tier's backlog — and the
    assess tier is the expensive one, so that is a real bill.

    Assess is pinned warm and has no scaler of its own now, which makes the leak worth checking
    run the OTHER way: no remaining query may count assess's job types. A scaler that did would
    grow discover or remediate every time an assessment backlog built up, on a tier the operator
    deliberately fixed at five replicas — the same wrong bill, arriving from the opposite side.
    """
    from acpctl.inventory import LANE_JOB_TYPES, TIER_ROLE

    manifests = render(load_example("standard-production"))
    queries = {}
    for obj in of_kind(manifests, "ScaledObject"):
        role = obj["metadata"]["labels"]["acp.mova.io/worker-role"]
        queries[role] = obj["spec"]["triggers"][0]["metadata"]["query"]
    assert set(queries) == {"discover", "remediate"}, sorted(queries)
    assert len(set(queries.values())) == 2, "worker roles share a scaler query"
    assert "remediate_file" in queries["remediate"]
    assert "scan_discover" in queries["discover"]
    # Parsed out of the IN list rather than searched for as substrings. The assess lane owns the
    # job type `scan`, which is a substring of discover's `scan_discover` and `scan_folder` — a
    # containment check reports a leak on a query that is correct, and the first draft of this
    # test did exactly that.
    # The label carries the TIER name and LANE_JOB_TYPES is keyed by ROLE; they are the same
    # string for assess and remediate and differ for discover/discovery, which is the mismatch
    # inventory.TIER_ROLE exists for and the one a hand-written lookup gets wrong.
    assess_lane = set(LANE_JOB_TYPES[TIER_ROLE["assess"]])
    for tier, query in queries.items():
        counted = set(re.findall(r"'([^']+)'", query)) - {"queued"}
        leaked = counted & assess_lane
        assert not leaked, (
            f"the {tier} scaler counts the pinned assess tier's backlog: {sorted(leaked)}")
        own = set(LANE_JOB_TYPES[TIER_ROLE[tier]])
        assert counted == own, (
            f"the {tier} scaler counts {sorted(counted)}, not its own lane {sorted(own)}")


@needs_helm
def test_replicas_are_pinned_exactly_where_no_autoscaler_owns_them():
    """Both directions of one rule, and the example now exercises both.

    An AUTOSCALED tier must not also set `spec.replicas`: every `helm upgrade` would reset it to
    the floor and the autoscaler would climb back — a scale-down at the exact moment a deploy is
    already adding load.

    A PINNED tier must set it. The assess tier is pinned warm at 5-5 by the owner's parity
    decision, and the only thing that actually makes five replicas exist is this field. Omitting
    it leaves the Deployment on Kubernetes' default of one, with nothing to scale it up and
    nothing anywhere reporting a difference — the document would say five, the estate would run
    one, and both halves of the decision would read as applied.

    Which tiers are which is read from the rendered manifests (what has a scaler pointed at it),
    not from a list written here, so the two cannot drift apart.
    """
    manifests = render(load_example("standard-production"))
    autoscaled = {obj["spec"]["scaleTargetRef"]["name"]
                  for kind in ("ScaledObject", "HorizontalPodAutoscaler")
                  for obj in of_kind(manifests, kind)}
    assert autoscaled, "nothing in the chart is autoscaled; this test would pass vacuously"

    pinned = []
    for deployment in of_kind(manifests, "Deployment"):
        name = deployment["metadata"]["name"]
        if name in autoscaled:
            assert "replicas" not in deployment["spec"], (
                f"{name} pins replicas while an autoscaler owns them")
        else:
            assert deployment["spec"].get("replicas"), (
                f"{name} has no autoscaler and no replica count, so it will run one replica "
                "whatever the document says")
            pinned.append(name)
    assert pinned, "no pinned tier was rendered; the second half of this test proved nothing"


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


# ── does the chart render what the plan promises? (PRD S21 phase 3, feature parity) ──────────
#
# `acpctl plan` prints the service inventory; `helm install` creates the workloads. Nothing
# compared the two, and they disagree: four services the inventory declares `provisioning:
# in-cluster` have no template in this chart at all.
#
# THE DISAGREEMENT IS NOT VISIBLE FROM EITHER SIDE ALONE. The inventory is a pure function of the
# document and is right about what the document asks for. The chart renders what it has templates
# for and is right about that. Only the comparison says that a document declaring
# `ai.ollama.enabled: true` — which packaging/docs/azure-current.acp-deployment.yaml does, because
# production runs Ollama — plans a service that installing would not create.
#
# TWO NAIVE COMPARISONS OVER-REPORT AND ARE NOT USED. The chart names workloads `acp-api` and
# `acp-worker-assess` where the inventory says `acp-web-api` and `acp-assess` (the tier/role split
# inventory.TIER_ROLE warns about), so a name comparison invents six gaps. And the chart ships two
# images where the inventory lists seven artifacts, because PRD S5.1 wants separately-signed
# images for what is one image today — so an image comparison invents five. The map below is
# explicit for that reason.

# Inventory service name -> the suffix the chart appends to the release name.
RENDERS_AS = {
    "acp-web-api": "api",
    "acp-discovery": "worker-discover",
    "acp-assess": "worker-assess",
    "acp-remediate": "worker-remediate",
    "acp-migrations": "migrate",
    "acp-preflight": "preflight",
}

# Declared in-cluster by the inventory, rendered by nothing. Each entry says what is KNOWN; none
# claims a rationale, because the repository does not record one — the chart simply has no
# template, and unlike the data services (which _dataservices.tpl refuses loudly and explains)
# these fail silently.
NOT_RENDERED = {
    "acp-ollama-gateway": (
        "A RELEASE IMAGE with no template. inventory.IMAGES lists `acp-ollama-gateway`, the "
        "service wants a persistent model volume so a restart does not re-pull multi-GB models, "
        "and production runs it (deploy/public/ creates acp-ollama). The chart declares "
        "`ai.ollama.enabled` in values.yaml and no template reads it. And the answer is not "
        "\"the platform supplies it\": deploy/compose/docker-compose.yml runs ollama/ollama "
        "ungated, so the evaluation path ships a model runtime the production path drops."),
    "acp-otel-collector": (
        "The only one with a seam. `_helpers.tpl` DOES read "
        "`observability.openTelemetry.enabled` and sets OTEL_SDK_DISABLED plus an endpoint — so "
        "the workloads are instrumented and the collector is expected from outside. That is "
        "coherent, and it contradicts the inventory, which calls this service `in-cluster`. One "
        "of the two is wrong; see test_the_otel_endpoint_is_never_actually_set for the sharper "
        "half of the same seam."),
    "acp-grafana": (
        "Upstream image, referenced not rebuilt (the inventory says so). "
        "`observability.grafana.enabled` is a values knob no template reads, and unlike langfuse "
        "and the OTel collector NOTHING else in the render refers to it either — no endpoint, no "
        "credential, no env var. So this and ollama are the two that are simply absent rather "
        "than expected from outside. NOT a platform concern the adapter supplies, either: "
        "deploy/compose/docker-compose.yml deploys grafana ungated, so the EVALUATION path ships "
        "it and the production path does not — see "
        "test_compose_deploys_what_the_chart_omits."),
    "acp-langfuse": (
        "Self-hosted LLM tracing, and the same shape as the OTel collector rather than the same "
        "shape as grafana — which is a distinction the first draft of these tests got wrong. No "
        "template reads `observability.langfuse.mode`, but the chart DOES project the "
        "`langfuse-secret-key` secret into the API container, so the application is configured "
        "to talk to a Langfuse the release does not deploy. Expected from outside, then, and the "
        "inventory calling it `in-cluster` is the half that looks wrong."),
}


def _in_cluster(doc):
    from acpctl.inventory import build_inventory
    return {s.name for s in build_inventory(doc)
            if s.kind in ("service", "job") and s.provisioning == "in-cluster"}


def test_every_in_cluster_service_is_classified():
    """ANTI-VACUOUS, AND THE POINT OF THE MAPS. A service added to the inventory tomorrow must be
    put in one of the two maps — rendered, or explicitly not — instead of joining a gap nobody
    notices. Without this the maps go stale in the direction that hides the problem."""
    from acpctl.spec import load_document
    classified = set(RENDERS_AS) | set(NOT_RENDERED)
    for name in RENDERABLE:
        doc = load_example(name)
        unclassified = _in_cluster(doc) - classified
        assert not unclassified, (
            f"{name} plans in-cluster service(s) {sorted(unclassified)} that this file does not "
            f"classify — add them to RENDERS_AS or to NOT_RENDERED with what is known")


@needs_helm
def test_everything_in_the_renders_as_map_actually_renders():
    doc = load_example("standard-production")
    workloads = {m["metadata"]["name"] for m in render(doc)
                 if m.get("kind") in ("Deployment", "StatefulSet", "Job", "CronJob")}
    for service, suffix in RENDERS_AS.items():
        assert any(w.endswith(suffix) for w in workloads), (
            f"{service} is mapped to a workload ending `{suffix}` and the chart rendered "
            f"{sorted(workloads)}")


@needs_helm
def test_everything_in_the_not_rendered_map_really_is_absent():
    """A STALENESS GUARD, and the same one azure_parity puts on its acknowledged differences: an
    entry that outlives the gap it documents still reads as a considered decision. If somebody
    adds an Ollama template, this fails and the entry has to go."""
    from acpctl.spec import load_document
    doc = load_document(PACKAGING / "docs" / "azure-current.acp-deployment.yaml")
    doc["api"]["replicas"]["min"] = 2                    # the two findings azure-rebuild.md names
    doc["data"]["postgres"]["backupRetentionDays"] = 35
    doc["observability"]["langfuse"] = {"mode": "self-hosted"}
    doc["secrets"]["refs"]["langfuse-secret-key"] = {"name": "langfuse", "key": "secret"}

    planned = _in_cluster(doc)
    for service in NOT_RENDERED:
        assert service in planned, (
            f"{service} is listed as planned-but-unrendered and the inventory no longer plans it "
            f"for this document — the entry is stale")

    # WORKLOADS, not every string in the render — and the first draft of this checked the whole
    # document text and failed, correctly. Turning Langfuse on makes the chart project the
    # `langfuse-secret-key` secret into the API container, which is right: the application talks
    # to Langfuse. Wiring a credential for a service is not deploying it, and conflating the two
    # would have made this test assert the chart must not even know the name.
    workloads = [m for m in render(doc)
                 if m.get("kind") in ("Deployment", "StatefulSet", "Job", "CronJob")]
    identities = set()
    for manifest in workloads:
        identities.add(manifest["metadata"]["name"].lower())
        spec = manifest["spec"]["template"]["spec"]
        for container in spec.get("containers", []) + spec.get("initContainers", []):
            identities.add(container["image"].lower())
    for token in ("ollama", "grafana", "langfuse", "otel"):
        assert not [i for i in identities if token in i], (
            f"the chart now renders a workload for {token} — NOT_RENDERED is stale, which is "
            f"better news than it sounds and still has to be recorded")


@needs_helm
def test_the_derived_production_document_plans_three_services_it_would_not_install():
    """THE HEADLINE, on the document that describes production rather than on an example.

    azure-current.acp-deployment.yaml declares `ai.ollama.enabled: true` and
    `observability.grafana: true` because deploy/public/ creates both. `acpctl plan` lists them;
    `helm install` creates neither. Adopting the chart as the Azure rebuild would silently drop
    the local model runtime that ADR 0010's remediation lane depends on.

    Named as an exact set so that closing one of them fails here and the count in
    packaging/docs/ has to move with it.
    """
    from acpctl.spec import load_document
    doc = load_document(PACKAGING / "docs" / "azure-current.acp-deployment.yaml")
    doc["api"]["replicas"]["min"] = 2
    doc["data"]["postgres"]["backupRetentionDays"] = 35

    planned = _in_cluster(doc)
    assert planned & set(NOT_RENDERED) == {
        "acp-ollama-gateway", "acp-otel-collector", "acp-grafana"}, sorted(planned)


# ── values knobs the chart declares and no template reads ────────────────────────────────────

# A knob that exists and is silently ignored is worse than an absent one: `acpctl values` renders
# it faithfully, `helm install` accepts it without complaint, and an operator reading either sees
# a configured feature. Listed with what is known, same as NOT_RENDERED.
INERT_VALUES = {
    "ai.ollama": "no template reads it; see NOT_RENDERED['acp-ollama-gateway']",
    "observability.grafana": "no template reads it; see NOT_RENDERED['acp-grafana']",
    "observability.langfuse": "no template reads it; see NOT_RENDERED['acp-langfuse']",
    "ai.externalProviders": (
        "FOUND BY FIXING THE GUARD ABOVE, not by looking. `acpctl values` emits the provider "
        "list and no template reads it. The credential does arrive — `ai.mode != local-only` "
        "makes `ai-provider-key` a required secret and secrets are projected — so an external-AI "
        "installation gets a key and no statement of which providers it is for. Whether the "
        "application needs the list at all is unrecorded; `ai.mode` is read and is what gates "
        "ACP_AI_LOCAL_ONLY."),
}


def _template_text() -> str:
    return "\n".join(p.read_text() for p in sorted((CHART / "templates").iterdir())
                      if p.is_file())


@pytest.mark.parametrize("path", sorted(INERT_VALUES))
def test_each_inert_values_key_really_is_unread(path):
    """The staleness half. If a template starts reading one of these, the knob has become live and
    the entry — and probably NOT_RENDERED beside it — is wrong."""
    leaf = path.rsplit(".", 1)[-1]
    assert leaf not in _template_text(), (
        f"values key `{path}` is now read by a template, so it is no longer inert — remove it "
        f"from INERT_VALUES and check whether NOT_RENDERED still holds")


def test_no_other_values_knob_is_silently_ignored():
    """THE GUARD THAT WOULD HAVE CAUGHT ALL OF THIS AT CHART-AUTHORING TIME.

    Every key values.yaml declares must be read by a template, or be listed above as knowingly
    inert. A knob that exists and does nothing is worse than an absent one: `acpctl values`
    renders it, `helm install` accepts it, and both surfaces show a configured feature.

    THE FIRST VERSION OF THIS GUARD DID NOT BITE, and that is why the rule below is shaped the
    way it is. It fell back to `section not in templates`, which exempts every key under any
    section a template mentions anywhere — so `.Values.ai.mode` being read made the whole `ai`
    section live, `ai.ollama` included. A bite check (adding an invented knob under `ai`) passed,
    which was a finding about the guard rather than a guard that held.

    The honest rule needs one exception and exactly one: a section rendered wholesale with
    `toYaml .Values.<section>` legitimately never names its leaves, which is how
    `podSecurityContext` and `securityContext` reach the pod. Everything else must be named.
    """
    values = yaml.safe_load((CHART / "values.yaml").read_text())
    templates = _template_text()
    wholesale = {section for section in values
                 if f"toYaml .Values.{section}" in templates
                 or f"toYaml $.Values.{section}" in templates}

    ignored = []
    for section, body in values.items():
        if section in wholesale:
            continue
        if not isinstance(body, dict):
            if section not in templates and section not in INERT_VALUES:
                ignored.append(section)
            continue
        for key in body:
            if f"{section}.{key}" in INERT_VALUES:
                continue
            if key not in templates:
                ignored.append(f"{section}.{key}")
    assert not ignored, (
        f"values.yaml declares {sorted(ignored)} and no template reads them — either wire them "
        f"up or add them to INERT_VALUES with what is known, so an operator setting one is not "
        f"silently told nothing")


@needs_helm
def test_the_otel_endpoint_is_never_actually_set():
    """THE SEAM THAT DOES NOT MEET, pinned because it is a live misconfiguration rather than a gap.

    `acpctl values` emits `observability.openTelemetry.{enabled, exporter}`. `_helpers.tpl` reads
    `{enabled, endpoint}`. So `exporter: azure-monitor` is rendered and ignored, `endpoint` is
    never written, and the workloads come up with OTEL_SDK_DISABLED=false and no destination —
    instrumentation switched on, pointing nowhere.

    Asserted rather than fixed: what endpoint an `azure-monitor` exporter implies is an adapter
    decision, and inventing one here would be the guess this programme keeps refusing to make.
    """
    from acpctl.spec import load_document
    from acpctl.values import build_values

    doc = load_example("standard-production")
    values = build_values(doc)
    otel = values["observability"]["openTelemetry"]
    assert otel["enabled"] is True and otel.get("exporter")
    assert "endpoint" not in otel, (
        "acpctl values now emits an OTel endpoint — the seam has been closed and this test should "
        "assert the endpoint reaches the workload instead")

    for manifest in render(doc):
        if manifest.get("kind") != "Deployment":
            continue
        env = {e["name"]: e.get("value")
               for e in manifest["spec"]["template"]["spec"]["containers"][0]["env"]}
        assert env.get("OTEL_SDK_DISABLED") == "false", "instrumentation is meant to be on here"
        assert "OTEL_EXPORTER_OTLP_ENDPOINT" not in env, (
            "an OTLP endpoint now reaches the workload — good, and this test needs rewriting to "
            "assert it matches the document's exporter")


def test_compose_deploys_what_the_chart_omits():
    """THE COMPARISON THAT DECIDES WHICH SIDE IS WRONG, and it refutes the comfortable reading.

    While writing the entries above it was tempting to record "these are platform concerns the
    infrastructure adapter supplies" as the likely rationale — it is plausible, and
    presets.PLATFORM_ADAPTER not claiming observability is at least consistent with it.

    `deploy/compose/docker-compose.yml` refutes it. The evaluation path deploys `ollama`,
    `grafana` and `langfuse` as ordinary services with no profile gate, which is to say the
    product includes them. So the inventory is not over-claiming when it calls them in-cluster;
    it agrees with Compose, and the Helm chart — the layer ADR 0048 makes PRIMARY for production
    — is the one outlier. An installation moved from the evaluation path to the production one
    loses three services and nothing says so.

    Asserted rather than written down, because the moment somebody adds these templates (or
    removes them from Compose) the two paths agree again and this test should stop passing for
    the reason it currently does.
    """
    compose = yaml.safe_load(
        (PACKAGING.parent / "deploy" / "compose" / "docker-compose.yml").read_text())
    ungated = {name for name, body in (compose.get("services") or {}).items()
               if not (body or {}).get("profiles")}

    for service in ("ollama", "grafana", "langfuse"):
        assert service in ungated, (
            f"deploy/compose no longer runs {service} ungated — the two deployment paths may "
            f"have converged, and the NOT_RENDERED entries above need re-reading")

    # And the chart still does not. Named as the exact set so closing one moves both sides.
    chart_side = {"acp-ollama-gateway", "acp-grafana", "acp-langfuse"}
    assert chart_side <= set(NOT_RENDERED), sorted(NOT_RENDERED)
