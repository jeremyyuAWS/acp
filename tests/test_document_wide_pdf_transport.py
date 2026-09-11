"""Native PDF requests use fake HTTP and synthetic prices; no cloud calls."""
import base64
from dataclasses import replace
import hashlib
from io import BytesIO
import json

import pikepdf
import pytest

from document_wide_pdf_transport import native_pdf_transport, _validate_pdf
from document_wide_provider import VISION_MODELS
from llm_waterfall_provider import StrictTextGenerator, PreDispatchRejected
from test_llm_waterfall_provider import specs, FakeProviders, Response
from test_document_wide_provider import request_package
from experiments.document_wide_ai.request.builder import build_request


@pytest.fixture
def pdf_request(request_package):
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page()
    target = BytesIO()
    pdf.save(target)
    data = target.getvalue()
    manifest = replace(request_package.manifest, source_sha256=hashlib.sha256(data).hexdigest())
    return build_request(manifest, request_id='native-pdf'), data


def make_generator(specs, post, provider='openai', context=32768):
    model = sorted(VISION_MODELS[provider])[0]
    spec = replace(specs[0], provider=provider, model=model, context_token_limit=context)
    class Providers(FakeProviders):
        selected = provider
    return StrictTextGenerator((spec, replace(spec, model=sorted(VISION_MODELS[provider])[1])), provider_module=Providers, post=post), model


