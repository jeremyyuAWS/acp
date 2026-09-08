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
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from packaging_helpers import PACKAGING, ROOT, load_example

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
    # One API tier plus one Deployment per worker role, and nothing else claiming to be an ACP
    # workload — a count rather than a membership check, so a duplicated template is caught.
    assert len(app_workloads(manifests)) == 4
    # And the model runtime beside them, because every example enables it. Counted separately
    # rather than folded into the four: they are different kinds of thing, and a single number
    # covering both would go on passing if one appeared twice and the other vanished.
    assert len([d for d in of_kind(manifests, "Deployment")
                if d["metadata"]["name"].endswith("-ollama")]) == 1


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
    assert len(app_workloads(manifests)) == 4


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
    import ast
    import re
    root = Path(__file__).resolve().parent.parent

    # THE INVARIANT IS "NOTHING BRANCHES ON IT", NOT "NOTHING MENTIONS IT", and the docstring above
    # has always said so: the variable "exists for telemetry and support bundles". This test used
    # to grep for the NAME, which was an adequate proxy only while no support bundle existed. When
    # `GET /admin/support-bundle` landed on 2026-09-08 and reported the platform as provenance —
    # the use the rule explicitly permits — the grep failed on the intended behaviour.
    #
    # So the check now parses. A read is fine; the value appearing in a CONDITION is not, because
    # that is the fork `_normalise_workload` would hide: an `if`, a `while`, a comparison, a
    # boolean operator or a conditional expression. Reporting the value verbatim passes; comparing
    # it to "azure" does not.
    # CONDITIONS ONLY, AND THROUGH ONE HOP OF ALIASING. Flagging every mention was the old rule
    # and it failed on the intended use; flagging every syntactic `or` would fail on `x or None`,
    # which is a default and not a decision. So the check looks at what a CONDITION is made of —
    # the test of an if/while/assert/conditional-expression, the subject of a match, and any
    # comparison anywhere (`is_azure = plat == "azure"` is a decision even outside an `if`).
    #
    # Aliasing is followed one hop because `plat = os.environ.get("ACP_PLATFORM")` followed by
    # `if plat == "azure"` is the obvious way around a rule that only looked for the literal name,
    # and a guard with an obvious way around it is not a guard.
    branching = []
    for path in (root / "api").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "ACP_PLATFORM" not in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:                     # not this test's business to report
            continue

        def _is_platform_read(value) -> bool:
            """Is this expression the environment read ITSELF, rather than something that merely
            mentions it?

            `plat = os.environ.get("ACP_PLATFORM")` aliases the platform. `ok = record(...,
            platform=os.environ.get("ACP_PLATFORM"))` does NOT — `ok` is a boolean about whether a
            row was written, and treating it as an alias flagged `if ok:` as a per-cloud fork.
            """
            while isinstance(value, (ast.BoolOp, ast.IfExp)):
                value = value.values[0] if isinstance(value, ast.BoolOp) else value.body
            if isinstance(value, ast.Subscript):                     # os.environ["ACP_PLATFORM"]
                return "ACP_PLATFORM" in (ast.get_source_segment(text, value) or "")
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
                if value.func.attr in ("get", "getenv"):
                    return "ACP_PLATFORM" in (ast.get_source_segment(text, value) or "")
            return False

        aliases = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                if node.value is None or not _is_platform_read(node.value):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        aliases.add(target.id)

        def _names(segment: str) -> bool:
            return "ACP_PLATFORM" in segment or any(
                re.search(rf"\b{re.escape(a)}\b", segment) for a in aliases)

        for node in ast.walk(tree):
            if isinstance(node, (ast.If, ast.While, ast.Assert, ast.IfExp)):
                segment = ast.get_source_segment(text, node.test) or ""
            elif isinstance(node, ast.Match):
                segment = ast.get_source_segment(text, node.subject) or ""
            elif isinstance(node, ast.Compare):
                segment = ast.get_source_segment(text, node) or ""
            else:
                continue
            if _names(segment):
                branching.append(f"{path.relative_to(root)}:{node.lineno}")
    assert not branching, (
        f"application code now BRANCHES on ACP_PLATFORM ({branching}) — it is no longer "
        "provenance, and _normalise_workload is hiding a real per-cloud behaviour difference. "
        "Reading it to report it is fine; deciding on it is not. If behaviour must differ, that "
        "belongs in the values as an explicit application setting the identity test can see.")


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


def test_the_production_autoscaler_counts_every_remediate_job_type():
    """The THIRD copy of the remediate lane list, and until now the unguarded one.

    `deploy/public/rightsize-production.sh` hands KEDA a literal SQL query — `type IN (...)` — as
    the remediate tier's queue-depth metric. A job type missing from it is invisible to the
    scaler: the jobs queue, the depth the scaler reads stays at zero, and the tier sits at its
    floor while the backlog grows. The acpctl copy above already carries a comment about exactly
    this failure ("autoscaling silently does not happen") and the guard next to it covers only
    acpctl; adding `deliver_corrected_copy` to core and to acpctl left the scaler counting four
    types out of five, which is how this test came to exist.

    Parsed rather than eyeballed, because the whole point is that nobody reads a shell script
    when they add a handler.
    """
    import re
    import sys
    root = Path(__file__).resolve().parent.parent
    if str(root / "api") not in sys.path:
        sys.path.insert(0, str(root / "api"))
    import core

    script = (root / "deploy/public/rightsize-production.sh").read_text()
    # ANCHORED ON THE RULE'S NAME, not on the first `type IN (...)` in the file. That shortcut
    # was safe only while the remediate rule was the sole scaler in the script; it stopped being
    # safe on 2026-09-06, when an assess rule joined it and a reordering of the two functions
    # would silently have pointed this guard at the wrong lane's query.
    block = re.search(r"--scale-rule-name remediation-queue.*?--scale-rule-auth", script, re.S)
    assert block, "the remediate autoscale rule is no longer named `remediation-queue`"
    match = re.search(r"type IN \(([^)]*)\)", block.group(0))
    assert match, "the remediate autoscale rule no longer contains a `type IN (...)` predicate"
    counted = tuple(value.strip().strip("'") for value in match.group(1).split(","))
    assert set(counted) == set(core.REMEDIATE_LANE_JOB_TYPES), (
        f"the production autoscaler counts {sorted(counted)} but the remediate lane owns "
        f"{sorted(core.REMEDIATE_LANE_JOB_TYPES)}. A type the scaler does not count cannot "
        f"cause the tier to scale up for it.")


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
def test_a_tier_that_runs_more_than_one_replica_gets_a_disruption_budget():
    """Anti-affinity is a preference; a PodDisruptionBudget is what survives a node drain.

    THIS TEST USED TO ASSERT THE DEFECT. It read "high availability gets one and standard does
    not", which is what `values.py` did — while the comment directly above that line described the
    rule as replica count, and standard-production runs a FLOOR OF TWO API replicas. `kubectl
    drain` on the node holding both evicted both, and the cluster autoscaler does exactly that
    during a routine node upgrade: the failure a second replica is bought to prevent, on the
    profile most installations will use. A green test named the profile and never asked what the
    profile actually ran.

    The rule the comment always stated is the rule now, and this asserts it on the object that
    delivers it rather than on the values that requested it.
    """
    for profile in RENDERABLE:
        doc = load_example(profile)
        assert doc["api"]["replicas"]["min"] > 1, f"{profile}: this test would prove nothing"
        budgets = of_kind(render(doc), "PodDisruptionBudget")
        assert budgets, f"{profile} runs {doc['api']['replicas']['min']} API replicas and no PDB"
        assert budgets[0]["spec"]["minAvailable"] == 1, (
            "minAvailable equal to the replica count blocks every drain")


@needs_helm
def test_a_single_replica_tier_gets_no_disruption_budget():
    """The control, and not a symmetry for its own sake: `minAvailable: 1` against ONE replica
    permits no evictions at all, so a budget there does not protect the tier — it stops the node
    being drained. A drain that cannot complete is its own incident."""
    doc = load_example("standard-production")
    doc["api"]["replicas"] = {"min": 1, "max": 4}
    assert not of_kind(render(doc), "PodDisruptionBudget")


