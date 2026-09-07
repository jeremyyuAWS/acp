from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import azure_capacity_gateway as gateway_mod  # noqa: E402
from capacity_policy import AppPolicy, ScaleRule  # noqa: E402


class Model:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


MODELS = SimpleNamespace(ContainerApp=Model, Template=Model, Scale=Model, ScaleRule=Model,
                         CustomScaleRule=Model, ScaleRuleAuth=Model)


class Poller:
    def __init__(self):
        self.waited = False

    def result(self):
        self.waited = True


class Operations:
    def __init__(self, app, etag='"revision-1"'):
        self.app = app
        self.etag = etag
        self.gets = []
        self.updates = []
        self.poller = Poller()

    def get(self, resource_group, app, **kwargs):
        self.gets.append((resource_group, app))
        response = SimpleNamespace(http_response=SimpleNamespace(headers={"ETag": self.etag}))
        return kwargs["cls"](response, self.app, {})

    def begin_update(self, *args, **kwargs):
        self.updates.append((args, kwargs))
        return self.poller


def app_model(*, location="westus2"):
    custom = Model(type="postgresql", metadata={"query": "SELECT 1"})
    scale = Model(min_replicas=1, max_replicas=10,
                  rules=[Model(name="assess-queue", custom=custom, azure_queue=None,
                               http=None, tcp=None)])
    return Model(location=location, properties=Model(template=Model(scale=scale)))


def policy():
    return AppPolicy(
        app="acp-assess-staging", service="assess", min_replicas=1, max_replicas=10,
        rules=(
            ScaleRule("business-hours", "cron", {"timezone": "America/Los_Angeles",
                                                   "start": "0 6 * * 1,2,3,4,5",
                                                   "end": "0 20 * * 1,2,3,4,5",
                                                   "desiredReplicas": "4"}),
            ScaleRule("assess-queue", "postgresql",
                      {"query": "SELECT 1", "targetQueryValue": "8"},
                      {"connection": "database-url"}),
        ),
    )


def test_read_captures_snapshot_and_normalizes_custom_rules():
    operations = Operations(app_model())
    gateway = gateway_mod.AzureCapacityGateway(
        SimpleNamespace(container_apps=operations), "rg", allowed_apps=("acp-assess-staging",))
    assert gateway.read_scale("acp-assess-staging") == {
        "min_replicas": 1, "max_replicas": 10,
        "rules": [{"name": "assess-queue", "type": "postgresql",
                   "metadata": {"query": "SELECT 1"}}],
    }


def test_apply_builds_complete_custom_scale_patch_with_if_match(monkeypatch):
    monkeypatch.setattr(gateway_mod, "_sdk_models", lambda: MODELS)
    operations = Operations(app_model())
    gateway = gateway_mod.AzureCapacityGateway(
        SimpleNamespace(container_apps=operations), "rg", allowed_apps=("acp-assess-staging",))
    gateway.read_scale("acp-assess-staging")
    gateway.apply_scale(policy())

    args, kwargs = operations.updates[0]
    assert args[:2] == ("rg", "acp-assess-staging")
    envelope = args[2]
    assert envelope.location == "westus2"
    assert envelope.template.scale.min_replicas == 1
    assert envelope.template.scale.max_replicas == 10
    assert [r.name for r in envelope.template.scale.rules] == ["business-hours", "assess-queue"]
    queue = envelope.template.scale.rules[1].custom
    assert queue.type == "postgresql"
    assert queue.auth[0].trigger_parameter == "connection"
    assert queue.auth[0].secret_ref == "database-url"
    assert kwargs == {"headers": {"If-Match": '"revision-1"'}}
    assert operations.poller.waited is True


@pytest.mark.parametrize("location,etag", [(None, '"revision-1"'), ("westus2", None)])
def test_apply_fails_closed_without_complete_snapshot(monkeypatch, location, etag):
    monkeypatch.setattr(gateway_mod, "_sdk_models", lambda: MODELS)
    operations = Operations(app_model(location=location), etag=etag)
    gateway = gateway_mod.AzureCapacityGateway(
        SimpleNamespace(container_apps=operations), "rg", allowed_apps=("acp-assess-staging",))
    gateway.read_scale("acp-assess-staging")
    with pytest.raises(RuntimeError, match="snapshot"):
        gateway.apply_scale(policy())
    assert operations.updates == []


def test_apply_requires_read_first(monkeypatch):
    monkeypatch.setattr(gateway_mod, "_sdk_models", lambda: MODELS)
    operations = Operations(app_model())
    gateway = gateway_mod.AzureCapacityGateway(
        SimpleNamespace(container_apps=operations), "rg", allowed_apps=("acp-assess-staging",))
    with pytest.raises(RuntimeError, match="snapshot"):
        gateway.apply_scale(policy())
    assert operations.updates == []


def test_gateway_refuses_an_app_outside_its_configured_fleet():
    operations = Operations(app_model())
    gateway = gateway_mod.AzureCapacityGateway(
        SimpleNamespace(container_apps=operations), "rg",
        allowed_apps=("acp-assess-staging",))
    with pytest.raises(RuntimeError, match="outside"):
        gateway.read_scale("unrelated-production-app")


def test_empty_allowlist_refuses_every_app():
    operations = Operations(app_model())
    gateway = gateway_mod.AzureCapacityGateway(
        SimpleNamespace(container_apps=operations), "rg", allowed_apps=())
    with pytest.raises(RuntimeError, match="outside"):
        gateway.read_scale("acp-assess")
    assert operations.gets == []


def test_logical_app_maps_only_to_its_exact_allowed_staging_name(monkeypatch):
    monkeypatch.setattr(gateway_mod, "_sdk_models", lambda: MODELS)
    operations = Operations(app_model())
    gateway = gateway_mod.AzureCapacityGateway(
        SimpleNamespace(container_apps=operations), "rg",
        allowed_apps=("acp-assess-staging",))

    # The policy and comparison layer continues to use the logical production-neutral name.
    wanted = policy()
    wanted = AppPolicy(app="acp-assess", service=wanted.service,
                       min_replicas=wanted.min_replicas, max_replicas=wanted.max_replicas,
                       rules=wanted.rules)
    observed = gateway.read_scale(wanted.app)
    assert observed["min_replicas"] == 1
    gateway.apply_scale(wanted)

    assert operations.gets == [("rg", "acp-assess-staging")]
    assert operations.updates[0][0][1] == "acp-assess-staging"


def test_suffix_mapping_does_not_select_a_similar_staging_app():
    operations = Operations(app_model())
    gateway = gateway_mod.AzureCapacityGateway(
        SimpleNamespace(container_apps=operations), "rg",
        allowed_apps=("acp-assess-v2-staging",))
    with pytest.raises(RuntimeError, match="outside"):
        gateway.read_scale("acp-assess")


def test_sdk_imports_are_lazy():
    source = (ROOT / "api" / "azure_capacity_gateway.py").read_text()
    assert "\nfrom azure." not in source
