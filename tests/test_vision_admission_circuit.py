"""Capacity/coordination rejection cannot strand a provider's half-open probe."""
import pytest
import ai
import providers
from test_vision_circuit_breaker import _Provider, _result


@pytest.mark.parametrize('reason', ['capacity_busy', 'shared_capacity_busy',
    'shared_coordination_unavailable', 'assessment_vision_budget_exhausted'])
def test_admission_rejection_releases_half_open_probe_for_later_recovery(monkeypatch, reason):
    provider = _Provider([])
    monkeypatch.setattr('llm_waterfall_provider.managed_context', lambda: None)
    monkeypatch.setattr(providers, 'active_vision_provider', lambda: provider)
    monkeypatch.setattr(ai, '_trace_ai', lambda *a, **kw: None)
    key = (provider.name, provider.base_url, provider.model)
    monkeypatch.setattr(ai, '_VISION_CIRCUITS', {key: {
        'opened_at': ai.time.monotonic() - ai.VISION_CIRCUIT_COOLDOWN - 1,
        'reason': providers.REASON_TIMEOUT, 'failures': 1}})
    outcomes = iter([_result(reason=reason), _result(ok=True, reason=providers.REASON_OK,
                                                   text='A useful chart description')])
    monkeypatch.setattr(ai, '_bounded_vision_generate', lambda *a, **kw: next(outcomes))
    assert ai._vision_generate('Describe', b'IMG', scan_id='scan') is None
    assert not ai._VISION_CIRCUITS[key]['probing']
    assert ai._vision_generate('Describe', b'IMG', scan_id='scan') == 'A useful chart description'
    assert key not in ai._VISION_CIRCUITS
