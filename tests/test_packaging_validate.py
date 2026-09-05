"""Each semantic rule gets a case that MAKES IT FIRE.

A rule with no failing case is a claim, not a check. The pattern throughout: take a valid
example, break exactly one thing, assert that exact rule id appears. Asserting on rule ids rather
than message text means improving the wording does not break the suite.
"""
from __future__ import annotations

import pytest

from packaging_helpers import EXAMPLE_IDS, EXAMPLES, errors_for, findings_for, load, load_example


@pytest.mark.parametrize("path", EXAMPLES, ids=EXAMPLE_IDS)
def test_shipped_examples_are_valid(path):
    result = findings_for(load(path))
    assert result.ok, "\n".join(f.render() for f in result.errors)


def test_min_greater_than_max_is_rejected():
    doc = load_example("standard-production")
    doc["workers"]["assess"]["replicas"] = {"min": 9, "max": 2}
    assert "replicas.bounds" in errors_for(doc)


def test_production_profile_requires_two_api_replicas():
    """PRD S8 Standard Production: minimum two API replicas."""
    doc = load_example("standard-production")
    doc["api"]["replicas"]["min"] = 1
    assert "profile.replica-floor" in errors_for(doc)


def test_high_availability_requires_two_replicas_per_critical_tier():
    doc = load_example("high-availability")
    doc["workers"]["assess"]["replicas"]["min"] = 1
    assert "profile.replica-floor" in errors_for(doc)


def test_preset_unavailable_on_the_platform_is_rejected():
    doc = load_example("evaluation")
    doc["workers"]["assess"]["resources"] = {"preset": "x-large"}
    assert "preset.platform" in errors_for(doc)


def test_stated_cpu_that_disagrees_with_the_preset_is_rejected():
    """The adapters use the preset, so a disagreeing literal would be silently discarded."""
    doc = load_example("standard-production")
    doc["api"]["resources"]["cpu"] = "8"
    assert "preset.consistency" in errors_for(doc)


def test_ephemeral_storage_below_the_computed_floor_is_rejected():
    doc = load_example("standard-production")
    doc["capacity"]["maxSourceFileSizeMb"] = 2048
    doc["capacity"]["concurrentFilesPerWorker"] = 8
    assert "storage.ephemeral-floor" in errors_for(doc)


def test_the_storage_floor_does_not_size_the_metadata_only_discovery_tier():
    """ADR 0020 made Discover metadata-only: it opens no file and downloads nothing.

    This is the inverse assertion to the one above, and it is the one that would be missed:
    charging Discover for source bytes it never holds inflates every plan, silently.
    """
    doc = load_example("standard-production")
    # A 9Gi floor: large (16Gi) clears it, small (4Gi) would not.
    doc["capacity"]["maxSourceFileSizeMb"] = 250
    doc["capacity"]["concurrentFilesPerWorker"] = 4
    doc["workers"]["assess"]["resources"] = {"preset": "large"}
    doc["workers"]["remediate"]["resources"] = {"preset": "large"}
    doc["data"]["postgres"]["maxConnections"] = 5000
    assert doc["workers"]["discover"]["resources"]["preset"] == "small"
    assert "storage.ephemeral-floor" not in errors_for(doc)


def test_embedded_data_services_are_rejected_in_production_profiles():
    """PRD S22: do not silently downgrade from managed services to embedded ones."""
    doc = load_example("standard-production")
    doc["data"]["postgres"]["mode"] = "embedded"
    rules = errors_for(doc)
    assert "data.no-downgrade" in rules


def test_compose_cannot_carry_a_production_profile():
    doc = load_example("evaluation")
    doc["runtime"]["profile"] = "standard"
    assert "profile.platform" in errors_for(doc)


def test_evaluation_profile_off_compose_is_rejected():
    doc = load_example("standard-production")
    doc["runtime"]["profile"] = "evaluation"
    assert "profile.platform" in errors_for(doc)


@pytest.mark.parametrize("mutate,rule", [
    (lambda d: d["ai"].__setitem__("mode", "external"), "regulated.ai"),
    (lambda d: d["observability"].__setitem__("exporter", "cloudwatch"), "regulated.telemetry"),
    (lambda d: d["observability"]["langfuse"].__setitem__("mode", "cloud"), "regulated.telemetry"),
    (lambda d: d["data"]["objectStorage"].__setitem__("encryption", "provider-managed"),
     "regulated.cmk"),
    (lambda d: d["data"]["postgres"].__setitem__("backupRetentionDays", 7), "regulated.retention"),
])
def test_regulated_profile_posture_is_not_optional(mutate, rule):
    """PRD S20.11: a regulated deployment can run without external AI or external telemetry.

    The profile is worth nothing if any of these can be quietly switched off while keeping the
    name, because the name is what a compliance reviewer reads.
    """
    doc = load_example("regulated")
    mutate(doc)
    assert rule in errors_for(doc)


def test_high_availability_is_not_claimable_without_ha_data_services():
    """PRD S22: do not claim high availability without it."""
    doc = load_example("high-availability")
    doc["data"]["postgres"]["highAvailability"] = False
    assert "ha.data" in errors_for(doc)