def output(model, **overrides):
    return {'id': 'native-call', 'model': model, 'status': 'completed',
            'usage': {'input_tokens': 9000, 'output_tokens': 10},
            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{}'}]}], **overrides}


def test_openai_exact_pdf_responses_payload_and_measured_accounting(pdf_request, specs):
    request, data = pdf_request
    calls = []
    def post(url, **kw):
        calls.append((url, kw))
        return Response(output(kw['json']['model']))
    generator, model = make_generator(specs, post)
    native = native_pdf_transport(generator, request, data, VISION_MODELS)
    result = native.generate_text(model, 'JSON scoped manifest')
    assert result['cost_usd'] == '0.00902'
    assert result['prompt_tokens'] == 9000 and not result['bounds_exceeded']
    url, kw = calls[0]
    assert url == 'https://fixture.invalid/v1/responses'
    assert kw['follow_redirects'] is False
    payload = kw['json']
    assert payload['store'] is False and payload['max_output_tokens'] == 128
    blocks = payload['input'][0]['content']
    assert [b['type'] for b in blocks] == ['input_file', 'input_text']
    assert base64.b64decode(blocks[0]['file_data'].split(',', 1)[1]) == data
    assert 'messages' not in payload and 'max_completion_tokens' not in payload
    # Full verified context is reserved, including native pages, not tiny prompt.
    assert native.models[0].max_cost_usd == '0.033024'


def test_anthropic_exact_pdf_document_block(pdf_request, specs):
    request, data = pdf_request
    calls = []
    def post(url, **kw):
        calls.append((url, kw))
        return Response({'id': 'claude-call', 'model': kw['json']['model'],
                         'usage': {'input_tokens': 9000, 'output_tokens': 10},
                         'content': [{'type': 'text', 'text': '{}'}], 'stop_reason': 'end_turn'})
    generator, model = make_generator(specs, post, 'anthropic')
    result = native_pdf_transport(generator, request, data, VISION_MODELS).generate_text(model, 'JSON')
    assert result['cost_usd'] == '0.00902'
    assert calls[0][0] == 'https://fixture.invalid/messages'
    blocks = calls[0][1]['json']['messages'][0]['content']
    assert [b['type'] for b in blocks] == ['document', 'text']
    assert base64.b64decode(blocks[0]['source']['data']) == data


@pytest.mark.parametrize('bad', ['hash', 'malformed', 'encrypted', 'pages', 'oversized', 'docx'])
def test_invalid_pdf_never_reaches_transport(pdf_request, specs, bad):
    request, data = pdf_request
    if bad == 'hash': data += b'\n'
    elif bad == 'malformed': data = b'%PDF-1.7 garbage'
    elif bad == 'oversized': data = b' ' * (20 * 1024 * 1024 + 1)
    elif bad in ('encrypted', 'pages'):
        pdf = pikepdf.Pdf.new()
        for _ in range(101 if bad == 'pages' else 1): pdf.add_blank_page()
        target = BytesIO()
        pdf.save(target, encryption=pikepdf.Encryption(owner='owner', user='secret') if bad == 'encrypted' else False)
        data = target.getvalue()
    if bad != 'hash':
        manifest = replace(request.manifest, source_sha256=hashlib.sha256(data).hexdigest())
        if bad == 'docx':
            from experiments.document_wide_ai.contracts.v1 import DocumentFormat
            manifest = replace(manifest, document_format=DocumentFormat.DOCX)
        request = build_request(manifest, request_id='bad')
    generator, _ = make_generator(specs, lambda *a, **kw: pytest.fail('paid transport'))
    with pytest.raises(ValueError, match='document_wide_native_pdf'):
        native_pdf_transport(generator, request, data, VISION_MODELS)


def test_page_visual_and_output_bound_rejected_before_http(pdf_request, specs):
    request, data = pdf_request
    generator, model = make_generator(specs, lambda *a, **kw: pytest.fail('paid transport'), context=9000)
    native = native_pdf_transport(generator, request, data, VISION_MODELS)
    with pytest.raises(PreDispatchRejected, match='context_limit'):
        native.generate_text(model, 'JSON')


@pytest.mark.parametrize('patch', [
    {'usage': None}, {'model': 'wrong'},
    {'usage': {'input_tokens': 9000, 'output_tokens': 10, 'input_tokens_details': {'cached_tokens': 1}}},
    {'output': []},
])
def test_native_unknown_usage_not_fabricated(pdf_request, specs, patch):
    request, data = pdf_request
    generator, model = make_generator(specs, lambda *a, **kw: Response({**output(kw['json']['model']), **patch}))
    with pytest.raises(ValueError):
        native_pdf_transport(generator, request, data, VISION_MODELS).generate_text(model, 'JSON')


@pytest.mark.parametrize('reason,expected', [('max_output_tokens', 'truncated'), ('content_filter', 'refused')])
def test_native_incomplete_preserves_measured_usage(pdf_request, specs, reason, expected):
    request, data = pdf_request
    generator, model = make_generator(specs, lambda *a, **kw: Response(output(kw['json']['model'], status='incomplete', incomplete_details={'reason': reason})))
    result = native_pdf_transport(generator, request, data, VISION_MODELS).generate_text(model, 'JSON')
    assert result['response_issue'] == expected and result['cost_usd'] == '0.00902'

from test_document_wide_provider import setup, response
from ai_run_policy import run_context, read_run_budget
from ai_attempt_history import AttemptHistory
import document_wide_provider as provider


@pytest.mark.parametrize('mode', ['success', 'fallback', 'unknown', 'context'])
def test_native_managed_durable_spend_and_replay(setup, pdf_request, specs, monkeypatch, mode):
    store, job, calls, _ = setup
    request, data = pdf_request
    def post(url, **kw):
        calls.append((url, kw))
        if mode == 'context': pytest.fail('must not dispatch')
        if mode == 'unknown': raise TimeoutError()
        raw = {} if mode == 'fallback' and len(calls) == 1 else response(request)
        answer = output(kw['json']['model'])
        answer['output'][0]['content'][0]['text'] = json.dumps(raw)
        return Response(answer)
    generator, _ = make_generator(specs, post, context=9000 if mode == 'context' else 32768)
    monkeypatch.setattr(provider, 'configured_generator', lambda: generator)
    with run_context(store, job['payload'], job) as ctx:
        native_ctx = replace(ctx, policy={**ctx.policy, 'document_wide_input_mode': 'native_pdf'})
        monkeypatch.setattr(provider, 'managed_context', lambda: native_ctx)
        generated = provider.generate_document(request, pdf_bytes=data, images={'redundant': b'ignored'})
        if mode in ('success', 'fallback'):
            replay = provider.generate_document(request, pdf_bytes=data)
            assert replay['replayed']
        budget = read_run_budget(store, ctx.owner_id, ctx.scan_id, ctx.run_id)
        history = AttemptHistory(store._db).list_run(ctx.owner_id, ctx.scan_id, ctx.run_id)
    if mode == 'context':
        assert not calls and budget['held_units'] == budget['spent_units'] == 0
        assert history[0]['spending_state'] == 'released'
    elif mode == 'unknown':
        assert len(calls) == 1 and generated['reason'] == 'provider_usage_unknown'
        assert budget['held_units'] > 0
    else:
        assert not generated['deferred']
        assert len(calls) == (2 if mode == 'fallback' else 1)
        assert all(h['spending_state'] == 'settled' for h in history)
        assert len(store.list_ai_calls('scan')) == 1
        assert generated['model_call_id'] == replay['model_call_id']


def test_native_bytes_require_explicit_consent(setup, pdf_request):
    store, job, calls, _ = setup
    request, data = pdf_request
    with run_context(store, job['payload'], job):
        result = provider.generate_document(request, pdf_bytes=data)
    assert result['reason'] == 'document_wide_native_pdf_consent_required' and not calls


def test_native_policy_keeps_docx_image_transport(setup, request_package, specs, monkeypatch):
    from test_document_wide_provider import image_package
    from experiments.document_wide_ai.contracts.v1 import DocumentFormat
    store, job, calls, _ = setup
    # Test transport routing independently of DOCX proposal schema; return unresolved.
    request, images = image_package(request_package)
    manifest = replace(request.manifest, document_format=DocumentFormat.DOCX)
    request = build_request(manifest, request_id='docx-native-policy')
    from test_llm_waterfall_provider import result
    def post(url, **kw):
        calls.append((url, kw))
        return Response(result(model=kw['json']['model'], text=json.dumps(response(request))))
    generator, _ = make_generator(specs, post)
    monkeypatch.setattr(provider, 'configured_generator', lambda: generator)
    with run_context(store, job['payload'], job) as ctx:
        monkeypatch.setattr(provider, 'managed_context', lambda: replace(ctx, policy={**ctx.policy, 'document_wide_input_mode': 'native_pdf'}))
        generated = provider.generate_document(request, images=images)
    assert not generated['deferred']
    assert calls[0][0].endswith('/chat/completions')
    assert any(b['type'] == 'image_url' for b in calls[0][1]['json']['messages'][0]['content'])


def test_native_unknown_model_fails_before_http(pdf_request, specs):
    request, data = pdf_request
    generator = StrictTextGenerator(specs, provider_module=FakeProviders,
        post=lambda *a, **kw: pytest.fail('must not send unknown capability'))
    with pytest.raises(ValueError, match='model_unavailable'):
        native_pdf_transport(generator, request, data, VISION_MODELS)


def test_native_actual_usage_overrun_is_reported_not_clamped(pdf_request, specs):
    request, data = pdf_request
    generator, model = make_generator(specs, lambda *a, **kw: Response(output(
        kw['json']['model'], usage={'input_tokens': 40000, 'output_tokens': 10})))
    result = native_pdf_transport(generator, request, data, VISION_MODELS).generate_text(model, 'JSON')
    assert result['bounds_exceeded'] and result['cost_usd'] == '0.04002'
