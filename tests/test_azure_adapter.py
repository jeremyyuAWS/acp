"""What the Azure adapter must provision — PRD S21 phase 3, the ownership question.

Slices 1 and 2 produced two artifacts that DESCRIBE Azure. This tests the one that says who makes
a description true, and its central claim is a negative one: `secrets.workloadIdentity` shipped in
slice 2 as a declaration with no consequence. A document could declare it, validate, render values,
template the chart and deploy onto a cluster where the identity did not exist — and the only
symptom would be a 403 from the worker tier at first write.

SO THE TESTS THAT MATTER HERE CHECK THAT A DECLARATION DECOMPOSES. A requirements list that echoed
`workloadIdentity: enabled` back would satisfy every shallow assertion and reproduce the exact
failure it exists to prevent.
"""
from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import pytest

from packaging_helpers import PACKAGING, load_example  # noqa: F401  (puts acpctl on sys.path)

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "packaging" / "docs" / "azure-adapter.md"
GENERATOR = ROOT / "scripts" / "gen_azure_adapter.py"
DERIVED = ROOT / "packaging" / "docs" / "azure-current.acp-deployment.yaml"


@pytest.fixture
def azure():
    """The derived description of production — the document the adapter has to satisfy."""
    from acpctl.spec import load_document
    return load_document(DERIVED)


def _settings(requirements) -> set[str]:
    return {f"{r.resource}.{r.setting}" for r in requirements}


# ── the declaration that had no consequence ──────────────────────────────────────────────────

def test_a_declared_identity_becomes_three_resources_not_one_boolean(azure):
    """THE HEADLINE. Slice 2's `workloadIdentity` was inert; this is what makes it not.

    All three are needed and each fails the same invisible way: an identity with no federated
    credential, a credential with the wrong subject, and a correct binding with no role assignment
    all produce a workload that starts cleanly and returns 403 at first write.
    """
    from acpctl.adapter_azure import requirements
    got = _settings(requirements(azure))
    for setting in ("userAssignedIdentity", "federatedCredential", "roleAssignment"):
        assert f"identity:object-storage.{setting}" in got, sorted(got)


def test_the_cluster_itself_must_be_able_to_issue_the_token(azure):
    """The two cluster-level prerequisites. Federated credentials are issued against the cluster's
    OIDC issuer and cannot exist without it; without the addon the SDK falls back to whatever else
    it finds, often the node identity — which usually has MORE access, so the failure is silent and
    in the permissive direction."""
    from acpctl.adapter_azure import requirements
    got = _settings(requirements(azure))
    assert "cluster.oidcIssuer" in got
    assert "cluster.workloadIdentity" in got


def test_the_blob_role_is_the_one_the_deploy_script_already_names(azure):
    """GROUNDED IN THE REPOSITORY, not in recollection of Azure's role catalogue.

    deploy/public/deploy.sh names `Storage Blob Data Contributor` for exactly this grant and calls
    it "one-time infra setup (not this script's job)" — which is why nothing owned it. If the
    script ever names a different role, this requirement is wrong and should fail here.
    """
    from acpctl.adapter_azure import requirements
    role = [r for r in requirements(azure)
            if r.resource == "identity:object-storage" and r.setting == "roleAssignment"]
    assert len(role) == 1
    assert "Storage Blob Data Contributor" in str(role[0].value)

    script = (ROOT / "deploy" / "public" / "deploy.sh").read_text(encoding="utf-8")
    assert "Storage Blob Data Contributor" in script, (
        "deploy.sh no longer names this role; the adapter requirement is now unsourced")


def test_a_document_with_no_workload_identity_asks_for_none_of_it(azure):
    """ANTI-VACUOUS. If these requirements appeared unconditionally, every assertion above would
    pass on a model that ignored the document entirely."""
    from acpctl.adapter_azure import requirements
    without = copy.deepcopy(azure)
    without["secrets"]["workloadIdentity"] = []
    without["secrets"]["refs"]["object-storage"] = {"name": "object-storage", "key": "value"}

    got = _settings(requirements(without))
    assert not [s for s in got if s.startswith("identity:")], sorted(got)
    assert "cluster.oidcIssuer" not in got
    assert "cluster.workloadIdentity" not in got


