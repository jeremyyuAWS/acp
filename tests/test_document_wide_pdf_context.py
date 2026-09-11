"""Real PDF context and fake-only provider transport; no cloud or customer data."""
from dataclasses import asdict, replace
from io import BytesIO
import hashlib
import json

import pikepdf
import pytest
from reportlab.pdfgen import canvas

from document_wide_manifest import build_manifest, package_images
from experiments.document_wide_ai.packaging.pdf_packager import package_pdf
from experiments.document_wide_ai.packaging.manifest_builder import build_pdf_manifest
from experiments.document_wide_ai.request.builder import build_request
from test_document_wide_manifest import setup_manifest
from test_document_wide_provider import setup, request_package, response
from test_llm_waterfall_provider import specs, FakeProviders, Response, result
from llm_waterfall_provider import StrictTextGenerator, PreDispatchRejected
from ai_run_policy import run_context
import document_wide_provider as provider


def pdf_context(*, figures=1):
    out = BytesIO()
    c = canvas.Canvas(out)
    c.drawString(60, 700, 'Patient name')
    c.acroForm.textfield(name='Text1', x=160, y=690, width=150, height=24)
    c.setFillColorRGB(1, 0, 0)
    c.circle(200, 500, 50, fill=1)
    c.showPage()
    c.drawString(60, 700, 'Emergency contact')
    c.acroForm.textfield(name='Text2', x=180, y=690, width=150, height=24)
    c.showPage(); c.save()
    with pikepdf.open(BytesIO(out.getvalue())) as pdf:
        for f in pdf.Root.AcroForm.Fields:
            if '/TU' in f:
                del f['/TU']
        root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name('/StructTreeRoot')))
        root.K = pikepdf.Array([pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name('/StructElem'), S=pikepdf.Name('/Figure'),
            Pg=pdf.pages[0].obj, P=root, K=i)) for i in range(figures)])
        pdf.Root.StructTreeRoot = root
        out = BytesIO(); pdf.save(out)
        return out.getvalue()


def test_pages_fields_and_nearby_evidence_are_distinct():
    data = pdf_context()
    packaged = package_pdf(data, max_text_chars=60000)
    assert not packaged.extraction_issues
    assert '[Page 1]' in packaged.text_context and '[Page 2]' in packaged.text_context
    first, second = packaged.form_fields
    assert (first.page_index, second.page_index) == (0, 1)
    assert first.internal_name == 'Text1' and first.field_type == '/Tx'
    assert first.rectangle == (160, 690, 310, 714)
    assert 'Patient name' in first.nearby_text
    assert 'Emergency contact' in second.nearby_text
    assert 'Emergency contact' not in first.nearby_text
    assert packaged.figures[0].locator == 'pdf:fig:1:0'
    assert packaged.figures[0].current_alt is None
    manifest = build_pdf_manifest(data, document_id='a.pdf', assessment_revision='v', selected_criteria=('1.1.1',))
    assert {f.success_criterion for f in manifest.findings} == {'1.1.1'}
    assert manifest.findings[0].locator.page_index == 0
    assert {o.op for o in manifest.allowed_operations} == {'set_pdf_figure_alt_text'}


def test_single_figure_has_bounded_source_bound_page_evidence(isolated_store, monkeypatch):
    data = pdf_context()
    setup_manifest(isolated_store, monkeypatch, data, 'a.pdf', '1.1.1', ['pdf:fig:1:0'])
    manifest = build_manifest(isolated_store, 'scan', 'a.pdf', data)
    assert len(manifest.evidence) == 1
    evidence = manifest.evidence[0]
    assert 'Page 1' in evidence.reason and 'full page' in evidence.reason
    images = package_images(data, manifest)
    image = images[evidence.image_ref]
    from PIL import Image
    with Image.open(BytesIO(image)) as img:
        assert max(img.size) <= 1568
    assert len(image) <= 1024 * 1024
    assert evidence.image_ref == 'sha256:' + hashlib.sha256(image).hexdigest()
    with pytest.raises(ValueError, match='document_source_changed'):
        package_images(data+b'changed', manifest)


def test_multiple_figures_never_guess_page_image_target(isolated_store, monkeypatch):
    data = pdf_context(figures=2)
    setup_manifest(isolated_store, monkeypatch, data, 'a.pdf', '1.1.1', ['pdf:fig:1:0', 'pdf:fig:1:1'])
    manifest = build_manifest(isolated_store, 'scan', 'a.pdf', data)
    assert len(manifest.findings) == 2 and not manifest.evidence
    assert len([i for i in manifest.extraction_issues if i.kind == 'missing_visual_evidence']) == 2
    assert package_images(data, manifest) == {}


def test_unsupported_selected_findings_are_advisory_not_write_targets(isolated_store, monkeypatch):
    data = pdf_context()
    rows = setup_manifest(isolated_store, monkeypatch, data, 'a.pdf', '1.1.1', ['pdf:fig:1:0', 'unsupported-location'])
    manifest = build_manifest(isolated_store, 'scan', 'a.pdf', data)
    assert manifest.finding_ids() == {rows[0]['finding_id']}
    assert rows[1]['finding_id'] in manifest.text_context
    assert 'no write authorization' in manifest.text_context
    assert rows[1]['finding_id'] not in manifest.finding_ids()


def test_text_context_reserves_output_before_transport(specs):
    calls = []
    generator = StrictTextGenerator(specs, provider_module=FakeProviders,
        post=lambda *a, **kw: calls.append(kw))
    # This formerly passed text-only admission: input+framing fits but output does not.
    prompt = 'x' * (8192 - 1024 - 64)
    with pytest.raises(PreDispatchRejected, match='bounded text request size'):
        generator.generate_text(specs[0].model, prompt)
    assert not calls