@needs_helm
def test_the_egress_policy_lets_acp_reach_its_own_api():
    """`helm install` FAILED ON EVERY CLUSTER THAT ENFORCES NETWORKPOLICY, and no render could
    show it.

    The preflight hook reads `http://<release>-api:80/readyz` and carries this chart's selector
    labels, so the `-egress` policy applies to it. That policy lists the ports ACP needs to leave
    the CLUSTER on — 53, 443, 5432, 6379, 6380 — and reaching your own API is not egress in the
    sense the list was written for, so neither the service port nor the container port was there.
    The request was dropped, the hook exited 1, and Helm failed the release:

        Error: INSTALLATION FAILED: failed post-install: job acp-preflight failed
        [preflight] could not reach http://acp-api:80/readyz: <urlopen error timed out>

    Eleven green reference runs said nothing about it, because kindnet accepts NetworkPolicy
    objects and enforces none of them. It surfaced the first time the cluster ran Calico.

    Asserted as a rule SCOPED TO THE API PODS rather than as a port in the global list, because
    `to` plus `ports` is an AND: this permits ACP's pods to reach ACP's API and nothing else.
    Both ports are required — a ClusterIP connection is DNATed to the backend before it leaves,
    and which one a given CNI matches on is not something this chart should depend on.
    """
    doc = load_example("standard-production")
    manifests = render(doc)
    policy = named(manifests, "NetworkPolicy", "-egress")
    scoped = [rule for rule in policy["spec"]["egress"] if rule.get("to")]
    assert len(scoped) == 1, policy["spec"]["egress"]
    selector = scoped[0]["to"][0]["podSelector"]["matchLabels"]
    assert selector.get("app.kubernetes.io/component") == "api", selector

    api = named(manifests, "Deployment", "-api")["spec"]["template"]
    assert selector.items() <= api["metadata"]["labels"].items(), (
        f"the rule selects pods the API Deployment does not produce: {selector}")

    allowed = {p["port"] for p in scoped[0]["ports"]}
    service = named(manifests, "Service", "-api")["spec"]["ports"][0]["port"]
    container = api["spec"]["containers"][0]["ports"][0]["containerPort"]
    assert {service, container} <= allowed, (
        f"the rule allows {sorted(allowed)}; a ClusterIP connection is DNATed to {container} "
        f"from {service} and either may be what the CNI matches on")

    # The preflight hook is the pod that failed. Its URL must be one this rule admits.
    preflight = named(manifests, "Job", "-preflight")["spec"]["template"]
    command = " ".join(preflight["spec"]["containers"][0]["command"])
    assert f":{service}/readyz" in command, (
        "the preflight URL no longer uses the service port this rule was written for")
    egress_applies = {k: v for k, v in preflight["metadata"]["labels"].items()
                      if k in policy["spec"]["podSelector"]["matchLabels"]}
    assert egress_applies == policy["spec"]["podSelector"]["matchLabels"], (
        "the preflight pod is no longer covered by the egress policy; if that is deliberate this "
        "test is testing nothing")


@needs_helm
def test_the_api_admits_only_the_release_when_nothing_outside_it_should_call():
    """A NETWORKPOLICY INGRESS RULE WITH NO `from` ADMITS EVERY POD IN EVERY NAMESPACE.

    This rule carried `ports` and nothing else. Under a CNI that does not enforce, that is
    invisible; under one that does, it is the posture the release ships with.

    The chart narrows only the half it can reason about. With a public ingress the controller
    lives in a namespace this chart cannot name — ingress-nginx, traefik, an application gateway —
    so a guessed selector would break every installation whose controller is elsewhere. With no
    public ingress there is nothing outside the release that legitimately calls the API.

    Both directions are asserted, because the failure that matters is a rule that reads as
    tightened and is not.
    """
    private = load_example("standard-production")
    private["network"]["publicIngress"] = False
    private["runtime"].pop("publicUrl", None)
    rule = named(render(private), "NetworkPolicy", "-api")["spec"]["ingress"][0]
    assert "from" in rule, "no `from` admits every pod in every namespace"
    selector = rule["from"][0]["podSelector"]["matchLabels"]
    assert selector, "an empty podSelector is every pod in the namespace, which tightens nothing"

    # The pods that must still get through, named from the render rather than assumed. The
    # preflight hook is the one that failed when this policy's egress half was wrong.
    manifests = render(private)
    for kind, suffix in (("Deployment", "-api"), ("Job", "-preflight")):
        labels = named(manifests, kind, suffix)["spec"]["template"]["metadata"]["labels"]
        assert selector.items() <= labels.items(), f"{suffix} can no longer reach the API"

    public = load_example("standard-production")
    assert public["network"]["publicIngress"] is True, "this test would prove nothing"
    open_rule = named(render(public), "NetworkPolicy", "-api")["spec"]["ingress"][0]
    assert "from" not in open_rule, (
        "with a public ingress the controller's namespace is not knowable here; guessing one "
        "breaks every installation whose controller lives somewhere else")


@needs_helm
def test_naming_api_ingress_peers_replaces_the_default_either_way():
    """The escape hatch, asserted on BOTH branches. An operator with a scraper or a controller
    outside the release names its peers, and that must win whether or not a public ingress is
    rendered — otherwise the knob silently does nothing in exactly the configuration that needs
    it."""
    peer = ["--set", "networkPolicy.apiIngressFrom[0].namespaceSelector."
                     "matchLabels.kubernetes\\.io/metadata\\.name=ingress-nginx"]
    for public in (True, False):
        doc = load_example("standard-production")
        doc["network"]["publicIngress"] = public
        if not public:
            doc["runtime"].pop("publicUrl", None)
        rule = named(render(doc, extra=peer), "NetworkPolicy", "-api")["spec"]["ingress"][0]
        assert rule["from"] == [{"namespaceSelector": {
            "matchLabels": {"kubernetes.io/metadata.name": "ingress-nginx"}}}], (public, rule)


@needs_helm
def test_private_workers_render_a_policy_that_admits_nothing():
    doc = load_example("standard-production")
    assert doc["network"]["privateWorkers"] is True
    manifests = render(doc)
    policy = named(manifests, "NetworkPolicy", "-worker-no-ingress")
    assert policy["spec"]["ingress"] == [], "worker ingress policy is not empty"


@needs_helm
def test_every_pod_meets_the_restricted_pod_security_standard():
    """THREE QUARTERS OF A STANDARD IS NOT THE STANDARD.

    `runAsNonRoot`, `allowPrivilegeEscalation: false` and `capabilities.drop: [ALL]` were all here.
    Without a seccomp profile the pods still fail admission in a namespace enforcing `restricted`,
    so PRD S5.B's "restricted pod security where technically possible" described three of the four
    things it needs — and the absence of the field means `Unconfined`, which is precisely what the
    standard exists to refuse.

    Asserted on EVERY pod the chart renders, hook Jobs and dependencies included, because
    admission does not exempt the ones that are inconvenient. The reference cluster now enforces
    the label, so this assertion and the API server agree or the install fails.
    """
    manifests = render(load_example("standard-production"))
    pods = [d for d in manifests if d["kind"] in ("Deployment", "Job")]
    assert pods, "nothing rendered; this test would prove nothing"
    for workload in pods:
        spec = workload["spec"]["template"]["spec"]
        name = workload["metadata"]["name"]
        pod_security = spec.get("securityContext", {})
        assert pod_security.get("seccompProfile", {}).get("type") == "RuntimeDefault", name
        assert pod_security.get("runAsNonRoot") is True, name
        for container in spec["containers"]:
            container_security = container.get("securityContext", {})
            assert container_security.get("allowPrivilegeEscalation") is False, name
            assert container_security.get("capabilities", {}).get("drop") == ["ALL"], name
        # `restricted` also constrains volume TYPES, and the chart now renders one: the scratch
        # emptyDir that makes `readOnlyRootFilesystem` possible. Asserted against the standard's
        # named list rather than against "none", so a hostPath — the type this actually exists to
        # refuse — fails here instead of at admission on someone's cluster.
        allowed = {"configMap", "secret", "emptyDir", "projected", "downwardAPI",
                   "persistentVolumeClaim", "ephemeral"}
        for volume in spec.get("volumes") or []:
            kinds = set(volume) - {"name"}
            assert kinds <= allowed, (
                f"{name} mounts {sorted(kinds)}, which the restricted standard does not allow")


@needs_helm
def test_grafana_differs_from_the_other_pods_in_exactly_one_field():
    """Grafana's image runs as 472 and owns its data directory as 472, so that UID cannot be
    shared. Everything else must be — and writing the three fields out by hand is how this pod
    would have become the only one without a seccomp profile, failing admission in a restricted
    namespace while every other workload passed."""
    manifests = render(load_example("standard-production"))
    grafana = named(manifests, "Deployment", "-grafana")["spec"]["template"]["spec"]
    api = named(manifests, "Deployment", "-api")["spec"]["template"]["spec"]
    differing = {k for k in set(grafana["securityContext"]) | set(api["securityContext"])
                 if grafana["securityContext"].get(k) != api["securityContext"].get(k)}
    assert differing == {"runAsUser", "fsGroup"}, differing


