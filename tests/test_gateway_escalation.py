"""Azure OpenAI vision adapter + acceptance-gated escalation (ADR 0019 Phase 1, §1/§3c).

The escalation is local-first and default-off: with no cloud provider configured, a scan behaves
exactly like the keyless local build (no cloud call, no escalation field). When an admin has
enabled Azure OpenAI AND its secret is present, an UNGROUNDED local result escalates — and the
transparent numbered path + real token-based cost are attached, never a fabricated score.
No real key is ever used: the Azure HTTP is mocked.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import providers  # noqa: E402


class _AzureResp:
    def __init__(self, text="A bar chart comparing regional sales", ptok=900, ctok=20):
        self._t, self._p, self._c = text, ptok, ctok
    def raise_for_status(self): pass
    def json(self):
        return {"choices": [{"message": {"content": self._t}}],
                "usage": {"prompt_tokens": self._p, "completion_tokens": self._c}}


# ── Azure adapter ────────────────────────────────────────────────────────────

def test_azure_adapter_calls_chat_completions_with_key_header_and_costs(monkeypatch):
    seen = {}
    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, json=json, headers=headers); return _AzureResp()
    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)
    p = providers.AzureOpenAIVisionProvider("https://acme.openai.azure.com", "gpt-4o",
                                            "SECRET-KEY-VALUE", model="gpt-4o")
    res = p.generate("describe", b"IMG")
    assert "chat/completions" in seen["url"] and "api-version=" in seen["url"]
    assert seen["headers"]["api-key"] == "SECRET-KEY-VALUE"   # key only in the header, to the tenant
    assert seen["json"]["messages"][0]["content"][1]["type"] == "image_url"
    assert res["ok"] and res["provider"] == "azure_openai" and res["zone"] == "tenant"
    assert res["text"] == "A bar chart comparing regional sales"
    # real measured cost: 900/1e6*2.50 + 20/1e6*10.00
    assert abs(res["cost_usd"] - (900/1e6*2.50 + 20/1e6*10.00)) < 1e-9


def test_azure_adapter_never_raises(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("500")))
    res = providers.AzureOpenAIVisionProvider("https://x.openai.azure.com", "d", "k").generate("p", b"B")
    assert res["ok"] is False and res["text"] is None


def test_unknown_model_costs_zero_not_fabricated(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _AzureResp())
    p = providers.AzureOpenAIVisionProvider("https://x.openai.azure.com", "custom-deploy", "k",
                                            model="mystery-model")
    assert p.generate("p", b"B")["cost_usd"] == 0.0          # no price known → no invented number


# ── cloud_vision_provider selection ──────────────────────────────────────────

def _store(monkeypatch, cfg):
    import core, types
    monkeypatch.setattr(core, "store", types.SimpleNamespace(get_ai_provider_config=lambda p: cfg))


def test_cloud_provider_none_when_unconfigured(monkeypatch):
    _store(monkeypatch, None)
    assert providers.cloud_vision_provider() is None


def test_cloud_provider_none_when_disabled_or_keyless(monkeypatch):
    monkeypatch.delenv("AZ_KEY", raising=False)
    _store(monkeypatch, {"enabled": False, "endpoint": "https://x.openai.azure.com",
                         "deployment": "gpt-4o", "key_secret_ref": "AZ_KEY"})
    assert providers.cloud_vision_provider() is None          # disabled
    _store(monkeypatch, {"enabled": True, "endpoint": "https://x.openai.azure.com",
                         "deployment": "gpt-4o", "key_secret_ref": "AZ_KEY"})
    assert providers.cloud_vision_provider() is None          # enabled but secret absent


def test_cloud_provider_ready_when_enabled_and_key_present(monkeypatch):
    monkeypatch.setenv("AZ_KEY", "sk-live")
    _store(monkeypatch, {"enabled": True, "endpoint": "https://x.openai.azure.com",
                         "deployment": "gpt-4o", "model": "gpt-4o", "key_secret_ref": "AZ_KEY"})
    p = providers.cloud_vision_provider()
    assert isinstance(p, providers.AzureOpenAIVisionProvider) and p.deployment == "gpt-4o"


# ── escalation in describe_image_structured ──────────────────────────────────

def test_no_escalation_when_no_cloud_configured(monkeypatch):
    import ai
    monkeypatch.setattr(ai, "_vision_generate", lambda *a, **k: "a plain photo of a dog")
    monkeypatch.setattr("providers.cloud_vision_provider", lambda: None)
    # force ungrounded (no OCR text)
    monkeypatch.setattr(ai, "describe_reading_order", lambda *a, **k: None, raising=False)
    import ocr
    monkeypatch.setattr(ocr, "ocr_text", lambda *a, **k: "", raising=False)
    out = ai.describe_image_structured(b"IMGBYTES", filename="p.png")
    assert out and out["grounded"] is False
    assert "escalation" not in out and out["model"] == ai.OLLAMA_VISION_MODEL   # local, unchanged


def test_ungrounded_escalates_and_attaches_transparent_path(monkeypatch):
    import ai
    # local model returns a weak ungrounded draft
    monkeypatch.setattr(ai, "_vision_generate", lambda *a, **k: "something unclear")
    import ocr
    monkeypatch.setattr(ocr, "ocr_text", lambda *a, **k: "", raising=False)   # ungrounded

    class _Cloud:
        name = "azure_openai"; zone = "tenant"
        def generate(self, prompt, image_bytes, *, model=None, timeout=120.0):
            return {"text": "Bar chart of quarterly revenue by region", "model": "gpt-4o",
                    "provider": "azure_openai", "zone": "tenant", "ok": True,
                    "cost_usd": 0.0032, "latency_ms": 800}
    monkeypatch.setattr("providers.cloud_vision_provider", lambda: _Cloud())
    out = ai.describe_image_structured(b"IMGBYTES", filename="chart.png")
    assert out["alt"] == "Bar chart of quarterly revenue by region"
    assert out["model"] == "gpt-4o" and out["provider"] == "azure_openai"
    assert out["processing_zone"] == "tenant" and out["cost_usd"] == 0.0032
    steps = out["escalation"]
    assert steps[0]["provider"] == "ollama" and "no grounded" in steps[0]["outcome"]
    assert steps[1]["provider"] == "azure_openai"


def test_grounded_result_never_escalates(monkeypatch):
    import ai
    monkeypatch.setattr(ai, "_vision_generate", lambda *a, **k: "Sales headline chart, north leads")
    import ocr
    monkeypatch.setattr(ocr, "ocr_text", lambda *a, **k: "Q4 Sales North South East West", raising=False)
    called = {"cloud": 0}
    monkeypatch.setattr("providers.cloud_vision_provider",
                        lambda: called.__setitem__("cloud", called["cloud"] + 1))
    out = ai.describe_image_structured(b"IMGBYTES", filename="chart.png")
    assert out["grounded"] is True and "escalation" not in out
    assert called["cloud"] == 0                                # grounded → cloud never consulted
