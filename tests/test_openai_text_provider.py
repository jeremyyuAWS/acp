"""Tests for the OpenAI half of the cloud TEXT path (ADR 0019 §1).

The Anthropic text transport has shipped since #1545; this covers the OpenAI one and the
selector that chooses between them. The implementation lives behind the providers seam
(providers.openai_text_generate / providers.active_text_provider / providers.text_generate /
providers.text_provider_provenance); ai.suggest_fix calls `text_generate` and never learns
which vendor ran.

NO TEST HERE MAKES A NETWORK CALL — every one either patches httpx.post or asserts that the
transport returned before it could reach for httpx at all. No real key appears in this file;
the fixtures use obvious placeholders, and the assertions are about the SECRET REFERENCE
(a name) rather than any value.

Verifies:
  1. openai_text_generate returns None when no key reference resolves (and makes no call).
  2. It parses the chat-completions response shape, with measured tokens/cost/zone/host.
  3. It degrades to None — never raises — on HTTP failure, on a timeout, and on an empty 200.
  4. active_text_provider needs an EXPLICIT selection for OpenAI, resolves its key through the
     governed key_secret_ref (env name and `keyvault:` ref alike), and never breaks the local
     floor when a selection is stale.
  5. text_generate dispatches to the selected vendor, and a pinned provider (the governed
     remediation pilot) overrides the selection.
  6. suggest_fix drafts through OpenAI end to end, records the provider/model provenance, and
     falls back to the local Ollama path when the cloud call cannot produce text.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import ai
import providers


@pytest.fixture(autouse=True)
def _no_ambient_cloud_text(monkeypatch):
    """Start every test from the out-of-box state: no cloud text secret, no selection, no
    provider row. Otherwise a box that happens to export ANTHROPIC_API_KEY or OPENAI_API_KEY
    (the evals kit and scripts/judge_drafts.py both read them) would decide these outcomes."""
    monkeypatch.setattr(providers, "_ANTHROPIC_KEY", "")
    monkeypatch.setattr(providers, "_OPENAI_KEY", "")
    monkeypatch.delenv("ACP_TEXT_PROVIDER", raising=False)
    monkeypatch.setattr(providers, "_config_for", lambda name: {"provider": name})
    # active_text_provider reads the admin setting through core.store; make that a definite
    # "no preference" rather than whatever a local database holds.
    import core
    monkeypatch.setattr(core.store, "get_setting", lambda key, *a, **k: None, raising=False)


class _Resp:
    """A minimal httpx-like response carrying one chat-completions body."""

    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


def _ok_body(text="Read the Q3 revenue summary.", prompt_tokens=120, completion_tokens=8):
    return {"choices": [{"message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}}


def _select_openai(monkeypatch, key="sk-placeholder-not-a-real-key"):
    monkeypatch.setenv("ACP_TEXT_PROVIDER", "openai")
    monkeypatch.setattr(providers, "_OPENAI_KEY", key)


# ── providers.openai_text_generate ────────────────────────────────────────────

def test_openai_text_generate_returns_none_without_key(monkeypatch):
    """No resolved reference → no call at all. httpx.post is booby-trapped: if the transport
    reached it, the test fails rather than silently passing on a None from somewhere else."""
    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail(
        "openai_text_generate called out with no resolved key"))
    assert providers.openai_text_generate("any prompt") is None


def test_openai_text_generate_parses_chat_completions_response(monkeypatch):
    monkeypatch.setattr(providers, "_OPENAI_KEY", "sk-placeholder-not-a-real-key")
    seen = {}
    import httpx

    def _post(url, **kwargs):
        seen["url"] = url
        seen["json"] = kwargs["json"]
        seen["headers"] = kwargs["headers"]
        return _Resp(_ok_body())

    monkeypatch.setattr(httpx, "post", _post)
    result = providers.openai_text_generate("draft link text")

    assert result is not None
    assert result["text"] == "Read the Q3 revenue summary."
    assert result["prompt_tokens"] == 120 and result["completion_tokens"] == 8
    assert result["provider"] == "openai"
    assert result["model"] == providers.OPENAI_TEXT_MODEL
    assert result["zone"] == "cloud" and result["host"] == "api.openai.com"
    # A measured cost from the real token counts and the module's list price (ADR 0016),
    # not an invented number: gpt-4o-mini is $0.15/$0.60 per 1M.
    price = providers._price_for(providers.OPENAI_TEXT_MODEL)
    assert price is not None, "the default OpenAI text model must be priced, or cost reads 0"
    assert result["cost_usd"] == round(120 / 1e6 * price[0] + 8 / 1e6 * price[1], 6)
    assert seen["url"] == "https://api.openai.com/v1/chat/completions"
    assert seen["json"]["model"] == providers.OPENAI_TEXT_MODEL
    # The key rides in the Authorization header only — never the URL, never the body.
    assert seen["headers"]["Authorization"].startswith("Bearer ")
    assert "sk-" not in seen["url"] and "sk-" not in repr(seen["json"])


def test_openai_text_generate_honours_a_model_override(monkeypatch):
    monkeypatch.setattr(providers, "_OPENAI_KEY", "sk-placeholder-not-a-real-key")
    sent = {}
    import httpx

    def _post(url, **kwargs):
        sent.update(kwargs["json"])
        return _Resp(_ok_body(prompt_tokens=1000, completion_tokens=100))

    monkeypatch.setattr(httpx, "post", _post)
    result = providers.openai_text_generate("draft", model="gpt-4o")
    assert sent["model"] == "gpt-4o"
    assert result["model"] == "gpt-4o"
    assert result["cost_usd"] == round(1000 / 1e6 * 2.50 + 100 / 1e6 * 10.00, 6)


@pytest.mark.parametrize("boom", [
    lambda: __import__("httpx").ConnectError("unreachable"),
    lambda: __import__("httpx").ReadTimeout("timed out"),
    lambda: __import__("httpx").HTTPStatusError("401", request=None, response=None),
])
def test_openai_text_generate_degrades_instead_of_raising(monkeypatch, boom):
    """Transport failure, timeout and HTTP status all degrade to None — the provider contract
    is 'never raises'. A raise here would surface as a 500 on the review card instead of a
    local-path draft."""
    monkeypatch.setattr(providers, "_OPENAI_KEY", "sk-placeholder-not-a-real-key")
    import httpx
    err = boom()
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(err))
    assert providers.openai_text_generate("prompt") is None


def test_openai_text_generate_returns_none_on_empty_200(monkeypatch):
    monkeypatch.setattr(providers, "_OPENAI_KEY", "sk-placeholder-not-a-real-key")
    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp(
        {"choices": [{"message": {"content": ""}}], "usage": {}}))
    assert providers.openai_text_generate("prompt") is None


def test_openai_text_zone_follows_the_endpoint(monkeypatch):
    """An OpenAI-compatible endpoint on your own infrastructure is 'local' — the zone is derived
    from the endpoint by zone_for_url, so the governance badge cannot claim bytes left the
    network when they did not (ADR 0016 / ADR 0019)."""
    monkeypatch.setattr(providers, "_OPENAI_TEXT_BASE_URL", "http://gpu.internal:8000/v1")
    monkeypatch.setattr(providers, "_OPENAI_KEY", "sk-placeholder-not-a-real-key")
    import httpx
    monkeypatch.setattr(httpx, "post", lambda url, **k: _Resp(_ok_body()))
    result = providers.openai_text_generate("prompt")
    assert result["zone"] == "local" and result["host"] == "gpu.internal"


# ── providers.active_text_provider — selection + key resolution ───────────────

def test_no_cloud_secret_means_no_cloud_text_provider():
    assert providers.active_text_provider() is None
    assert providers.text_provider_provenance() is None


def test_anthropic_key_alone_still_selects_anthropic(monkeypatch):
    """The shipped behaviour, unchanged: a deployment holding only the Anthropic secret keeps
    getting Anthropic text with nothing to reconfigure."""
    monkeypatch.setattr(providers, "_ANTHROPIC_KEY", "placeholder-anthropic-key")
    assert providers.active_text_provider() == "anthropic"


def test_openai_key_alone_does_not_activate_openai_text(monkeypatch):
    """Cloud egress is opt-in. OPENAI_API_KEY exists in environments that run the evals kit, so
    its mere presence must not start posting remediation drafts to a third party."""
    monkeypatch.setattr(providers, "_OPENAI_KEY", "sk-placeholder-not-a-real-key")
    assert providers.active_text_provider() is None


def test_explicit_selection_plus_key_activates_openai(monkeypatch):
    _select_openai(monkeypatch)
    assert providers.active_text_provider() == "openai"
    prov = providers.text_provider_provenance()
    assert prov == {"provider": "openai", "model": providers.OPENAI_TEXT_MODEL,
                    "zone": "cloud", "host": "api.openai.com"}


def test_admin_setting_beats_the_deploy_default(monkeypatch):
    """Same precedence as the vision lane: the stored admin choice overrides the env default."""
    monkeypatch.setenv("ACP_TEXT_PROVIDER", "anthropic")
    monkeypatch.setattr(providers, "_ANTHROPIC_KEY", "placeholder-anthropic-key")
    monkeypatch.setattr(providers, "_OPENAI_KEY", "sk-placeholder-not-a-real-key")
    import core
    monkeypatch.setattr(core.store, "get_setting",
                        lambda key, *a, **k: "openai" if key == "ai_text_provider" else None,
                        raising=False)
    assert providers.active_text_provider() == "openai"


def test_stale_openai_selection_falls_back_and_never_breaks_the_floor(monkeypatch):
    """A selection whose key does not resolve degrades — to Anthropic when that secret is
    present, otherwise to the keyless local path — rather than erroring or blocking drafts."""
    monkeypatch.setenv("ACP_TEXT_PROVIDER", "openai")
    assert providers.active_text_provider() is None
    monkeypatch.setattr(providers, "_ANTHROPIC_KEY", "placeholder-anthropic-key")
    assert providers.active_text_provider() == "anthropic"


def test_openai_key_resolves_through_the_governed_secret_reference(monkeypatch):
    """The Settings-page path (ADR 0019 §6): the row stores the NAME of an ops-provisioned
    environment secret, and the adapter reads the value at call time."""
    monkeypatch.setenv("ACP_TEXT_PROVIDER", "openai")
    monkeypatch.setenv("ACP_OPENAI_KEY", "sk-placeholder-not-a-real-key")
    monkeypatch.setattr(providers, "_config_for", lambda name: (
        {"provider": name, "enabled": True, "model": "gpt-4o",
         "key_secret_ref": "ACP_OPENAI_KEY"} if name == "openai" else {"provider": name}))
    assert providers.active_text_provider() == "openai"


def test_openai_key_resolves_through_a_key_vault_reference(monkeypatch):
    """ADR 0050 write-through: a `keyvault:` reference resolves through secret_store, so a key
    an admin wrote to the vault serves the text lane without an ops redeploy. The assistant
    still never sees a key — only the reference name travels through configuration."""
    monkeypatch.setenv("ACP_TEXT_PROVIDER", "openai")
    monkeypatch.setattr(providers, "_config_for", lambda name: (
        {"provider": name, "enabled": True, "model": "gpt-4o",
         "key_secret_ref": "keyvault:acp-ai-openai-key"} if name == "openai" else {"provider": name}))
    import secret_store
    monkeypatch.setattr(secret_store, "read_ref",
                        lambda ref: "sk-placeholder-not-a-real-key"
                        if ref == "keyvault:acp-ai-openai-key" else None)
    assert providers.active_text_provider() == "openai"


def test_a_disabled_provider_row_does_not_serve_text(monkeypatch):
    """A key provisioned for VISION on a row the admin has not enabled must not start serving
    the text lane. Consent is the `enabled` flag, not the presence of a credential."""
    monkeypatch.setenv("ACP_TEXT_PROVIDER", "openai")
    monkeypatch.setenv("ACP_OPENAI_KEY", "sk-placeholder-not-a-real-key")
    monkeypatch.setattr(providers, "_config_for", lambda name: (
        {"provider": name, "enabled": False, "model": "gpt-4o",
         "key_secret_ref": "ACP_OPENAI_KEY"} if name == "openai" else {"provider": name}))
    assert providers.active_text_provider() is None


# ── providers.text_generate — dispatch ────────────────────────────────────────

def test_text_generate_dispatches_to_the_selected_vendor(monkeypatch):
    _select_openai(monkeypatch)
    urls = []
    import httpx
    monkeypatch.setattr(httpx, "post", lambda url, **k: (urls.append(url), _Resp(_ok_body()))[1])
    result = providers.text_generate("draft")
    assert result["provider"] == "openai"
    assert urls == ["https://api.openai.com/v1/chat/completions"]


def test_text_generate_returns_none_when_nothing_is_configured():
    assert providers.text_generate("draft") is None


def test_a_pinned_provider_overrides_the_selection(monkeypatch):
    """The governed pilot pins its vendor because its model id is vendor-specific. With OpenAI
    selected as the deployment default, a pinned Anthropic pilot call must still go to
    Anthropic — otherwise the ai_calls row would name a model that never ran (ADR 0016)."""
    _select_openai(monkeypatch)
    monkeypatch.setattr(providers, "_ANTHROPIC_KEY", "placeholder-anthropic-key")
    urls = []
    import httpx

    def _post(url, **k):
        urls.append(url)
        return _Resp({"content": [{"type": "text", "text": "Read the Q3 revenue summary."}],
                      "usage": {"input_tokens": 10, "output_tokens": 5}})

    monkeypatch.setattr(httpx, "post", _post)
    import remediation_pilot
    result = providers.text_generate("draft", model=remediation_pilot.MODEL,
                                     provider=remediation_pilot.PROVIDER)
    assert urls == [providers._ANTHROPIC_MESSAGES_URL], "the pin was ignored — a Claude model id went to another vendor"
    assert result["provider"] == "anthropic" and result["model"] == remediation_pilot.MODEL


def test_a_pinned_provider_without_a_key_degrades_to_none(monkeypatch):
    _select_openai(monkeypatch)
    assert providers.text_generate("draft", provider="anthropic") is None


# ── ai.suggest_fix / ai.provenance through the OpenAI lane ────────────────────

def test_suggest_fix_drafts_through_openai_and_records_provenance(monkeypatch):
    _select_openai(monkeypatch)
    calls = []
    import httpx
    monkeypatch.setattr(httpx, "post", lambda url, **k: (
        calls.append(url), _Resp(_ok_body("Read the Q3 revenue summary.")))[1])

    out = ai.suggest_fix("2.4.4", "Link Purpose", "A", "report.docx", detail="Click here")

    assert out is not None
    assert out["suggestion"] == "Read the Q3 revenue summary."
    # A remediation whose provenance cannot say which model produced it is not auditable.
    assert out["provider"] == "openai"
    assert out["model"] == providers.OPENAI_TEXT_MODEL
    assert out["processing_zone"] == "cloud"
    assert out["cost_usd"] > 0
    # One cloud call, and no Ollama call behind it.
    assert calls == ["https://api.openai.com/v1/chat/completions"]


def test_suggest_fix_falls_back_to_the_local_path_when_openai_cannot_draft(monkeypatch):
    _select_openai(monkeypatch)
    urls = []
    import httpx

    def _post(url, **k):
        urls.append(url)
        if "openai" in url:
            return _Resp({"choices": [{"message": {"content": ""}}], "usage": {}})
        return _Resp({"response": "Descriptive link text here."})

    monkeypatch.setattr(httpx, "post", _post)
    out = ai.suggest_fix("2.4.4", "Link Purpose", "A", "doc.docx")
    assert out["suggestion"] == "Descriptive link text here."
    assert out.get("model") == ai.OLLAMA_MODEL
    assert "provider" not in out          # the local path adds no governance fields
    assert any("openai" in u for u in urls)
    assert any("11434" in u or "ollama" in u for u in urls)


def test_suggest_fix_uses_the_local_path_with_no_cloud_secret(monkeypatch):
    """The out-of-box state stays exactly the keyless local build: selecting OpenAI without a
    key changes nothing, and no request is made to any cloud host."""
    monkeypatch.setenv("ACP_TEXT_PROVIDER", "openai")
    urls = []
    import httpx
    monkeypatch.setattr(httpx, "post", lambda url, **k: (
        urls.append(url), _Resp({"response": "Descriptive link text here."}))[1])
    out = ai.suggest_fix("2.4.4", "Link Purpose", "A", "doc.docx")
    assert out["suggestion"] == "Descriptive link text here."
    assert not any("openai.com" in u or "anthropic.com" in u for u in urls)


def test_provenance_reports_the_openai_text_lane(monkeypatch):
    _select_openai(monkeypatch)
    p = ai.provenance()
    assert p["provider"] == "openai"
    assert p["model"] == providers.OPENAI_TEXT_MODEL
    assert p["zone"] == "cloud" and p["host"] == "api.openai.com"
    assert p["vision_model"] == ai.OLLAMA_VISION_MODEL


def test_an_unknown_text_provider_selection_is_not_an_error(monkeypatch):
    """`gemini` is a governed VISION adapter with no text transport here. Naming it as the text
    provider must read as 'no preference' and fall through, not raise and not silently post a
    remediation prompt to a vendor this module cannot account for."""
    monkeypatch.setenv("ACP_TEXT_PROVIDER", "gemini")
    monkeypatch.setattr(providers, "_OPENAI_KEY", "sk-placeholder-not-a-real-key")
    assert "gemini" not in providers.TEXT_PROVIDERS
    assert providers.active_text_provider() is None
    monkeypatch.setattr(providers, "_ANTHROPIC_KEY", "placeholder-anthropic-key")
    assert providers.active_text_provider() == "anthropic"
