"""The normalized service inventory is what every platform adapter consumes.

If it is wrong, every adapter is wrong in the same way — which is the trade this contract makes:
one place to get it right instead of five places to get it wrong.
"""
from __future__ import annotations

import pytest

from packaging_helpers import EXAMPLE_IDS, EXAMPLES, load, load_example


def inv(doc):
    from acpctl.inventory import build_inventory
    return {s.name: s for s in build_inventory(doc)}


def test_api_headroom_matches_the_application_constant_it_copies():
    """packaging must not depend on api/, so the headroom figure is duplicated — and pinned here.

    Without this the copy drifts silently and the connection budget quietly stops describing the
    pool api/store.py actually opens.
    """
    import store

    from acpctl.inventory import API_HEADROOM_CONN
    assert API_HEADROOM_CONN == store._API_HEADROOM_CONN, (
        "api/store.py's _API_HEADROOM_CONN changed. Update API_HEADROOM_CONN in "
        "packaging/cli/acpctl/inventory.py — the connection budget is derived from it.")


def test_connection_budget_uses_the_applications_own_formula():
    """The budget must equal what store.db_max_conn would return per replica, summed."""
    import store

    from acpctl.inventory import build_inventory
    doc = load_example("standard-production")
    for service in build_inventory(doc):
        if not service.replicas or not service.env.get("ACP_WORKERS"):
            continue
        per_replica = store.db_max_conn({"ACP_WORKERS": service.env["ACP_WORKERS"]})
        assert service.db_connections_max == service.replicas[1] * per_replica, service.name


@pytest.mark.parametrize("path", EXAMPLES, ids=EXAMPLE_IDS)
def test_every_profile_yields_the_four_application_tiers(path):
    services = inv(load(path))
    for name in ("acp-web-api", "acp-discovery", "acp-assess", "acp-remediate"):
        assert name in services, f"{name} missing from {path.name}"


@pytest.mark.parametrize("path", EXAMPLES, ids=EXAMPLE_IDS)
def test_the_api_tier_claims_no_jobs(path):
    """ACP_WORKERS=0 on the API container is the split topology (#113, docs/worker-split.md): it
    is what stops an API deploy from restarting a running scan. Not a tuning choice."""
    assert inv(load(path))["acp-web-api"].env["ACP_WORKERS"] == "0"


@pytest.mark.parametrize("path", EXAMPLES, ids=EXAMPLE_IDS)
def test_worker_roles_are_the_values_the_application_accepts(path):
    """api/core.py raises on anything but mixed/discovery/assess/remediate/processing, and the
    spec's tier names are NOT those strings ('discover' vs 'discovery')."""
    accepted = {"mixed", "discovery", "assess", "remediate", "processing"}
    for service in inv(load(path)).values():
        if service.role:
            assert service.role in accepted, service.name


def test_worker_role_values_match_the_application_validator():
    """The role strings are read out of api/core.py rather than retyped here.

    `_worker_job_types` dispatches on ACP_WORKER_ROLE and raises on anything it does not
    recognise, so a role this inventory invents would deploy a worker that CRASHES on boot. The
    source is parsed rather than imported because importing core pulls apscheduler and the whole
    application; this check has to hold in a bare installer environment too.
    """
    import re
    from pathlib import Path

    from acpctl.inventory import TIER_ROLE

    core_src = (Path(__file__).resolve().parent.parent / "api" / "core.py").read_text()
    body = core_src[core_src.index("def _worker_job_types"):]
    body = body[:body.index("\ndef ", 1)]
    accepted = set(re.findall(r'role == "([a-z]+)"', body)) | {"mixed"}
    assert accepted >= {"discovery", "assess", "remediate"}, (
        f"parsed {accepted} from api/core.py._worker_job_types — the parse, not the roles, is "
        f"probably what broke")
    missing = set(TIER_ROLE.values()) - accepted
    assert not missing, (
        f"inventory would deploy workers with ACP_WORKER_ROLE={sorted(missing)}, which "
        f"api/core.py._worker_job_types rejects with a ValueError at boot")


@pytest.mark.parametrize("path", EXAMPLES, ids=EXAMPLE_IDS)
def test_no_worker_tier_has_ingress(path):
    """PRD S13, asserted on the artifact adapters consume rather than on the document."""
    for service in inv(load(path)).values():
        if service.role:
            assert service.ingress == "none", service.name


@pytest.mark.parametrize("path", EXAMPLES, ids=EXAMPLE_IDS)
def test_migrations_run_before_every_application_tier(path):
    services = inv(load(path))
    assert services["acp-migrations"].kind == "job"
    for name in ("acp-web-api", "acp-discovery", "acp-assess", "acp-remediate"):
        assert "acp-migrations" in services[name].depends_on, name


@pytest.mark.parametrize("path", EXAMPLES, ids=EXAMPLE_IDS)
def test_every_image_carries_the_release_version(path):
    """PRD S5.1: one release, one version across every image."""
    doc = load(path)
    for service in inv(doc).values():
        if service.image:
            assert service.image_version == doc["runtime"]["version"], service.name


@pytest.mark.parametrize("path", EXAMPLES, ids=EXAMPLE_IDS)
def test_managed_data_services_are_not_provisioned_in_cluster(path):
    doc = load(path)
    services = inv(doc)
    for key, name in (("postgres", "postgres"), ("redis", "redis"),
                      ("objectStorage", "object-storage")):
        expected = "managed" if doc["data"][key]["mode"] == "managed" else "in-cluster"
        assert services[name].provisioning == expected, name


def test_the_ollama_gateway_appears_only_when_the_ai_lane_is_on():
    doc = load_example("standard-production")
    assert "acp-ollama-gateway" in inv(doc)
    doc["ai"]["ollama"]["enabled"] = False
    assert "acp-ollama-gateway" not in inv(doc)


def test_workers_depend_on_the_ai_lane_when_it_is_on():
    services = inv(load_example("standard-production"))
    assert "acp-ollama-gateway" in services["acp-assess"].depends_on


def test_the_api_tier_does_not_carry_the_smb_credential():
    """SMB is walked by the discovery worker; the API has no reason to hold that secret."""
    services = inv(load_example("regulated"))
    assert "smb-credentials" not in services["acp-web-api"].secret_refs
    assert "smb-credentials" in services["acp-discovery"].secret_refs


@pytest.mark.parametrize("path", EXAMPLES, ids=EXAMPLE_IDS)
def test_every_declared_secret_ref_is_a_reference_not_a_value(path):
    """The inventory names secrets; it must never carry one."""
    doc = load(path)
    declared = set(doc["secrets"]["refs"])
    for service in inv(doc).values():
        for ref in service.secret_refs:
            assert ref in declared, f"{service.name} references undeclared secret {ref}"


@pytest.mark.parametrize("path", EXAMPLES, ids=EXAMPLE_IDS)
def test_worker_scratch_is_declared_and_disposable(path):
    """PRD S12/S20.5: no authoritative output may depend on ephemeral storage. The inventory
    records scratch as a volume so an adapter cannot quietly make it the only copy."""
    for service in inv(load(path)).values():
        if service.role:
            assert any(v.startswith("scratch:") for v in service.volumes), service.name


@pytest.mark.parametrize("path", EXAMPLES, ids=EXAMPLE_IDS)
def test_the_inventory_serializes_without_leaking_anything(path):
    import json

    from acpctl.inventory import inventory_as_dict
    text = json.dumps(inventory_as_dict(load(path)))
    for marker in ("password", "hunter2", "-----BEGIN", "sk-lf-"):
        assert marker not in text
