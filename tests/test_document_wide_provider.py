"""Offline actual budget/attempt path with synthetic measured HTTP responses."""
from dataclasses import replace
import json
import pytest

import document_wide_provider as provider
from ai_run_policy import run_context
from ai_attempt_history import AttemptHistory
from test_ai_run_policy import seed, enqueue
from test_llm_waterfall_provider import specs, FakeProviders, Response, result
from llm_waterfall_provider import StrictTextGenerator
from experiments.document_wide_ai.contracts.v1 import (
    CONTRACT_VERSION, DocumentContextManifest, DocumentFormat, Finding, Locator, AllowedOperation,
)
from experiments.document_wide_ai.request.builder import build_request


@pytest.fixture
def request_package():
    manifest = DocumentContextManifest(CONTRACT_VERSION, 'extract.v1', 'adapter.v1', 'a.pdf',
        DocumentFormat.PDF, 'a'*64, 'snapshot', ('4.1.2',),
        (Finding('finding1', 'pdf.form', '4.1.2', Locator(DocumentFormat.PDF, 0, None, 'pdf:field:name', 'abc')),),
        (AllowedOperation('set_pdf_field_accessible_name', DocumentFormat.PDF),), 'Name: ____')
    return build_request(manifest, request_id='doc-request')


def response(request, **changes):
    raw = dict(contract_version=CONTRACT_VERSION, request_id=request.request_id,
        source_sha256=request.manifest.source_sha256, edits=[],
        unresolved=[dict(finding_id='finding1', reason='insufficient_evidence')])
    return {**raw, **changes}


@pytest.fixture
def setup(isolated_store, monkeypatch, specs):
    import core, lf
    monkeypatch.setattr(core, 'store', isolated_store)
    monkeypatch.setattr(lf, 'trace_ai_call', lambda *a, **kw: None)
    seed(isolated_store)
    batch = enqueue(isolated_store, files=('a.pdf',))
    job = isolated_store.get_job(batch['job_ids'][0])
    calls, outputs = [], []
    def post(*args, **kwargs):
        calls.append(kwargs['json'])
        output = outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return Response(result(model=kwargs['json']['model'], text=json.dumps(output)))
    generator = StrictTextGenerator(specs, provider_module=FakeProviders, post=post)
    monkeypatch.setattr(provider, 'configured_generator', lambda: generator)
    return isolated_store, job, calls, outputs


def test_one_batch_replay_does_not_spend_again(setup, request_package):
    store, job, calls, outputs = setup
    outputs.append(response(request_package))
    with run_context(store, job['payload'], job) as ctx:
        first = provider.generate_document(request_package)
        again = provider.generate_document(request_package)
        history = AttemptHistory(store._db).list_run(ctx.owner_id, ctx.scan_id, ctx.run_id)
    assert not first['deferred'] and again['replayed']
    assert len(calls) == len(history) == 1
    assert first['model_call_id'] == again['model_call_id']
    assert len(store.list_ai_calls('scan')) == 1
    assert first['cost_usd'] == '0.00012'
    assert first['envelope'].unresolved[0].finding_id == 'finding1'


@pytest.mark.parametrize('bad', ['missing', 'wrong_request', 'unknown', 'duplicate', 'invalid'])
def test_invalid_response_uses_one_fallback(setup, request_package, bad):
    store, job, calls, outputs = setup
    raw = response(request_package)
    if bad == 'missing': raw['unresolved'] = []
    elif bad == 'wrong_request': raw['request_id'] = 'other'
    elif bad == 'unknown': raw['unresolved'][0]['finding_id'] = 'other'
    elif bad == 'duplicate': raw['unresolved'] *= 2
    else: raw = {'oops': True}
    outputs.extend([raw, response(request_package)])
    with run_context(store, job['payload'], job) as ctx:
        generated = provider.generate_document(request_package)
        history = AttemptHistory(store._db).list_run(ctx.owner_id, ctx.scan_id, ctx.run_id)
    assert not generated['deferred']
    assert len(calls) == len(history) == 2
    assert {r['purpose'] for r in history} == {'draft', 'fallback'}
    assert all(r['spending_state'] == 'settled' for r in history)


