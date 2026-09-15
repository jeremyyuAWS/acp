"""Offline assessment routing evidence; optional AI misses never certify a document."""
from types import SimpleNamespace
import pytest
import ai
import vision_generation as vision
import llm_waterfall_provider as waterfall
import providers


@pytest.mark.parametrize('reason', ['quality_first_cloud_vision_unavailable',
    'cloud_capacity_busy', 'assessment_vision_budget_exhausted'])
def test_quality_first_never_probes_or_dispatches_local_after_cloud_miss(monkeypatch, reason):
    ctx = SimpleNamespace(enabled=True, local_drafting=False, policy={'quality_first': True})
    monkeypatch.setattr(waterfall, 'managed_context', lambda: ctx)
    monkeypatch.setattr(vision, 'available', lambda: reason != 'quality_first_cloud_vision_unavailable')
    monkeypatch.setattr(vision, 'generate', lambda *a, **kw: {'ok': False, 'reason': reason})
    monkeypatch.setattr(providers, 'active_vision_provider', lambda: pytest.fail('Legacy provider selected'))
    monkeypatch.setattr(ai, '_tags_cached', lambda: pytest.fail('Local model probe'))
    monkeypatch.setattr(ai, '_bounded_vision_generate', lambda *a, **kw: pytest.fail('Local dispatched'))
    assert ai._vision_generate('Describe', b'image', scan_id='scan', file='a.pdf') is None
    assert ai.vision_failure_reason() == reason


@pytest.mark.parametrize('override', [None, 'minicpm-v:latest'])
def test_known_missing_primary_and_override_models_do_not_dispatch(monkeypatch, override):
    traces = []
    monkeypatch.setattr(waterfall, 'managed_context', lambda: None)
    provider = providers.OllamaVisionProvider(ai.OLLAMA_BASE_URL, 'missing-primary:latest')
    monkeypatch.setattr(providers, 'active_vision_provider', lambda: provider)
    monkeypatch.setattr(ai, '_tags_cached', lambda: [{'name': 'moondream:latest'}])
    monkeypatch.setattr(ai, '_bounded_vision_generate', lambda *a, **kw: pytest.fail('Unavailable model dispatched'))
    monkeypatch.setattr(ai, '_trace_ai', lambda *a, **kw: traces.append(kw))
    assert ai._vision_generate('Describe', b'image', model=override, scan_id='scan', file='a.pdf') is None
    assert ai.vision_failure_reason() == 'model_not_installed'
    assert traces[0]['reason'] == 'model_not_installed'


def test_unavailable_model_probe_does_not_assert_model_absence(monkeypatch):
    monkeypatch.setattr(waterfall, 'managed_context', lambda: None)
    provider = providers.OllamaVisionProvider(ai.OLLAMA_BASE_URL, 'missing-primary:latest')
    monkeypatch.setattr(providers, 'active_vision_provider', lambda: provider)
    monkeypatch.setattr(ai, '_tags_cached', lambda: None)
    monkeypatch.setattr(ai, '_trace_ai', lambda *a, **kw: 'offline-call')
    monkeypatch.setattr(ai, '_bounded_vision_generate', lambda *a, **kw: {
        'ok': True, 'text': 'A blue square on white paper.', 'model': provider.model, 'reason': 'ok'})
    ai.reset_vision_circuits()
    assert ai._vision_generate('Describe', b'image', scan_id='scan', file='a.pdf')
