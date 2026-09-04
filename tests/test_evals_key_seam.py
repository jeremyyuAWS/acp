"""The evals kit reads the SAME credential the product does.

Before this seam the kit read `ANTHROPIC_API_KEY` and the product read whatever
`key_secret_ref` names in Settings -> AI providers. An ops team that provisioned the credential
as `ACP_ANTHROPIC_KEY` — which is exactly what that field exists to allow — had a working
product and an evals run that failed with an auth error, and nothing said why. Two places to
configure, one of which fails silently.

What is deliberately NOT changed: the key value still never reaches the database or the browser.
The Settings page stores the secret's NAME; both readers resolve it from the environment.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

from evals.candidates import resolve, resolve_api_key            # noqa: E402
import providers                                                  # noqa: E402


# ── api/providers.credential_for ─────────────────────────────────────────────────────────────

def test_credential_for_returns_the_value_and_the_name_it_came_from(monkeypatch):
    monkeypatch.setattr(providers, "_config_for",
                        lambda p: {"provider": p, "key_secret_ref": "ACP_ANTHROPIC_KEY"})
    monkeypatch.setenv("ACP_ANTHROPIC_KEY", "sk-not-a-real-key")
    key, source = providers.credential_for("anthropic")
    assert key == "sk-not-a-real-key"
    assert source == "ACP_ANTHROPIC_KEY", "the source is a NAME; it must never be the value"


def test_credential_for_distinguishes_unconfigured_from_secret_absent(monkeypatch):
    """Two different fixes: 'nobody filled in the field' vs 'the field names a secret this
    environment does not carry'. One message for both is how a deployment problem gets debugged
    as a configuration problem."""
    monkeypatch.setattr(providers, "_config_for", lambda p: {"provider": p})
    assert providers.credential_for("anthropic") == (None, "not_configured")

    monkeypatch.setattr(providers, "_config_for",
                        lambda p: {"provider": p, "key_secret_ref": "NEVER_SET_ANYWHERE"})
    monkeypatch.delenv("NEVER_SET_ANYWHERE", raising=False)
    key, source = providers.credential_for("anthropic")
    assert key is None and source == "secret_absent:NEVER_SET_ANYWHERE"


def test_credential_for_survives_a_store_that_is_not_there(monkeypatch):
    """On a CI runner there is no database. The seam must degrade, not raise — `_config_for`
    already swallows, and this pins that `credential_for` does not undo it."""
    monkeypatch.setattr(providers, "_config_for",
                        lambda p: (_ for _ in ()).throw(RuntimeError("no store")))
    with pytest.raises(RuntimeError):
        providers.credential_for("anthropic")   # documents that the swallow lives in _config_for
    # ...and that the KIT's wrapper is the layer that must not propagate it:
    from evals import candidates
    monkeypatch.setattr(candidates, "_provider_credential",
                        lambda p: (None, "provider_config_unavailable:RuntimeError"))
    key, src = resolve_api_key("anthropic", "NOT_SET_ANYWHERE_EITHER",
                               lookup=candidates._provider_credential)
    assert key is None and "unavailable" in src


# ── the kit's resolution order ───────────────────────────────────────────────────────────────

def test_an_exported_key_wins_because_the_sdk_would_have_used_it_anyway(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    key, source = resolve_api_key("anthropic", "ANTHROPIC_API_KEY",
                                  lookup=lambda p: ("sk-from-config", "ACP_ANTHROPIC_KEY"))
    assert key == "sk-from-env" and source == "env:ANTHROPIC_API_KEY"


def test_the_product_config_covers_a_custom_secret_name(monkeypatch):
    """The whole point: a key provisioned under the ops team's own name now works for the evals
    without a second place to configure it."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    key, source = resolve_api_key("anthropic", "ANTHROPIC_API_KEY",
                                  lookup=lambda p: ("sk-from-config", "ACP_ANTHROPIC_KEY"))
    assert key == "sk-from-config"
    assert source == "provider_config:ACP_ANTHROPIC_KEY"


def test_a_missing_key_says_where_it_looked(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    key, source = resolve_api_key("anthropic", "ANTHROPIC_API_KEY",
                                  lookup=lambda p: (None, "not_configured"))
    assert key is None and source == "missing (not_configured)"


def test_the_reported_source_never_carries_the_key(monkeypatch):
    """A source string is printed in the pre-flight and could end up in a CI log."""
    secret = "sk-this-must-never-be-printed"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    _, source = resolve_api_key("anthropic", "ANTHROPIC_API_KEY", lookup=lambda p: (secret, "X"))
    assert secret not in source
    assert secret not in resolve("anthropic:claude-haiku-4-5").key_source()

    # ...and at the layer that actually holds the value, exercised directly rather than through
    # the env-first shortcut, which would never reach it.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(providers, "_config_for",
                        lambda p: {"provider": p, "key_secret_ref": "SOME_REF"})
    monkeypatch.setenv("SOME_REF", secret)
    key, src = providers.credential_for("anthropic")
    assert key == secret and secret not in src
    assert secret not in resolve_api_key("anthropic", "ANTHROPIC_API_KEY")[1]


def test_candidates_that_need_no_key_say_so():
    assert resolve("rules-only").key_source() == "no key needed"
    assert resolve("stub:good").key_source() == "no key needed"
    assert resolve("ollama:qwen2.5:0.5b").key_source() == "no key needed"