def test_unknown_usage_never_spends_fallback(setup, request_package):
    store, job, calls, outputs = setup
    outputs.append(TimeoutError())
    with run_context(store, job['payload'], job):
        generated = provider.generate_document(request_package)
    assert generated['reason'] == 'provider_usage_unknown'
    assert generated['envelope'] is None and len(calls) == 1


def test_exhausted_invalid_never_returns_edits(setup, request_package):
    store, job, calls, outputs = setup
    outputs.extend([{}, {}])
    with run_context(store, job['payload'], job):
        generated = provider.generate_document(request_package)
    assert generated['reason'] == 'attempts_exhausted'
    assert generated['envelope'] is None and len(calls) == 2


@pytest.mark.parametrize('condition,reason', [
    ('local', 'document_wide_cloud_required'), ('disabled', 'ai_disabled_or_budget_zero'),
    ('identity', 'document_wide_source_identity_mismatch'), ('prefix', 'document_wide_manifest_mismatch'),
])
def test_no_egress_when_admission_fails(setup, request_package, condition, reason, monkeypatch):
    store, job, calls, _ = setup
    with run_context(store, job['payload'], job) as ctx:
        if condition == 'local': monkeypatch.setattr(provider, 'managed_context', lambda: replace(ctx, policy={**ctx.policy, 'ai_zone': 'local'}))
        elif condition == 'disabled': monkeypatch.setattr(provider, 'managed_context', lambda: replace(ctx, policy={**ctx.policy, 'ai': 0}))
        elif condition == 'identity': request_package = replace(request_package, manifest=replace(request_package.manifest, document_id='other.pdf'))
        else: request_package = replace(request_package, stable_prefix='instructions instead')
        generated = provider.generate_document(request_package)
    assert generated['reason'] == reason and not calls


def test_valid_edit_requires_manifest_allowlist_and_criterion(request_package):
    from dataclasses import asdict
    locator = asdict(request_package.manifest.findings[0].locator)
    raw = response(request_package, unresolved=[], edits=[dict(edit_id='e1', finding_ids=['finding1'],
        locator=locator, operation='set_pdf_field_accessible_name', proposed_value='Full name', expected_original_value=None)])
    envelope, validated = provider._decode(request_package, json.dumps(raw))
    assert len(validated.valid_edits) == 1
    altered = replace(request_package, manifest=replace(request_package.manifest, allowed_operations=()))
    with pytest.raises(ValueError): provider._decode(altered, json.dumps(raw))


def image_package(request_package):
    from PIL import Image
    from io import BytesIO
    from hashlib import sha256
    from experiments.document_wide_ai.contracts.v1 import Evidence, EvidenceKind
    stream = BytesIO()
    Image.new('RGB', (32, 32), 'red').save(stream, format='PNG')
    data = stream.getvalue()
    ref = 'sha256:' + sha256(data).hexdigest()
    manifest = replace(request_package.manifest, evidence=(Evidence(EvidenceKind.IMAGE,
        request_package.manifest.findings[0].locator, 'field evidence', image_ref=ref),))
    return build_request(manifest, request_id=request_package.request_id), {ref: data}


