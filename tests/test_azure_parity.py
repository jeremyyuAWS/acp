"""The Azure parity baseline — derived, and guarded against the ways a derivation goes quiet.

A parity report has two failure modes and only one of them is loud. The loud one is a wrong
comparison. The quiet one is a comparison that stopped happening: a regex that no longer matches
after somebody reformats `deploy/public/`, yielding an empty baseline, no differences, and a
document that reads **"None. Every field matches"** — the most reassuring possible way to say
nothing was checked.

So the first tests here assert the parse FOUND things, and the rest pin the specific findings, so
that a change on either side of the comparison has to be acknowledged rather than absorbed.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from packaging_helpers import PACKAGING  # noqa: F401  (puts acpctl on sys.path)

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "deploy" / "public"

# The tiers the contract models and Azure serves. Written out so that a tier vanishing from either
# side is a failure rather than a silently shorter report.
TIERS = ("api", "discover", "assess", "remediate")


@pytest.fixture(scope="module")
def report():
    from acpctl.azure_parity import compare
    return compare()


# ── the parse is not vacuous ──────────────────────────────────────────────────

def test_the_deployment_scripts_are_where_this_expects_them():
    """If `deploy/public/` moves, every test below would pass against nothing."""
    assert (DEPLOY / "rightsize-production.sh").is_file()
    assert (DEPLOY / "deploy.sh").is_file()


def test_the_baseline_found_every_workload_tier():
    """THE ANTI-VACUOUS GUARD.

    An empty parse produces an empty baseline, zero differences, and a report claiming parity.
    That is the failure this file is shaped around, so the apps are named: a script rewrite that
    breaks the regex fails here, with the app it can no longer see.
    """
    from acpctl.azure_baseline import baseline
    apps = baseline()
    for name in ("acp-app", "acp-discovery", "acp-assess", "acp-remediate"):
        assert name in apps, f"the parse no longer finds {name} in deploy/public/"
        assert apps[name].cpu is not None, f"{name} parsed with no CPU"
        assert apps[name].min_replicas is not None, f"{name} parsed with no replica range"


def test_the_baseline_reads_sizing_from_the_reviewed_capacity_script():
    """rightsize-production.sh is the authority, not deploy.sh's create flags.

    The API app is CREATED with `--max-replicas 1` and right-sized afterwards to 1–3. Reading the
    creation flags would report a production topology that has not existed since that script was
    first run — and it would look perfectly plausible.
    """
    from acpctl.azure_baseline import baseline, parse_deploy
    created = parse_deploy()
    assert created["acp-app"].max_replicas == 1, "deploy.sh's create flag changed; re-read this"
    assert baseline()["acp-app"].max_replicas == 3, "the baseline is reading the wrong file"


def test_every_deployed_app_is_either_a_tier_or_explicitly_out_of_scope():
    """An app nobody classified is the gap a parity report exists to surface — so it cannot be
    dropped silently. Adding a container app to the deployment fails this until somebody decides
    whether the contract should model it."""
    from acpctl.azure_baseline import APP_TO_TIER, OUT_OF_SCOPE, baseline
    unclassified = [n for n in baseline() if n not in APP_TO_TIER and n not in OUT_OF_SCOPE]
    assert not unclassified, (
        f"deploy/public/ creates {unclassified}, which is neither mapped to a contract tier nor "
        "recorded as out of scope. Decide which, in azure_baseline.py.")


def test_the_grafana_app_is_in_the_baseline():
    """A regression test for a real miss. The first parser matched only
    `APP="${ACP_APP:-acp-app}"` and not `GF_APP="acp-grafana"`, so an app the deployment creates
    was absent from the report — and absence in a differences report reads as agreement."""
    from acpctl.azure_baseline import baseline
    assert "acp-grafana" in baseline()


# ── the comparison itself ─────────────────────────────────────────────────────

def test_cpu_and_memory_match_on_every_tier(report):
    """The example's header claims its sizes mirror the reviewed Azure baseline. For CPU and
    memory that claim is TRUE, and asserting it is what makes the replica findings below
    meaningful — otherwise "everything differs" would be the uninformative answer."""
    off = [d for d in report["differences"] if d.field in ("cpu", "memory")]
    assert not off, [d.render() for d in off]


def test_memory_is_compared_as_a_quantity_not_a_string():
    """The scripts write `4.0Gi` and `4Gi` for the same amount."""
    from acpctl.azure_parity import _normalise_memory
    assert _normalise_memory("4.0Gi") == _normalise_memory("4Gi") == "4Gi"
    assert _normalise_memory("1.5Gi") == "1.5Gi"


def test_a_decimal_memory_quantity_is_not_reported_as_a_difference(monkeypatch):
    """THE TEST THAT MAKES THE NORMALISATION LOAD-BEARING, and it exists because a bite check
    found it was not.

    Reverting `_normalise_memory` to a plain string comparison changed nothing: today the decimal
    form (`4.0Gi`) appears only on apps outside the tier model, so every value the comparison
    actually reaches is already written the short way. The unit test above passed either way,
    which made it a test of a helper nobody depended on.

    The normalisation still earns its place — `deploy.sh` writes `4.0Gi` while
    `rightsize-production.sh` writes `4Gi`, so one edit in the other file's style would invent a
    difference. This drives the comparison with that value so the claim is exercised rather than
    asserted.
    """
    from acpctl import azure_parity
    from acpctl.azure_baseline import baseline

    apps = baseline()
    apps["acp-assess"].memory = "4.0Gi"          # the same 4Gi, written deploy.sh's way
    monkeypatch.setattr(azure_parity, "baseline", lambda: apps)

    memory_differences = [d for d in azure_parity.compare()["differences"] if d.field == "memory"]
    assert not memory_differences, [d.render() for d in memory_differences]


def test_the_assess_tier_stays_pinned_warm(report):
    """THE DECISION, GUARDED ON BOTH SIDES — and this test has now outlived two states of it.

    It began as the headline FINDING: production pinned assess at five warm replicas and the
    contract described it autoscaling 3-10, so adopting the chart unchanged would have replaced a
    deliberate warm pool with an autoscaler. On 2026-09-05 the owner decided that question — bring
    the contract to production — and the example was changed to `{min: 5, max: 5}` with no
    `autoscale` block. So the assertion below flipped: it used to require the two sides to DIFFER
    and now requires them to AGREE.

    It covered both batch tiers once. PR #1370 gave remediate a real queue-depth scale rule and a
    5-10 range while this file was being written, and this test failed on the merge rather than
    letting the document keep a claim about remediate that had stopped being true. Same job now,
    against a decision instead of a finding.

    WHY THE CONTRACT HALF NEEDS THREE ASSERTIONS AND NOT ONE. `min == max` and the absent
    `autoscale` block are two halves of one statement, and either alone is wrong in a way that
    reads as configured: a scale rule on a tier that cannot move is a declaration with no
    consequence, and a ceiling above the floor with nothing to scale describes capacity nothing
    will ever reach. values.py derives `autoscaling.enabled` from the block's ABSENCE, so the
    chart is only right when both hold. The way this decision gets lost is not an argument — it is
    somebody restoring a plausible-looking autoscale block and nothing going red.
    """
    from acpctl.azure_baseline import baseline
    assess = baseline()["acp-assess"]
    assert assess.min_replicas == assess.max_replicas == 5, (
        "assess is no longer pinned at 5 in rightsize-production.sh — the parity document's "
        "central argument needs rewriting")
    assert not assess.autoscaled

    contract = report["contract"]["assess"]
    assert (contract["replicas.min"], contract["replicas.max"]) == (5, 5), (
        "the contract no longer pins assess at 5-5; the owner's 2026-09-05 decision was to record "
        "production's warm pool, and packaging/docs/azure-parity.md says it did")
    assert contract["autoscaled"] is False, (
        "an autoscale block is back on the assess tier. That is a performance change — it replaces "
        "a warm pool with an autoscaler on a throughput-sensitive batch stage — so it needs the "
        "owner's decision and a rewrite of azure-parity.md, not a passing test")


def test_pinning_assess_lowered_what_postgres_has_to_be_provisioned_for():
    """THE DECISION'S CONSEQUENCE, SO IT CANNOT BE MISREAD AS COSMETIC.

    The assess ceiling was the largest single term in the fleet's connection demand: ten replicas
    at `ACP_WORKERS` threads plus API headroom each. Pinning it at five takes the worst case from
    518 to 418, and the Azure adapter's Postgres requirement from `max_connections >= 533` to
    `>= 433`.

    That is the seam the packaging contract exists to create, working in the direction that is
    easy to miss — a latency decision, stated once in the document, moving the number a database
    server has to be provisioned to reach. Asserted here rather than left to the generated table,
    because a number in a generated table is not evidence that anything derived it.
    """
    import yaml

    from acpctl.azure_parity import EXAMPLE
    from acpctl.inventory import connection_budget

    # The generator's own pointer to the example, not a second copy of the path — a comparison
    # against a file the report does not read would prove nothing about the report.
    doc = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    budget = connection_budget(doc)
    assert budget["worstCaseConnections"] == 418, budget
    assert budget["withinBudget"] is True

    doc["workers"]["assess"]["replicas"]["max"] = 10
    assert connection_budget(doc)["worstCaseConnections"] == 518, (
        "restoring the 3-10 ceiling no longer moves the budget — the demand arithmetic has "
        "stopped reading the replica maximum, and this test proves nothing")


def test_remediation_now_autoscales_on_its_own_lane_job_types():
    """#1370's scale rule, recorded — and a corroboration worth keeping.

    Its query filters `type IN ('remediate_file','rescore_file','apply_approved_values')`: the
    remediate lane's job types, arrived at independently of the Helm chart's KEDA query, which
    takes the same list from `inventory.LANE_JOB_TYPES`. Two people reached the same shape from
    opposite ends, which is the strongest evidence available here that the shape is right.

    It also means the `jobs` table having a `type` column and no `role` column is now load-bearing
    in production, not only in the chart — the bug that cost this programme a day once already.
    """
    text = (ROOT / "deploy" / "public" / "rightsize-production.sh").read_text(encoding="utf-8")
    assert "remediation-queue" in text
    for job_type in ("remediate_file", "rescore_file", "apply_approved_values"):
        assert job_type in text, f"the production scale rule no longer names {job_type}"
    assert "role =" not in text, "a scale rule now queries a column the jobs table does not have"

    from acpctl.azure_baseline import baseline
    assert "remediation-queue" in baseline()["acp-remediate"].scale_rules


def test_the_connection_pool_ceiling_is_carried_into_the_baseline():
    """#1370 also pinned ACP_DB_MAX_CONN per worker replica, to hold the fleet under Postgres's
    measured 150-connection ceiling. A replica ceiling means something different once each replica
    caps its own pool, so the baseline records the pool rather than reporting replicas alone.

    This is also the field whose arrival broke the parser: `update_app` grew a sixth positional
    argument, the anchored regex stopped matching three of the five calls, and the baseline went
    quietly short. Reading it here keeps it parsed.
    """
    from acpctl.azure_baseline import baseline
    apps = baseline()
    for name in ("acp-discovery", "acp-assess", "acp-remediate"):
        assert apps[name].db_pool == 2, f"{name} no longer pins a connection pool"


def test_the_known_divergences_are_exactly_these(report):
    """The full set, listed. A new divergence appearing — from either side — fails here rather
    than being absorbed into a growing number nobody reads.

    Resolving one is meant to fail this test. That is the point: the fix and the record of it move
    together, the same way CLAUDE.md's unmounted-component list works.
    """
    from acpctl.azure_parity import DIVERGENCE
    found = {(d.tier, d.field) for d in report["differences"] if d.classification == DIVERGENCE}
    assert found == {
        ("api", "replicas.max"),
        ("discover", "replicas.max"),
        ("remediate", "replicas.min"),
    }, sorted(found)


def test_an_acknowledged_difference_must_still_be_a_real_difference():
    """AN ACKNOWLEDGEMENT THAT OUTLIVES ITS DIFFERENCE IS A LIE THAT READS AS DILIGENCE.

    Without this, resolving a divergence leaves its entry sitting in the table explaining why
    something that no longer happens is fine — and the next reader trusts it. Same guard, same
    reason, as the unmounted-component list.
    """
    from acpctl.azure_parity import ACKNOWLEDGED_DIFFERENCES, compare
    report = compare()
    real = {(d.tier, d.field) for d in report["differences"]}
    stale = [key for key in ACKNOWLEDGED_DIFFERENCES if key not in real]
    assert not stale, (
        f"these acknowledgements no longer describe a real difference: {stale}. Remove them from "
        "ACKNOWLEDGED_DIFFERENCES — the difference they excuse is gone.")


def test_every_acknowledgement_carries_a_reason():
    """"Acknowledged" with no text is indistinguishable from unnoticed."""
    from acpctl.azure_parity import ACKNOWLEDGED_DIFFERENCES
    for key, reason in ACKNOWLEDGED_DIFFERENCES.items():
        assert len(reason) > 40, f"{key} is acknowledged without saying why"


def test_the_report_does_not_claim_parity_while_divergences_exist(report):
    assert report["parity"] is False
    assert report["divergences"] == 3


# ── what the repository can and cannot confirm ────────────────────────────────

def test_nothing_in_the_azure_deployment_configures_a_disruption_budget_or_network_policy():
    """THE CHECKABLE HALF OF ADR 0048's CLAIM.

    The ADR says Container Apps cannot express a PodDisruptionBudget or a NetworkPolicy. Whether
    ACA *could* is a question about Azure's API surface that cannot be settled from this repository
    offline — so what is asserted here is the narrower thing that CAN be: the deployment does not
    configure either. Consistent with the ADR, and not a proof of it, which is what the parity
    document says.
    """
    text = "\n".join((DEPLOY / name).read_text(encoding="utf-8")
                     for name in ("deploy.sh", "redeploy.sh", "rightsize-production.sh"))
    for term in ("disruption", "PodDisruptionBudget", "networkpolicy", "NetworkPolicy"):
        assert term not in text, (
            f"deploy/public/ now mentions {term!r} — ADR 0048's premise may have changed, and "
            "packaging/docs/azure-parity.md says this repository found no such configuration.")


def test_the_largest_configured_memory_is_the_eight_gib_the_adr_names():
    """Corroboration, labelled as corroboration. The ADR cites an 8Gi Consumption ceiling; the
    largest memory any app is given is exactly 8Gi. That is consistent with the ceiling and is not
    evidence of it — an estate could sit under a limit it never approached."""
    from acpctl.azure_baseline import baseline
    from acpctl.azure_parity import _normalise_memory
    sizes = [_normalise_memory(a.memory) for a in baseline().values() if a.memory]
    biggest = max(float(s.rstrip("Gi")) for s in sizes)
    assert biggest == 8.0, f"largest configured memory is now {biggest}Gi, not 8Gi"


def test_the_things_this_comparison_cannot_see_are_named(report):
    """A clean comparison must not read as a complete one. At least one piece of real
    configuration — acp-discovery's scale rule — exists outside this repository, and the report
    says so rather than implying the scripts are the whole truth."""
    assert report["unverifiable"], "the report claims to see everything"
    assert any("scale rule" in what for what in report["unverifiable"])


def test_the_discovery_scale_rule_really_is_absent_from_this_repository():
    """The claim behind that entry, checked rather than asserted. rightsize-production.sh says
    discovery "can use its existing CPU scale rule"; if one were defined here, the report would be
    wrong to call it unverifiable."""
    text = "\n".join((DEPLOY / name).read_text(encoding="utf-8")
                     for name in ("deploy.sh", "redeploy.sh", "rightsize-production.sh"))
    rules = re.findall(r'-n "\$(\w+)"[^&|]*?--scale-rule-name\s+(\S+)', text, re.DOTALL)
    named = {var for var, _ in rules}
    assert "DISCOVERY_WORKER" not in named and "ACP_DISCOVERY_WORKER" not in named, (
        "a scale rule for acp-discovery now exists in this repository; the parity report still "
        "lists it as configured outside and unverifiable")


# ── the generated document ────────────────────────────────────────────────────

def test_the_generated_document_is_current():
    """What CI runs. The document is derived, so a change to the deploy scripts that nobody
    regenerated leaves it describing a deployment that no longer exists."""
    import subprocess
    import sys
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_azure_parity.py"), "--check"],
                          capture_output=True, text=True, cwd=str(ROOT), timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_document_keeps_its_authored_half():
    """The decision — adopt the pinned-warm model or adopt autoscaling — is authored above the
    markers. A generator that overwrote it would delete the only part nobody can re-derive."""
    text = (PACKAGING / "docs" / "azure-parity.md").read_text(encoding="utf-8")
    assert "The finding that mattered, and the decision taken" in text
    assert "Decided 2026-09-05 by the owner" in text, (
        "the authored half no longer records WHO decided the pinned-warm question and when. That "
        "sentence is the whole reason the example pins assess; without it the document reads as "
        "though the contract simply happens to agree with production")
    assert text.index("The finding that mattered") < text.index("BEGIN GENERATED")


def test_the_check_fails_when_the_document_is_stale():
    """A --check that cannot fail is indistinguishable from one that passed — same guard, and the
    same reason, as tests/test_packaging_docs.py. The generated table is the entire evidentiary
    value of this document; a guard that waves it through would leave a parity claim standing on
    numbers nobody re-derived.
    """
    import subprocess
    import sys
    target = PACKAGING / "docs" / "azure-parity.md"
    generator = ROOT / "scripts" / "gen_azure_parity.py"
    original = target.read_text(encoding="utf-8")
    try:
        target.write_text(original.replace("| `acp-assess` |", "| `acp-assess-RENAMED` |", 1),
                          encoding="utf-8")
        proc = subprocess.run([sys.executable, str(generator), "--check"],
                              capture_output=True, text=True, cwd=str(ROOT), timeout=120)
        assert proc.returncode == 1, (
            "the parity document was corrupted and --check still passed, so it guards nothing")
        assert "STALE" in proc.stderr
    finally:
        target.write_text(original, encoding="utf-8")
    proc = subprocess.run([sys.executable, str(generator), "--check"],
                          capture_output=True, text=True, cwd=str(ROOT), timeout=120)
    assert proc.returncode == 0, "the document was not restored"
