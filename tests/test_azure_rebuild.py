"""Can the contract express today's Azure? — PRD S21 phase 3, the derived document.

`test_azure_parity.py` compares production to the standard-production EXAMPLE. This tests the
question underneath it: whether a document exists in the contract's vocabulary that describes what
production actually runs, and whether the answer stays true as the scripts change.

THE TESTS THAT MATTER MOST ARE THE ONES THAT WOULD PASS ON A BROKEN DERIVATION. A parse that goes
short produces a smaller document with fewer errors, which reads as progress; a connection model
that quietly ignores a pinned pool produces a number nobody checks. Both have precedents in this
programme — #1370's sixth positional argument silently emptied the baseline parse within an hour of
it being written — so the anti-vacuous guards come first here and the arithmetic is pinned against
the APPLICATION's own function rather than against a copy of it.
"""
from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import pytest

from packaging_helpers import PACKAGING  # noqa: F401  (puts acpctl on sys.path)

ROOT = Path(__file__).resolve().parent.parent
DOCUMENT = ROOT / "packaging" / "docs" / "azure-current.acp-deployment.yaml"
REPORT = ROOT / "packaging" / "docs" / "azure-rebuild.md"
GENERATOR = ROOT / "scripts" / "gen_azure_rebuild.py"

# The two errors the derived document is EXPECTED to carry, by rule id. Both are findings about
# the deployment rather than about the derivation, and both are named in azure-rebuild.md. Pinned
# as a set so a third error appearing — or one of these being silently resolved — fails here.
EXPECTED_ERROR_RULES = {"profile.replica-floor", "production.retention"}


@pytest.fixture
def document():
    from acpctl.azure_document import derive
    return derive(version="2026.9")


# ── the derivation found what it should have found ───────────────────────────────────────────

def test_the_derivation_covers_every_tier_the_contract_requires(document):
    """ANTI-VACUOUS, and the reason this file leads with it.

    Every other assertion here is weaker on a document that came out short. A parse that finds two
    apps instead of five produces a document with fewer fields, fewer errors and a smaller
    connection budget — all of which read as things getting better.
    """
    assert set(document["workers"]) == {"discover", "assess", "remediate"}
    for tier in ("discover", "assess", "remediate"):
        assert document["workers"][tier]["replicas"]["max"] >= 1
        assert document["workers"][tier]["resources"]["preset"]
    assert document["api"]["replicas"] == {"min": 1, "max": 3}


def test_the_document_records_todays_replica_ranges_not_the_examples(document):
    """The point of deriving rather than adapting the example.

    THE ORIGINAL WORDING NO LONGER HOLDS FOR ONE OF THESE THREE, and rewriting it is the honest
    move rather than leaving a rationale that has quietly become false. It said: if these ever
    equal the standard-production example's ranges, the derivation has stopped reading the
    scripts. On 2026-09-05 the owner pinned the example's assess tier to 5-5 to match production
    (packaging/docs/azure-parity.md), so assess NOW equals the example and that is correct — the
    example moved to production, not the derivation to the example.

    Discover (1-2 against the example's 1-3) and remediate (5-10 against 3-10) still differ, so
    the guard keeps its discriminating power: a derivation that started copying the example would
    still be caught by those two. Assess is now a fixed expectation like any other.
    """
    assert document["workers"]["assess"]["replicas"] == {"min": 5, "max": 5}
    assert document["workers"]["remediate"]["replicas"] == {"min": 5, "max": 10}
    assert document["workers"]["discover"]["replicas"] == {"min": 1, "max": 2}


def test_a_pinned_tier_gets_no_autoscale_block(document):
    """Assess is pinned 5-5. Recording an autoscale block for it would misdescribe the warm pool
    the operator deliberately chose — the finding azure-parity.md put to the owner, and which the
    owner settled on 2026-09-05 by pinning the contract's example to match. The derived document
    said this before the decision and says it after; that it needed no change is the evidence that
    it was describing production rather than arguing for a position."""
    assert "autoscale" not in document["workers"]["assess"]
    assert document["workers"]["remediate"]["autoscale"] == {"signals": ["queue-depth"]}


def test_the_discovery_scale_rule_is_not_invented(document):
    """rightsize-production.sh REFERS to a discovery CPU scale rule that exists nowhere in this
    repository (azure_parity.UNVERIFIABLE). Discovery does scale — 1-2 — but the signal is not
    knowable from here, so no autoscale block is written. Guessing one would put a fabrication in
    a generated document, which is the failure mode this whole exercise is built against."""
    assert "autoscale" not in document["workers"]["discover"]


# ── the connection pool: the finding, made executable ────────────────────────────────────────