@pytest.mark.parametrize('vendor', ['openai', 'anthropic'])
def test_images_use_native_payload_and_same_measured_budget(setup, request_package, specs, monkeypatch, vendor):
    store, job, calls, _ = setup
    request_package, images = image_package(request_package)
    models = (('gpt-4.1-mini-2025-04-14', 'gpt-4.1-2025-04-14') if vendor == 'openai'
              else ('claude-haiku-4-5-20251001', 'claude-sonnet-5'))
    class Config(FakeProviders):
        selected = vendor
    def post(endpoint, **kwargs):
        payload = kwargs['json']; calls.append(payload)
        if vendor == 'openai':
            return Response(result(model=payload['model'], text=json.dumps(response(request_package))))
        return Response(dict(model=payload['model'], id='anthropic-call',
            usage=dict(input_tokens=100, output_tokens=10),
            content=[dict(type='text', text=json.dumps(response(request_package)))]))
    generator = StrictTextGenerator(tuple(replace(s, model=m, provider=vendor) for s,m in zip(specs, models)),
        provider_module=Config, post=post)
    monkeypatch.setattr(provider, 'configured_generator', lambda: generator)
    with run_context(store, job['payload'], job):
        generated = provider.generate_document(request_package, images=images)
    assert not generated['deferred'] and generated['cost_usd'] == '0.00012'
    blocks = calls[0]['messages'][0]['content']
    assert blocks[-1]['type'] == ('image_url' if vendor == 'openai' else 'image')
    assert next(iter(images)) in blocks[-2]['text']
    assert isinstance(generator.post, type(post))  # no mutation to shared transport


@pytest.mark.parametrize('case', ['hash', 'extra', 'missing', 'invalid_image'])
def test_bad_images_never_dispatch(setup, request_package, case):
    from hashlib import sha256
    from experiments.document_wide_ai.contracts.v1 import Evidence
    store, job, calls, _ = setup
    request_package, images = image_package(request_package)
    if case == 'hash': images = {next(iter(images)): b'changed'}
    elif case == 'extra': images['extra'] = b'bytes'
    elif case == 'missing': images = {}
    else:
        data = b'not an image'; ref = 'sha256:' + sha256(data).hexdigest()
        evidence = replace(request_package.manifest.evidence[0], image_ref=ref)
        request_package = build_request(replace(request_package.manifest, evidence=(evidence,)), request_id=request_package.request_id)
        images = {ref: data}
    with run_context(store, job['payload'], job):
        generated = provider.generate_document(request_package, images=images)
    assert generated['deferred'] and not calls


def test_docx_without_visuals_cannot_generate_alt_text(setup, request_package):
    store, job, calls, _ = setup
    request_package = replace(request_package, manifest=replace(request_package.manifest, document_format=DocumentFormat.DOCX))
    with run_context(store, job['payload'], job):
        generated = provider.generate_document(request_package)
    assert generated['reason'] == 'document_wide_insufficient_visual_evidence' and not calls


def test_unknown_vision_model_does_not_dispatch(setup, request_package):
    store, job, calls, _ = setup
    request_package, images = image_package(request_package)
    with run_context(store, job['payload'], job):
        generated = provider.generate_document(request_package, images=images)
    assert generated['reason'] == 'document_wide_image_model_unavailable' and not calls


def test_unselected_image_locator_rejected(setup, request_package):
    store, job, calls, _ = setup
    request_package, images = image_package(request_package)
    evidence = replace(request_package.manifest.evidence[0], source_locator=replace(request_package.manifest.findings[0].locator, element_ref='elsewhere'))
    request_package = build_request(replace(request_package.manifest, evidence=(evidence,)), request_id=request_package.request_id)
    with run_context(store, job['payload'], job):
        generated = provider.generate_document(request_package, images=images)
    assert generated['reason'] == 'document_wide_image_manifest_mismatch' and not calls


def test_missing_durable_call_cannot_authorize_apply(setup, request_package, monkeypatch):
    import ai
    store, job, _, outputs = setup
    outputs.append(response(request_package))
    monkeypatch.setattr(ai, '_trace_ai', lambda *a, **kw: None)
    with run_context(store, job['payload'], job):
        generated = provider.generate_document(request_package)
    assert generated['reason'] == 'document_wide_provenance_unavailable' and generated['envelope'] is None
