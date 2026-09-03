"""The governed activation path for the OpenAI and Anthropic vision providers (ADR 0019).

WHAT WAS ACTUALLY MISSING, because it was not the adapters. OpenAIVisionProvider and
AnthropicVisionProvider have shipped complete in providers.py — token usage, real cost from the
returned usage, the three-way failure classification, key in the request header only — and both
are wired into _adapter_for, cloud_vision_provider() and active_vision_provider(). Two things
stood between them and a customer:

  1. Settings.jsx gated the enable switch on ADAPTER_READY = {'azure_openai'}, so an admin could
     not turn either on. (frontend/src/aiProviders.test.js now derives that set from this
     module's own _REQUIRED_FIELDS, so the gate cannot fall behind an adapter again.)

  2. Enabling was UNCONDITIONAL. Established by running it rather than by reading: a config with
     no model and no key_secret_ref stored as enabled=True, built no adapter, and reported
     credential_source='not_configured'. The Settings page said the provider was on; every
     document silently stayed local. An enable switch that does nothing is worse than one that
     refuses, because it reads as consent having been honoured.

These tests cover the activation path end to end: configuration validation, secret-reference
resolution, the local-first fallback, failure handling, provenance, token usage and cost, the
connection test that sends no customer document, and the escalation that returns to human review
when it fails.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import providers  # noqa: E402


class _Resp:
    """A stand-in httpx response. `raise_for_status` mirrors httpx's own contract closely enough
    for _classify: the exception carries the response, which is how an HTTP status is told apart
    from a transport throw."""

    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload) if isinstance(payload, dict) else str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            err = Exception(f"HTTP {self.status_code}")
            err.response = self
            raise err


def _openai_ok(prompt_tokens=1200, completion_tokens=40, text="A black square on a white field."):
    return _Resp({"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                  "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}})


def _anthropic_ok(input_tokens=1200, output_tokens=40, text="A black square on a white field."):
    return _Resp({"content": [{"type": "text", "text": text}], "stop_reason": "end_turn",
                  "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens}})


# ── 1. configuration validation ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("provider,cfg,expect_missing", [
    ("openai", {}, ["model", "key_secret_ref"]),
    ("openai", {"model": "gpt-4o"}, ["key_secret_ref"]),
    ("anthropic", {}, ["model", "key_secret_ref"]),
    ("anthropic", {"key_secret_ref": "ANTHROPIC_API_KEY"}, ["model"]),
    ("azure_openai", {"key_secret_ref": "AZ"}, ["endpoint", "deployment"]),
    ("huggingface", {}, ["endpoint", "model", "key_secret_ref"]),
    ("huggingface", {"endpoint": "https://ep.hf.co", "model": "m"}, ["key_secret_ref"]),
    ("huggingface", {"endpoint": "https://ep.hf.co", "key_secret_ref": "HF_TOKEN"}, ["model"]),
])
def test_readiness_names_every_missing_field(provider, cfg, expect_missing):
    r = providers.activation_readiness(provider, cfg)
    assert r["ready"] is False
    assert r["missing"] == expect_missing
    assert r["detail"].startswith("missing ")


def test_a_provider_with_no_adapter_is_never_ready():
    """gemini and bedrock are in the catalogue so Settings can show them, with no adapter behind
    them. Reporting them ready would arm an escalation that cannot fire."""
    for name in ("gemini", "bedrock"):
        r = providers.activation_readiness(name, {"model": "x", "key_secret_ref": "K"})
        assert r["ready"] is False
        assert "no adapter" in r["detail"]


def test_the_required_fields_table_and_the_adapter_factory_agree(monkeypatch):
    """THE ANTI-DRIFT GUARD, and the reason _REQUIRED_FIELDS is a table rather than prose.

    Two places know what a provider needs: _adapter_for (which builds one, returning None when it
    cannot) and activation_readiness (which explains why not). If they disagree, the product gets
    one of two silent failures — a provider that enables and never runs, or one that runs and
    cannot be enabled. Neither raises. So: for every provider in the catalogue, with the secret
    present, readiness must say 'ready' exactly when the factory can build.
    """
    monkeypatch.setenv("K", "sk-test-value")
    full = {"endpoint": "https://x.openai.azure.com", "deployment": "gpt-4o",
            "model": "gpt-4o", "key_secret_ref": "K"}
    for name in providers.CLOUD_PROVIDERS:
        for cfg in (full, {**full, "model": ""}, {**full, "endpoint": ""},
                    {**full, "deployment": ""}, {**full, "key_secret_ref": ""}):
            ready = providers.activation_readiness(name, cfg)["ready"]
            built = providers._adapter_for(name, cfg) is not None
            assert ready == built, (
                f"{name} with {cfg}: readiness says ready={ready} but the factory "
                f"{'built' if built else 'could not build'} an adapter")


# ── 2. secret-reference resolution ────────────────────────────────────────────────────────────

def test_a_complete_config_whose_secret_is_absent_is_not_ready(monkeypatch):
    """The two halves of 'not ready' need two different people, so they are reported apart. Every
    field filled and the named environment secret missing is ops's job, not the admin's."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = providers.activation_readiness(
        "anthropic", {"model": "claude-sonnet-5", "key_secret_ref": "ANTHROPIC_API_KEY"})
    assert r["ready"] is False
    assert r["missing"] == []                      # nothing for the ADMIN to fill in
    assert r["secret_resolves"] is False
    assert "ANTHROPIC_API_KEY is not present" in r["detail"]


