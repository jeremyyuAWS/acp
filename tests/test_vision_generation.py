"""Actual image HTTP bodies + durable spending, offline synthetic providers."""
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace
import time

import pytest
from PIL import Image
import ai
import vision_generation as vision
from ai_run_policy import run_context
from ai_attempt_history import AttemptHistory
from test_ai_run_policy import seed, enqueue
from test_llm_waterfall_provider import specs, FakeProviders, Response, result
from llm_waterfall_provider import StrictTextGenerator


def image(color='red'):
    out = BytesIO()
    Image.new('RGB', (16, 16), color).save(out, format='PNG')
    return out.getvalue()


@pytest.fixture
def setup(isolated_store, monkeypatch, specs):
    import core, lf
    monkeypatch.setattr(core, 'store', isolated_store)
    monkeypatch.setattr(lf, 'trace_ai_call', lambda *a, **kw: None)
    seed(isolated_store)
    batch = enqueue(isolated_store, files=('a.pdf',))
    job = isolated_store.get_job(batch['job_ids'][0])
    specs = tuple(replace(s, model=name, context_token_limit=20000) for s, name in zip(specs,
        ('gpt-4.1-mini-2025-04-14', 'gpt-4.1-2025-04-14')))
    calls, outputs = [], []
    def post(*args, **kwargs):
        calls.append(kwargs['json'])
        output = outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return Response(result(model=kwargs['json']['model'], text=output))
    generator = StrictTextGenerator(specs, provider_module=FakeProviders, post=post)
    monkeypatch.setattr(vision, 'configured_generator', lambda: generator)
    return isolated_store, job, calls, outputs


def test_cloud_plan_generates_image_caption_without_gpu_and_replays(setup, monkeypatch):
    store, job, calls, outputs = setup
    outputs.append('A red bicycle leaning against a brick wall.')
    monkeypatch.setattr(ai, '_bounded_vision_generate', lambda *a, **kw: pytest.fail('GPU was used'))
    with run_context(store, job['payload'], job) as ctx:
        assert ai.vision_is_available()
        first = ai._vision_generate('Describe', image(), scan_id='scan', file='a.pdf')
        again = ai._vision_generate('Describe', image(), scan_id='scan', file='a.pdf')
    assert first == again == 'A red bicycle leaning against a brick wall.'
    assert first.ai_call_id
    assert len(calls) == 1
    blocks = calls[0]['messages'][0]['content']
    assert blocks[-1]['image_url']['url'].startswith('data:image/png;base64,')
    assert len(store.list_ai_calls('scan')) == 1


def test_unusable_caption_falls_through_to_next_authorized_model(setup):
    store, job, calls, outputs = setup
    outputs.extend(['~~~~~~', 'A red bicycle leaning against a brick wall.'])
    with run_context(store, job['payload'], job) as ctx:
        generated = vision.generate('Describe', image())
        rows = AttemptHistory(store._db).list_run(ctx.owner_id, ctx.scan_id, ctx.run_id)
    assert generated['ok']
    assert generated['model'] == 'gpt-4.1-2025-04-14'
    assert len(calls) == len(rows) == 2
    assert all(row['spending_state'] == 'settled' for row in rows)
    assert generated['approval_required'] is True


def test_different_images_do_not_share_durable_caption(setup):
    store, job, calls, outputs = setup
    outputs.extend(['A red bicycle beside a brick wall.', 'A blue bicycle beside a brick wall.'])
    with run_context(store, job['payload'], job):
        red = vision.generate('Describe', image())
        blue = vision.generate('Describe', image('blue'))
    assert red['operation_id'] != blue['operation_id']
    assert len(calls) == 2


def test_timeout_keeps_uncertain_spend_and_never_blindly_buys_fallback(setup):
    store, job, calls, outputs = setup
    outputs.append(TimeoutError())
    with run_context(store, job['payload'], job) as ctx:
        generated = vision.generate('Describe', image())
        rows = AttemptHistory(store._db).list_run(ctx.owner_id, ctx.scan_id, ctx.run_id)
    assert not generated['ok']
    assert generated['reason'] == 'provider_usage_unknown'
    assert len(calls) == len(rows) == 1
    assert rows[0]['spending_state'] == 'uncertain'


def test_invalid_image_is_rejected_before_spending(setup):
    store, job, calls, outputs = setup
    with run_context(store, job['payload'], job):
        generated = vision.generate('Describe', b'not an image')
    assert not generated['ok'] and not calls


def test_local_only_never_opens_cloud_transport(monkeypatch):
    ctx = SimpleNamespace(enabled=True, policy={'ai_zone': 'local'})
    monkeypatch.setattr(vision, 'managed_context', lambda: ctx)
    monkeypatch.setattr(vision, 'configured_generator', lambda: pytest.fail('Cloud initialized'))
    assert not vision.available()
    assert vision.generate('Describe', image())['reason'] == 'vision_cloud_consent_required'


