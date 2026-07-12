"""AI provider gateway config — secret-ref storage (ADR 0019 §6).

The load-bearing security property: a provider's API KEY never enters the database, a request
body, a log, or the browser. The DB stores only non-secret config + the NAME of an ops-provisioned
environment/Key-Vault secret (key_secret_ref); the adapter resolves the value from os.environ at
call time. These tests pin: (a) the store never has a key column, (b) the safe view never leaks a
value and reports key_present/credential_source honestly, (c) the route rejects a pasted key and
any stray key-like field.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import providers  # noqa: E402


# ── store roundtrip ────────────────────────────────────────────────────────────

def test_store_roundtrip_has_no_key_column(isolated_store):
    s = isolated_store
    s.upsert_ai_provider_config("azure_openai", enabled=True,
                                endpoint="https://x.openai.azure.com", deployment="gpt-4o",
                                model="gpt-4o", key_secret_ref="AZURE_OPENAI_API_KEY",
                                updated_by="admin@acp.mova.io")
    got = s.get_ai_provider_config("azure_openai")
    assert got["enabled"] is True and got["endpoint"] == "https://x.openai.azure.com"
    assert got["key_secret_ref"] == "AZURE_OPENAI_API_KEY"
    assert "key" not in got and "api_key" not in got          # only the reference, never a value
    assert [c["provider"] for c in s.list_ai_provider_configs()] == ["azure_openai"]


def test_store_upsert_updates_in_place(isolated_store):
    s = isolated_store
    s.upsert_ai_provider_config("openai", enabled=False, endpoint=None, deployment=None,
                                model="gpt-4.1", key_secret_ref=None)
    s.upsert_ai_provider_config("openai", enabled=True, endpoint=None, deployment=None,
                                model="gpt-4.1", key_secret_ref="OPENAI_API_KEY")
    rows = s.list_ai_provider_configs()
    assert len(rows) == 1 and rows[0]["enabled"] is True and rows[0]["key_secret_ref"] == "OPENAI_API_KEY"


# ── safe view + key resolver ─────────────────────────────────────────────────────

def test_provider_view_never_leaks_a_value_and_reports_presence(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "sk-super-secret")
    v = providers.provider_view({"provider": "azure_openai", "enabled": True,
                                 "endpoint": "https://x.openai.azure.com",
                                 "key_secret_ref": "AZURE_OPENAI_API_KEY"})
    assert v["key_present"] is True and v["credential_source"] == "environment_managed"
    assert "sk-super-secret" not in str(v)                     # the value is nowhere in the view
    assert v["key_secret_ref"] == "AZURE_OPENAI_API_KEY"       # only the name
    assert v["zone"] == "cloud"


def test_provider_view_unconfigured(monkeypatch):
    monkeypatch.delenv("NOPE_KEY", raising=False)
    v = providers.provider_view({"provider": "gemini", "key_secret_ref": "NOPE_KEY"})
    assert v["key_present"] is False and v["credential_source"] == "environment_managed"
    v2 = providers.provider_view({"provider": "gemini"})
    assert v2["credential_source"] == "not_configured" and v2["key_present"] is False


def test_resolve_key_reads_env(monkeypatch):
    monkeypatch.setenv("MY_KEY", "abc123")
    assert providers._resolve_key({"key_secret_ref": "MY_KEY"}) == "abc123"
    assert providers._resolve_key({"key_secret_ref": "ABSENT"}) is None
    assert providers._resolve_key({}) is None


def test_list_views_covers_all_cloud_providers(monkeypatch):
    import core
    import types
    monkeypatch.setattr(core, "store", types.SimpleNamespace(list_ai_provider_configs=lambda: []))
    views = providers.list_provider_views()
    assert {v["provider"] for v in views} == set(providers.CLOUD_PROVIDERS)
    assert all(v["credential_source"] == "not_configured" for v in views)


# ── route: rejects a pasted key + stray fields ───────────────────────────────────

def _client(monkeypatch, isolated_store):
    import core
    monkeypatch.setattr(core, "store", isolated_store)
    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app)


def test_route_accepts_ref_name_and_returns_safe_view(monkeypatch, isolated_store):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "sk-live")
    c = _client(monkeypatch, isolated_store)
    r = c.put("/ai/providers", json={"provider": "azure_openai", "enabled": True,
                                     "endpoint": "https://x.openai.azure.com",
                                     "deployment": "gpt-4o", "model": "gpt-4o",
                                     "key_secret_ref": "AZURE_OPENAI_API_KEY"})
    assert r.status_code == 200
    azure = next(p for p in r.json()["providers"] if p["provider"] == "azure_openai")
    assert azure["enabled"] is True and azure["key_present"] is True
    assert "sk-live" not in r.text                              # value never returned
    # GET is admin-gated and returns the same safe shape
    g = c.get("/ai/providers")
    assert g.status_code == 200 and "sk-live" not in g.text


def test_route_rejects_a_pasted_key_as_ref(monkeypatch, isolated_store):
    c = _client(monkeypatch, isolated_store)
    r = c.put("/ai/providers", json={"provider": "azure_openai",
                                     "key_secret_ref": "sk-ThisLooksLikeARealKey-9f8a7b"})
    assert r.status_code == 422                                 # not an env-var NAME → refused


def test_route_rejects_a_stray_key_field(monkeypatch, isolated_store):
    c = _client(monkeypatch, isolated_store)
    # extra='forbid' → a client trying to submit the value itself is rejected, not silently dropped
    r = c.put("/ai/providers", json={"provider": "azure_openai", "api_key": "sk-secret"})
    assert r.status_code == 422


def test_route_rejects_unknown_provider(monkeypatch, isolated_store):
    c = _client(monkeypatch, isolated_store)
    r = c.put("/ai/providers", json={"provider": "skynet", "enabled": True})
    assert r.status_code == 422