def test_the_pool_model_is_the_applications_own_arithmetic():
    """PINNED AGAINST api/store.py ITSELF, not against a copy of its numbers.

    acpctl cannot import the application (it ships in an installer bundle without api/), so the
    override semantics are reimplemented in inventory.pool_per_replica. A reimplementation that is
    never compared to the original is a second source of truth waiting to drift — so this drives
    both with the same inputs and requires them to agree, including the cases where they could
    plausibly differ: an override SMALLER than the formula, one LARGER, and none at all.
    """
    sys.path.insert(0, str(ROOT / "api"))
    import store

    from acpctl.inventory import pool_per_replica

    for threads, pinned in [(0, None), (2, None), (4, None), (4, 2), (4, 64), (2, 2), (8, 3)]:
        tier = {"connectionPool": pinned} if pinned else {}
        env = {"ACP_WORKERS": str(threads)}
        if pinned:
            env["ACP_DB_MAX_CONN"] = str(pinned)
        assert pool_per_replica(tier, threads=threads) == store.db_max_conn(env=env), (
            f"acpctl and api/store.py disagree at threads={threads} pinned={pinned}")


def test_the_override_replaces_the_formula_rather_than_capping_it():
    """The specific way a plausible reimplementation would be wrong.

    `min(formula, pinned)` agrees with production today, because production pins 2 and the formula
    gives 18-20. It diverges the moment somebody pins a pool LARGER than the formula — which is the
    direction an operator RAISING a limit moves, and the case where under-reporting demand is most
    dangerous. api/store.py returns the override outright; so does this.
    """
    from acpctl.inventory import pool_per_replica
    assert pool_per_replica({"connectionPool": 64}, threads=4) == 64
    assert pool_per_replica({}, threads=4) == 20


def test_todays_azure_fits_its_postgres_server(document):
    """82 of 150. The number production actually runs at."""
    from acpctl.inventory import connection_budget
    budget = connection_budget(document)
    assert budget["serverMaxConnections"] == 150, (
        "the derived document no longer names the Postgres server production runs")
    assert budget["worstCaseConnections"] == 82
    assert budget["withinBudget"]


def test_without_the_pinned_pools_the_same_fleet_reads_as_oversubscribed(document):
    """THE FINDING, EXECUTABLE — and the test that makes `connectionPool` load-bearing.

    Strip the pools the scripts pin and nothing else changes: same tiers, same replica ranges, same
    server. Demand goes from 82 to 384 against a 150-connection ceiling, and `acpctl plan` reports
    today's Azure as 2.5x oversubscribed when it demonstrably is not.

    That was the state of the contract before this slice. It is kept as a test rather than a
    paragraph because a paragraph cannot fail: if `connectionPool` is ever dropped from the schema
    or stops being read, this goes red instead of the claim quietly becoming false.
    """
    from acpctl.inventory import connection_budget

    unpinned = copy.deepcopy(document)
    for tier in unpinned["workers"].values():
        tier.pop("connectionPool", None)

    budget = connection_budget(unpinned)
    assert budget["worstCaseConnections"] == 384
    assert not budget["withinBudget"], (
        "the pre-slice-2 contract no longer misreports this fleet — if the formula changed, this "
        "test's premise did too and the document's headline needs rewriting")


def test_the_pinned_pool_reaches_the_container_not_just_the_arithmetic(document):
    """A pool that stops at the budget calculation would describe a fleet that fits its server
    while deploying one that does not. It has to arrive as ACP_DB_MAX_CONN on the workload."""
    from acpctl.inventory import build_inventory
    from acpctl.values import build_values

    by_name = {s.name: s for s in build_inventory(document)}
    for name in ("acp-discovery", "acp-assess", "acp-remediate"):
        assert by_name[name].env.get("ACP_DB_MAX_CONN") == "2"

    values = build_values(document)
    for tier in ("discover", "assess", "remediate"):
        assert values["workers"][tier]["env"]["ACP_DB_MAX_CONN"] == "2"
    # The API pins none, so it must not acquire one from a default.
    assert "ACP_DB_MAX_CONN" not in values["api"]["env"]


# ── workload identity: an access path with no credential ─────────────────────────────────────

def test_the_scripts_really_do_hold_no_storage_secret():
    """THE PREMISE OF THE WHOLE workloadIdentity CLAIM, checked rather than asserted.

    If deploy.sh did wire a storage credential, `secrets.workloadIdentity: [object-storage]` would
    be a misdescription of production dressed as a security posture — the exact shape of error this
    programme keeps finding in confident comments.
    """
    from acpctl.azure_baseline import secret_names
    names = secret_names()
    assert "database-url" in names and "redis-url" in names, (
        "deploy.sh no longer wires the database/redis secrets the derived document declares")
    assert not [n for n in names if "blob" in n or "storage" in n], (
        f"deploy.sh now wires a storage credential ({sorted(names)}) — production may no longer "
        f"reach Blob Storage by managed identity, and the derived document's workloadIdentity "
        f"entry would be wrong")


