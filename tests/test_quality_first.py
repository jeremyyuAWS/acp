from dataclasses import replace
from types import SimpleNamespace
import pytest

from ai_run_policy import normalize_run_policy
from ai_spending_budget import BudgetError
from remediation_impact_settings import normalize_policy
from quality_first import configured_quality_generator
from test_llm_waterfall_provider import specs, FakeProviders


def policy(**changes):
    return normalize_policy(dict(rule_based=2, ai=1, ai_zone='any',
        cloud_input_strategy='automatic', quality_first=True, **changes))


def test_saved_and_accepted_quality_choice_preserves_cap_and_review():
    selected = policy(ai_budget_usd='3.00', ai_review={'enabled': False}, auto_approve_ai=False)
    frozen = normalize_run_policy(selected)
    assert frozen['quality_first'] is True
    assert frozen['ai_budget_usd'] == '3.00'
    assert frozen['auto_approve_ai'] is False
    assert not frozen['ai_review']['enabled']
    assert 'quality_first' not in normalize_run_policy({'ai': 1, 'ai_budget_usd': '3.00'})


@pytest.mark.parametrize('value', ['true', 1, None])
def test_invalid_quality_choice_rejected(value):
    with pytest.raises(ValueError):
        normalize_policy({'rule_based': 2, 'ai': 1, 'quality_first': value})
    with pytest.raises(BudgetError):
        normalize_run_policy({'ai': 1, 'ai_budget_usd': '3.00', 'quality_first': value})


def test_quality_choice_cannot_authorize_local_or_unbudgeted_run():
    with pytest.raises(ValueError):
        normalize_policy({'rule_based': 2, 'ai': 1, 'quality_first': True,
                          'ai_zone': 'local', 'ai_budget_usd': '0.00'})
    with pytest.raises(BudgetError):
        normalize_run_policy({'ai': 1, 'quality_first': True})


def test_quality_skips_local_text_without_even_loading_or_probing_model(monkeypatch):
    import ai
    from automatic_cloud_input import try_local_text_draft
    monkeypatch.setattr(ai, '_TAGS_CACHE', None)  # would crash if inspected
    assert try_local_text_draft('private text', SimpleNamespace(policy={'quality_first': True})) is None


def test_quality_vision_never_falls_back_to_ollama(monkeypatch):
    import ai, providers, vision_generation, llm_waterfall_provider
    monkeypatch.setattr(llm_waterfall_provider, 'managed_context', lambda: SimpleNamespace(
        policy={'quality_first': True}, enabled=True, local_drafting=False))
    monkeypatch.setattr(vision_generation, 'available', lambda: False)
    def forbidden(*args, **kwargs):
        pytest.fail('Local vision was called')
    monkeypatch.setattr(providers, 'OllamaVisionProvider', forbidden)
    assert ai._vision_generate('describe', b'image') is None


@pytest.mark.parametrize('selected', ['openai', 'anthropic'])
def test_quality_models_keep_owner_provider_first_and_require_both_permissions(specs, monkeypatch, selected):
    import native_pdf_quality
    models = [('openai', 'gpt-4.1-2025-04-14'), ('anthropic', 'claude-sonnet-5')]
    monkeypatch.setattr(native_pdf_quality, 'profile_specs', lambda: tuple(
        replace(specs[0], provider=p, model=m) for p, m in models))
    class Providers(FakeProviders):
        fallbacks = ('openai', 'anthropic')
        @staticmethod
        def zone_for_url(url):
            return 'cloud'
    providers = Providers
    providers.selected = selected
    generator = configured_quality_generator(provider_module=providers, post=lambda *a, **k: None)
    assert generator.specs[generator.models[0].name].provider == selected
    assert {m.name for m in generator.models} == {m for _, m in models}
    providers.fallbacks = ()
    with pytest.raises(ValueError):
        configured_quality_generator(provider_module=providers)


def test_quality_rejects_private_cloud_compatible_endpoint(specs, monkeypatch):
    import native_pdf_quality
    monkeypatch.setattr(native_pdf_quality, 'profile_specs', lambda: specs)
    class Providers(FakeProviders):
        @staticmethod
        def zone_for_url(url):
            return 'local'
    with pytest.raises(ValueError, match='cloud endpoints'):
        configured_quality_generator(provider_module=Providers())


def test_quality_readiness_blocks_without_probing_or_enabling_provider(monkeypatch):
    import quality_first
    from ai_plan_readiness import plan_ai_readiness
    def unavailable():
        raise ValueError('provider not authorized')
    monkeypatch.setattr(quality_first, 'configured_quality_generator', unavailable)
    assert plan_ai_readiness(policy()) == {'state': 'quality_first_cloud_unavailable', 'blocked': True}
    assert plan_ai_readiness({'ai': 1, 'ai_zone': 'any'})['blocked'] is False


def test_api_request_preserves_quality_choice():
    from routes.remediation_policy import ImpactPreviewRequest
    parsed = ImpactPreviewRequest(**policy()).model_dump(exclude_none=True)
    assert parsed['quality_first'] is True
    assert normalize_run_policy(normalize_policy(parsed))['quality_first'] is True


def test_dispatch_selects_quality_only_for_explicit_run(monkeypatch):
    import quality_first, llm_waterfall_provider
    sentinel = object()
    monkeypatch.setattr(quality_first, 'configured_quality_generator', lambda: sentinel)
    monkeypatch.setattr(llm_waterfall_provider, 'managed_context', lambda: SimpleNamespace(policy={'quality_first': True}))
    assert llm_waterfall_provider.configured_generator() is sentinel
    monkeypatch.setattr(llm_waterfall_provider, 'managed_context', lambda: SimpleNamespace(policy={}))
    monkeypatch.delenv('ACP_BOUNDED_TEXT_PROFILE', raising=False)
    monkeypatch.delenv('ACP_BOUNDED_TEXT_MODELS_JSON', raising=False)
    with pytest.raises(ValueError, match='verified model configurations'):
        llm_waterfall_provider.configured_generator()