def test_public_worker_ingress_is_rejected_everywhere():
    for name in EXAMPLE_IDS:
        doc = load_example(name)
        doc["network"]["privateWorkers"] = False
        assert "network.private-workers" in errors_for(doc), name


def test_public_url_and_public_ingress_must_agree():
    doc = load_example("standard-production")
    doc["network"]["publicIngress"] = False
    assert "network.public-url" in errors_for(doc)


def test_a_source_without_its_egress_host_is_rejected():
    doc = load_example("standard-production")
    doc["network"]["allowedEgress"] = ["graph.microsoft.com"]
    assert "egress.source" in errors_for(doc)     # google-drive has no googleapis.com


def test_external_ai_under_deny_all_egress_is_rejected():
    doc = load_example("evaluation")
    doc["ai"]["mode"] = "hybrid"
    assert "egress.ai" in errors_for(doc)


def test_cpu_cannot_be_the_only_autoscaling_signal():
    """PRD S11: CPU may be a secondary signal but must not be the only one."""
    doc = load_example("standard-production")
    doc["workers"]["assess"]["autoscale"] = {"signals": ["cpu"]}
    assert "autoscale.signals" in errors_for(doc)


def test_an_ingress_signal_on_a_tier_with_no_ingress_is_rejected():
    doc = load_example("standard-production")
    doc["workers"]["assess"]["autoscale"] = {"signals": ["queue-depth", "concurrent-requests"]}
    assert "autoscale.signals" in errors_for(doc)


def test_secret_provider_must_be_resolvable_on_the_platform():
    doc = load_example("standard-production")
    doc["secrets"]["provider"] = "gcp-secret-manager"
    assert "secrets.platform" in errors_for(doc)


def test_a_required_secret_reference_cannot_be_missing():
    doc = load_example("standard-production")
    del doc["secrets"]["refs"]["database-url"]
    assert "secrets.required" in errors_for(doc)


def test_a_source_that_is_added_pulls_in_its_secret_requirement():
    doc = load_example("standard-production")
    doc["sources"].append("smb")
    assert "secrets.required" in errors_for(doc)


@pytest.mark.parametrize("field,value", [
    # The placement that has actually happened in this repo: deploy/public/deploy.sh carries a
    # literal pk-lf-655083d1... Langfuse key as a default value.
    ("langfuse", "pk-lf-655083d12dacf12febf1f1e8d2293905"),
    ("connstr", "postgresql://acpadmin:hunter2@db.example.org:5432/acpdb"),
    ("openai", "sk-abcdefghijklmnop"),
    ("aws", "AKIAIOSFODNN7EXAMPLE"),
    ("jwt", "eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.signature"),
])
def test_a_literal_secret_in_a_free_text_field_is_rejected(field, value):
    """PRD S13, and specifically the reachable version of it.

    A key-name check cannot fire under this schema: every object is additionalProperties:false, so
    a field called `password` is already a structural error. What the schema cannot stop is a
    credential in a field that legitimately takes a string — here, a secret REFERENCE's own name.
    """
    doc = load_example("standard-production")
    doc["secrets"]["refs"]["database-url"]["name"] = value
    rules = errors_for(doc)
    assert "secrets.no-literals" in rules, f"{field}: {rules}"


def test_a_key_named_like_a_secret_is_already_a_structural_error():
    """The bite check for the paragraph above: proves the key-name rule would be unreachable."""
    doc = load_example("standard-production")
    doc["ai"]["api_key"] = "anything"
    assert errors_for(doc) == ["schema"]


def test_a_secret_reference_is_not_mistaken_for_a_literal():
    """The inverse of the rule above. Without this, the no-literals rule would fire on every
    valid document's own secrets.refs.*.key and the rule would have to be deleted."""
    doc = load_example("standard-production")
    assert "secrets.no-literals" not in errors_for(doc)


def test_the_connection_budget_rejects_a_fleet_the_database_cannot_serve():
    """api/store.py sizes each replica's pool at ACP_WORKERS + headroom, and every replica holds
    its own — so an autoscaling ceiling can exhaust the server without load ever changing. That
    is the 2026-08-30 `connection pool exhausted` incident."""
    doc = load_example("standard-production")
    doc["data"]["postgres"]["maxConnections"] = 150
    assert "data.connection-budget" in errors_for(doc)


def test_warnings_do_not_fail_validation():
    """A check that fails on a legitimate choice gets ignored, so warnings must stay warnings."""
    result = findings_for(load_example("evaluation"))
    assert result.ok
    assert result.warnings


def test_a_planned_platform_warns_rather_than_failing():
    result = findings_for(load_example("high-availability"))
    assert result.ok
    assert any(f.rule == "support.status" for f in result.warnings)


def test_structural_errors_short_circuit_the_semantic_rules():
    """Semantic rules index into the document freely; running them over a structurally invalid
    one produces KeyErrors dressed up as findings."""
    doc = load_example("standard-production")
    del doc["workers"]
    result = findings_for(doc)
    assert not result.ok
    assert {f.rule for f in result.errors} == {"schema"}