def test_workload_identity_satisfies_the_object_storage_requirement(document):
    from acpctl.spec import required_secret_names, validate
    assert "object-storage" in required_secret_names(document)
    assert document["secrets"]["workloadIdentity"] == ["object-storage"]
    assert not [f for f in validate(document).errors if f.rule == "secrets.required"]


def test_removing_the_identity_declaration_brings_the_error_back(document):
    """A BITE CHECK ON THE RULE CHANGE. Without it, `_rule_required_secrets` could have been
    loosened to accept anything and every test above would still pass."""
    from acpctl.spec import validate
    stripped = copy.deepcopy(document)
    stripped["secrets"].pop("workloadIdentity")
    rules = [f.rule for f in validate(stripped).errors]
    assert "secrets.required" in rules


def test_an_identity_entry_that_satisfies_nothing_is_flagged(document):
    """Same guard as azure_parity's acknowledged-difference check: an entry that outlives its
    requirement still reads as deliberate care to the next person."""
    from acpctl.spec import validate
    doc = copy.deepcopy(document)
    doc["secrets"]["workloadIdentity"].append("langfuse-secret-key")
    rules = [f.rule for f in validate(doc).warnings]
    assert "secrets.identity-unused" in rules


def test_declaring_both_a_secret_and_an_identity_is_flagged(document):
    from acpctl.spec import validate
    doc = copy.deepcopy(document)
    doc["secrets"]["workloadIdentity"].append("database-url")
    rules = [f.rule for f in validate(doc).warnings]
    assert "secrets.identity-redundant" in rules


def test_the_secret_references_are_read_from_the_scripts_not_asserted(document, monkeypatch):
    """Declaring a reference the deployment does not hold is the same class of error as claiming
    an identity it does not use. Stop wiring redis-url and the document stops declaring it."""
    from acpctl import azure_document
    monkeypatch.setattr(azure_document, "secret_names", lambda: {"database-url"})
    assert set(azure_document._secrets()["refs"]) == {"database-url"}


# ── what the contract still cannot say ───────────────────────────────────────────────────────

def test_the_document_carries_exactly_the_two_known_errors(document):
    """Both are facts about the deployment, and both are explained in azure-rebuild.md. A third
    error appearing means either the scripts changed or the derivation started guessing; one of
    these disappearing means production or the contract moved and the document's argument is
    stale. Either way somebody should look."""
    from acpctl.spec import validate
    assert {f.rule for f in validate(document).errors} == EXPECTED_ERROR_RULES


def test_the_api_floor_error_is_the_finding_azure_parity_already_named(document):
    """Slice 1 asserted production fails its own profile's floor by reading PRD S8. Here the
    contract's own validator says it, on a document derived from the scripts."""
    from acpctl.spec import validate
    floor = [f for f in validate(document).errors if f.rule == "profile.replica-floor"]
    assert len(floor) == 1 and floor[0].path == "api.replicas.min"
    assert document["api"]["replicas"]["min"] == 1


def test_backup_retention_is_left_unstated_rather_than_guessed(document):
    """The scripts do not provision the Postgres server, so retention is not derivable. Guessing
    Azure's default would produce a document that validates and lies; leaving it out produces one
    that fails and is true."""
    assert "backupRetentionDays" not in document["data"]["postgres"]


def test_every_unexpressible_field_says_why():
    """An entry with no reason is indistinguishable from an oversight."""
    from acpctl.azure_document import NOT_EXPRESSIBLE
    assert NOT_EXPRESSIBLE
    for field, why in NOT_EXPRESSIBLE.items():
        assert len(why) > 60, f"{field}: the reason is too short to be one"


def test_a_size_that_matches_no_preset_refuses_rather_than_rounding(monkeypatch):
    """NotExpressible is raised, not approximated. A derived document that rounds an
    unrepresentable value reads as proof the contract fits — the one claim this module tests."""
    from acpctl import azure_document

    apps = azure_document.baseline()
    apps["acp-assess"].cpu = 3.0          # between `standard` (2) and `large` (4)
    monkeypatch.setattr(azure_document, "baseline", lambda: apps)
    with pytest.raises(azure_document.NotExpressible, match="matches no preset"):
        azure_document.derive(version="2026.9")