def test_a_second_identity_gets_its_own_three_resources(azure):
    """One identity per reference, not one shared. A single identity holding every grant makes
    each workload as privileged as the most privileged one."""
    from acpctl.adapter_azure import requirements
    doc = copy.deepcopy(azure)
    doc["secrets"]["workloadIdentity"] = ["object-storage", "redis-url"]
    doc["secrets"]["refs"].pop("redis-url")

    got = _settings(requirements(doc))
    for name in ("object-storage", "redis-url"):
        for setting in ("userAssignedIdentity", "federatedCredential", "roleAssignment"):
            assert f"identity:{name}.{setting}" in got


# ── the connection ceiling, derived rather than typed ────────────────────────────────────────

def test_the_server_requirement_is_derived_from_the_fleet(azure):
    """82 of demand plus 15 the server keeps for itself. The document's declared 150 is not
    consulted: the point of the inversion is that demand tells the adapter what to build."""
    from acpctl.adapter_azure import requirements
    from acpctl.inventory import SERVER_RESERVED_CONNECTIONS, connection_budget

    demand = connection_budget(azure)["worstCaseConnections"]
    assert demand == 82
    row = [r for r in requirements(azure) if r.setting == "max_connections"]
    assert len(row) == 1
    assert row[0].value == f">= {demand + SERVER_RESERVED_CONNECTIONS}"


def test_raising_a_replica_ceiling_raises_the_server_requirement(azure):
    """The requirement TRACKS the document. A constant dressed as a derivation would pass the test
    above and fail this one."""
    from acpctl.adapter_azure import requirements

    def ceiling(doc):
        return [r for r in requirements(doc) if r.setting == "max_connections"][0].value

    bigger = copy.deepcopy(azure)
    bigger["workers"]["remediate"]["replicas"]["max"] = 20
    bigger["data"]["postgres"]["maxConnections"] = 700
    assert ceiling(bigger) != ceiling(azure)


def test_the_band_where_the_document_validates_and_the_server_still_runs_out(azure):
    """A CEILING THAT CLEARS THE FLEET AND NOT THE RESERVE, which the budget check cannot see.

    `data.connection-budget` fails when demand EXCEEDS the ceiling. Between the demand and the
    demand plus the server's own reserve, the document validates and a real server refuses
    connections — starting, characteristically, with the psql session opened to find out why.
    """
    from acpctl.adapter_azure import report
    from acpctl.spec import validate

    tight = copy.deepcopy(azure)
    tight["data"]["postgres"]["maxConnections"] = 90     # clears 82, leaves 8 of the 15 needed

    rules = {f.rule for f in validate(tight).errors}
    assert "data.connection-budget" not in rules, "the budget check should still pass here"
    assert "data.connection-reserve" in {f.rule for f in validate(tight).warnings}
    assert len(report(tight).conflicts) == 1


def test_a_comfortable_ceiling_produces_no_warning_and_no_conflict(azure):
    """The other half, so the check above is not simply always-on."""
    from acpctl.adapter_azure import report
    from acpctl.spec import validate
    roomy = copy.deepcopy(azure)
    roomy["data"]["postgres"]["maxConnections"] = 300
    assert "data.connection-reserve" not in {f.rule for f in validate(roomy).warnings}
    assert not report(roomy).conflicts


def test_the_budget_error_names_the_lever_this_document_actually_has(azure):
    """THE MESSAGE WENT STALE UNDER SLICE 2'S FEET, and a wrong lever is worse than none.

    It used to say "each replica's pool is ACP_WORKERS + 16" and send the operator to ACP_WORKERS —
    which does nothing on a document that pins `connectionPool`, i.e. every document describing
    production. The direction matters too: demand has to come DOWN here.
    """
    from acpctl.spec import validate
    over = copy.deepcopy(azure)
    over["data"]["postgres"]["maxConnections"] = 50

    message = [f.message for f in validate(over).errors if f.rule == "data.connection-budget"]
    assert len(message) == 1
    text = message[0]
    assert "connectionPool" in text and "lower" in text
    assert "ACP_WORKERS + 16" not in text


def test_a_document_with_no_pinned_pools_is_told_about_replica_ceilings_instead():
    """The other branch of that message. An example that pins nothing must not be advised to lower
    a `connectionPool` it does not have."""
    from acpctl.spec import validate
    doc = load_example("standard-production")
    assert not any(t.get("connectionPool") for t in doc["workers"].values())
    doc["data"]["postgres"]["maxConnections"] = 50

    text = [f.message for f in validate(doc).errors if f.rule == "data.connection-budget"][0]
    assert "connectionPool" not in text
    assert "replica ceilings" in text


