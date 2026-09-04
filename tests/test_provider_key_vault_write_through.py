"""Key Vault write-through for provider keys — the one path that accepts a key VALUE.

ADR 0019 §6 kept keys out of the product entirely: an ops team provisioned an environment secret
and Settings stored its NAME. That is still what happens to the DATABASE — no key is written to
it here either — but a key value now crosses one boundary it did not before, the browser -> API
request that sets it. These tests pin the properties that make that acceptable:

  * a deployment with no vault REFUSES rather than storing the value somewhere else;
  * the vault secret's name is derived, never supplied by the caller;
  * no read path returns the value: not the safe view, not the audit row, not the config row;
  * the env-var path is untouched, so existing deployments behave exactly as before.

The Azure client itself is NOT exercised — there is no vault in CI. Every test drives a fake
through the same Protocol, and `AzureKeyVaultSecretStore` says so in its own docstring. A green
run here is evidence about this product's handling of the value, not about the SDK call.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import providers      # noqa: E402
import secret_store   # noqa: E402

KEY = "sk-live-DO-NOT-STORE-ME"


class FakeVault:
    """A writable store, in memory. Counts reads so the cache is testable."""
    kind = "azure_key_vault"

    def __init__(self, *, ok: bool = True, reason: str = "", raises: Exception | None = None):
        self.secrets: dict[str, str] = {}
        self.reads = 0
        self._ok, self._reason, self._raises = ok, reason, raises

    def writable(self):
        return self._ok, self._reason

    def write(self, name, value):
        if self._raises:
            raise self._raises
        self.secrets[name] = value

    def read(self, name):
        self.reads += 1
        return self.secrets.get(name)


@pytest.fixture(autouse=True)
def _clean_cache():
    secret_store.clear_cache()
    yield
    secret_store.clear_cache()


# ── the reference name ───────────────────────────────────────────────────────────────────────

def test_the_vault_name_is_derived_from_the_provider_not_supplied():
    assert secret_store.ref_for("anthropic") == "keyvault:acp-ai-anthropic-key"
    assert secret_store.ref_for("azure_openai") == "keyvault:acp-ai-azure-openai-key"
    assert secret_store.is_vault_ref(secret_store.ref_for("openai"))
    assert not secret_store.is_vault_ref("OPENAI_API_KEY")


def test_a_vault_name_uses_the_vaults_charset_not_the_env_vars():
    """Key Vault allows [A-Za-z0-9-] and rejects underscores; env-var names require them. A name
    generated in the wrong charset fails at write time with a half-configured row behind it."""
    name = secret_store.vault_name(secret_store.ref_for("azure_openai"))
    assert "_" not in name
    assert secret_store.VAULT_NAME_RE.match(name)


# ── the refusal ──────────────────────────────────────────────────────────────────────────────

def test_a_deployment_with_no_vault_refuses_to_take_a_key(monkeypatch):
    """The refusal IS the feature: it keeps 'we could not do this safely' from becoming 'we did
    it unsafely'."""
    monkeypatch.delenv("ACP_KEY_VAULT_URL", raising=False)
    store = secret_store.active_secret_store()
    ok, reason = store.writable()
    assert not ok and "ACP_KEY_VAULT_URL" in reason
    with pytest.raises(RuntimeError) as e:
        secret_store.write_provider_secret("anthropic", KEY)
    assert "ACP_KEY_VAULT_URL" in str(e.value)


def test_a_non_https_vault_url_is_not_a_vault(monkeypatch):
    monkeypatch.setenv("ACP_KEY_VAULT_URL", "http://vault.internal")
    ok, reason = secret_store.active_secret_store().writable()
    assert not ok and "https" in reason


def test_an_empty_value_is_rejected_before_the_vault_is_touched(monkeypatch):
    fake = FakeVault()
    monkeypatch.setattr(secret_store, "active_secret_store", lambda: fake)
    with pytest.raises(ValueError):
        secret_store.write_provider_secret("anthropic", "   ")
    assert fake.secrets == {}


# ── write, then read ─────────────────────────────────────────────────────────────────────────

def test_write_then_resolve_round_trips_without_returning_the_value(monkeypatch):
    fake = FakeVault()
    monkeypatch.setattr(secret_store, "active_secret_store", lambda: fake)
    ref = secret_store.write_provider_secret("anthropic", KEY)
    assert ref == "keyvault:acp-ai-anthropic-key"
    assert KEY not in ref
    assert fake.secrets["acp-ai-anthropic-key"] == KEY
    assert secret_store.read_ref(ref) == KEY


def test_reads_are_cached_so_the_ai_path_is_not_a_vault_round_trip_per_call(monkeypatch):
    fake = FakeVault()
    fake.secrets["acp-ai-openai-key"] = KEY
    monkeypatch.setattr(secret_store, "active_secret_store", lambda: fake)
    ref = "keyvault:acp-ai-openai-key"
    assert secret_store.read_ref(ref) == KEY
    assert secret_store.read_ref(ref) == KEY
    assert fake.reads == 1, "the second read must come from the cache"
    secret_store.clear_cache()
    assert secret_store.read_ref(ref) == KEY and fake.reads == 2


def test_a_write_invalidates_the_cache_so_a_rotated_key_takes_effect(monkeypatch):
    fake = FakeVault()
    monkeypatch.setattr(secret_store, "active_secret_store", lambda: fake)
    ref = secret_store.write_provider_secret("openai", "old-key")
    assert secret_store.read_ref(ref) == "old-key"
    secret_store.write_provider_secret("openai", "new-key")
    assert secret_store.read_ref(ref) == "new-key"


