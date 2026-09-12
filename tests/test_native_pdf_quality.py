"""Scoped native PDF routing with real managed reservations and fake HTTP only."""
from dataclasses import replace
import json
from types import MappingProxyType

import pytest
import document_wide_provider as provider
import native_pdf_quality as quality
from ai_run_policy import run_context, read_run_budget
from ai_attempt_history import AttemptHistory
from test_document_wide_provider import setup, request_package, response
from test_document_wide_pdf_transport import pdf_request, output
from test_llm_waterfall_provider import specs, FakeProviders, Response


def policy(ctx, **overrides):
    return replace(ctx, policy=MappingProxyType({**ctx.policy, 'document_wide_ai': True,
        'ai_zone': 'any', 'document_wide_input_mode': 'native_pdf',
        'document_wide_model_profile': quality.PROFILE_ID, **overrides}))


@pytest.mark.parametrize('mode', ['success', 'fallback', 'unknown', 'both_invalid'])
def test_exact_native_primary_fallback_and_accounted_replay(setup, pdf_request, specs, monkeypatch, mode):
    store, job, calls, _ = setup
    request, data = pdf_request
    monkeypatch.setattr(quality, 'profile_specs', lambda: tuple(replace(specs[0], provider=p, model=m,
        context_token_limit=32768) for p, m in quality.MODELS))
    class Providers(FakeProviders):
        selected = 'anthropic'  # Global default must remain Anthropic.
        fallbacks = ('openai',)
    def post(url, **kwargs):
        calls.append((url, kwargs['json']))
        if mode == 'unknown':
            raise TimeoutError('uncertain transport')
        model = kwargs['json']['model']
        raw = {} if mode == 'both_invalid' or (mode == 'fallback' and len(calls) == 1) else response(request)
        if model == quality.MODELS[0][1]:
            result = output(model)
            result['output'][0]['content'][0]['text'] = json.dumps(raw)
        else:
            result = {'id': 'fallback-call', 'model': model, 'stop_reason': 'end_turn',
                      'usage': {'input_tokens': 9000, 'output_tokens': 20},
                      'content': [{'type': 'text', 'text': json.dumps(raw)}]}
        return Response(result)
    factory = quality.configured_native_pdf_generator
    monkeypatch.setattr(quality, 'configured_native_pdf_generator', lambda ctx: factory(ctx, provider_module=Providers, post=post))
    monkeypatch.setattr(provider, 'configured_generator', lambda: pytest.fail('native profile must not use global model factory'))
    with run_context(store, job['payload'], job) as ctx:
        native = policy(ctx)
        monkeypatch.setattr(provider, 'managed_context', lambda: native)
        result = provider.generate_document(request, pdf_bytes=data)
        if mode in ('success', 'fallback'):
            assert not result['deferred']
            replay = provider.generate_document(request, pdf_bytes=data)
            assert replay['replayed'] and replay['model_call_id'] == result['model_call_id']
        budget = read_run_budget(store, ctx.owner_id, ctx.scan_id, ctx.run_id)
        history = AttemptHistory(store._db).list_run(ctx.owner_id, ctx.scan_id, ctx.run_id)
    assert Providers.active_text_provider() == 'anthropic'
    assert len(calls) == (1 if mode in ('success','unknown') else 2)
    assert calls[0][0].endswith('/responses') and calls[0][1]['model'] == quality.MODELS[0][1]
    assert quality.PROFILE_ID in calls[0][1]['input'][0]['content'][1]['text']
    if len(calls) == 2:
        assert calls[1][0].endswith('/messages') and calls[1][1]['model'] == quality.MODELS[1][1]
        assert calls[1][1]['messages'][0]['content'][0]['type'] == 'document'
    if mode == 'unknown':
        assert result['deferred'] and budget['held_units'] > 0 and len(history) == 1
    else:
        assert budget['spent_units'] > 0 and budget['held_units'] == 0
        assert all(h['spending_state']=='settled' for h in history)


@pytest.mark.parametrize('changes', [{'document_wide_model_profile':None}, {'document_wide_input_mode':'extracted'},
    {'ai_zone':'local'}, {'document_wide_ai':False}, {'cap_units':0}])
