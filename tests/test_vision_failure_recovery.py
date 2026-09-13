"""Only exhausted drafting misses schedule recovery; dependency misses aren't repeated."""
from types import SimpleNamespace
import ai
import providers
import vision_recovery
import vision_generation
import llm_waterfall_provider


def setup(monkeypatch, context=None):
    monkeypatch.setattr(llm_waterfall_provider, 'managed_context', lambda: context)
    monkeypatch.setattr(vision_generation, 'available', lambda: False)
    monkeypatch.setattr(providers, 'active_vision_provider', lambda: SimpleNamespace(name='ollama'))


def test_timeout_skips_immediate_same_gpu_retry_and_recovers_final_miss(monkeypatch):
    setup(monkeypatch, SimpleNamespace(local_drafting=True, enabled=False))
    calls = []
    monkeypatch.setattr(ai, '_vision_generate', lambda *a, **k: (calls.append(1), ai._vision_failed('timeout'))[1])
    monkeypatch.setattr(ai, '_escalate_vision', lambda *a, **k: (_ for _ in ()).throw(AssertionError('Unbudgeted cloud')))
    with vision_recovery.capture() as misses:
        assert ai.describe_image(b'image') is None
    assert calls == [1]
    assert misses == ['timeout']


def test_successful_cloud_fallback_does_not_schedule_local_miss(monkeypatch):
    setup(monkeypatch)
    calls = []
    monkeypatch.setattr(ai, '_vision_generate', lambda *a, **k: (calls.append(1), ai._vision_failed('circuit_open'))[1])
    monkeypatch.setattr(ai, '_escalate_vision', lambda *a, **k: dict(alt='A red bicycle beside a brick wall.', model='cloud',
        provider='cloud', zone='cloud', cost_usd=0, steps=[]))
    with vision_recovery.capture() as misses:
        assert ai.describe_image(b'image')['model'] == 'cloud'
    assert calls == [1]
    assert misses == []
    assert ai.vision_failure_reason() is None


def test_empty_reply_still_gets_smaller_prompt_once(monkeypatch):
    setup(monkeypatch)
    calls = []
    def generate(*args, **kwargs):
        calls.append(1)
        return ai._vision_failed('empty') if len(calls) == 1 else 'A red bicycle beside a brick wall.'
    monkeypatch.setattr(ai, '_vision_generate', generate)
    with vision_recovery.capture() as misses:
        assert ai.describe_image(b'image')['alt']
    assert calls == [1, 1]
    assert misses == []
