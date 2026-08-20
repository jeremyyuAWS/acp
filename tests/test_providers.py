"""Vision provider adapter seam (ADR 0019 Phase 1, §1).

Slice 1 must be a pure seam: the Ollama adapter does exactly what the old inline call did
(same URL, same payload shape, base64 image), returns a normalized result, and NEVER raises —
a transport error degrades to ok=False so the gateway can fall back. The selector defaults to
Ollama and reads its endpoint from ai's live globals (so a runtime endpoint switch is honoured).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import providers  # noqa: E402


def test_zone_local_vs_cloud():
    assert providers.zone_for_url("http://localhost:11434") == "local"
    assert providers.zone_for_url("http://10.0.0.5:11434") == "local"
    assert providers.zone_for_url("https://api.openai.com") == "cloud"
    assert providers.zone_for_url("https://acp-ollama.eastus2.azurecontainerapps.io") == "cloud"


def test_provenance_zone_is_derived_from_zone_for_url_single_source(monkeypatch):
    """ai.provenance() must not reimplement the zone test — it derives the governance zone from
    providers.zone_for_url, so /config (provenance) and the per-call trace can never disagree about
    whether a document left the network. Pin them together across a local and a cloud endpoint, so a
    future edit to one implementation alone fails here rather than shipping a divergent PHI signal."""
    import ai
    for url in ("http://10.0.0.5:11434", "https://acp-ollama.eastus2.azurecontainerapps.io",
                "http://analysis.corp.internal:11434", "https://api.openai.com"):
        monkeypatch.setattr(ai, "OLLAMA_BASE_URL", url)
        assert ai.provenance()["zone"] == providers.zone_for_url(url)
    # …and the two named outcomes explicitly, so the guard fails loudly if the shared helper changes.
    monkeypatch.setattr(ai, "OLLAMA_BASE_URL", "http://localhost:11434")
    assert ai.provenance()["zone"] == "local"
    monkeypatch.setattr(ai, "OLLAMA_BASE_URL", "https://api.openai.com")
    assert ai.provenance()["zone"] == "cloud"


def test_ollama_adapter_posts_images_and_normalizes(monkeypatch):
    seen = {}

    class _R:
        def raise_for_status(self): pass
        def json(self): return {"response": "  A bar chart of Q4 revenue  "}

    def fake_post(url, json=None, timeout=None):
        seen["url"] = url; seen["json"] = json; seen["timeout"] = timeout
        return _R()

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)
    p = providers.OllamaVisionProvider("http://localhost:11434/", "llava:13b")
    res = p.generate("describe", b"IMGBYTES", timeout=42.0)
    assert seen["url"] == "http://localhost:11434/api/generate"
    assert seen["json"]["model"] == "llava:13b"
    assert seen["json"]["images"] and isinstance(seen["json"]["images"][0], str)   # base64
    assert seen["timeout"] == 42.0
    assert res["text"] == "A bar chart of Q4 revenue"      # stripped, raw (ai.py owns cleaning)
    assert res["ok"] is True and res["provider"] == "ollama"
    assert res["zone"] == "local" and res["cost_usd"] == 0.0
    assert isinstance(res["latency_ms"], int)


def test_ollama_adapter_model_override(monkeypatch):
    captured = {}

    class _R:
        def raise_for_status(self): pass
        def json(self): return {"response": "x y z"}

    import httpx
    monkeypatch.setattr(httpx, "post", lambda url, json=None, timeout=None: captured.update(json=json) or _R())
    p = providers.OllamaVisionProvider("http://localhost:11434", "moondream")
    p.generate("d", b"B", model="llava:13b")
    assert captured["json"]["model"] == "llava:13b"        # per-call override wins


def test_ollama_adapter_never_raises_on_transport_error(monkeypatch):
    import httpx
    def boom(*a, **k): raise RuntimeError("connection refused")
    monkeypatch.setattr(httpx, "post", boom)
    res = providers.OllamaVisionProvider("http://localhost:11434", "m").generate("d", b"B")
    assert res["ok"] is False and res["text"] is None      # degraded, not raised
    assert res["provider"] == "ollama"


def test_selector_defaults_to_ollama_from_ai_globals(monkeypatch):
    import ai
    monkeypatch.setattr(ai, "OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setattr(ai, "OLLAMA_VISION_MODEL", "moondream")
    monkeypatch.setattr(ai, "_maybe_refresh_endpoint", lambda: None)
    p = providers.active_vision_provider()
    assert isinstance(p, providers.OllamaVisionProvider)
    assert p.base_url == "http://localhost:11434" and p.model == "moondream"


def test_selector_unknown_provider_falls_back_to_ollama(monkeypatch):
    import ai
    import core
    monkeypatch.setattr(ai, "_maybe_refresh_endpoint", lambda: None)
    monkeypatch.setattr(ai, "OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setattr(ai, "OLLAMA_VISION_MODEL", "moondream")
    import types
    monkeypatch.setattr(core, "store",
                        types.SimpleNamespace(get_setting=lambda k: "azure_openai" if k == "ai_vision_provider" else None))
    p = providers.active_vision_provider()
    assert isinstance(p, providers.OllamaVisionProvider)   # un-provisioned cloud never breaks local


def test_conforms_to_protocol():
    p = providers.OllamaVisionProvider("http://localhost:11434", "m")
    assert isinstance(p, providers.VisionProvider)


# ── OpenAI + Anthropic cloud vision adapters (ADR 0019 — HITL escalation) ────────────────────

def test_openai_adapter_posts_and_normalizes(monkeypatch):
    seen = {}

    class _R:
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"message": {"content": "  A pie chart of payer mix  "},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 500}}

    import httpx
    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, json=json, headers=headers, timeout=timeout)
        return _R()
    monkeypatch.setattr(httpx, "post", fake_post)

    p = providers.OpenAIVisionProvider("sk-abc", model="gpt-4o")
    res = p.generate("describe", b"IMG", timeout=42.0)

    assert seen["url"] == "https://api.openai.com/v1/chat/completions"
    assert seen["headers"] == {"Authorization": "Bearer sk-abc"}      # key rides only in the header
    assert seen["json"]["model"] == "gpt-4o"
    content = seen["json"]["messages"][0]["content"]
    assert content[0]["type"] == "text" and content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert res["ok"] is True and res["provider"] == "openai" and res["zone"] == "cloud"
    assert res["text"] == "A pie chart of payer mix"                  # stripped, raw
    assert res["cost_usd"] == round(1000 / 1e6 * 2.50 + 500 / 1e6 * 10.00, 6)  # measured, not invented


def test_anthropic_adapter_parses_blocks_and_costs(monkeypatch):
    seen = {}

    class _R:
        def raise_for_status(self): pass
        def json(self):
            return {"stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "A "}, {"type": "text", "text": "bar chart."}],
                    "usage": {"input_tokens": 1000, "output_tokens": 200}}

    import httpx
    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, json=json, headers=headers)
        return _R()
    monkeypatch.setattr(httpx, "post", fake_post)

    p = providers.AnthropicVisionProvider("sk-ant", model="claude-opus-4-8")
    res = p.generate("describe", b"IMG")

    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"] == {"x-api-key": "sk-ant", "anthropic-version": "2023-06-01"}
    assert seen["json"]["thinking"] == {"type": "disabled"}           # budget goes to the caption
    content = seen["json"]["messages"][0]["content"]
    assert content[0]["source"]["type"] == "base64" and content[0]["source"]["media_type"] == "image/png"
    assert res["ok"] is True and res["provider"] == "anthropic" and res["zone"] == "cloud"
    assert res["text"] == "A bar chart."                             # text blocks joined
    assert res["cost_usd"] == round(1000 / 1e6 * 5.00 + 200 / 1e6 * 25.00, 6)  # input/output usage


def test_anthropic_refusal_degrades_to_not_ok(monkeypatch):
    class _R:
        def raise_for_status(self): pass
        def json(self): return {"stop_reason": "refusal", "content": []}

    import httpx
    monkeypatch.setattr(httpx, "post", lambda url, json=None, headers=None, timeout=None: _R())
    res = providers.AnthropicVisionProvider("sk-ant", model="claude-opus-4-8").generate("d", b"B")
    assert res["ok"] is False and res["text"] is None                 # a safety refusal is not an answer


def test_cloud_adapters_never_raise_on_transport_error(monkeypatch):
    import httpx
    def boom(*a, **k): raise RuntimeError("connection refused")
    monkeypatch.setattr(httpx, "post", boom)
    for p in (providers.OpenAIVisionProvider("k", model="gpt-4o"),
              providers.AnthropicVisionProvider("k", model="claude-opus-4-8")):
        res = p.generate("d", b"B")
        assert res["ok"] is False and res["text"] is None             # degraded, not raised


def _store(setting=None, configs=None):
    import types
    configs = configs or {}
    return types.SimpleNamespace(get_setting=lambda k: setting if k == "ai_vision_provider" else None,
                                 get_ai_provider_config=lambda name: configs.get(name))


def test_selector_routes_to_anthropic(monkeypatch):
    import ai, core
    monkeypatch.setattr(ai, "_maybe_refresh_endpoint", lambda: None)
    monkeypatch.setattr(ai, "OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setattr(ai, "OLLAMA_VISION_MODEL", "moondream")
    monkeypatch.setenv("ANTHROPIC_KEY", "sk-ant")
    cfg = {"provider": "anthropic", "enabled": True, "model": "claude-opus-4-8",
           "key_secret_ref": "ANTHROPIC_KEY"}
    monkeypatch.setattr(core, "store", _store(setting="anthropic", configs={"anthropic": cfg}))
    p = providers.active_vision_provider()
    assert isinstance(p, providers.AnthropicVisionProvider) and p.model == "claude-opus-4-8"


def test_selector_openai_without_key_falls_back_to_ollama(monkeypatch):
    import ai, core
    monkeypatch.setattr(ai, "_maybe_refresh_endpoint", lambda: None)
    monkeypatch.setattr(ai, "OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setattr(ai, "OLLAMA_VISION_MODEL", "moondream")
    monkeypatch.delenv("OPENAI_KEY", raising=False)                   # secret not provisioned
    cfg = {"provider": "openai", "enabled": True, "model": "gpt-4o", "key_secret_ref": "OPENAI_KEY"}
    monkeypatch.setattr(core, "store", _store(setting="openai", configs={"openai": cfg}))
    p = providers.active_vision_provider()
    assert isinstance(p, providers.OllamaVisionProvider)             # under-configured never breaks local


def test_cloud_vision_provider_picks_enabled(monkeypatch):
    import core
    monkeypatch.setenv("OAI_KEY", "sk-oai")
    cfg = {"provider": "openai", "enabled": True, "model": "gpt-4o", "key_secret_ref": "OAI_KEY"}
    monkeypatch.setattr(core, "store", _store(setting="openai", configs={"openai": cfg}))
    assert isinstance(providers.cloud_vision_provider(), providers.OpenAIVisionProvider)


def test_cloud_adapters_conform_to_protocol():
    assert isinstance(providers.OpenAIVisionProvider("k", model="gpt-4o"), providers.VisionProvider)
    assert isinstance(providers.AnthropicVisionProvider("k", model="claude-opus-4-8"), providers.VisionProvider)


# ── Token usage surfaces on the normalized result (Langfuse audit N1) ────────────────────────
# Every adapter already reads the API's token usage to compute cost; N1 also surfaces those counts
# on the result as prompt_tokens/completion_tokens so ai._trace_ai can forward them to the Langfuse
# generation's `usage`. Numbers only — never any prompt/completion text (docs/audit-langfuse-phi.md).

def test_ollama_result_surfaces_token_usage(monkeypatch):
    class _R:
        def raise_for_status(self): pass
        def json(self):
            return {"response": "A bar chart of Q4 revenue",
                    "prompt_eval_count": 266, "eval_count": 31}

    import httpx
    monkeypatch.setattr(httpx, "post", lambda url, json=None, timeout=None: _R())
    res = providers.OllamaVisionProvider("http://localhost:11434", "llava:13b").generate("d", b"B")
    assert res["prompt_tokens"] == 266 and res["completion_tokens"] == 31   # prompt_eval_count/eval_count


def test_openai_result_surfaces_token_usage(monkeypatch):
    class _R:
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"message": {"content": "A pie chart"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 500}}

    import httpx
    monkeypatch.setattr(httpx, "post", lambda url, json=None, headers=None, timeout=None: _R())
    res = providers.OpenAIVisionProvider("sk-abc", model="gpt-4o").generate("d", b"B")
    assert res["prompt_tokens"] == 1000 and res["completion_tokens"] == 500


def test_azure_result_surfaces_token_usage(monkeypatch):
    class _R:
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"message": {"content": "A line chart"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 800, "completion_tokens": 40}}

    import httpx
    monkeypatch.setattr(httpx, "post", lambda url, json=None, headers=None, timeout=None: _R())
    res = providers.AzureOpenAIVisionProvider("https://x.openai.azure.com", "gpt-4o", "k",
                                              model="gpt-4o").generate("d", b"B")
    assert res["prompt_tokens"] == 800 and res["completion_tokens"] == 40


def test_anthropic_result_surfaces_token_usage(monkeypatch):
    class _R:
        def raise_for_status(self): pass
        def json(self):
            return {"stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "A bar chart."}],
                    "usage": {"input_tokens": 1000, "output_tokens": 200}}

    import httpx
    monkeypatch.setattr(httpx, "post", lambda url, json=None, headers=None, timeout=None: _R())
    res = providers.AnthropicVisionProvider("sk-ant", model="claude-opus-4-8").generate("d", b"B")
    # Messages API names them input/output; the result normalizes to prompt/completion.
    assert res["prompt_tokens"] == 1000 and res["completion_tokens"] == 200


def test_runpod_result_surfaces_token_usage(monkeypatch):
    class _R:
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"message": {"content": "A scatter plot"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 512, "completion_tokens": 64}}

    import httpx
    monkeypatch.setattr(httpx, "post", lambda url, json=None, headers=None, timeout=None: _R())
    res = providers.RunPodServerlessVisionProvider("eid", "k", model="qwen2.5-vl").generate("d", b"B")
    assert res["prompt_tokens"] == 512 and res["completion_tokens"] == 64


def test_failed_call_reports_no_token_usage(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    res = providers.OpenAIVisionProvider("k", model="gpt-4o").generate("d", b"B")
    assert res["ok"] is False
    assert res["prompt_tokens"] is None and res["completion_tokens"] is None   # nothing to count
