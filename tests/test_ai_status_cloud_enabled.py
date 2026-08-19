"""GET /ai/status exposes a NON-admin 'is a governed cloud provider enabled?' signal (ADR 0019).

Gap 2 deferred from #367: the review card's empty-state honesty message must know, WITHOUT admin
rights, whether a cloud vision provider is a configured fallback — but the provider config is
admin-only. So the non-admin status endpoint reports a SAFE derivative: `cloud_enabled` is true
only when a provider is both admin-enabled AND its ops-provisioned secret is present, with a
display-safe `cloud_provider` name and `cloud_zone`. It must NEVER leak the key, the
key_secret_ref value, or the endpoint — a boolean + safe display name/zone only.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import core  # noqa: E402
import providers  # noqa: E402


@pytest.fixture()
def client(monkeypatch, isolated_store):
    from fastapi.testclient import TestClient

    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", "", raising=False)
    return TestClient(app)


def test_out_of_box_reports_no_cloud(client):
    """No provider configured → the keyless local build: cloud_enabled false, no name/zone."""
    s = client.get("/ai/status").json()
    assert s["cloud_enabled"] is False
    assert s["cloud_provider"] is None and s["cloud_zone"] is None


def test_enabled_but_keyless_is_not_a_fallback(client, isolated_store, monkeypatch):
    """Admin-enabled but the ops secret is absent → escalation can't fire, so cloud_enabled false."""
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    isolated_store.upsert_ai_provider_config(
        "azure_openai", enabled=True, endpoint="https://acme.openai.azure.com",
        deployment="gpt-4o", model="gpt-4o", key_secret_ref="AZURE_OPENAI_API_KEY")
    s = client.get("/ai/status").json()
    assert s["cloud_enabled"] is False


def test_configured_but_disabled_is_not_a_fallback(client, isolated_store, monkeypatch):
    """Key present but the admin left it disabled → not a fallback."""
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "sk-live-value")
    isolated_store.upsert_ai_provider_config(
        "azure_openai", enabled=False, endpoint="https://acme.openai.azure.com",
        deployment="gpt-4o", model="gpt-4o", key_secret_ref="AZURE_OPENAI_API_KEY")
    s = client.get("/ai/status").json()
    assert s["cloud_enabled"] is False


def test_enabled_and_key_present_reports_true_with_safe_display(client, isolated_store, monkeypatch):
    """Enabled AND key-present → cloud_enabled true, with a display-safe provider name + zone."""
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "sk-live-super-secret")
    isolated_store.upsert_ai_provider_config(
        "azure_openai", enabled=True, endpoint="https://acme.openai.azure.com",
        deployment="gpt-4o", model="gpt-4o", key_secret_ref="AZURE_OPENAI_API_KEY")
    r = client.get("/ai/status")
    s = r.json()
    assert s["cloud_enabled"] is True
    assert s["cloud_provider"] == "azure_openai"
    assert s["cloud_zone"] in ("cloud", "tenant", "local")
    # The load-bearing security property: no secret in the response, in any form.
    assert "sk-live-super-secret" not in r.text
    assert "AZURE_OPENAI_API_KEY" not in r.text          # not even the ref NAME
    assert "acme.openai.azure.com" not in r.text          # not the endpoint


def test_cloud_status_helper_never_carries_a_secret(monkeypatch):
    """Unit-level guard on the helper the route calls: view is secret-free by construction."""
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "sk-secret-xyz")
    import types
    monkeypatch.setattr(core, "store", types.SimpleNamespace(
        list_ai_provider_configs=lambda: [{
            "provider": "azure_openai", "enabled": True,
            "endpoint": "https://acme.openai.azure.com", "deployment": "gpt-4o",
            "model": "gpt-4o", "key_secret_ref": "AZURE_OPENAI_API_KEY"}]))
    st = providers.cloud_status()
    assert st == {"enabled": True, "provider": "azure_openai", "zone": "cloud"}
    assert "sk-secret-xyz" not in str(st) and "AZURE_OPENAI_API_KEY" not in str(st)
