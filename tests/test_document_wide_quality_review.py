"""The automatic document path and cached replies must honor chart review policy."""
from dataclasses import replace
import pytest
import document_wide_workflow as workflow
from test_document_wide_workflow import setup
from test_quality_chart_review import SWAPPED
from experiments.document_wide_ai.contracts.v1 import DocumentFormat, Evidence, EvidenceKind


@pytest.mark.parametrize('ext', ['pdf', 'docx', 'pptx', 'xlsx'])
@pytest.mark.parametrize('cached', [False, True])
def test_quality_document_chart_draft_needs_review_on_fresh_and_cached_path(monkeypatch, ext, cached):
    from pathlib import Path
    store, ctx, calls, logs, queued = setup(monkeypatch, sc='1.1.1')
    import document_wide_provider
    import document_wide_manifest
    ctx.file = 'file.' + ext
    ctx.policy.update(quality_first=True, cloud_input_strategy='automatic', _automatic_input_selected=True,
                      auto_approve_ai=True)
    manifest = document_wide_manifest.build_manifest()
    fmt = DocumentFormat(ext)
    locator = replace(manifest.findings[0].locator, format=fmt,
                      part_name=None if ext == 'pdf' else 'word/document.xml')
    finding = replace(manifest.findings[0], locator=locator)
    op = 'set_pdf_figure_alt_text' if ext == 'pdf' else 'set_office_image_alt_text'
    manifest = replace(manifest, document_format=fmt, findings=(finding,),
        allowed_operations=(replace(manifest.allowed_operations[0], format=fmt, op=op),),
        evidence=(Evidence(EvidenceKind.IMAGE, locator, 'exact image', image_ref='source-image'),))
    monkeypatch.setattr(document_wide_manifest, 'build_manifest', lambda *a: manifest)
    image = (Path(__file__).parent/'fixtures/vision/labeled_bar_chart.png').read_bytes()
    monkeypatch.setattr(document_wide_manifest, 'package_images', lambda *a: {'source-image': image})
    store.list_hitl_queue = lambda **kw: [{'file':ctx.file, 'rule_id':'1.1.1','status':'pending'}]
    store.list_finding_dispositions = lambda *a:[{'finding_id':'real-finding','file':ctx.file,'rule_id':'1.1.1'}]
    original_generate = document_wide_provider.generate_document
    def generate(request, **kw):
        result = original_generate(request, **kw)
        envelope = result['envelope']
        result['envelope'] = replace(envelope, edits=(replace(envelope.edits[0], locator=locator,
            operation=op, proposed_value=SWAPPED),))
        return result
    monkeypatch.setattr(document_wide_provider, 'generate_document', generate)
    if cached:
        monkeypatch.setattr(workflow, '_saved', lambda *a:{'proposals':{'1.1.1':[{
            'locator':'image', 'finding_ids':['real-finding'], 'proposed_value':SWAPPED,
            'rationale':'Visible chart', 'source':'ai'}]}})
    workflow.process_file(store, ctx)
    assert bool(calls) is (not cached)
    p = queued[0][0][3][0]
    assert p['automatic_write_blocked'] and p['review_status'] == 'needs_review'
    assert p['chart_review']['checks'] == ['series', 'year', 'sign', 'value', 'units']
    assert p['thumb'] and 'Needs review' in p['why_review']
    from release_continuation import eligibility
    assert 'individual review' in eligibility(dict(status='pending', rule_id='1.1.1', proposals=[p]),ctx.file)


def test_cached_quality_result_does_not_replace_human_decision(monkeypatch):
    store, ctx, calls, logs, queued = setup(monkeypatch, sc='1.1.1', status='approved')
    ctx.policy['quality_first'] = True
    monkeypatch.setattr(workflow, '_saved', lambda *a:{'proposals':{'1.1.1':[{'proposed_value':SWAPPED}]}})
    workflow.process_file(store, ctx)
    assert not calls and not queued
    assert any('existing review decision' in detail['detail'].lower() for _, detail in logs)


def test_native_pdf_image_packaging_limit_keeps_review_without_thumbnail(monkeypatch):
    import hashlib
    from types import SimpleNamespace
    from test_document_wide_workflow import fixture
    import experiments.document_wide_ai.packaging.pdf_images as pdf_images
    data, digest, locator, manifest = fixture(monkeypatch, '1.1.1')
    # Native-PDF transport can carry this document; extracted-image packaging
    # imposes a separate eight-image limit and must not abort pending review.
    monkeypatch.setattr(pdf_images, 'render_pdf_page', lambda data, page: bytes([page]))
    evidence = tuple(Evidence(EvidenceKind.IMAGE, replace(locator, page_index=i), 'exact',
        image_ref='sha256:' + hashlib.sha256(bytes([i])).hexdigest()) for i in range(9))
    manifest = replace(manifest, evidence=evidence)
    ctx = SimpleNamespace(policy={'quality_first': True, 'document_wide_input_mode':'native_pdf'})
    proposal = {'finding_ids':['real-finding'], 'proposed_value':SWAPPED}
    result = workflow._quality_image_proposals([proposal], ctx, manifest, data)[0]
    assert result['automatic_write_blocked'] and result['review_status'] == 'needs_review'
    assert 'thumb' not in result


def test_thumbnail_source_change_still_fails_closed(monkeypatch):
    from types import SimpleNamespace
    from test_document_wide_workflow import fixture
    data, digest, locator, manifest = fixture(monkeypatch, '1.1.1')
    manifest = replace(manifest, evidence=(Evidence(EvidenceKind.IMAGE, locator, 'exact', image_ref='image'),))
    ctx = SimpleNamespace(policy={'quality_first': True})
    with pytest.raises(ValueError, match='document_source_changed'):
        workflow._quality_image_proposals([{'finding_ids':['real-finding'], 'proposed_value':SWAPPED}],
                                         ctx, manifest, data + b'changed')