def test_missing_configured_credentials_is_unavailable(monkeypatch):
    ctx = SimpleNamespace(enabled=True, policy={'ai_zone': 'cloud'})
    monkeypatch.setattr(vision, 'managed_context', lambda: ctx)
    def missing():
        raise ValueError('selected provider credential unavailable')
    monkeypatch.setattr(vision, 'configured_generator', missing)
    assert not vision.available()


def test_rate_limit_retries_are_bounded_and_do_not_retry_timeouts(monkeypatch):
    sleeps, calls = [], []
    responses = [SimpleNamespace(status_code=429, headers={'retry-after': '0.1'}),
                 SimpleNamespace(status_code=429, headers={}), SimpleNamespace(status_code=200)]
    monkeypatch.setattr(vision.time, 'sleep', sleeps.append)
    generator = SimpleNamespace(post=lambda *a, **kw: calls.append(1) or responses.pop(0))
    assert vision._rate_limit_retry(generator).post('url').status_code == 200
    assert len(calls) == 3 and sleeps == [0.1, 1.0]
    calls.clear()
    def timeout(*a, **kw):
        calls.append(1)
        raise TimeoutError()
    with pytest.raises(TimeoutError):
        vision._rate_limit_retry(SimpleNamespace(post=timeout)).post('url')
    assert len(calls) == 1


def test_rate_limit_long_cooldown_is_not_ignored(monkeypatch):
    monkeypatch.setattr(vision.time, 'sleep', lambda *a: pytest.fail('Long wait'))
    responses = []
    response = SimpleNamespace(status_code=429, headers={'retry-after': '60'})
    generator = SimpleNamespace(post=lambda *a, **kw: responses.append(1) or response)
    assert vision._rate_limit_retry(generator).post('url') is response
    assert len(responses) == 1


def test_assessment_cloud_fallback_does_not_share_busy_gpu_gate(monkeypatch):
    import threading
    import providers
    monkeypatch.setattr('llm_waterfall_provider.managed_context', lambda: None)
    gate = threading.BoundedSemaphore(1)
    assert gate.acquire()
    monkeypatch.setattr(ai, '_VISION_GATE', gate)
    monkeypatch.setattr(ai, '_CLOUD_VISION_GATE', threading.BoundedSemaphore(1))
    cloud = SimpleNamespace(name='anthropic', zone='cloud', model='configured-vision',
        generate=lambda *a, **kw: {'ok': True, 'text': 'A red bicycle beside a brick wall.',
                                  'model': 'configured-vision', 'provider': 'anthropic',
                                  'zone': 'cloud', 'cost_usd': 0.001})
    monkeypatch.setattr(providers, 'cloud_vision_provider', lambda: cloud)
    monkeypatch.setattr(ai, '_trace_ai', lambda *a, **kw: 'cloud-call')
    generated = ai._escalate_vision('Describe', image(), scan_id='scan', file='a.pdf')
    assert generated['provider'] == 'anthropic'
    assert generated['cost_usd'] == 0.001 and generated['ai_call_id'] == 'cloud-call'
    gate.release()


def test_selected_assessment_cloud_does_not_require_installed_ollama(monkeypatch):
    import providers
    monkeypatch.setattr('llm_waterfall_provider.managed_context', lambda: None)
    monkeypatch.setattr(providers, 'active_vision_provider', lambda: SimpleNamespace(name='anthropic'))
    monkeypatch.setattr(ai, '_tags_cached', lambda: pytest.fail('Unrelated GPU probe'))
    assert ai.vision_is_available()
    assert ai.vision_unavailable_reason() is None


def test_paid_timeout_does_not_buy_minimal_prompt_retry_in_describe_image(setup):
    store, job, calls, outputs = setup
    outputs.append(TimeoutError())
    with run_context(store, job['payload'], job):
        assert ai.describe_image(image(), filename='a.pdf', scan_id='scan', file='a.pdf') is None
    assert len(calls) == 1


def test_caption_returns_actual_cloud_provider_model_and_cost(setup):
    store, job, calls, outputs = setup
    outputs.append('A red bicycle leaning against a brick wall.')
    with run_context(store, job['payload'], job):
        described = ai.describe_image(image(), filename='a.pdf', scan_id='scan', file='a.pdf')
    assert described['model'] == 'gpt-4.1-mini-2025-04-14'
    assert described['provider'] == 'openai'
    assert described['processing_zone'] == 'fixture'
    assert described['cost_usd'] == '0.00012'