# ── retention: the gap slice 2 could not close ───────────────────────────────────────────────

def test_an_unstated_retention_is_undecided_rather_than_defaulted(azure):
    """azure-rebuild.md fails validation on this exact field because nothing owned it. The adapter
    owns it now — and renders it UNDECIDED, because a requirement quietly defaulted to Azure's own
    value is a decision nobody made."""
    from acpctl.adapter_azure import report
    assert "backupRetentionDays" not in azure["data"]["postgres"]
    undecided = report(azure).undecided
    assert [r.setting for r in undecided] == ["backup.retentionDays"]


def test_a_stated_retention_is_carried_through():
    from acpctl.adapter_azure import report
    doc = load_example("standard-production")
    row = [r for r in report(doc).requirements if r.setting == "backup.retentionDays"]
    assert len(row) == 1 and row[0].value == doc["data"]["postgres"]["backupRetentionDays"]
    assert not report(doc).undecided


# ── the data-service modes ───────────────────────────────────────────────────────────────────

def test_a_self_hosted_postgres_asks_the_azure_adapter_for_no_server():
    """The adapter's job shrinks when the document's does not use a managed service. A model that
    emitted server requirements regardless would have the adapter provision a database nobody
    connects to."""
    from acpctl.adapter_azure import requirements
    doc = load_example("regulated")
    assert doc["data"]["postgres"]["mode"] == "self-hosted"
    got = _settings(requirements(doc))
    assert "postgres.max_connections" not in got
    assert "postgres.provisioning" in got   # stated, so the absence is deliberate rather than lost


def test_every_requirement_says_where_it_came_from(azure):
    """A requirement with no provenance is indistinguishable from a preference. This is the same
    guard as azure_parity's every-acknowledgement-carries-a-reason."""
    from acpctl.adapter_azure import DERIVED, DOCUMENT, PROFILE, VENDOR, requirements
    for r in requirements(azure):
        assert r.source in {DOCUMENT, DERIVED, PROFILE, VENDOR}, r.render()
        assert len(r.because) > 20, r.render()


def test_no_sku_table_is_invented(azure):
    """The one place it would be tempting to write down a vendor number from memory. The
    requirement states the condition to satisfy and marks the SKU choice `vendor`."""
    from acpctl.adapter_azure import VENDOR, requirements
    sku = [r for r in requirements(azure) if r.setting == "sku"]
    assert len(sku) == 1 and sku[0].source == VENDOR
    assert not any(char.isdigit() for char in str(sku[0].value)), (
        "the sku requirement now carries a number, which would read as a verified vendor fact")


def test_what_the_contract_cannot_express_is_named_with_a_reason():
    from acpctl.adapter_azure import UNOWNED
    assert len(UNOWNED) >= 4
    for what, why in UNOWNED.items():
        assert len(why) > 60, what


# ── private networking (PRD S21 phase 3's third clause) ──────────────────────────────────────

def test_private_data_services_require_the_three_things_that_make_them_work(azure):
    """A private endpoint ADDS a private route; it does not remove the public one, and without a
    linked DNS zone the pods resolve the public name and take the public route. Both are ways to
    configure this and not achieve it."""
    from acpctl.adapter_azure import requirements
    doc = copy.deepcopy(azure)
    doc["network"]["privateDataServices"] = True

    got = {f"{r.resource}.{r.setting}": r for r in requirements(doc)}
    assert got["network.privateEndpoints"].value == ["objectStorage", "postgres", "redis"]
    assert "network.publicNetworkAccess" in got
    assert "network.privateDnsZones" in got


def test_the_public_default_is_stated_rather_than_left_to_be_assumed(azure):
    """Today's Azure uses public endpoints. Saying so is what stops a reader inferring either
    answer from the absence of a row."""
    from acpctl.adapter_azure import requirements
    got = {f"{r.resource}.{r.setting}": r for r in requirements(azure)}
    assert got["network.privateEndpoints"].value == "none"


def test_a_private_control_plane_is_a_separate_decision(azure):
    """Separate from the data services because they fail differently — administrative exposure
    versus data exposure."""
    from acpctl.adapter_azure import requirements
    assert "cluster.apiServerAccess" not in _settings(requirements(azure))
    private = copy.deepcopy(azure)
    private["network"]["privateControlPlane"] = True
    assert "cluster.apiServerAccess" in _settings(requirements(private))


