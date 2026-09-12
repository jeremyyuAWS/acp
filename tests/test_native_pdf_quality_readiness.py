"""Preview uses actual factory validation without calls, secrets or reservations."""
from dataclasses import replace

import pytest
import native_pdf_quality as quality
import remediation_impact as impact
from test_remediation_impact import Facts
from test_llm_waterfall_provider import FakeProviders, specs

POLICY = {'rule_based': 2, 'ai': 1, 'ai_zone': 'any', 'ai_budget_usd': '10.00',
          'document_wide_ai': True, 'document_wide_input_mode': 'native_pdf',
          'document_wide_model_profile': 'native-pdf-quality.v1'}


@pytest.fixture
def preflight(monkeypatch, specs):
    facts = Facts()
    monkeypatch.setattr(impact, 'load_run_findings', lambda *a: ([], [
        {'file': 'a.pdf', 'complete': True}, {'file': 'b.docx', 'complete': True}]))
    import ai_generation_chain
    monkeypatch.setattr(ai_generation_chain, 'chain_options', lambda *a: {'supported': False, 'models': []})
    class Providers(FakeProviders):
        selected = 'anthropic'
        fallbacks = ('openai',)
        missing = None
        @classmethod
        def _text_key_for(cls, provider):
            return '' if provider == cls.missing else 'fixture-key-never-rendered'
    selected_specs = tuple(replace(specs[0], provider=p, model=m) for p, m in quality.MODELS)
    monkeypatch.setattr(quality, 'profile_specs', lambda: selected_specs)
    factory = quality.configured_native_pdf_generator
    monkeypatch.setattr(quality, 'configured_native_pdf_generator', lambda ctx, **kw:
                        factory(ctx, provider_module=Providers, **kw))
    return facts, Providers, selected_specs


@pytest.mark.parametrize('failure', ['permission', 'openai-key', 'anthropic-key', 'expired', 'model', 'endpoint'])
def test_quality_preflight_blocks_missing_current_requirements(preflight, monkeypatch, failure):
    facts, providers, selected_specs = preflight
    if failure == 'permission': providers.fallbacks = ()
    elif failure.endswith('-key'): providers.missing = failure.split('-')[0]
    elif failure == 'expired': monkeypatch.setattr(quality, 'profile_specs', lambda: (replace(selected_specs[0], verified_until=1), selected_specs[1]))
    elif failure == 'model': monkeypatch.setattr(quality, 'profile_specs', lambda: (replace(selected_specs[0], model='unknown'), selected_specs[1]))
    elif failure == 'endpoint': providers._OPENAI_TEXT_BASE_URL = ''
    result = impact.build_run_impact(facts, 's', 'demo', POLICY)
    assert result['capabilities']['execute'] is False
    assert 'PDF quality profile is not ready' in result['capabilities']['reason']
    assert 'fixture-key' not in str(result)


def test_quality_preflight_ready_does_not_call_provider_or_change_global_order(preflight):
    facts, providers, _ = preflight
    result = impact.build_run_impact(facts, 's', 'demo', POLICY)
    assert result['capabilities']['execute'] is True
    assert providers.active_text_provider() == 'anthropic'


def test_ordinary_and_docx_only_plans_do_not_require_quality_providers(preflight, monkeypatch):
    facts, providers, _ = preflight
    providers.fallbacks = ()
    standard = {k: v for k, v in POLICY.items() if k != 'document_wide_model_profile'}
    assert impact.build_run_impact(facts, 's', 'demo', standard)['capabilities']['execute']
    assert impact.build_run_impact(facts, 's', 'demo', POLICY, scope=['b.docx'])['capabilities']['execute']