def test_unmanaged_selected_cloud_timeout_does_not_repeat_paid_call(monkeypatch):
    import providers
    calls = []
    monkeypatch.setattr('llm_waterfall_provider.managed_context', lambda: None)
    provider = SimpleNamespace(name='openai', model='configured-cloud', zone='cloud',
        generate=lambda *a, **kw: calls.append(1) or {'ok': False, 'reason': 'timeout',
                                                    'provider': 'openai', 'model': 'configured-cloud'})
    monkeypatch.setattr(providers, 'active_vision_provider', lambda: provider)
    monkeypatch.setattr(providers, 'local_vision_provider', lambda: SimpleNamespace(name='disabled'))
    monkeypatch.setattr(ai, '_trace_ai', lambda *a, **kw: 'failure-call')
    monkeypatch.setattr(providers, 'cloud_vision_provider', lambda: pytest.fail('Repeated escalation'))
    assert ai.describe_image(image(), scan_id='scan', file='a.pdf') is None
    assert len(calls) == 1


def test_real_anthropic_profile_supports_first_two_image_models_and_ignores_text_only_third(monkeypatch):
    from ai_model_profiles import model_config
    from llm_waterfall_provider import TextModelSpec
    monkeypatch.setattr(FakeProviders, 'selected', 'anthropic')
    configured = StrictTextGenerator(tuple(TextModelSpec(**s) for s in model_config(
        'anthropic-balanced', include_second_fallback=True)), provider_module=FakeProviders,
        post=lambda *a, **kw: pytest.fail('Configuration must not send a request'))
    monkeypatch.setattr(vision, 'configured_generator', lambda: configured)
    generator = vision.configured_vision_generator()
    assert len(configured.models) == 3
    assert [m.name for m in generator.models] == ['claude-haiku-4-5-20251001', 'claude-sonnet-5']
    assert configured.specs[configured.models[2].name].plain_text_only


def test_frozen_three_position_policy_uses_verified_image_prefix_without_changing_policy(isolated_store, monkeypatch):
    import json
    import core, lf
    from ai_model_profiles import model_config
    from llm_waterfall_provider import TextModelSpec, managed_generate_attempts
    monkeypatch.setattr(core, 'store', isolated_store)
    monkeypatch.setattr(lf, 'trace_ai_call', lambda *a, **kw: None)
    monkeypatch.setattr(FakeProviders, 'selected', 'anthropic')
    seed(isolated_store)
    specs = tuple(TextModelSpec(**s) for s in model_config('anthropic-balanced', include_second_fallback=True))
    chain = {'version': 1, 'steps': [dict(step_id=step, position=i, provider=s.provider,
        model=s.model, enabled=True, capabilities=['text']) for i, (step, s) in enumerate(zip(
            ('primary', 'fallback_1', 'fallback_2'), specs))]}
    policy = {'ai': 1, 'ai_budget_usd': '20.00', 'ai_zone': 'any', 'generation_chain': chain}
    batch = isolated_store.enqueue_stage_batch('scan', 'remediate', 'remediate_file', [
        {'owner': 'owner', 'scan_id': 'scan', 'file': 'a.pdf', 'remediation_impact_policy': policy}],
        snapshot_id='snapshot', request_fingerprint='prefix')
    job = isolated_store.get_job(batch['job_ids'][0])
    calls = []
    def post(*args, **kw):
        calls.append(kw['json'])
        text = '~~~~~~' if len(calls) == 1 else 'A red bicycle beside a brick wall.'
        return Response({'model': kw['json']['model'], 'id': 'fixture-call',
            'usage': {'input_tokens': 100, 'output_tokens': 10}, 'stop_reason': 'end_turn',
            'content': [{'type': 'text', 'text': text}]})
    generator = StrictTextGenerator(specs, provider_module=FakeProviders, post=post)
    monkeypatch.setattr(vision, 'configured_generator', lambda: generator)
    with run_context(isolated_store, job['payload'], job) as ctx:
        before = json.dumps(dict(ctx.policy), sort_keys=True)
        generated = vision.generate('Describe', image())
        assert json.dumps(dict(ctx.policy), sort_keys=True) == before
        assert managed_generate_attempts('ordinary', ctx, generator, tier_indices=(1, 2))['reason'] == 'approved_generation_chain_mismatch'
        # Image-prefix mode retains source binding when an adapter is present.
        monkeypatch.setattr('ai_generation_adapter.current_generation_adapter', lambda: {
            'source_sha256': 'a'*64, 'assessment_revision': 'snapshot', 'finding_ids': ['finding'],
            'locator': 'image', 'adapter_id': 'fixture-image', 'validator': lambda t: None})
        from remediation_contribution import SOURCE
        token = SOURCE.set(('scan', 'a.pdf', 'b'*64))
        try:
            assert managed_generate_attempts('changed source', ctx, generator, tier_indices=(1, 2),
                image_prefix=True)['reason'] == 'assessed_source_changed'
        finally:
            SOURCE.reset(token)
    assert generated['ok']
    assert [c['model'] for c in calls] == ['claude-haiku-4-5-20251001', 'claude-sonnet-5']
    assert all(any(block.get('type') == 'image' for block in c['messages'][0]['content']) for c in calls)
