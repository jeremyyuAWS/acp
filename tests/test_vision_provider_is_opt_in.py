"""Cloud vision is OPT-IN: a key alone never sends a customer's images to a third party.

`active_vision_provider` carried a branch returning AnthropicVisionProvider whenever
ANTHROPIC_API_KEY was set and nothing had been chosen. It had been unreachable since
`choice = choice or "ollama"` was introduced above it, so it never selected anything — and the
comment above it went on describing a behaviour the code did not have, which is the kind of claim
CLAUDE.md records this repo losing days to.

IT WAS DELETED RATHER THAN REVIVED, and this file is why that is the right direction rather than
the convenient one. ADR 0019 constraint 2 makes cloud egress opt-in, and every other cloud adapter
earns its place two ways: an explicit selection AND an `enabled` governed row with a resolved
secret. Key presence is neither. ANTHROPIC_API_KEY is set wherever the evals kit or the text lane
runs, so auto-selecting on it would start posting CUSTOMER DOCUMENT IMAGES to a third party nobody
chose. #1756 answered the same question for the text lane the same way.

No capability was lost, which is the half that makes deletion safe rather than merely cautious:
the governed path already reaches Anthropic vision, and honours the row's own model. The deleted
branch pinned CLAUDE_TEXT_MODEL — a TEXT model id — onto a vision adapter, so it was wrong about
the model as well as about the consent.

Every case below is measured through the real selector against a real store.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

KEY = "sk-ant-not-a-real-key"


@pytest.fixture()
def selector(monkeypatch):
    """The real selector, a real store, and a resolvable Anthropic key.

    THE KEY IS PATCHED ONTO THE MODULE, NOT INTO THE ENVIRONMENT, and the first draft got that
    wrong in a way worth recording. `_ANTHROPIC_KEY` is read once at import, so setting the env var
    does nothing to an already-imported module — which is why the draft reached for
    `importlib.reload(providers)`. That works, and it leaks: the reloaded module keeps the fake key
    for the rest of the process, long after monkeypatch has restored the environment. It turned
    `test_providers.py` and `test_ai_suggest_vision.py` red when this file ran before them, and
    both passed alone. `monkeypatch.setattr` is precise and undone per test.
    """
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "vis.db")
    st = store_mod.Store()

    import core
    import providers
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setattr(providers, "_ANTHROPIC_KEY", KEY)
    monkeypatch.setenv("K", KEY)                # the secret ref an enabled row resolves through
    monkeypatch.delenv("ACP_VISION_PROVIDER", raising=False)
    assert providers._ANTHROPIC_KEY, "the fixture must actually have a key, or it proves nothing"
    return providers, st


def _enable_anthropic(st, model: str = "claude-opus-5"):
    st.upsert_ai_provider_config("anthropic", enabled=True, endpoint=None, deployment=None,
                                 model=model, key_secret_ref="K", updated_by="admin")


def test_a_key_alone_does_not_send_images_to_the_cloud(selector):
    """THE POLICY. A deployment that merely holds an Anthropic key — because the text lane or the
    evals kit needs one — keeps the keyless local floor for vision until somebody chooses."""
    providers, _ = selector
    assert type(providers.active_vision_provider()).__name__ == "OllamaVisionProvider"


def test_choosing_anthropic_without_a_governed_row_is_not_enough(selector):
    """The second half of the gate. An admin naming a provider does not activate it — the row must
    exist and be enabled, with a secret that resolves. A stale or aspirational selection falls
    through to the floor rather than breaking vision or leaking bytes."""
    providers, st = selector
    st.set_setting("ai_vision_provider", "anthropic")
    assert type(providers.active_vision_provider()).__name__ == "OllamaVisionProvider"


def test_an_explicit_choice_with_an_enabled_row_does_select_anthropic(selector):
    """No capability was lost by the deletion — asserted, not assumed, because that is the claim
    that makes removing the branch safe rather than merely cautious."""
    providers, st = selector
    st.set_setting("ai_vision_provider", "anthropic")
    _enable_anthropic(st)
    a = providers.active_vision_provider()
    assert type(a).__name__ == "AnthropicVisionProvider"
    assert a.zone == "cloud"                     # and it is honest about leaving the network


def test_the_governed_path_uses_the_rows_model_not_the_text_model(selector):
    """The deleted branch built its adapter with CLAUDE_TEXT_MODEL. The governed path takes the
    model from the provider row, which is what an administrator actually configured — so the
    deletion removed a wrong model as well as a wrong consent."""
    providers, st = selector
    st.set_setting("ai_vision_provider", "anthropic")
    _enable_anthropic(st, model="claude-sonnet-5")
    a = providers.active_vision_provider()
    assert a.model == "claude-sonnet-5"
    assert a.model != providers.CLAUDE_TEXT_MODEL or providers.CLAUDE_TEXT_MODEL == "claude-sonnet-5"


def test_an_enabled_row_alone_still_waits_to_be_chosen(selector):
    """Enabling a provider is configuration, not activation. Governance and selection are separate
    steps on purpose, so preparing a provider never silently starts using it."""
    providers, st = selector
    _enable_anthropic(st)                        # enabled, but nothing selected it
    assert type(providers.active_vision_provider()).__name__ == "OllamaVisionProvider"


def test_no_branch_selects_a_cloud_adapter_on_key_presence(selector):
    """The structural guard, so the branch cannot come back by being retyped.

    Read from the source rather than exercised, because the failure it prevents is a line that
    LOOKS reasonable in review — `if not choice and _ANTHROPIC_KEY` reads like a convenience.
    Structural, not a substring ban: the module legitimately names both `_ANTHROPIC_KEY` and
    `AnthropicVisionProvider` on the governed path and in the comment explaining this deletion.
    """
    import ast
    src = (ACP / "api" / "providers.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "active_vision_provider")
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
        if "_ANTHROPIC_KEY" not in names:
            continue
        raise AssertionError(
            "active_vision_provider branches on _ANTHROPIC_KEY again. Key presence is not consent: "
            "ANTHROPIC_API_KEY is set wherever the text lane or the evals kit runs, and selecting a "
            "cloud adapter on it would post customer document images to a third party nobody chose "
            "(ADR 0019 constraint 2). Anthropic vision is reachable via an explicit selection plus "
            "an enabled provider row — see the tests above.")