def test_the_same_config_is_ready_once_ops_provisions_the_secret(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    r = providers.activation_readiness(
        "anthropic", {"model": "claude-sonnet-5", "key_secret_ref": "ANTHROPIC_API_KEY"})
    assert r["ready"] is True and r["secret_resolves"] is True


def test_readiness_never_returns_the_secret_value(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-value")
    r = providers.activation_readiness("openai", {"model": "gpt-4o", "key_secret_ref": "OPENAI_API_KEY"})
    assert "sk-super-secret-value" not in json.dumps(r)


# ── 3. the connection test — no customer document, no secret ──────────────────────────────────

def test_the_probe_image_is_synthetic_and_deterministic():
    """It must be generated here, not read from a corpus or a scan: the whole safety claim of
    'Test connection' is that pressing it cannot send customer content anywhere."""
    a, b = providers.probe_image_bytes(), providers.probe_image_bytes()
    assert a == b                                        # deterministic
    assert a.startswith(b"\x89PNG\r\n\x1a\n")            # a real PNG, so a vision API accepts it
    assert len(a) < 4096                                 # tiny; nothing could be hidden in it


def test_the_probe_image_is_not_a_single_pixel():
    """A 1x1 image is a legitimate reason for a model to answer with nothing, and an empty answer
    is the one outcome this test has to be able to call a failure. Read the PNG header rather than
    trusting the constant: this is the property, not the number."""
    import struct
    w, h = struct.unpack(">II", providers.probe_image_bytes()[16:24])
    assert w >= 32 and h >= 32


def test_test_connection_sends_the_probe_and_reports_usage_without_the_key(monkeypatch, isolated_store):
    import core
    import httpx
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-value")
    isolated_store.upsert_ai_provider_config(
        "anthropic", enabled=False, endpoint=None, deployment=None,
        model="claude-sonnet-5", key_secret_ref="ANTHROPIC_API_KEY", updated_by="admin")

    sent = {}

    def _post(url, **kw):
        sent.update(url=url, json=kw.get("json"), headers=kw.get("headers"))
        return _anthropic_ok()
    monkeypatch.setattr(httpx, "post", _post)

    res = providers.test_connection("anthropic")
    assert res["ok"] is True and res["provider"] == "anthropic"

    # The bytes that went out are the synthetic probe — byte for byte, not merely "small".
    import base64
    img = sent["json"]["messages"][0]["content"][0]["source"]["data"]
    assert base64.b64decode(img) == providers.probe_image_bytes()

    # Real token usage and a real cost, computed from what the API returned.
    assert res["prompt_tokens"] == 1200 and res["completion_tokens"] == 40
    assert res["cost_usd"] > 0

    # No secret anywhere in the RESULT, and no model output either.
    assert "sk-ant-secret-value" not in json.dumps(res)
    assert "text" not in res and "content" not in res
    assert res["described"] is True                       # that it answered, not what it said


def test_test_connection_works_before_the_provider_is_enabled(monkeypatch, isolated_store):
    """Testing before enabling is the point — requiring the switch first would invert the order
    this whole feature exists to establish."""
    import core
    import httpx
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    isolated_store.upsert_ai_provider_config(
        "openai", enabled=False, endpoint=None, deployment=None,
        model="gpt-4o", key_secret_ref="OPENAI_API_KEY", updated_by="admin")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _openai_ok())
    assert providers.test_connection("openai")["ok"] is True


def test_test_connection_on_an_unconfigured_provider_says_what_is_missing(monkeypatch, isolated_store):
    import core
    monkeypatch.setattr(core, "store", isolated_store)
    res = providers.test_connection("openai")
    assert res["ok"] is False and res["reason"] == "not_configured"
    assert "model" in res["missing"] and "key_secret_ref" in res["missing"]


# ── 4. failure handling — the three outcomes stay distinct ────────────────────────────────────

def _configured(store, monkeypatch, provider="openai", model="gpt-4o"):
    import core
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setenv("K", "sk-test")
    store.upsert_ai_provider_config(provider, enabled=True, endpoint=None, deployment=None,
                                    model=model, key_secret_ref="K", updated_by="admin")


def test_a_transport_throw_is_reported_as_a_transport_error(monkeypatch, isolated_store):
    import httpx
    _configured(isolated_store, monkeypatch)

    def _boom(*a, **k):
        raise Exception("ConnectError: [Errno 61] Connection refused")
    monkeypatch.setattr(httpx, "post", _boom)
    res = providers.test_connection("openai")
    assert res["ok"] is False and res["reason"] == providers.REASON_TRANSPORT


def test_an_http_status_is_reported_as_that_status(monkeypatch, isolated_store):
    """A 401 is a wrong key and a 404 is a wrong model or route — different fixes, so they must
    not collapse into one 'failed'."""
    import httpx
    _configured(isolated_store, monkeypatch)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp({"error": "invalid api key"}, status=401))
    assert providers.test_connection("openai")["reason"] == "http_401"
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp({"error": "no such model"}, status=404))
    assert providers.test_connection("openai")["reason"] == "http_404"


