"""Which vendors a text waterfall may span, and how one becomes permitted.

The rule this file exists to hold: KEY PRESENCE IS NOT AUTHORISATION. `active_text_provider`
refuses to auto-activate OpenAI text on a key alone, because OPENAI_API_KEY is present wherever
the evals kit runs and an enabled `openai` row may exist for vision only. Widening a chain to
span vendors had to widen WHICH vendors may be used without widening HOW one qualifies, so the
same standard applies to a fallback: the owner names it, or it is not permitted.
"""
import os
import pytest

import providers


@pytest.fixture(autouse=True)
def _no_ambient_configuration(monkeypatch):
    # The setting is read through core.store; make it absent rather than depending on a DB.
    monkeypatch.setattr(providers, 'active_text_provider', lambda: 'anthropic')
    monkeypatch.setattr(providers, '_text_key_for', lambda provider: 'fixture-not-a-secret')
    monkeypatch.delenv('ACP_TEXT_FALLBACK_PROVIDERS', raising=False)
    yield


def test_the_primary_alone_is_permitted_when_nothing_is_named():
    assert providers.permitted_text_providers() == frozenset({'anthropic'})


def test_a_named_vendor_with_a_resolvable_key_is_permitted(monkeypatch):
    monkeypatch.setenv('ACP_TEXT_FALLBACK_PROVIDERS', 'openai')
    assert providers.permitted_text_providers() == frozenset({'anthropic', 'openai'})


def test_a_named_vendor_without_a_key_is_not_permitted(monkeypatch):
    monkeypatch.setenv('ACP_TEXT_FALLBACK_PROVIDERS', 'openai')
    monkeypatch.setattr(providers, '_text_key_for',
                        lambda provider: '' if provider == 'openai' else 'fixture-not-a-secret')
    assert providers.permitted_text_providers() == frozenset({'anthropic'})


def test_an_unnamed_vendor_is_not_permitted_however_available_its_key_is():
    # The whole point: _text_key_for resolves for openai here and it is still not permitted.
    assert providers._text_key_for('openai')
    assert 'openai' not in providers.permitted_text_providers()


@pytest.mark.parametrize('named', ['gemini', 'bedrock', 'not-a-provider', 'OpenAI ', 'openai;'])
def test_unknown_or_vision_only_names_are_no_preference_not_an_error(named, monkeypatch):
    monkeypatch.setenv('ACP_TEXT_FALLBACK_PROVIDERS', named)
    permitted = providers.permitted_text_providers()
    # A name this module has no TEXT transport for never widens the set; a separator or
    # surrounding space around a real one must not silently drop it either.
    assert permitted == (frozenset({'anthropic', 'openai'}) if 'openai' in named.strip().lower()
                         else frozenset({'anthropic'}))


def test_no_active_provider_means_no_waterfall_to_extend(monkeypatch):
    # The keyless local floor has no chain; a fallback list must not conjure a primary.
    monkeypatch.setattr(providers, 'active_text_provider', lambda: None)
    monkeypatch.setenv('ACP_TEXT_FALLBACK_PROVIDERS', 'openai')
    assert providers.permitted_text_providers() == frozenset()