def test_profile_authorization_requires_frozen_native_cloud_selection(setup, monkeypatch, changes):
    store, job, _, _ = setup
    with run_context(store, job['payload'], job) as ctx:
        with pytest.raises(ValueError, match='not_authorized'):
            quality.configured_native_pdf_generator(policy(ctx, **changes), provider_module=FakeProviders)


def test_missing_provider_key_fails_before_transport(setup, monkeypatch):
    store, job, _, _ = setup
    class Providers(FakeProviders):
        fallbacks = ('anthropic',)
        @staticmethod
        def _text_key_for(provider): return None if provider == 'anthropic' else 'fixture'
    with run_context(store, job['payload'], job) as ctx:
        with pytest.raises(ValueError, match='credential unavailable'):
            quality.configured_native_pdf_generator(policy(ctx), provider_module=Providers,
                post=lambda *a, **k: pytest.fail('no paid call'))


def test_scoped_context_preserves_original_identity_and_generic_chain(setup):
    store, job, _, _ = setup
    with run_context(store, job['payload'], job) as ctx:
        native=policy(ctx, generation_chain={'version':1,'steps':['original']})
        scoped=quality.native_profile_context(native)
        assert 'generation_chain' not in scoped.policy
        assert native.policy['generation_chain']['steps']==['original']
        assert scoped.ledger is native.ledger and scoped.deferred is native.deferred
        assert (scoped.owner_id,scoped.scan_id,scoped.run_id,scoped.file)==(native.owner_id,native.scan_id,native.run_id,native.file)


def test_profile_field_does_not_reroute_extracted_pdf(setup, pdf_request, monkeypatch):
    store, job, calls, outputs = setup
    request, _ = pdf_request
    outputs.append(response(request))
    monkeypatch.setattr(quality, 'configured_native_pdf_generator', lambda *a: pytest.fail('extracted PDF must retain global routing'))
    with run_context(store, job['payload'], job) as ctx:
        monkeypatch.setattr(provider, 'managed_context', lambda: policy(ctx, document_wide_input_mode='extracted'))
        result=provider.generate_document(request)
    assert not result['deferred'] and len(calls)==1
    assert calls[0]['model']=='small-pinned-v1'
    assert 'Native PDF model profile:' not in calls[0]['messages'][0]['content']


@pytest.mark.parametrize('change', [{'ai_zone':'local'},{'ai':0},{'cap_units':0}])
def test_disabled_local_profiles_never_enter_factory(setup,pdf_request,monkeypatch,change):
    store,job,calls,_=setup
    request,data=pdf_request
    monkeypatch.setattr(quality,'configured_native_pdf_generator',lambda *a:pytest.fail('no model setup for disabled/local run'))
    with run_context(store,job['payload'],job) as ctx:
        monkeypatch.setattr(provider,'managed_context',lambda:policy(ctx,**change))
        assert provider.generate_document(request,pdf_bytes=data)['deferred']
    assert not calls


def test_profile_cannot_override_admin_provider_withdrawal(setup):
    store, job, _, _ = setup
    class Providers(FakeProviders):
        selected = 'anthropic'
        fallbacks = ()  # OpenAI credential exists, but admin has not permitted egress.
    with run_context(store, job['payload'], job) as ctx:
        with pytest.raises(ValueError, match='not authorised'):
            quality.configured_native_pdf_generator(policy(ctx), provider_module=Providers,
                post=lambda *a, **k: pytest.fail('must not dispatch'))


def test_revoked_permission_stops_existing_generator_before_http(setup, specs, monkeypatch):
    from llm_waterfall_provider import PreDispatchRejected
    store, job, _, _ = setup
    class Providers(FakeProviders):
        fallbacks = ('anthropic',)
    monkeypatch.setattr(quality, 'profile_specs', lambda: tuple(replace(specs[0], provider=p, model=m,
        context_token_limit=32768) for p, m in quality.MODELS))
    with run_context(store, job['payload'], job) as ctx:
        generator = quality.configured_native_pdf_generator(policy(ctx), provider_module=Providers,
            post=lambda *a, **k: pytest.fail('permission revoked before paid HTTP'))
        Providers.fallbacks = ()
        with pytest.raises(PreDispatchRejected, match='governance changed'):
            generator.generate_text(quality.MODELS[1][1], 'test')