def test_a_200_with_nothing_in_it_is_reported_as_empty(monkeypatch, isolated_store):
    """The deployment answers and cannot caption a black square. That is a real finding about the
    deployment, and it used to be indistinguishable from a dead endpoint."""
    import httpx
    _configured(isolated_store, monkeypatch)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _openai_ok(text=""))
    assert providers.test_connection("openai")["reason"] == providers.REASON_EMPTY


def test_an_anthropic_safety_refusal_is_not_reported_as_success(monkeypatch, isolated_store):
    import httpx
    _configured(isolated_store, monkeypatch, provider="anthropic", model="claude-sonnet-5")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp(
        {"content": [], "stop_reason": "refusal", "usage": {}}))
    res = providers.test_connection("anthropic")
    assert res["ok"] is False and res["reason"] == providers.REASON_EMPTY


# ── 5. provenance and cost ────────────────────────────────────────────────────────────────────

def test_the_public_endpoints_report_the_cloud_zone(monkeypatch):
    """The 🟡 badge has to stay honest: on api.openai.com and api.anthropic.com the bytes leave
    the network, and both adapters must say so rather than borrowing 'tenant' or 'local'."""
    monkeypatch.setenv("K", "sk-test")
    cfg = {"model": "gpt-4o", "key_secret_ref": "K"}
    assert providers._adapter_for("openai", cfg).zone == "cloud"
    assert providers._adapter_for("anthropic", {**cfg, "model": "claude-sonnet-5"}).zone == "cloud"


def test_a_self_hosted_openai_compatible_endpoint_reports_local(monkeypatch):
    """zone is derived from the endpoint, not from the provider's name — an OpenAI-compatible
    server on your own network is genuinely local, and saying 'cloud' would be as dishonest as
    the reverse."""
    monkeypatch.setenv("K", "sk-test")
    a = providers._adapter_for("openai", {"model": "gpt-4o", "key_secret_ref": "K",
                                          "endpoint": "http://10.0.0.5:8000/v1"})
    assert a.zone == "local"


@pytest.mark.parametrize("provider,model,resp,expect", [
    # 1200 in @ $2.50/1M + 40 out @ $10/1M
    ("openai", "gpt-4o", _openai_ok, round(1200 / 1e6 * 2.50 + 40 / 1e6 * 10.00, 6)),
    # 1200 in @ $3/1M + 40 out @ $15/1M
    ("anthropic", "claude-sonnet-5", _anthropic_ok, round(1200 / 1e6 * 3.00 + 40 / 1e6 * 15.00, 6)),
])
def test_cost_is_computed_from_the_real_returned_usage(monkeypatch, isolated_store,
                                                       provider, model, resp, expect):
    import httpx
    _configured(isolated_store, monkeypatch, provider=provider, model=model)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: resp())
    res = providers.test_connection(provider)
    assert res["cost_usd"] == expect
    assert res["prompt_tokens"] == 1200 and res["completion_tokens"] == 40


def test_an_unpriced_model_records_tokens_and_no_invented_cost(monkeypatch, isolated_store):
    """ADR 0016: a number we cannot compute is 0, never a guess. The tokens are still real and
    still recorded, so the usage half of the report survives an unknown model."""
    import httpx
    _configured(isolated_store, monkeypatch, model="some-unreleased-model")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _openai_ok())
    res = providers.test_connection("openai")
    assert res["cost_usd"] == 0.0
    assert res["prompt_tokens"] == 1200 and res["completion_tokens"] == 40


