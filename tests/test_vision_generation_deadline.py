"""Cloud vision respects remaining assessment time without changing frozen prices."""
import pytest
import ai
import vision_generation as vision
from ai_run_policy import run_context
from llm_waterfall_provider import PreDispatchRejected
from test_vision_generation import setup, specs, image  # noqa: F401


def test_expired_budget_does_not_prepare_reserve_or_dispatch(setup, monkeypatch):
    store, job, calls, outputs = setup
    monkeypatch.setattr(vision, 'prepare_image', lambda data: pytest.fail('Prepared expired image'))
    with run_context(store, job['payload'], job), ai.assessment_vision_budget(0):
        result = vision.generate('Describe', image())
    assert result['reason'] == 'assessment_vision_budget_exhausted'
    assert not calls


def test_cloud_queue_wait_is_bounded_by_remaining_budget(setup, monkeypatch):
    store, job, calls, outputs = setup
    waits = []
    class Gate:
        def acquire(self, timeout):
            waits.append(timeout)
            return False
    monkeypatch.setattr(ai, '_CLOUD_VISION_GATE', Gate())
    with run_context(store, job['payload'], job), ai.assessment_vision_budget(0.5):
        result = vision.generate('Describe', image())
    assert 0 < waits[0] <= 0.5
    assert result['reason'] == 'cloud_capacity_busy'
    assert not calls


def test_elapsed_primary_prevents_paid_fallback_and_releases_unused_reservation(setup, monkeypatch):
    store, job, calls, outputs = setup
    # Advance only the vision deadline clock; model catalog verification stays real.
    clock = [0.0]
    monkeypatch.setattr(vision.time, 'monotonic', lambda: clock[0])
    original = vision._CaptionGenerator.generate_text
    def generate(self, model, prompt):
        result = original(self, model, prompt)
        clock[0] = 2.0
        return result
    monkeypatch.setattr(vision._CaptionGenerator, 'generate_text', generate)
    outputs.append('~~~~~~')
    with run_context(store, job['payload'], job) as ctx, ai.assessment_vision_budget(1):
        result = vision.generate('Describe', image())
        assert ctx.deferred[-1]['reason'] == 'assessment_vision_budget_exhausted'
    assert len(calls) == 1
    assert result['reason'] == 'assessment_vision_budget_exhausted'
    assert result['attempts'][0]['status'] == 'unusable_response'
    assert result['attempts'][1]['status'] == 'rejected_before_dispatch'


def test_transport_uses_lower_per_call_timeout_without_mutating_specs(monkeypatch):
    from types import SimpleNamespace
    sends = []
    spec = SimpleNamespace(timeout_seconds=30)
    generator = SimpleNamespace(specs={'model': spec}, post=lambda endpoint, **kw:
        sends.append(kw['timeout']) or SimpleNamespace(status_code=200))
    wrapped = vision._rate_limit_retry(generator)
    with ai.assessment_vision_budget(0.5):
        wrapped.post('https://fixture', timeout=spec.timeout_seconds)
    assert 0 < sends[0] <= 0.5
    assert spec.timeout_seconds == 30


def test_rate_limit_cooldown_cannot_dispatch_after_deadline(monkeypatch):
    from types import SimpleNamespace
    sends = []
    generator = SimpleNamespace(post=lambda endpoint, **kw: sends.append(1) or
        SimpleNamespace(status_code=429, headers={'retry-after': '1'}))
    with ai.assessment_vision_budget(0.5), pytest.raises(PreDispatchRejected,
            match='assessment_vision_budget_exhausted'):
        vision._rate_limit_retry(generator).post('https://fixture', timeout=30)
    assert len(sends) == 1
