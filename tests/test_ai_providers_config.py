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


# ── activation: enable only what can actually run ─────────────────────────────────────────────
# Until these guards, PUT stored enabled=true whatever else was blank. `_adapter_for` then
# returned None at call time and every document silently stayed on the local path, while the
# Settings page reported the provider as on. Verified by running it, not by reading: a config
# with no model and no key_secret_ref stored as enabled=True and built no adapter.

def test_route_refuses_to_enable_an_incomplete_provider(monkeypatch, isolated_store):
    c = _client(monkeypatch, isolated_store)
    r = c.put("/ai/providers", json={"provider": "anthropic", "enabled": True})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["provider"] == "anthropic"
    assert "model" in detail["missing"] and "key_secret_ref" in detail["missing"]
    # And it did not store the half-state it refused.
    assert isolated_store.get_ai_provider_config("anthropic") is None


def test_route_refuses_to_enable_when_the_referenced_secret_is_absent(monkeypatch, isolated_store):
    """The other half of 'not ready', and a different person's job: every field is filled, and the
    key VALUE that ops provisions outside this app is not there. Saying which of the two is
    missing is the difference between an admin fixing it and an admin filing a ticket."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    c = _client(monkeypatch, isolated_store)
    r = c.put("/ai/providers", json={"provider": "anthropic", "enabled": True,
                                     "model": "claude-sonnet-5",
                                     "key_secret_ref": "ANTHROPIC_API_KEY"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["missing"] == []                    # nothing left for the ADMIN to type
    assert detail["secret_resolves"] is False
    assert "ANTHROPIC_API_KEY is not present" in detail["detail"]


def test_a_complete_config_enables_in_one_save(monkeypatch, isolated_store):
    """The fields and the switch arrive together in a single save, so the guard has to validate
    the config being WRITTEN. Checking the stored row instead would refuse the first correct save
    and accept nothing after it."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-value")
    c = _client(monkeypatch, isolated_store)
    r = c.put("/ai/providers", json={"provider": "openai", "enabled": True, "model": "gpt-4o",
                                     "key_secret_ref": "OPENAI_API_KEY"})
    assert r.status_code == 200, r.text
    row = next(p for p in r.json()["providers"] if p["provider"] == "openai")
    assert row["enabled"] is True and row["key_present"] is True
    assert row["credential_source"] == "environment_managed"
    assert "sk-live-value" not in r.text


def test_saving_config_without_enabling_is_always_allowed(monkeypatch, isolated_store):
    """An admin fills the endpoint today and waits for ops to provision the key. Refusing that
    save would make the two-person workflow impossible; only ENABLING is gated."""
    c = _client(monkeypatch, isolated_store)
    r = c.put("/ai/providers", json={"provider": "anthropic", "enabled": False,
                                     "model": "claude-sonnet-5"})
    assert r.status_code == 200
    assert isolated_store.get_ai_provider_config("anthropic")["model"] == "claude-sonnet-5"


def test_an_enabled_provider_can_still_be_disabled_after_its_secret_disappears(monkeypatch,
                                                                              isolated_store):
    """A rotated-away key must not trap the switch in the on position — turning something OFF is
    always safe, so the guard applies to enabling only."""
    monkeypatch.delenv("K", raising=False)
    isolated_store.upsert_ai_provider_config("openai", enabled=True, endpoint=None,
                                             deployment=None, model="gpt-4o",
                                             key_secret_ref="K", updated_by="admin")
    c = _client(monkeypatch, isolated_store)
    r = c.put("/ai/providers", json={"provider": "openai", "enabled": False})
    assert r.status_code == 200
    assert isolated_store.get_ai_provider_config("openai")["enabled"] is False


# ── the connection test route ─────────────────────────────────────────────────────────────────

def test_test_route_rejects_a_stray_key_field(monkeypatch, isolated_store):
    c = _client(monkeypatch, isolated_store)
    r = c.post("/ai/providers/test", json={"provider": "openai", "api_key": "sk-secret"})
    assert r.status_code == 422                       # extra='forbid' — no field can carry a key


def test_test_route_rejects_an_unknown_provider(monkeypatch, isolated_store):
    c = _client(monkeypatch, isolated_store)
    assert c.post("/ai/providers/test", json={"provider": "skynet"}).status_code == 422


def test_test_route_reports_what_is_missing_without_calling_out(monkeypatch, isolated_store):
    import httpx
    c = _client(monkeypatch, isolated_store)

    def _never(*a, **k):
        raise AssertionError("an unconfigured provider must not be called")
    monkeypatch.setattr(httpx, "post", _never)
    r = c.post("/ai/providers/test", json={"provider": "anthropic"})
    assert r.status_code == 200
    assert r.json()["ok"] is False and r.json()["reason"] == "not_configured"


def test_test_route_sends_the_synthetic_probe_and_returns_no_secret(monkeypatch, isolated_store):
    import base64
    import httpx
    import providers as _providers
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-secret-value")
    isolated_store.upsert_ai_provider_config("openai", enabled=False, endpoint=None,
                                             deployment=None, model="gpt-4o",
                                             key_secret_ref="OPENAI_API_KEY", updated_by="admin")
    c = _client(monkeypatch, isolated_store)
    sent = {}

    class _R:
        status_code = 200
        text = "{}"

        def json(self):
            return {"choices": [{"message": {"content": "A black square."},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 900, "completion_tokens": 12}}

        def raise_for_status(self):
            pass

    def _post(url, **kw):
        sent.update(json=kw.get("json"), headers=kw.get("headers"))
        return _R()
    monkeypatch.setattr(httpx, "post", _post)

    r = c.post("/ai/providers/test", json={"provider": "openai"})
    assert r.status_code == 200 and r.json()["ok"] is True

    # What actually went to the third party is the synthetic probe, byte for byte.
    url = sent["json"]["messages"][0]["content"][1]["image_url"]["url"]
    assert base64.b64decode(url.split(",", 1)[1]) == _providers.probe_image_bytes()

    # The key rode in the request header and appears NOWHERE in the response.
    assert sent["headers"]["Authorization"] == "Bearer sk-live-secret-value"
    assert "sk-live-secret-value" not in r.text
    # Nor does the model's caption of the probe — a test action returns an outcome, not output.
    assert "A black square." not in r.text
    assert r.json()["prompt_tokens"] == 900 and r.json()["completion_tokens"] == 12


def test_test_route_is_audited_without_the_credential(monkeypatch, isolated_store):
    """This is the one control on the Settings page that can make an outbound call to a third
    party, so who pressed it and what came back belongs in the record — the outcome, never a key."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-secret-value")
    isolated_store.upsert_ai_provider_config("openai", enabled=False, endpoint=None,
                                             deployment=None, model="gpt-4o",
                                             key_secret_ref="OPENAI_API_KEY", updated_by="admin")
    c = _client(monkeypatch, isolated_store)
    import httpx

    def _boom(*a, **k):
        raise Exception("ConnectError: refused")
    monkeypatch.setattr(httpx, "post", _boom)
    c.post("/ai/providers/test", json={"provider": "openai"})

    rows = [d for d in isolated_store.list_decisions()
            if d["action"] == "settings.ai_provider.openai.test"]
    assert len(rows) == 1
    assert "no customer document sent" in rows[0]["detail"]
    assert "sk-live-secret-value" not in rows[0]["detail"]