def test_a_missing_tier_refuses_rather_than_emitting_a_partial_document(monkeypatch):
    """The #1370 failure mode, guarded at the document layer too: a short parse must not yield a
    document describing three tiers as though the fourth did not exist."""
    from acpctl import azure_document

    apps = {k: v for k, v in azure_document.baseline().items() if k != "acp-remediate"}
    monkeypatch.setattr(azure_document, "baseline", lambda: apps)
    with pytest.raises(azure_document.NotExpressible, match="remediate"):
        azure_document.derive(version="2026.9")


# ── the rebuild path itself ──────────────────────────────────────────────────────────────────

def test_the_chart_renders_todays_azure_once_the_two_findings_are_cleared(document):
    """THE REBUILD, END TO END — the thing PRD S21 phase 3 actually asks for.

    Clearing the two errors is not papering over them: they are a missing API replica and an
    unprovisioned backup policy, neither of which is a property of the WORKLOAD. What this proves
    is that the workload — pinned pools, the queue-depth scaler on remediate, private workers,
    every replica range — survives the trip through values and into real manifests.
    """
    import shutil

    import yaml

    from acpctl.values import build_values

    if not shutil.which("helm"):
        pytest.fail("helm is not installed; tests/test_packaging_chart.py requires it in CI too")

    doc = copy.deepcopy(document)
    doc["api"]["replicas"]["min"] = 2
    doc["data"]["postgres"]["backupRetentionDays"] = 35

    from acpctl.spec import validate
    assert not validate(doc).errors, [f.render() for f in validate(doc).errors]

    values = yaml.safe_dump(build_values(doc))
    out = ROOT / "packaging" / "chart" / "acp"
    proc = subprocess.run(
        ["helm", "template", "acp", str(out), "-f", "-"],
        input=values, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr

    rendered = list(yaml.safe_load_all(proc.stdout))
    workers = [d for d in rendered if d and d.get("kind") == "Deployment"
               and "worker" in d["metadata"]["name"]]
    assert len(workers) == 3, [d["metadata"]["name"] for d in workers]
    for deployment in workers:
        env = {e["name"]: e.get("value")
               for e in deployment["spec"]["template"]["spec"]["containers"][0]["env"]}
        assert env.get("ACP_DB_MAX_CONN") == "2", deployment["metadata"]["name"]

    scaled = [d for d in rendered if d and d.get("kind") == "ScaledObject"]
    assert len(scaled) == 1, (
        "exactly one tier autoscales on a queue in today's Azure (remediate, #1370); "
        f"the chart rendered {[d['metadata']['name'] for d in scaled]}")


def test_the_document_that_ships_is_the_one_the_derivation_produces(document):
    """The checked-in YAML and the live derivation cannot disagree — same guard as every other
    generated document here, and the reason `--check` runs in CI."""
    import yaml
    assert DOCUMENT.exists()
    assert yaml.safe_load(DOCUMENT.read_text()) == document


# ── the generated artifacts ──────────────────────────────────────────────────────────────────

def _run(*args):
    return subprocess.run([sys.executable, str(GENERATOR), *args],
                          capture_output=True, text=True, cwd=ROOT)


def test_the_generated_artifacts_are_current():
    proc = _run("--check")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_report_keeps_its_authored_half():
    text = REPORT.read_text()
    head = text[: text.index("<!-- BEGIN GENERATED: azure-rebuild")]
    assert "connectionPool" in head and "workloadIdentity" in head, (
        "the authored half no longer explains the two gaps this slice closed")


def test_the_check_fails_when_an_artifact_is_stale():
    """A --check THAT CANNOT FAIL IS INDISTINGUISHABLE FROM ONE THAT PASSED.

    Both artifacts are perturbed, because a --check covering only the report would pass while the
    YAML an operator actually runs through acpctl went stale.

    THE REPORT IS EDITED INSIDE ITS MARKERS, and the first version of this test was not — it
    appended after the END marker and `--check` passed, correctly. That is authored territory:
    the guard covers the generated block, and text below it is a human's to write. Discovering
    that cost one red test and is worth recording, because "the check did not fire" reads as a
    broken guard when it can equally mean the check was pointed at the wrong bytes.
    """
    report = REPORT.read_text()
    marker = report.index("_Generated by")
    perturbations = [
        (REPORT, report[:marker] + "<!-- drift -->\n" + report[marker:]),
        (DOCUMENT, DOCUMENT.read_text() + "\n# drift\n"),
    ]
    for target, stale in perturbations:
        original = target.read_text()
        try:
            target.write_text(stale)
            proc = _run("--check")
            assert proc.returncode == 1, (
                f"gen_azure_rebuild.py --check passed with {target.name} modified")
            assert target.name in proc.stderr
        finally:
            target.write_text(original)
    assert _run("--check").returncode == 0