def test_pdf_context_reaches_cloud_transport_and_missing_visual_cannot_authorize(setup, request_package, specs, monkeypatch):
    store, job, calls, _ = setup
    manifest = build_pdf_manifest(pdf_context(), document_id='a.pdf', assessment_revision='v', selected_criteria=('4.1.2',))
    request = build_request(manifest, request_id='pdf-context')
    raw = dict(contract_version=manifest.contract_version, request_id=request.request_id,
               source_sha256=manifest.source_sha256, edits=[],
               unresolved=[{'finding_id': f.finding_id, 'reason': 'Needs semantic review'} for f in manifest.findings])
    def post(endpoint, **kwargs):
        calls.append(kwargs['json'])
        return Response(result(model=kwargs['json']['model'], text=json.dumps(raw)))
    generator = StrictTextGenerator(tuple(replace(s, context_token_limit=32768) for s in specs), provider_module=FakeProviders, post=post)
    monkeypatch.setattr(provider, 'configured_generator', lambda: generator)
    with run_context(store, job['payload'], job):
        generated = provider.generate_document(request)
    assert not generated['deferred'] and len(calls) == 1
    prompt = calls[0]['messages'][0]['content']
    assert manifest.to_json() in prompt and 'Patient name' in prompt and 'Emergency contact' in prompt
    assert all(f.finding_id in prompt for f in manifest.findings)

    manifest = build_pdf_manifest(pdf_context(), document_id='a.pdf', assessment_revision='v', selected_criteria=('1.1.1',))
    request = build_request(manifest, request_id='pdf-context')
    finding = manifest.findings[0]
    raw.update(source_sha256=manifest.source_sha256, unresolved=[], edits=[dict(edit_id='e1',
        finding_ids=[finding.finding_id], locator=asdict(finding.locator), operation='set_pdf_figure_alt_text',
        proposed_value='Red circle', expected_original_value=None, rationale='A guess without evidence')])
    with pytest.raises(ValueError, match='invalid_required_structure'):
        provider._decode(request, json.dumps(raw))


@pytest.mark.parametrize('vendor', ['openai', 'anthropic'])
def test_real_pdf_page_reaches_each_vendor_as_image_with_locator(setup, specs, monkeypatch, vendor):
    from experiments.document_wide_ai.contracts.v1 import Evidence, EvidenceKind
    from experiments.document_wide_ai.packaging.pdf_images import render_pdf_page
    store, job, calls, _ = setup
    data = pdf_context()
    manifest = build_pdf_manifest(data, document_id='a.pdf', assessment_revision='v', selected_criteria=('1.1.1',))
    finding = manifest.findings[0]
    image = render_pdf_page(data, 0)
    assert image
    ref = 'sha256:' + hashlib.sha256(image).hexdigest()
    manifest = replace(manifest, evidence=(Evidence(EvidenceKind.IMAGE, finding.locator, 'Page 1, single Figure', image_ref=ref),))
    request = build_request(manifest, request_id='figure-request')
    raw = dict(contract_version=manifest.contract_version, request_id=request.request_id,
        source_sha256=manifest.source_sha256, unresolved=[], edits=[dict(edit_id='e1',
        finding_ids=[finding.finding_id], locator=asdict(finding.locator), operation='set_pdf_figure_alt_text',
        proposed_value='Red circle', expected_original_value=None, rationale='Visible in page context')])
    names = (('gpt-4.1-mini-2025-04-14', 'gpt-4.1-2025-04-14') if vendor == 'openai'
             else ('claude-haiku-4-5-20251001', 'claude-sonnet-5'))
    class Config(FakeProviders):
        selected = vendor
    def post(endpoint, **kwargs):
        payload = kwargs['json']; calls.append(payload)
        if vendor == 'openai':
            return Response(result(model=payload['model'], text=json.dumps(raw)))
        return Response(dict(model=payload['model'], id='anthropic-pdf-call',
            usage=dict(input_tokens=100, output_tokens=10), content=[dict(type='text', text=json.dumps(raw))]))
    generator = StrictTextGenerator(tuple(replace(s, model=m, provider=vendor, context_token_limit=32768)
        for s, m in zip(specs, names)), provider_module=Config, post=post)
    monkeypatch.setattr(provider, 'configured_generator', lambda: generator)
    with run_context(store, job['payload'], job):
        generated = provider.generate_document(request, images={ref: image})
    assert not generated['deferred'] and generated['provider'] == vendor
    assert len(calls) == 1 and generated['envelope'].edits[0].proposed_value == 'Red circle'
    blocks = calls[0]['messages'][0]['content']
    assert finding.locator.element_ref in blocks[0]['text']
    assert blocks[-1]['type'] == ('image_url' if vendor == 'openai' else 'image')


def test_unavailable_pdf_renderer_keeps_explicit_unresolved_evidence(isolated_store, monkeypatch):
    data = pdf_context()
    setup_manifest(isolated_store, monkeypatch, data, 'a.pdf', '1.1.1', ['pdf:fig:1:0'])
    monkeypatch.setattr('experiments.document_wide_ai.packaging.pdf_images.render_pdf_page', lambda *a: None)
    manifest = build_manifest(isolated_store, 'scan', 'a.pdf', data)
    assert len(manifest.findings) == 1 and not manifest.evidence
    assert manifest.extraction_issues[0].kind == 'missing_visual_evidence'
