"""Admission wait is measured before generation, never inferred from total latency."""
from types import SimpleNamespace
import json
import pytest


def test_local_queue_wait_includes_local_and_shared_admission_but_not_generation(monkeypatch):
    import ai, llm_waterfall_provider, vision_admission
    now = [10.0]
    monkeypatch.setattr(ai.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(llm_waterfall_provider, 'managed_context', lambda: None)
    monkeypatch.setattr(ai, '_leave_vision_capacity', lambda: None)
    def local(wait):
        now[0] += 1.25
        return True
    monkeypatch.setattr(ai, '_enter_vision_capacity', local)
    def shared(*args, **kwargs):
        now[0] += 2.5
        return SimpleNamespace(admitted=True, ownership_lost=False, release=lambda: None)
    monkeypatch.setattr(vision_admission, 'configured_admission', lambda: SimpleNamespace(acquire=shared))
    def generate(*args, **kwargs):
        now[0] += 100
        return {'ok': True, 'text': 'A blue square.', 'timing': {'model_load_ms': 12, 'queue_wait_ms': 99999, 'content': 'PRIVATE'}}
    provider = SimpleNamespace(name='ollama', model='vision', zone='local', base_url='http://localhost', generate=generate)
    result = ai._bounded_vision_generate(provider, 'describe', b'image')
    assert result['timing'] == {'model_load_ms': 12, 'queue_wait_ms': 3750}


def test_blocked_queue_retains_measured_wait_without_dispatch(monkeypatch):
    import ai, llm_waterfall_provider
    now = [0.0]
    monkeypatch.setattr(ai.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(llm_waterfall_provider, 'managed_context', lambda: None)
    def blocked(wait):
        now[0] += .25
        return False
    monkeypatch.setattr(ai, '_enter_vision_capacity', blocked)
    provider = SimpleNamespace(name='ollama', model='vision', zone='local', generate=lambda *a, **kw: pytest.fail('dispatched'))
    result = ai._bounded_vision_generate(provider, 'describe', b'image')
    assert result['reason'] == 'capacity_busy'
    assert result['timing']['queue_wait_ms'] == 250


def test_queue_wait_is_numeric_only_in_durable_trace(isolated_store):
    from ollama_runtime import safe_timings
    assert safe_timings({'queue_wait_ms': 1.23456, 'content': 'PRIVATE'}) == {'queue_wait_ms': 1.235}
    assert safe_timings({'queue_wait_ms': True}) == {}
    isolated_store.record_ai_call(surface='vision', provider='ollama', model='m', zone='local', latency_ms=30, ok=True,
                                 timing={'queue_wait_ms': 2.5, 'content': 'PRIVATE'})
    rows = isolated_store.list_ai_calls()
    assert json.loads(rows[0]['timing']) == {'queue_wait_ms': 2.5}
    assert 'PRIVATE' not in json.dumps(rows)


from test_vision_generation import setup, image
from test_llm_waterfall_provider import specs


def test_managed_image_queue_wait_reaches_exact_attempt_trace(setup, monkeypatch):
    import vision_generation as vision
    from ai_run_policy import run_context
    store, job, calls, outputs = setup
    outputs.append('A blue square on a white background.')
    now = [10.0]
    monkeypatch.setattr(vision.time, 'monotonic', lambda: now[0])
    class Gate:
        def acquire(self, **kwargs):
            now[0] += 2
            return True
        def release(self): pass
    import ai
    monkeypatch.setattr(ai, '_CLOUD_VISION_GATE', Gate())
    generate = vision.managed_generate_attempts
    def slow_generation(*args, **kwargs):
        now[0] += 100
        return generate(*args, **kwargs)
    monkeypatch.setattr(vision, 'managed_generate_attempts', slow_generation)
    with run_context(store, job['payload'], job):
        result = vision.generate('Describe', image())
    assert result['ok']
    assert len(calls) == 1
    row = store.list_ai_calls('scan')[0]
    assert json.loads(row['timing'])['queue_wait_ms'] == 2000
    assert row['latency_ms'] == 102000


@pytest.mark.parametrize('exhausted', [False, True])
def test_managed_blocked_admission_retains_durable_zero_dispatch_timing(setup, monkeypatch, exhausted):
    import ai, vision_generation as vision
    from ai_run_policy import run_context
    store, job, calls, outputs = setup
    now = [10.0]
    monkeypatch.setattr(vision.time, 'monotonic', lambda: now[0])
    class Gate:
        def acquire(self, timeout):
            now[0] += timeout if exhausted else .25
            return False
        def release(self):
            pytest.fail('Unowned semaphore released')
    monkeypatch.setattr(ai, '_CLOUD_VISION_GATE', Gate())
    with run_context(store, job['payload'], job), ai.assessment_vision_budget(.5):
        result = vision.generate('Describe', image())
    assert result['reason'] == ('assessment_vision_budget_exhausted' if exhausted else 'cloud_capacity_busy')
    assert result['timing']['queue_wait_ms'] == (500 if exhausted else 250)
    assert not calls
    row = store.list_ai_calls('scan')[0]
    assert row['ok'] == 0 and row['model'] == 'not-dispatched'
    assert row['reason'] == result['reason']
    assert json.loads(row['timing']) == result['timing']
    assert float(row['cost_usd']) == 0