@needs_helm
def test_tracing_gets_all_three_of_the_variables_it_needs():
    """`api/lf.py` is `_ENABLED = bool(_HOST and _PK and _SK)`.

    The chart projected the secret key alone, so a document that declared a Langfuse mode,
    satisfied the reference the contract demanded and provisioned a Langfuse got one third of what
    the module needs. It reports itself disabled and raises nothing — the quietest way a feature
    can be absent.

    Asserted as all three together, because that is the condition the application evaluates. Two
    of three is the same as none.
    """
    api = named(render(load_example("standard-production")), "Deployment", "-api")
    env = {e["name"]: e for e in api["spec"]["template"]["spec"]["containers"][0]["env"]}
    for name in ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        assert name in env, f"{name} missing; api/lf.py needs all three: {sorted(env)}"
    assert env["LANGFUSE_HOST"]["value"].startswith("https://")
    # The keys are references, the host is not. A host in a Secret would be a value nobody needs
    # to protect sitting where the things that do are kept.
    for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        assert "secretKeyRef" in env[key]["valueFrom"], key
    assert "value" in env["LANGFUSE_HOST"]


@needs_helm
def test_tracing_switched_off_renders_no_host():
    """The control. A chart that always rendered the host would carry an empty variable on every
    installation with tracing disabled, which reads as configured and is not."""
    doc = load_example("standard-production")
    doc["observability"]["langfuse"] = {"mode": "disabled"}
    del doc["secrets"]["refs"]["langfuse-secret-key"]
    del doc["secrets"]["refs"]["langfuse-public-key"]
    api = named(render(doc), "Deployment", "-api")
    names = {e["name"] for e in api["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert not any(n.startswith("LANGFUSE_") for n in names), sorted(names)


@needs_helm
def test_the_application_is_told_which_environment_it_is_in():
    """ONE UNDERSCORE FROM A SECURITY CONTROL.

    The chart rendered `ACP_ENVIRONMENT` — a name nothing in `api/` reads — while `api/core.py`
    computes IS_PROD from `ACP_DEPLOY_ENV`, and IS_PROD is what forces TEST_BYPASS_ENABLED off:
    the X-E2E-Key and X-Demo-Key gate bypasses are refused in production regardless of the opt-in
    that enables them.

    `api/core.py` records this failing once already, in its own words — "IS_PROD stayed False on
    the public demo, and the X-E2E-Key bypass stayed live" — because the variable operators were
    told to set never reached the container. The bypass is fail-closed now, so nothing was open
    here; what was true is that an installation enabling it for staging and promoting the same
    values to production kept it, because the chart gave the application no way to know which it
    was.

    Asserted on every workload, since the bypass is checked wherever a request lands.
    """
    doc = load_example("standard-production")
    assert doc["metadata"]["environment"] == "production"
    workloads = app_workloads(render(doc))
    assert workloads, "nothing rendered; this test would prove nothing"
    for workload in workloads:
        env = {e["name"]: e.get("value")
               for e in workload["spec"]["template"]["spec"]["containers"][0]["env"]}
        assert env.get("ACP_DEPLOY_ENV") == "production", workload["metadata"]["name"]
        assert "ACP_ENVIRONMENT" not in env, (
            f"{workload['metadata']['name']} carries both names, leaving a reader to guess which "
            f"one the application acts on")


@needs_helm
def test_a_non_production_document_does_not_claim_production():
    """The control, and the direction that matters: a chart hardcoding "production" would satisfy
    the test above while telling every development installation to refuse its own test bypasses —
    and, worse, would make the value meaningless the moment anyone relied on it."""
    doc = load_example("standard-production")
    doc["metadata"]["environment"] = "staging"
    api = named(render(doc), "Deployment", "-api")
    env = {e["name"]: e.get("value")
           for e in api["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["ACP_DEPLOY_ENV"] == "staging"


@needs_helm
def test_the_worker_drains_for_as_long_as_kubernetes_waits_for_it():
    """A GRACE PERIOD IS NOT A DRAIN. Kubernetes waits `terminationGracePeriodSeconds` before
    SIGKILL; how long the worker keeps working is `ACP_SHUTDOWN_DRAIN_SECONDS`, which
    `api/core.py:1943` defaults to 20 and this chart never set.

    So the template asked for 300 seconds and the pod used 20 of them — less than the 30 the
    template's own comment calls too short — then idled for 280 while the document it abandoned
    went back on the queue to be retried from the top. Nothing failed; a rolling upgrade just cost
    more than it looked like it did.

    Asserted as a RELATIONSHIP rather than two numbers, because the defect was never a wrong
    value: it was two values that were not connected to each other.
    """
    for deployment in [d for d in app_workloads(render(load_example("standard-production")))
                       if d["metadata"]["labels"]["app.kubernetes.io/component"] == "worker"]:
        pod = deployment["spec"]["template"]["spec"]
        env = {e["name"]: e.get("value") for e in pod["containers"][0]["env"]}
        assert "ACP_SHUTDOWN_DRAIN_SECONDS" in env, deployment["metadata"]["name"]
        drain = int(env["ACP_SHUTDOWN_DRAIN_SECONDS"])
        grace = int(pod["terminationGracePeriodSeconds"])
        assert 0 < drain < grace, (deployment["metadata"]["name"], drain, grace)
        assert drain > 30, "less than the platform default the template calls too short"


@needs_helm
def test_a_shorter_grace_period_shortens_the_drain_with_it():
    """The relationship holds when the operator moves the grace period, which is the point of
    deriving one from the other. A chart that hardcoded 240 would pass the test above and go back
    to abandoning work the moment anybody tuned the grace period down."""
    manifests = render(load_example("standard-production"),
                       extra=["--set", "workerTerminationGracePeriodSeconds=120"])
    worker = named(manifests, "Deployment", "-worker-assess")
    pod = worker["spec"]["template"]["spec"]
    env = {e["name"]: e.get("value") for e in pod["containers"][0]["env"]}
    assert pod["terminationGracePeriodSeconds"] == 120
    assert int(env["ACP_SHUTDOWN_DRAIN_SECONDS"]) == 60


@needs_helm
def test_a_grace_period_shorter_than_the_headroom_still_drains_for_something():
    """The floor. Without it the arithmetic goes negative, and `float()` in api/core.py accepts a
    negative deadline happily — a worker that stops the instant it is asked to, arrived at by
    arithmetic nobody reads."""
    manifests = render(load_example("standard-production"),
                       extra=["--set", "workerTerminationGracePeriodSeconds=30"])
    worker = named(manifests, "Deployment", "-worker-assess")
    env = {e["name"]: e.get("value")
           for e in worker["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert int(env["ACP_SHUTDOWN_DRAIN_SECONDS"]) == 10


@needs_helm
def test_the_api_tier_gets_no_drain_window_because_it_drains_nothing():
    """The API runs at ACP_WORKERS=0 and has no in-process pool, so a drain window there would be
    a number describing nothing."""
    api = named(render(load_example("standard-production")), "Deployment", "-api")
    names = {e["name"] for e in api["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert "ACP_SHUTDOWN_DRAIN_SECONDS" not in names


@needs_helm
def test_the_access_gate_variable_actually_reaches_the_api():
    """The end of the chain for `network.unauthenticated-ingress`, asserted on the render.

    The rule makes a document declare an authentication reference; this establishes that declaring
    it WIRES something — the chart's `secrets.refs` projection turns the key into
    ACP_GOOGLE_CLIENT_ID, which is the variable `api/app.py` reads to arm the gate. A rule that
    demanded a reference the chart then dropped would be a contract that felt safer and changed
    nothing.
    """
    api = named(render(load_example("standard-production")), "Deployment", "-api")
    env = api["spec"]["template"]["spec"]["containers"][0]["env"]
    by_name = {e["name"]: e for e in env}
    assert "ACP_GOOGLE_CLIENT_ID" in by_name, sorted(by_name)
    assert "secretKeyRef" in by_name["ACP_GOOGLE_CLIENT_ID"]["valueFrom"]


@needs_helm
def test_asking_for_a_gpu_renders_a_gpu_request():
    """`ai.ollama.gpu: true` RENDERED NOTHING AT ALL until 2026-09-08.

    The flag gated a pod-level block containing only `nodeSelector` and `tolerations`, both
    `with`-guarded on values nothing sets — while the comment beside it described an
    `nvidia.com/gpu` limit that was not written anywhere and could not have been at that level: an
    extended resource is a CONTAINER resource. The standard-production example asks for a GPU,
    `grep nvidia` over the render returned nothing, and the pod scheduled onto whatever node had
    room and ran CPU inference. The document said GPU, the cluster did CPU, and nothing disagreed.

    Only the limit is asserted. Kubernetes fills an extended resource's request in from its limit
    and rejects the pod if the two are written and differ.
    """
    doc = load_example("standard-production")
    assert doc["ai"]["ollama"]["gpu"] is True, "this test would prove nothing"
    ollama = named(render(doc), "Deployment", "-ollama")
    resources = ollama["spec"]["template"]["spec"]["containers"][0]["resources"]
    assert resources["limits"]["nvidia.com/gpu"] == 1
    assert "requests" not in resources or "nvidia.com/gpu" not in resources["requests"]


@needs_helm
def test_no_gpu_asked_for_means_no_gpu_requested():
    """The control. A chart that requested a GPU unconditionally would satisfy the assertion above
    and make every CPU-only installation unschedulable."""
    doc = load_example("standard-production")
    doc["ai"]["ollama"]["gpu"] = False
    ollama = named(render(doc), "Deployment", "-ollama")
    resources = ollama["spec"]["template"]["spec"]["containers"][0].get("resources", {})
    assert "nvidia.com/gpu" not in json.dumps(resources)


@needs_helm
def test_the_gpu_count_is_a_values_knob():
    manifests = render(load_example("standard-production"),
                       extra=["--set", "ai.ollama.gpuCount=4"])
    ollama = named(manifests, "Deployment", "-ollama")
    limits = ollama["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"]
    assert limits["nvidia.com/gpu"] == 4


@needs_helm
def test_a_numeric_annotation_is_rendered_as_a_string():
    """FOUND BY THE UPGRADE STEP ON ITS FIRST RUN, and by nothing else that exists.

    `toYaml` preserves YAML's types. Annotations and `nodeSelector` are `map[string]string` in the
    Kubernetes API, so a value that parses as a number or a boolean is rejected — not by the
    template, not by `helm template`, not by `helm lint`, but by the API SERVER:

        cannot patch "acp-api" with kind Deployment: "" is invalid: patch: Invalid value: "{…}":
        json: cannot unmarshal number into Go struct field
        ObjectMeta.spec.template.metadata.annotations of type string

    Nothing about it is upgrade-specific; an install carrying the same value fails identically.
    The reason it surfaced on an upgrade is that the CI step sets a probe annotation to
    `$GITHUB_RUN_ID`, which is all digits.

    `--set-string` is not the fix. The operator most likely to hit this is writing a values FILE,
    where `build-number: 1234` is an int before helm sees it and there is no per-key string flag.
    So the chart quotes, and the CI step deliberately keeps using plain `--set` so it goes on
    exercising the numeric path.
    """
    manifests = render(load_example("standard-production"), extra=[
        "--set", "podAnnotations.build-number=1234",
        "--set", "podAnnotations.rollout-forced=true",
        "--set", "nodeSelector.pool-index=3",
    ])
    checked = 0
    for workload in manifests:
        if workload["kind"] != "Deployment":
            continue
        template = workload["spec"]["template"]
        name = workload["metadata"]["name"]
        for field, block in (("annotations", template["metadata"].get("annotations") or {}),
                             ("nodeSelector", template["spec"].get("nodeSelector") or {})):
            for key, value in block.items():
                assert isinstance(value, str), f"{name}.{field}.{key} is {type(value).__name__}"
                checked += 1
    assert checked, "nothing carried an annotation or selector; this test would prove nothing"


@needs_helm
def test_no_selector_label_changes_between_two_releases():
    """`spec.selector` IS IMMUTABLE ON A DEPLOYMENT, and this is the one immutability the chart
    can break silently.

    A selector label that varies with anything — the release version, the image tag, a values
    checksum — installs perfectly, passes every render test, and makes the FIRST UPGRADE fail:

        cannot patch "acp-api": Deployment.apps "acp-api" is invalid: spec.selector: Invalid
        value: field is immutable

    An operator reads that on a running installation, with no way forward but deleting the
    Deployment. `acp.labels` legitimately carries `app.kubernetes.io/version` and
    `helm.sh/chart`, both of which move with a release — so the risk is one line: a template
    selecting on `acp.labels` instead of `acp.selectorLabels`, which reads almost identically.

    Rendered twice at different versions rather than inspected, because the property is
    "unchanged across releases" and a single render cannot express it. The reference cluster now
    performs a real `helm upgrade`, which is where this would otherwise be found.
    """
    doc = load_example("standard-production")
    older = copy.deepcopy(doc)
    older["runtime"]["version"] = "2026.1.1"
    newer = copy.deepcopy(doc)
    newer["runtime"]["version"] = "2029.12.31"

    def selectors(document):
        out = {}
        for workload in render(document):
            if workload["kind"] in ("Deployment", "StatefulSet"):
                out[workload["metadata"]["name"]] = workload["spec"]["selector"]["matchLabels"]
        return out

    before, after = selectors(older), selectors(newer)
    assert before, "nothing rendered; this test would prove nothing"
    assert before == after, (
        "a selector label moves with the release, so the first upgrade of this chart will be "
        f"refused as an immutable-field change: {before} vs {after}")


@needs_helm
def test_every_spread_constraint_selects_the_pods_it_is_attached_to():
    """A TOPOLOGY CONSTRAINT WHOSE SELECTOR MATCHES NOTHING IS NOT AN ERROR.

    It is satisfied vacuously: the manifest renders, `kubectl get` shows the constraint, and the
    scheduler spreads nothing. The first draft of this helper built its selector from
    `app.kubernetes.io/component`, which is `worker` on all THREE worker Deployments — so every
    worker constraint would have selected the union of the tiers, and one built per role would
    have selected none. Neither shows up as a failure anywhere.

    So the assertion is the one that matters: each constraint's `matchLabels` must be a subset of
    the labels its own pod template carries, and must include whatever distinguishes that
    Deployment from its siblings. Anything else is a constraint about somebody else's pods.
    """
    for profile in RENDERABLE:
        for workload in render(load_example(profile)):
            if workload["kind"] != "Deployment":
                continue
            spec = workload["spec"]["template"]["spec"]
            name = workload["metadata"]["name"]
            for constraint in spec.get("topologySpreadConstraints", []):
                selector = constraint["labelSelector"]["matchLabels"]
                pod_labels = workload["spec"]["template"]["metadata"]["labels"]
                assert selector.items() <= pod_labels.items(), (
                    f"{name} ({profile}): the constraint selects pods this Deployment does not "
                    f"produce: {selector} vs {pod_labels}")
                # The label that tells the three worker Deployments apart. Without it a worker
                # constraint balances the union of all three tiers, which is not what any of them
                # asked for and is invisible in the render.
                if "worker" in name:
                    assert "acp.mova.io/worker-role" in selector, (
                        f"{name}: without the role label this constraint covers every worker tier")


@needs_helm
def test_multi_replica_tiers_are_spread_across_zones_and_single_ones_are_not():
    """WHAT THE EXISTING ANTI-AFFINITY DID NOT DO. It is `preferredDuringScheduling` across
    `kubernetes.io/hostname`: it asks for different NODES and says nothing about zones, so three
    API replicas can land on three nodes in one availability zone and satisfy it completely. Losing
    a zone is the failure a multi-replica tier is bought to survive.

    Rendered only where there is something to spread. A constraint on a one-pod tier is arithmetic
    on a single pod, and rendering it everywhere would put a scheduling rule on Ollama and Grafana
    that can never do anything.
    """
    manifests = render(load_example("high-availability"))
    api = named(manifests, "Deployment", "-api")["spec"]["template"]["spec"]
    constraint = api["topologySpreadConstraints"][0]
    assert constraint["topologyKey"] == "topology.kubernetes.io/zone"
    assert constraint["maxSkew"] == 1
    for suffix in ("-ollama", "-grafana"):
        single = named(manifests, "Deployment", suffix)
        assert single["spec"]["replicas"] == 1, "this test would prove nothing"
        assert "topologySpreadConstraints" not in single["spec"]["template"]["spec"], suffix


@needs_helm
def test_the_spread_falls_back_rather_than_stranding_a_pod():
    """`DoNotSchedule` IS A CLAIM ABOUT THE CLUSTER, AND ITS FAILURE MODE IS AN OUTAGE.

    Nodes without the topologyKey LABEL are not eligible under `DoNotSchedule`, so on a cluster
    whose nodes carry no `topology.kubernetes.io/zone` — every kind and k3d cluster, and any
    single-zone install, the reference cluster this chart is actually installed on included —
    there is no eligible node and every replica stays Pending forever. And without `matchLabelKeys`
    (1.27+, against `doctor.MINIMUM_KUBERNETES` of 1.23) the constraint counts the outgoing
    ReplicaSet during a rolling update, so an update can wedge against its own predecessors.

    PRD S4 is explicit that a target is not supported because Helm renders for it. The chart
    therefore ships the soft value on every profile, `high-availability` included, and leaves
    hardening to an operator who knows their nodes are labelled — which this asserts is one value.
    """
    for profile in RENDERABLE:
        api = named(render(load_example(profile)), "Deployment", "-api")["spec"]["template"]["spec"]
        assert api["topologySpreadConstraints"][0]["whenUnsatisfiable"] == "ScheduleAnyway", profile
    hardened = render(load_example("high-availability"),
                      extra=["--set", "topologySpread.whenUnsatisfiable=DoNotSchedule"])
    api = named(hardened, "Deployment", "-api")["spec"]["template"]["spec"]
    assert api["topologySpreadConstraints"][0]["whenUnsatisfiable"] == "DoNotSchedule"


@needs_helm
def test_ollamas_root_stays_writable_whatever_the_shared_value_says():
    """A COMMENT THAT DESCRIBED A SETTING NOBODY HAD SET.

    `templates/ollama.yaml` said the shared securityContext "sets it true, which is right for the
    API and the workers" — and `values.yaml` has `readOnlyRootFilesystem: false`, so it had never
    been true for anything. The override was a guard reading as an exception in force, and a
    reader deciding whether the chart hardens its root filesystems would have concluded it does.

    So this asserts the guard rather than the comment: turn the shared value on and ollama alone
    must stay writable, because it writes its runtime state under the model root while serving.
    That is a property of `merge`'s precedence, which is what the override actually relies on, and
    it holds no matter what the default becomes.
    """
    manifests = render(load_example("standard-production"),
                       extra=["--set", "securityContext.readOnlyRootFilesystem=true"])
    ollama = named(manifests, "Deployment", "-ollama")["spec"]["template"]["spec"]
    assert ollama["containers"][0]["securityContext"]["readOnlyRootFilesystem"] is False
    for suffix in ("-api", "-worker-remediate"):
        other = named(manifests, "Deployment", suffix)["spec"]["template"]["spec"]
        assert other["containers"][0]["securityContext"]["readOnlyRootFilesystem"] is True, suffix


@needs_helm
def test_the_root_filesystem_is_read_only_and_the_writes_have_somewhere_to_go():
    """THIS TEST HAS NOW BEEN WRONG-FOOTED TWICE, WHICH IS WHAT IT IS FOR.

    It began asserting that `readOnlyRootFilesystem` was false and that `PUT /rubric` still wrote
    into the image, because that write was the reason. The rubric moved to the database and it
    failed, as its docstring said it would. It was then re-pointed at the packaging work that
    remained — a writable /tmp, which the chart did not render — and it failed again when that
    landed. Both times the failure said where to look, which is the whole job.

    It now asserts the flag is ON and, more usefully, that the three things the flag DEPENDS ON
    are all present. Turning it on without them fails silently: `render_page_png` and
    `_office_to_pdf` return None on any exception and `_analyse_office` turns OSError into an
    engine-error bucket that scores as `uncertain`, so Office documents would degrade with no
    startup signal at all. There is no loud failure to catch this in production.
    """
    values = yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8"))
    assert values["securityContext"]["readOnlyRootFilesystem"] is True
    scratch = values["scratch"]["mountPath"]

    manifests = render(load_example("standard-production"))
    checked = 0
    for workload in manifests:
        if workload["kind"] not in ("Deployment", "Job"):
            continue
        spec = workload["spec"]["template"]["spec"]
        name = workload["metadata"]["name"]
        container = spec["containers"][0]
        if container["securityContext"].get("readOnlyRootFilesystem") is not True:
            continue  # Ollama and Grafana pin it false; their own tests cover that.
        checked += 1

        mounts = {m["mountPath"] for m in container.get("volumeMounts") or []}
        assert scratch in mounts, f"{name} has a read-only root and nowhere to write"
        mounted = {m["name"] for m in container["volumeMounts"] if m["mountPath"] == scratch}
        declared = {v["name"] for v in spec.get("volumes") or []}
        assert mounted <= declared, f"{name} mounts a volume the pod does not declare"

        # The caches that do NOT live under $TMPDIR, each redirected onto the scratch volume.
        # Without these the writes fail in libraries — fontconfig, the .NET CLI — rather than in
        # this application, which is why they are asserted rather than left to review.
        env = {e["name"]: e.get("value") for e in container.get("env") or []}
        for key in ("HOME", "XDG_CACHE_HOME", "DOTNET_CLI_HOME"):
            assert key in env, f"{name} is missing {key}; that cache write has nowhere to go"
            assert env[key].startswith(scratch), (
                f"{name} points {key} at {env[key]}, which is not on the writable volume")
        assert env.get("PYTHONDONTWRITEBYTECODE") == "1", (
            f"{name} will attempt a __pycache__ write per module against a read-only /app")

    assert checked >= 5, f"only {checked} workloads checked; expected the API, three workers and "\
                         f"the hook Jobs"


@needs_helm
def test_the_scratch_volume_does_not_shrink_the_storage_the_preset_promises():
    """An emptyDir counts against the pod's `ephemeral-storage` LIMIT, which this chart already
    sets per tier from the preset — 8Gi for remediate. A `sizeLimit` here would be a second bound
    on one budget, and the tighter one would win by accident, silently capping a worker below the
    storage its own preset promises.

    Memory-backing would be worse still: charged to the pod's MEMORY limit, so one large document
    OOM-kills the worker instead of filling a disk it was given.
    """
    for workload in render(load_example("standard-production")):
        if workload["kind"] not in ("Deployment", "Job"):
            continue
        for volume in workload["spec"]["template"]["spec"].get("volumes") or []:
            empty = volume.get("emptyDir")
            if empty is None:
                continue
            assert not empty.get("sizeLimit"), (
                f"{workload['metadata']['name']}: a sizeLimit here is a second bound on the "
                f"ephemeral-storage budget the preset already sets")
            assert empty.get("medium") != "Memory", (
                f"{workload['metadata']['name']}: memory-backed scratch is charged to the memory "
                f"limit, so a large document OOM-kills the pod")


@needs_helm
def test_the_remediated_output_store_reaches_every_workload_that_writes_to_it():
    """THE SEAM THAT DID NOT MEET UNTIL 2026-09-08, asserted on the render.

    `api/blob.py` is the primary store for a remediated file's fixed copy (ADR 0010) and reads one
    variable to decide whether it exists: ACP_BLOB_ACCOUNT. This chart set none, while
    `deploy/public/deploy.sh` has always set it on both the API and the worker apps — so the
    Container Apps deployment persisted output and every Helm install silently did not, remediating
    documents and dropping them.

    Asserted on the WORKERS as well as the API, because the remediate tier is what writes: an
    env var that reached only the API would look wired and lose every corrected file.
    """
    doc = load_example("standard-production")
    doc["data"]["objectStorage"]["account"] = "acpremediatedstore"
    workloads = app_workloads(render(doc))
    assert workloads, "nothing rendered; this test would prove nothing"
    for workload in workloads:
        env = {e["name"]: e.get("value")
               for e in workload["spec"]["template"]["spec"]["containers"][0]["env"]}
        assert env.get("ACP_BLOB_ACCOUNT") == "acpremediatedstore", workload["metadata"]["name"]


@needs_helm
def test_no_account_renders_no_variable_rather_than_an_empty_one():
    """An empty ACP_BLOB_ACCOUNT and an absent one behave the same in `api/blob.py` — `_ENABLED`
    is `bool(_ACCOUNT)` either way — but they do not READ the same. An operator seeing the
    variable set to "" on a running Deployment has been told the store is configured."""
    doc = load_example("standard-production")
    assert "account" not in doc["data"]["objectStorage"]
    for workload in app_workloads(render(doc)):
        names = {e["name"] for e in workload["spec"]["template"]["spec"]["containers"][0]["env"]}
        assert "ACP_BLOB_ACCOUNT" not in names, workload["metadata"]["name"]


@needs_helm
def test_no_pre_install_hook_needs_a_resource_the_release_creates_after_it():
    """THE ORDERING RENDERING CANNOT SEE, AND THE ONE THAT MADE THIS CHART UNINSTALLABLE.

    Helm runs `pre-install` hooks BEFORE it creates the release's own resources. Until 2026-09-08
    both hook Jobs named the chart's ServiceAccount, which is one of those resources — so the
    admission plugin rejected the Job's pod, the Job controller created none, and Helm timed out
    after ten minutes on a Job at 0/1 with no pod at all:

        Error: INSTALLATION FAILED: failed pre-install: 1 error occurred:
                * timed out waiting for the condition

    Every `helm install` of this chart failed that way, and `helm template` was clean throughout,
    because a rendered manifest has no ordering. The first run of the reference cluster is what
    surfaced it.

    Written as a general rule rather than an assertion about those two Jobs: any future
    pre-install hook that references a chart-created ServiceAccount fails here instead of after
    fifteen minutes of image build.
    """
    manifests = render(load_example("standard-production"))
    created_later = {d["metadata"]["name"] for d in manifests
                     if d["kind"] == "ServiceAccount"
                     and "helm.sh/hook" not in (d["metadata"].get("annotations") or {})}
    assert created_later, "the chart creates no ServiceAccount; this test would prove nothing"
    checked = 0
    for d in manifests:
        annotations = d["metadata"].get("annotations") or {}
        phases = set(annotations.get("helm.sh/hook", "").split(","))
        if not phases & {"pre-install", "pre-upgrade"}:
            continue
        checked += 1
        pod = d["spec"]["template"]["spec"]
        name = pod.get("serviceAccountName")
        assert name not in created_later, (
            f"{d['metadata']['name']} is a pre-install hook naming ServiceAccount {name!r}, "
            f"which Helm does not create until after the hooks have run")
    assert checked, "no pre-install hook was rendered; this test would prove nothing"


@needs_helm
def test_the_hook_jobs_drop_the_service_account_token_they_do_not_use():
    """The companion to the rule above: running as `default` is only safe because neither hook
    touches the Kubernetes API. Asserted rather than assumed, so a hook that grows an API call
    has to say so."""
    for name in ("-migrate", "-preflight"):
        job = named(render(load_example("standard-production")), "Job", name)
        assert job["spec"]["template"]["spec"]["automountServiceAccountToken"] is False, name


@needs_helm
def test_default_deny_always_lets_the_pods_reach_their_own_data_services():
    """DEFAULT-DENY WITH NO EGRESS RULE DENIES DNS.

    Adding `Egress` to a policyType with no egress rule denies every outbound packet from every
    ACP pod. Until 2026-09-08 the companion policy that lets anything back out rendered only when
    `allowedEgress` was non-empty, and even then opened 53 and 443 only — so on a cluster that
    ENFORCES policy, a document with no external sources resolved nothing at all, and one with
    external sources still could not reach Postgres on 5432 or Redis on 6379. The installation
    cannot start either way.

    Nothing caught it because no cluster anybody tested on enforces NetworkPolicy — and
    `acpctl doctor` treats a CNI that does not enforce as a BLOCKER, so the chart required exactly
    the environment in which it could not run.

    Asserted for BOTH shapes of document, because the empty-`allowedEgress` case is the one that
    rendered nothing and the one a regulated installation is most likely to have.
    """
    for profile in RENDERABLE:
        doc = load_example(profile)
        for allowed in ([], ["googleapis.com"]):
            doc["network"]["allowedEgress"] = allowed
            manifests = render(doc)
            deny = named(manifests, "NetworkPolicy", "-default-deny")
            assert "Egress" in deny["spec"]["policyTypes"], "this test would prove nothing"
            policy = named(manifests, "NetworkPolicy", "-egress")
            ports = {(p["port"], p["protocol"])
                     for rule in policy["spec"]["egress"] for p in rule["ports"]}
            assert (53, "UDP") in ports, f"{profile}/{allowed}: no DNS, so nothing resolves"
            assert (5432, "TCP") in ports, f"{profile}/{allowed}: Postgres unreachable"
            assert (6379, "TCP") in ports or (6380, "TCP") in ports, (
                f"{profile}/{allowed}: Redis unreachable")


@needs_helm
def test_the_egress_ports_are_a_values_knob_and_not_a_hardcoded_list():
    """An installation whose Postgres listens somewhere else edits values rather than discovering
    at rollout that its database is unreachable.

    Read off the UNSCOPED rule only. The policy also carries a rule scoped to the API pods with
    `to`, which exists so ACP can reach its own API and is deliberately NOT operator-tunable: it
    is the chart's own wiring, not a statement about the network the cluster sits in. Collecting
    ports across both rules would make this test fail whenever that one changes, and would let
    the knob be broken as long as the scoped rule happened to carry the right number.
    """
    manifests = render(load_example("standard-production"),
                       extra=["--set", "networkPolicy.egressPorts[0].port=15432",
                              "--set", "networkPolicy.egressPorts[0].protocol=TCP"])
    policy = named(manifests, "NetworkPolicy", "-egress")
    unscoped = [rule for rule in policy["spec"]["egress"] if not rule.get("to")]
    assert len(unscoped) == 1, policy["spec"]["egress"]
    assert {p["port"] for p in unscoped[0]["ports"]} == {15432}
    scoped = [rule for rule in policy["spec"]["egress"] if rule.get("to")]
    assert {p["port"] for p in scoped[0]["ports"]} == {80, 8077}, (
        "the knob moved a port it does not own; the scoped rule is the chart's own wiring")


@needs_helm
def test_the_egress_policy_still_records_the_destinations_it_cannot_enforce():
    """NetworkPolicy matches on IP, never on hostname, so the allow-list survives as an annotation
    for a FQDN-aware policy engine to act on. Opening the ports must not have quietly dropped the
    statement of intent, which is the only record of what the ports are FOR."""
    doc = load_example("standard-production")
    policy = named(render(doc), "NetworkPolicy", "-egress")
    annotations = policy["metadata"]["annotations"]
    assert annotations["acp.mova.io/intended-egress"] == ",".join(doc["network"]["allowedEgress"])
    assert "FQDN-aware" in annotations["acp.mova.io/egress-enforcement"]


@needs_helm
def test_no_default_deny_renders_no_egress_policy():
    """The companion, so the assertions above cannot pass for an unrelated reason: a chart that
    rendered the egress policy unconditionally would satisfy them while saying nothing about
    default-deny."""
    manifests = render(load_example("standard-production"),
                       extra=["--set", "networkPolicy.defaultDeny=false"])
    assert not [d for d in manifests
                if d["kind"] == "NetworkPolicy" and d["metadata"]["name"].endswith("-egress")]


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
    workers = [d for d in app_workloads(manifests)
               if d["metadata"]["labels"]["app.kubernetes.io/component"] == "worker"]
    assert workers, "no worker Deployment was rendered; this test would prove nothing"
    for deployment in workers:
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        assert "readinessProbe" not in container, deployment["metadata"]["name"]
        assert "livenessProbe" not in container, deployment["metadata"]["name"]


@needs_helm
def test_the_api_gets_both_probes_and_they_are_not_the_same_endpoint():
    """Readiness sheds traffic, liveness restarts the process. Pointing both at one endpoint
    means a database outage restarts every pod, which moves the outage around instead of
    shedding it."""
    api = named(render(load_example("standard-production")), "Deployment", "-api")
    container = api["spec"]["template"]["spec"]["containers"][0]
    assert container["readinessProbe"]["httpGet"]["path"] == "/probe/readyz"
    assert container["livenessProbe"]["httpGet"]["path"] == "/healthz"


@needs_helm
def test_the_readiness_probe_points_at_a_route_that_can_actually_fail():
    """A READINESS PROBE THAT CANNOT RETURN NON-200 IS NOT A READINESS PROBE.

    This chart pointed readiness at `/readyz` until 2026-09-08, and nothing ever failed because
    nothing could: that handler takes no Response and never sets a status, so it answers 200 from
    a replica whose database reads have not started answering — the exact replica the gate exists
    to hold traffic away from. `api/routes/system.py` says so in its own words, in the block
    comment above `probe_readyz` calling it "the ONE route a platform probe may point at".

    So this asserts against the APPLICATION rather than against a string: whatever path the chart
    probes must be a route in system.py whose handler sets 503. A future chart edit back to
    /readyz fails here, and so does an application change that stops /probe/readyz being able to
    fail — which is the direction nothing else would catch.
    """
    api = named(render(load_example("standard-production")), "Deployment", "-api")
    path = api["spec"]["template"]["spec"]["containers"][0]["readinessProbe"]["httpGet"]["path"]
    source = (ROOT / "api" / "routes" / "system.py").read_text(encoding="utf-8")
    route = re.search(
        rf'@router\.get\("{re.escape(path)}"\)\s*\ndef (\w+)\(([^)]*)\):(.*?)(?=\n@router\.|\Z)',
        source, re.DOTALL)
    assert route, f"the chart probes {path}, which is not a GET route in api/routes/system.py"
    name, signature, body = route.group(1), route.group(2), route.group(3)
    assert "Response" in signature, (
        f"{name} takes no Response, so it cannot set a status code and the probe can never fail")
    assert "status_code = 503" in body, (
        f"{name} never sets 503, so an unready replica would still be sent traffic")


@needs_helm
def test_a_worker_container_runs_the_worker_and_not_the_api():
    """THE FAILURE THIS CATCHES IS COMPLETELY SILENT.

    The application image's CMD starts uvicorn (deploy/public/Dockerfile), and the API and every
    worker tier share that image — they differ by command and by ACP_WORKER_ROLE, which is the
    topology ADR 0048 is built on. A worker Deployment that inherits the image's CMD therefore
    runs the API SERVER: it starts, it binds, its pods report Ready, and it claims no jobs. The
    Deployment is healthy in every way Kubernetes can see. The only symptoms are a queue that
    never drains and a tier that never writes a heartbeat, and both read as ACP being slow.

    Until 2026-09-08 the chart rendered exactly that, with a comment beside it saying "workers do
    not listen".
    """
    manifests = render(load_example("standard-production"))
    workers = [d for d in app_workloads(manifests)
               if d["metadata"]["labels"]["app.kubernetes.io/component"] == "worker"]
    assert workers, "no worker Deployment was rendered; this test would prove nothing"
    for deployment in workers:
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        command = container.get("command")
        assert command, f"{deployment['metadata']['name']} inherits the image CMD, which is uvicorn"
        assert command == ["acp-worker"], command
        # The other direction, so the assertion above cannot pass on a command that still serves
        # HTTP: nothing in a worker's command may start the API.
        joined = " ".join(command)
        for forbidden in ("uvicorn", "app:app", "gunicorn"):
            assert forbidden not in joined, (
                f"{deployment['metadata']['name']} would serve HTTP, not claim jobs")


@needs_helm
def test_the_api_does_not_get_the_worker_command():
    """The companion. One image, two roles, and the command is the whole of the difference — so a
    chart that set it on both would have swapped the failure rather than fixed it."""
    api = named(render(load_example("standard-production")), "Deployment", "-api")
    assert "command" not in api["spec"]["template"]["spec"]["containers"][0]


@needs_helm
def test_a_role_may_override_the_worker_command():
    """A purpose-built worker image can have a different entrypoint. The override exists so that
    the fix above is not also a constraint on which images an operator may run."""
    manifests = render(load_example("standard-production"),
                       extra=["--set", "workers.assess.command={/bin/custom-worker}"])
    assess = named(manifests, "Deployment", "-worker-assess")
    discover = named(manifests, "Deployment", "-worker-discover")
    assert assess["spec"]["template"]["spec"]["containers"][0]["command"] == ["/bin/custom-worker"]
    assert discover["spec"]["template"]["spec"]["containers"][0]["command"] == ["acp-worker"]


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
    # CLOSED 2026-09-05, and the entry is kept as the record of which side moved. Three
    # deployment paths described this service: Compose ran it ungated, deploy/public/ created
    # `acp-ollama` in production, and all four example documents set `ai.ollama.enabled: true`.
    # The chart — the layer ADR 0048 makes primary for production — was the only one that shipped
    # nothing. So the chart moved. See templates/ollama.yaml for the trap that made the obvious
    # implementation wrong (the model volume the inventory asked for would have shadowed the
    # models baked into the image).
    "acp-ollama-gateway": "-ollama",
    # CLOSED 2026-09-05, the second of the pair and for the same reason: Compose builds and runs
    # grafana ungated, deploy/public/ creates `acp-grafana` in production, and every example
    # document sets `observability.grafana: true`. The chart rendered nothing. Its datasource
    # needed a DSN split into four fields, which the image's own entrypoint now does — see
    # templates/grafana.yaml for why that belongs in the image rather than in the contract.
    "acp-grafana": "-grafana",
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
    "acp-langfuse": (
        "Self-hosted LLM tracing, and the same shape as the OTel collector rather than the same "
        "shape as grafana — which is a distinction the first draft of these tests got wrong. No "
        "template reads `observability.langfuse.mode`; the chart projects the two key references "
        "and, since 2026-09-08, `observability.langfuse.host` — all three of the variables "
        "api/lf.py needs — so the application is fully configured to talk to a Langfuse the "
        "release does not deploy. Expected from outside, then, and the inventory calling it "
        "`in-cluster` is the half that looks wrong: production runs Langfuse as its own Azure "
        "Container App, and v1alpha1 has no mode that says 'self-hosted, but not by this "
        "release'. That gap is why the derived Azure document does not declare a langfuse block."),
}


# The Deployments that run ACP's own code. Ollama is a Deployment too, and from this file's
# point of view a different KIND of thing: it takes no `acp.commonEnv`, serves no ACP HTTP API,
# and is a dependency the release happens to deploy rather than a tier of the application. Several
# tests below were written when "every Deployment" and "every ACP workload" were the same set —
# they stopped being the same the moment the chart learned to render the model runtime, and each
# one now says which it means instead of inheriting the coincidence.
APP_COMPONENTS = ("api", "worker")


def app_workloads(manifests):
    return [d for d in of_kind(manifests, "Deployment")
            if (d["metadata"]["labels"].get("app.kubernetes.io/component") in APP_COMPONENTS)]


# The substring that identifies each unrendered service in a workload name or image reference.
# Kept as a map rather than a literal tuple at the call site because that tuple went stale the
# first time an entry moved out: ollama was still being searched for after the chart started
# rendering it, and the test failed with a message about a map that no longer mentioned it.
NOT_RENDERED_TOKENS = {
    "acp-langfuse": "langfuse",
}


def test_the_token_map_covers_exactly_the_unrendered_services():
    """Two structures describing one set is how the pair drifts. A service leaving NOT_RENDERED
    without leaving this map means the absence test goes on searching for something that is now
    supposed to be there; joining without joining this map means it is never searched for at
    all — and that direction is silent."""
    assert set(NOT_RENDERED_TOKENS) == set(NOT_RENDERED), (
        f"token map {sorted(NOT_RENDERED_TOKENS)} vs NOT_RENDERED {sorted(NOT_RENDERED)}")


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
    for token in sorted(NOT_RENDERED_TOKENS.values()):
        assert not [i for i in identities if token in i], (
            f"the chart now renders a workload for {token} — NOT_RENDERED is stale, which is "
            f"better news than it sounds and still has to be recorded")


@needs_helm
def test_the_derived_production_document_plans_nothing_it_would_not_install():
    """THE HEADLINE, CLOSED — on the document that describes production rather than on an example.

    It began at three. `azure-current.acp-deployment.yaml` declares `ai.ollama.enabled: true`,
    `observability.grafana: true` and `openTelemetry: true` because deploy/public/ configures all
    three; `acpctl plan` listed a model runtime, a dashboard server and an OTLP collector, and
    `helm install` created none of them. Adopting the chart as the Azure rebuild would have
    silently dropped the local model runtime ADR 0010's remediation lane depends on.

    Each closed differently, and the difference is the whole finding of this comparison:

      ollama, grafana   THE CHART was wrong. Both are real workloads that Compose and production
                        deploy, and it rendered neither. Templates were the fix.
      otel collector    THE INVENTORY was wrong, and about the mechanism rather than the count.
                        ACP has no OTLP anywhere: api/telemetry.py configures the Azure Monitor
                        distribution and needs a connection string, not a collector on 4317. The
                        fix was to stop planning a workload for a credential — and to require the
                        credential, which nothing had.

    So "the chart renders less than the plan promises" turned out to be two different faults
    wearing one number. The empty set is the assertion now; anything appearing in it is a new
    fault of one of those two kinds.
    """
    from acpctl.spec import load_document
    doc = load_document(PACKAGING / "docs" / "azure-current.acp-deployment.yaml")
    doc["api"]["replicas"]["min"] = 2
    doc["data"]["postgres"]["backupRetentionDays"] = 35

    planned = _in_cluster(doc)
    assert planned, "the derivation planned no in-cluster services at all; this proves nothing"
    assert planned & set(NOT_RENDERED) == set(), sorted(planned & set(NOT_RENDERED))


# ── values knobs the chart declares and no template reads ────────────────────────────────────

# A knob that exists and is silently ignored is worse than an absent one: `acpctl values` renders
# it faithfully, `helm install` accepts it without complaint, and an operator reading either sees
# a configured feature. Listed with what is known, same as NOT_RENDERED.
INERT_VALUES = {
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
def test_the_workloads_get_the_telemetry_credential_the_application_reads():
    """THE SEAM THAT DID NOT MEET, now closed — and it was two seams, not one.

    The first was mechanical: `acpctl values` emits
    `observability.openTelemetry.{enabled, exporter}` and `_helpers.tpl` read `{enabled,
    endpoint}`, so the endpoint was never written and workloads came up with
    OTEL_SDK_DISABLED=false and no destination. Instrumentation switched on, pointing nowhere.

    The second is why fixing the first would have been wrong. OTLP was never the mechanism.
    `api/telemetry.py` configures the AZURE MONITOR OpenTelemetry distribution and starts nothing
    without APPLICATIONINSIGHTS_CONNECTION_STRING — `configure()` returns
    `{"enabled": false, "reason": "not configured"}`, and no SDK, exporter or egress is created.
    So OTEL_SDK_DISABLED=false described an SDK that was never constructed, and an OTLP endpoint
    would have pointed at a protocol nothing in this product speaks.

    What closes it is a CREDENTIAL, and the wiring is the secret reference itself: `acp.commonEnv`
    projects every entry of `secrets.refs` as its own uppercase variable, so declaring
    `applicationinsights-connection-string` and `acp-telemetry-salt` produces exactly the two
    names telemetry.py reads, with no special case in any template.
    """
    from acpctl.values import build_values

    doc = load_example("standard-production")
    values = build_values(doc)
    otel = values["observability"]["openTelemetry"]
    assert otel["enabled"] is True and otel.get("exporter") == "azure-monitor"

    for manifest in app_workloads(render(doc)):
        if manifest.get("kind") != "Deployment":
            continue
        name = manifest["metadata"]["name"]
        env = {e["name"]: e for e in manifest["spec"]["template"]["spec"]["containers"][0]["env"]}

        ref = env.get("APPLICATIONINSIGHTS_CONNECTION_STRING", {}).get("valueFrom", {})
        assert ref.get("secretKeyRef", {}).get("key") == "applicationinsights-connection-string", (
            f"{name} cannot start telemetry: api/telemetry.py reads this variable and nothing "
            f"else, and it is not projected")
        assert "value" not in env["APPLICATIONINSIGHTS_CONNECTION_STRING"], (
            f"{name} carries the connection string as a literal rather than a reference")

        assert env.get("OTEL_SERVICE_NAME", {}).get("value"), (
            f"{name} would appear in Application Insights unnamed")

        # THE ONES THAT SHOULD BE GONE. Both described a mechanism this product does not use, and
        # OTEL_SDK_DISABLED was the actively misleading one: it read as "instrumentation is on".
        for dead in ("OTEL_SDK_DISABLED", "OTEL_EXPORTER_OTLP_ENDPOINT"):
            assert dead not in env, (
                f"{name} sets {dead} again — ACP exports through the Azure Monitor distribution, "
                f"not OTLP, so this describes a pipeline that does not exist")


@needs_helm
def test_no_duplicate_environment_variables_reach_any_container():
    """A GUARD ON THE SHAPE OF THE FIX, and it caught a real one.

    The first draft set APPLICATIONINSIGHTS_CONNECTION_STRING explicitly in `acp.commonEnv` while
    the secret-ref loop in the same helper ALSO emitted it — two entries of the same name in one
    container, which Kubernetes resolves by taking the last and a reader resolves by guessing. The
    salt was worse: mapped by hand as `telemetry-salt`, it arrived as both ACP_TELEMETRY_SALT and
    a junk TELEMETRY_SALT that nothing reads.

    Nothing about that fails to render, which is why it is asserted across every container rather
    than for the two variables that happened to collide.
    """
    for name in RENDERABLE:
        for manifest in render(load_example(name)):
            if manifest.get("kind") not in ("Deployment", "StatefulSet", "Job", "CronJob"):
                continue
            spec = manifest["spec"].get("template", manifest["spec"])["spec"]
            for container in spec.get("containers", []) + spec.get("initContainers", []):
                names = [e["name"] for e in container.get("env") or []]
                dupes = sorted({n for n in names if names.count(n) > 1})
                assert not dupes, (
                    f"{name}/{manifest['metadata']['name']}/{container['name']} sets {dupes} "
                    f"more than once")


def _grafana(manifests):
    return next(d for d in of_kind(manifests, "Deployment")
                if d["metadata"]["name"].endswith("-grafana"))


@needs_helm
def test_grafana_is_not_exposed_by_default():
    """The image ships with ANONYMOUS ACCESS ON — GF_AUTH_ANONYMOUS_ENABLED=true, baked into
    deploy/grafana/Dockerfile so the embedded dashboards work without a second login. That is a
    reasonable default for something reachable only inside the cluster and a bad one for anything
    else: a Service that published itself would put every ACP dashboard in front of whoever found
    the address, with no credential to stop them.

    Production does expose its Grafana, through Container Apps external ingress — a deliberate
    per-installation act. The equivalent here is an Ingress rule the operator writes, not a
    default this chart picks.
    """
    manifests = render(load_example("standard-production"))
    svc = next(s for s in of_kind(manifests, "Service")
               if s["metadata"]["name"].endswith("-grafana"))
    assert svc["spec"]["type"] == "ClusterIP", svc["spec"]["type"]


@needs_helm
def test_grafana_gets_the_dsn_its_entrypoint_splits():
    """The seam, from the chart's side. deploy/grafana/acp-entrypoint.sh derives the four
    ACP_GRAFANA_PG_* variables Grafana's provisioning needs — but only if it is handed a DSN, and
    only from the secret rather than a literal. Rendering the Deployment without this would give
    a Grafana that starts, provisions a datasource with four unsubstituted `${VAR}` fields, and
    reports the problem as empty dashboards.
    """
    env = {e["name"]: e for e in _grafana(render(load_example("standard-production")))
           ["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert "DATABASE_URL" in env, sorted(env)
    ref = env["DATABASE_URL"].get("valueFrom", {}).get("secretKeyRef", {})
    assert ref.get("key") == "database-url", env["DATABASE_URL"]
    assert "value" not in env["DATABASE_URL"], "the DSN is rendered as a literal, not a reference"


@needs_helm
def test_grafana_runs_as_the_uid_its_image_owns():
    """472, not the chart's 10001. Read from the registry config of grafana/grafana:11.6.0 rather
    than assumed. Under the shared podSecurityContext Grafana cannot write its own data directory,
    and the symptom is a container that starts, logs a permissions error once, and serves an empty
    UI — which reads as a configuration problem with the datasource.
    """
    pod = _grafana(render(load_example("standard-production")))["spec"]["template"]["spec"]
    assert pod["securityContext"]["runAsUser"] == 472, pod["securityContext"]
    assert pod["securityContext"]["fsGroup"] == 472, pod["securityContext"]
    assert pod["securityContext"]["runAsNonRoot"] is True


@needs_helm
def test_neither_dependency_workload_renders_when_the_document_turns_it_off():
    """THE OTHER DIRECTION, and the one that makes these templates a contract rather than a
    preference. `observability.grafana: false` and `ai.ollama.enabled: false` are things a
    document is allowed to say, and a chart that rendered them anyway would be deciding for the
    operator — the same fault as not rendering them when asked, pointing the other way.
    """
    doc = load_example("standard-production")
    doc["observability"]["grafana"] = False
    doc["ai"]["ollama"]["enabled"] = False
    names = {m["metadata"]["name"] for m in render(doc)}
    assert not [n for n in names if n.endswith("-grafana") or n.endswith("-ollama")], sorted(names)


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

    # OLLAMA HAS BEEN CLOSED, on the chart's side, and this is where that is recorded. The other
    # two are still open and are not the same shape as each other:
    #
    #   langfuse  Compose runs it for EVALUATION and production runs none at all — the parity
    #             baseline has no acp-langfuse — so this one is not "the chart is behind", it is
    #             the contract claiming an in-cluster service no production deployment has ever
    #             had. Which side moves there is a decision, not a gap to fill.
    for closed in ("acp-ollama-gateway", "acp-grafana"):
        assert closed not in NOT_RENDERED, (
            f"{closed} is back in NOT_RENDERED — the chart stopped rendering something both "
            f"Compose and production deploy")
    assert {"acp-langfuse"} <= set(NOT_RENDERED), sorted(NOT_RENDERED)