# ── 6. local-first: a cloud provider never displaces the local default ────────────────────────

def test_an_enabled_but_unresolvable_provider_falls_back_to_local(monkeypatch, isolated_store):
    """The stale-selection case. A provider enabled while its secret was present, then the secret
    rotated away, must degrade to the local floor — not break the vision path."""
    import core
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.delenv("K", raising=False)
    isolated_store.upsert_ai_provider_config("anthropic", enabled=True, endpoint=None,
                                             deployment=None, model="claude-sonnet-5",
                                             key_secret_ref="K", updated_by="admin")
    isolated_store.set_setting("ai_vision_provider", "anthropic")
    assert isinstance(providers.active_vision_provider(), providers.OllamaVisionProvider)
    assert providers.cloud_vision_provider() is None


def test_with_nothing_configured_there_is_no_cloud_escalation_at_all(monkeypatch, isolated_store):
    """The out-of-box state, and the one that must never regress: no cloud provider means the
    product is exactly the keyless local build and no document can leave the network."""
    import core
    monkeypatch.setattr(core, "store", isolated_store)
    assert providers.cloud_vision_provider() is None
    assert providers.cloud_status() == {"enabled": False, "provider": None, "zone": None}
    assert isinstance(providers.active_vision_provider(), providers.OllamaVisionProvider)


def test_cloud_status_reports_an_activated_provider_without_leaking_anything(monkeypatch, isolated_store):
    import core
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-value")
    isolated_store.upsert_ai_provider_config(
        "anthropic", enabled=True, endpoint=None, deployment=None, model="claude-sonnet-5",
        key_secret_ref="ANTHROPIC_API_KEY", updated_by="admin")
    st = providers.cloud_status()
    assert st == {"enabled": True, "provider": "anthropic", "zone": "cloud"}
    assert "sk-ant-secret-value" not in json.dumps(st)


# ── 7. HuggingFace Inference Endpoint ────────────────────────────────────────────────────────

def test_huggingface_is_in_the_cloud_provider_catalogue():
    """HuggingFace must appear in CLOUD_PROVIDERS so the Settings page renders it and
    cloud_vision_provider() can select it."""
    assert "huggingface" in providers.CLOUD_PROVIDERS


def test_cloud_vision_provider_can_select_huggingface(monkeypatch, isolated_store):
    import core
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("HF_API_TOKEN", "hf-live-token")
    isolated_store.upsert_ai_provider_config(
        "huggingface", enabled=True,
        endpoint="https://my-ep.endpoints.huggingface.cloud",
        deployment=None, model="meta-llama/Llama-3.2-11B-Vision-Instruct",
        key_secret_ref="HF_API_TOKEN", updated_by="admin")
    p = providers.cloud_vision_provider()
    assert isinstance(p, providers.HuggingFaceVisionProvider)
    assert p.zone == "cloud"


def test_huggingface_readiness_requires_endpoint_model_and_key(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf-secret")
    full = {"endpoint": "https://ep.hf.co", "model": "m", "key_secret_ref": "HF_TOKEN"}
    r = providers.activation_readiness("huggingface", full)
    assert r["ready"] is True and r["secret_resolves"] is True
    assert r["missing"] == []


def test_huggingface_without_endpoint_is_not_ready():
    r = providers.activation_readiness("huggingface", {"model": "m", "key_secret_ref": "K"})
    assert "endpoint" in r["missing"]


def test_huggingface_test_connection_sends_probe_not_customer_content(monkeypatch, isolated_store):
    import base64, core, httpx
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("HF_API_TOKEN", "hf-test-token")
    isolated_store.upsert_ai_provider_config(
        "huggingface", enabled=False,
        endpoint="https://ep.endpoints.huggingface.cloud",
        deployment=None, model="meta-llama/Llama-3.2-11B-Vision-Instruct",
        key_secret_ref="HF_API_TOKEN", updated_by="admin")
    sent = {}

    def _post(url, **kw):
        sent.update(url=url, json=kw.get("json"), headers=kw.get("headers"))
        return _openai_ok()
    monkeypatch.setattr(httpx, "post", _post)

    res = providers.test_connection("huggingface")
    assert res["ok"] is True

    url = sent["json"]["messages"][0]["content"][1]["image_url"]["url"]
    assert base64.b64decode(url.split(",", 1)[1]) == providers.probe_image_bytes()
    assert sent["headers"]["Authorization"] == "Bearer hf-test-token"
    assert "hf-test-token" not in json.dumps(res)
