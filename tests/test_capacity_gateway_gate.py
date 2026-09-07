from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))


@pytest.mark.parametrize(
    "enabled,target,apps,subscription",
    [
        ("0", "staging", ("acp-assess-staging",), "sub"),
        ("1", "production", ("acp-assess-staging",), "sub"),
        ("1", "staging", ("acp-assess",), "sub"),
        ("1", "staging", ("acp-assess-staging", "acp-remediate"), "sub"),
        ("1", "staging", (), "sub"),
        ("1", "staging", ("acp-assess-staging",), None),
        ("1", "production", ("acp-assess",), "sub"),
        ("1", "production", ("acp-discovery", "acp-assess", "other"), "sub"),
        ("1", "development", ("acp-discovery", "acp-assess", "acp-remediate"), "sub"),
    ],
)
def test_capacity_gateway_gate_fails_closed(monkeypatch, enabled, target, apps, subscription):
    from routes import control

    monkeypatch.setenv("ACP_CAPACITY_APPLY_ENABLED", enabled)
    monkeypatch.setenv("ACP_DEPLOY_ENV", target)
    monkeypatch.setattr(control, "_AZ_SUB", subscription)
    monkeypatch.setattr(control, "_CAPACITY_APP_NAMES", ())
    monkeypatch.setattr(control, "_configured_apps", lambda: apps)
    assert control._capacity_gateway_for_environment() is None


def test_capacity_gateway_gate_constructs_only_for_all_staging_apps(monkeypatch):
    import azure_capacity_gateway
    from routes import control

    marker = object()
    calls = []
    monkeypatch.setenv("ACP_CAPACITY_APPLY_ENABLED", "1")
    monkeypatch.setenv("ACP_DEPLOY_ENV", "STAGING")
    monkeypatch.setattr(control, "_AZ_SUB", "subscription")
    monkeypatch.setattr(control, "_AZ_RG", "resource-group")
    monkeypatch.setattr(control, "_CAPACITY_APP_NAMES", ())
    monkeypatch.setattr(control, "_configured_apps",
                        lambda: ("acp-assess-staging", "acp-remediate-staging"))
    monkeypatch.setattr(
        azure_capacity_gateway, "default_gateway",
        lambda subscription, group, **kwargs: calls.append((subscription, group, kwargs)) or marker)
    assert control._capacity_gateway_for_environment() is marker
    assert calls == [("subscription", "resource-group",
                      {"allowed_apps": ("acp-assess-staging", "acp-remediate-staging")})]


def test_capacity_gateway_gate_constructs_for_exact_production_fleet(monkeypatch):
    import azure_capacity_gateway
    from routes import control

    marker = object()
    calls = []
    apps = ("acp-app", "acp-discovery", "acp-assess", "acp-remediate", "acp-ollama")
    monkeypatch.setenv("ACP_CAPACITY_APPLY_ENABLED", "1")
    monkeypatch.setenv("ACP_DEPLOY_ENV", "production")
    monkeypatch.setattr(control, "_AZ_SUB", "subscription")
    monkeypatch.setattr(control, "_AZ_RG", "resource-group")
    monkeypatch.setattr(control, "_CAPACITY_APP_NAMES", apps)
    monkeypatch.setattr(
        azure_capacity_gateway, "default_gateway",
        lambda subscription, group, **kwargs: calls.append((subscription, group, kwargs)) or marker)

    assert control._capacity_gateway_for_environment() is marker
    assert calls == [("subscription", "resource-group", {"allowed_apps": apps})]