def test_the_new_network_keys_are_accepted_by_the_schema(azure):
    from acpctl.spec import validate
    doc = copy.deepcopy(azure)
    doc["network"]["privateDataServices"] = True
    doc["network"]["privateControlPlane"] = True
    assert "schema" not in {f.rule for f in validate(doc).errors}


def test_an_unknown_network_key_is_still_rejected(azure):
    """additionalProperties:false is doing the work; adding two keys must not have loosened it."""
    from acpctl.spec import validate
    doc = copy.deepcopy(azure)
    doc["network"]["privateEverything"] = True
    assert "schema" in {f.rule for f in validate(doc).errors}


# ── the CLI stays read-only ──────────────────────────────────────────────────────────────────

def _cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "acpctl", *args], capture_output=True, text=True, cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "packaging" / "cli"), "PATH": "/usr/bin:/bin"})


def test_the_adapter_command_refuses_an_invalid_document():
    """The derived azure-current document is invalid by design (two known findings), which makes
    it the honest fixture for this: requirements derived from an invalid document are confidently
    wrong about what to BUILD, and infrastructure gets created from them."""
    proc = _cli("adapter", str(DERIVED))
    assert proc.returncode == 1
    assert "refusing to derive adapter requirements" in proc.stderr


def test_the_adapter_command_runs_on_a_valid_document():
    proc = _cli("adapter", str(ROOT / "packaging" / "examples" /
                              "standard-production.acp-deployment.yaml"))
    assert proc.returncode == 0, proc.stderr
    assert "Azure adapter requirements" in proc.stdout
    assert "Storage account + container" in proc.stdout


def test_a_non_azure_document_is_refused_rather_than_answered_wrongly(tmp_path):
    """AWS and GCP are phase 4. Answering with Azure requirements for a GCP document would be a
    confident wrong answer, which is the failure mode this whole programme keeps finding."""
    import yaml
    doc = load_example("high-availability")
    doc["runtime"]["platform"] = "gcp"
    doc["secrets"]["provider"] = "gcp-secret-manager"
    path = tmp_path / "gcp.acp-deployment.yaml"
    path.write_text(yaml.safe_dump(doc))

    proc = _cli("adapter", str(path))
    assert proc.returncode == 2
    assert "phase 4" in proc.stderr


def test_the_adapter_command_writes_nothing(monkeypatch):
    """Same guard the rest of the CLI carries: acpctl is read-only in this release."""
    from acpctl.adapter_azure import report
    from acpctl.spec import load_document

    def refuse(*a, **k):
        raise AssertionError("acpctl adapter opened a file for writing")

    doc = load_document(ROOT / "packaging" / "examples" /
                        "standard-production.acp-deployment.yaml")
    monkeypatch.setattr("builtins.open", refuse)
    report(doc)


# ── the generated document ───────────────────────────────────────────────────────────────────

def _gen(*args):
    return subprocess.run([sys.executable, str(GENERATOR), *args],
                          capture_output=True, text=True, cwd=ROOT)


def test_the_generated_document_is_current():
    proc = _gen("--check")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_check_fails_when_the_document_is_stale():
    """Edited INSIDE the markers — text below them is the author's and --check correctly ignores
    it, which cost a red test to learn on the previous slice."""
    original = REPORT.read_text()
    marker = original.index("_Generated by")
    try:
        REPORT.write_text(original[:marker] + "<!-- drift -->\n" + original[marker:])
        proc = _gen("--check")
        assert proc.returncode == 1, "gen_azure_adapter.py --check passed on a stale document"
    finally:
        REPORT.write_text(original)
    assert _gen("--check").returncode == 0


def test_the_report_covers_the_derived_production_document():
    """ANTI-VACUOUS on the generator: a filter that excluded every document would produce a short,
    clean report with no requirements to disagree with."""
    text = REPORT.read_text()
    assert "azure-current (derived from production)" in text
    assert "identity:object-storage" in text
    assert "UNDECIDED" in text


def test_the_report_keeps_its_authored_half():
    text = REPORT.read_text()
    head = text[: text.index("<!-- BEGIN GENERATED: azure-adapter")]
    assert "403" in head, "the authored half no longer says how the missing grant surfaces"
    assert "Terraform" in head, "the authored half no longer states what this deliberately is not"