# ── the resolution path in providers.py ──────────────────────────────────────────────────────

def test_env_refs_still_resolve_from_the_environment(monkeypatch):
    """The pre-existing path, unchanged — this is what every current deployment uses."""
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    assert providers._resolve_key({"key_secret_ref": "OPENAI_API_KEY"}) == "from-env"
    assert providers.credential_source_for("OPENAI_API_KEY") == "environment_managed"
    assert providers.credential_source_for(None) == "not_configured"


def test_vault_refs_resolve_through_the_secret_store(monkeypatch):
    fake = FakeVault()
    fake.secrets["acp-ai-anthropic-key"] = KEY
    monkeypatch.setattr(secret_store, "active_secret_store", lambda: fake)
    cfg = {"key_secret_ref": "keyvault:acp-ai-anthropic-key"}
    assert providers._resolve_key(cfg) == KEY
    assert providers.credential_source_for(cfg["key_secret_ref"]) == "key_vault"


def test_the_safe_view_reports_a_vault_key_as_present_and_never_carries_it(monkeypatch):
    """Before this, a key written to the vault read as absent and the provider looked broken on
    the very page an admin uses to check it."""
    fake = FakeVault()
    fake.secrets["acp-ai-anthropic-key"] = KEY
    monkeypatch.setattr(secret_store, "active_secret_store", lambda: fake)
    view = providers.provider_view({"provider": "anthropic", "enabled": True,
                                    "key_secret_ref": "keyvault:acp-ai-anthropic-key"})
    assert view["key_present"] is True
    assert view["credential_source"] == "key_vault"
    assert KEY not in repr(view)


def test_credential_for_reports_the_ref_not_the_value(monkeypatch):
    fake = FakeVault()
    fake.secrets["acp-ai-anthropic-key"] = KEY
    monkeypatch.setattr(secret_store, "active_secret_store", lambda: fake)
    monkeypatch.setattr(providers, "_config_for",
                        lambda p: {"provider": p, "key_secret_ref": "keyvault:acp-ai-anthropic-key"})
    key, source = providers.credential_for("anthropic")
    assert key == KEY
    assert source == "keyvault:acp-ai-anthropic-key" and KEY not in source


# ── the route ────────────────────────────────────────────────────────────────────────────────

def _client(monkeypatch, isolated_store):
    import core
    monkeypatch.setattr(core, "store", isolated_store)
    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app)


def test_the_route_refuses_when_the_deployment_has_no_vault(monkeypatch, isolated_store):
    monkeypatch.delenv("ACP_KEY_VAULT_URL", raising=False)
    c = _client(monkeypatch, isolated_store)
    r = c.post("/ai/providers/anthropic/secret", json={"value": KEY})
    assert r.status_code == 422
    assert isolated_store.get_ai_provider_config("anthropic") in (None, {})
    assert KEY not in r.text


def test_the_route_stores_the_reference_and_never_the_value(monkeypatch, isolated_store):
    fake = FakeVault()
    monkeypatch.setattr(secret_store, "active_secret_store", lambda: fake)
    c = _client(monkeypatch, isolated_store)
    r = c.post("/ai/providers/anthropic/secret", json={"value": KEY})
    assert r.status_code == 200, r.text
    assert KEY not in r.text, "no read path may return the value"

    row = isolated_store.get_ai_provider_config("anthropic")
    assert row["key_secret_ref"] == "keyvault:acp-ai-anthropic-key"
    assert KEY not in repr(row)
    assert fake.secrets["acp-ai-anthropic-key"] == KEY, "the value goes to the vault, only there"


def test_the_audit_row_names_the_reference_and_never_the_value(monkeypatch, isolated_store):
    fake = FakeVault()
    monkeypatch.setattr(secret_store, "active_secret_store", lambda: fake)
    c = _client(monkeypatch, isolated_store)
    c.post("/ai/providers/anthropic/secret", json={"value": KEY})
    rows = isolated_store.list_decisions(limit=50)
    assert any("key_secret_ref=keyvault:acp-ai-anthropic-key" in (d.get("detail") or "")
               for d in rows)
    assert not any(KEY in (d.get("detail") or "") for d in rows)


def test_an_unknown_provider_is_refused_before_anything_is_written(monkeypatch, isolated_store):
    fake = FakeVault()
    monkeypatch.setattr(secret_store, "active_secret_store", lambda: fake)
    c = _client(monkeypatch, isolated_store)
    r = c.post("/ai/providers/not-a-provider/secret", json={"value": KEY})
    assert r.status_code == 422 and fake.secrets == {}


def test_a_vault_that_rejects_the_write_is_reported_not_swallowed(monkeypatch, isolated_store):
    fake = FakeVault(raises=PermissionError("secrets/set denied"))
    monkeypatch.setattr(secret_store, "active_secret_store", lambda: fake)
    c = _client(monkeypatch, isolated_store)
    r = c.post("/ai/providers/anthropic/secret", json={"value": KEY})
    assert r.status_code == 502
    assert "PermissionError" in r.text and KEY not in r.text
    assert isolated_store.get_ai_provider_config("anthropic") in (None, {})


def test_the_get_route_advertises_whether_a_key_can_be_pasted(monkeypatch, isolated_store):
    """The UI must not render an input that cannot work — without this the only way to discover
    an unconfigured vault is to type a live credential into a box and have it rejected."""
    monkeypatch.delenv("ACP_KEY_VAULT_URL", raising=False)
    c = _client(monkeypatch, isolated_store)
    body = c.get("/ai/providers").json()
    assert body["secret_write"]["available"] is False
    assert "ACP_KEY_VAULT_URL" in body["secret_write"]["reason"]
