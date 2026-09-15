"""Offline mandatory source review: no model agreement or stored flags grant credit."""
import hashlib
import io
import zipfile
from types import SimpleNamespace
import pytest
from PIL import Image, ImageDraw
import quality_source_review as quality


def picture():
    image = Image.new('RGB', (80, 80), 'white')
    ImageDraw.Draw(image).ellipse((20, 20, 60, 60), fill='blue')
    out = io.BytesIO(); image.save(out, format='PNG')
    return out.getvalue()


def natural_picture():
    image = Image.new('RGB', (80,80), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((12,40,45,52), fill='brown')
    draw.ellipse((40,32,54,46),fill='brown')
    draw.line((15,52,10,68),fill='brown',width=4)
    draw.line((43,52,48,68),fill='brown',width=4)
    draw.rectangle((64,25,68,70),fill='black')
    draw.ellipse((55,8,77,35),fill='green')
    output=io.BytesIO(); image.save(output,format='PNG')
    return output.getvalue()


def package(*, crop='', transform='', duplicate=False, stretch=False, image=None):
    image = image or picture()
    xml = f'''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
      xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
      xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
      xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
      <w:body><wp:inline><wp:extent cx="{160 if stretch else 80}" cy="80"/>
      <wp:docPr name="Picture 1" id="1"/><a:blip r:embed="r1"/>{crop}{transform}</wp:inline>
      {'<wp:inline><wp:docPr name="Picture 1" id="2"/><a:blip r:embed="r1"/></wp:inline>' if duplicate else ''}
      </w:body></w:document>'''
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('word/document.xml', xml)
        archive.writestr('word/_rels/document.xml.rels', '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Target="media/image1.png" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"/></Relationships>''')
        archive.writestr('word/media/image1.png', image)
    return output.getvalue()


def test_independent_pixel_review_accepts_finite_facts_and_rejects_wrong_color():
    assert quality.review_image('A blue circle on a white background', picture())['passed']
    assert not quality.review_image('A red circle on a white background', picture())['passed']
    assert not quality.review_image('Revenue rose 40% in 2024', picture())['passed']


@pytest.mark.parametrize('locator', ['word/document.xml#Picture 1', 'word/document.xml#r1'])
def test_exact_unique_office_source_passes_without_model_review(locator):
    data = package(); digest = hashlib.sha256(data).hexdigest()
    assert quality.enabled({'quality_first':True,'auto_approve_ai':True,'ai_review':{'enabled':False}})
    review = quality.review_proposals(data, 'file.docx', '1.1.1', [dict(locator=locator,
        proposed_value='A blue circle on a white background', source_sha256=digest)], digest)
    assert review['passed'] and review['source_sha256'] == digest
    assert review['checks'][0]['image_sha256'] == hashlib.sha256(picture()).hexdigest()


@pytest.mark.parametrize('kwargs', [dict(crop='<a:srcRect l="1"/>'),
    dict(transform='<a:xfrm rot="60000"/>'), dict(duplicate=True), dict(stretch=True)])
def test_ambiguous_cropped_rotated_or_stretched_source_is_unsupported(kwargs):
    assert quality.office_image(package(**kwargs), 'word/document.xml#Picture 1') is None


def test_changed_artifact_and_cached_pass_flags_cannot_authorize():
    data = package(); p = dict(locator='word/document.xml#Picture 1',
        proposed_value='A red circle on a white background', quality_source_review={'passed':True},
        agreement={'verdict':'consistent'})
    digest = hashlib.sha256(data).hexdigest()
    p['source_sha256'] = digest
    assert not quality.review_proposals(data, 'file.docx', '1.1.1', [p], digest)['passed']
    assert quality.review_proposals(data, 'file.docx', '1.1.1', [p], 'old')['status'] == 'source_changed'
    p['proposed_value'] = 'A blue circle on a white background'
    assert quality.review_proposals(data, 'file.docx', '1.1.1', [p], digest)['passed']


@pytest.mark.parametrize('policy', [{}, {'quality_first':True}, {'auto_approve_ai':True},
                                   {'quality_first':False,'auto_approve_ai':True}])
def test_legacy_and_nonautomatic_preferences_do_not_enable_gate(policy):
    assert not quality.enabled(policy)


def test_unsupported_other_semantics_cannot_pass_on_proposal_flags():
    data = package()
    assert not quality.review_proposals(data, 'file.docx', '2.4.4', [dict(
        proposed_value='Trust me', quality_source_review={'passed':True})],
        hashlib.sha256(data).hexdigest())['passed']


def test_quality_automatic_ocr_is_not_a_semantic_shortcut(monkeypatch):
    import ai, ocr, llm_waterfall_provider
    monkeypatch.setattr(llm_waterfall_provider, 'managed_context', lambda:SimpleNamespace(
        policy={'quality_first':True,'auto_approve_ai':True,'ai_review':{'enabled':False}}, enabled=True))
    monkeypatch.setattr(ocr, 'ocr_text', lambda *a:'This is a complete paragraph with many words in a picture.')
    monkeypatch.setattr(ai, '_vision_generate', lambda *a, **kw:'A patient welcomes a doctor.')
    result = ai.describe_image_structured(picture(), allow_transcription=True)
    assert not result['grounded'] and result['automatic_write_blocked']
    assert not result['quality_source_review']['passed']


def test_correct_pixel_caption_automatically_passes_source_review(monkeypatch):
    import ai, ocr, llm_waterfall_provider
    monkeypatch.setattr(llm_waterfall_provider, 'managed_context', lambda:SimpleNamespace(
        policy={'quality_first':True,'auto_approve_ai':True,'ai_review':{'enabled':False}}, enabled=True))
    monkeypatch.setattr(ocr, 'ocr_text', lambda *a:'')
    monkeypatch.setattr(ai, '_vision_generate', lambda *a, **kw:'A blue circle on a white background')
    result = ai.describe_image_structured(picture())
    assert result['quality_source_review']['passed']
    assert not result.get('automatic_write_blocked')


def test_cloud_source_reviewer_is_independent_bound_and_advisory():
    calls = []
    image = picture()
    def generate(prompt, data, **kwargs):
        calls.append((prompt, data, kwargs))
        return dict(text='{"verdict":"accept","reason":"Visible source agrees","observations":["Blue circular object on white"],"unsupported_claims":[],"semantic_certification":true}',
                    model='reviewer', ai_call_id='paid-ledger-call', provider='cloud',
                    image_processing={'original_sha256':hashlib.sha256(data).hexdigest()})
    review = quality.cloud_review('A blue shape', image, 'draft',
                                  generate=generate, models=['draft','reviewer'])
    assert review['verdict'] == 'accept'
    assert review['semantic_certification'] is False
    assert calls[0][1] == image and calls[0][2] == {'clean':False,'model':'reviewer','purpose':'review'}
    assert 'series/year/value associations' in calls[0][0]
    assert not quality.review_image('A blue shape', image)['passed']


@pytest.mark.parametrize('reason', ['budget_admission_denied','provider_usage_unknown','provider_access_denied'])
def test_cloud_review_budget_permission_or_unknown_usage_stops_without_retry(reason):
    calls = []
    def generate(*args, **kwargs):
        calls.append(1)
        return {'deferred':True,'reason':reason}
    review = quality.cloud_review('Caption', picture(), 'draft', generate=generate,
                                  models=['draft','reviewer'])
    assert review['verdict'] == 'unable' and review['reason'] == reason and calls == [1]


@pytest.mark.parametrize('mutation', ['image','model','unsupported','bad_json'])
def test_cloud_review_rejects_changed_source_wrong_model_or_unsupported_acceptance(mutation):
    import json
    def generate(prompt, data, **kwargs):
        result = dict(text=json.dumps(dict(verdict='accept', reason='Source visible',
            observations=['Blue circle'], unsupported_claims=['Value unreadable'] if mutation == 'unsupported' else [])),
            model='draft' if mutation == 'model' else 'reviewer', ai_call_id='call',
            image_processing={'original_sha256':'changed' if mutation == 'image' else hashlib.sha256(data).hexdigest()})
        if mutation == 'bad_json': result['text'] = 'No JSON'
        return result
    review = quality.cloud_review('Caption', picture(), 'draft',generate=generate,models=['draft','reviewer'])
    assert review['verdict'] == 'unable' and not review['semantic_certification']


def test_auto_quality_invokes_source_review_even_when_optional_ai_review_is_disabled(monkeypatch):
    import ai, ocr, llm_waterfall_provider
    monkeypatch.setattr(llm_waterfall_provider, 'managed_context', lambda:SimpleNamespace(
        policy={'quality_first':True,'auto_approve_ai':True,'ai_review':{'enabled':False}}, enabled=True))
    monkeypatch.setattr(ocr, 'ocr_text', lambda *a:'')
    monkeypatch.setattr(ai, '_vision_generate', lambda *a, **kw:'A patient welcomes a doctor.')
    calls = []
    def review(caption, image, model):
        calls.append((caption,image))
        return {'verdict':'accept','semantic_certification':False}
    monkeypatch.setattr(quality,'cloud_review',review)
    result = ai.describe_image_structured(picture())
    assert calls == [('A patient welcomes a doctor.', picture())]
    assert result['automatic_write_blocked']
    assert result['quality_source_review']['cloud_review']['verdict'] == 'accept'


def test_standing_admission_invokes_mandatory_source_gate_with_optional_review_off(isolated_store, monkeypatch):
    import blob
    from test_ai_standing_approval import seed, proposal, apply_jobs, rows, SID, FILE, DIGEST, BYTES
    from ai_run_policy import run_context
    from ai_standing_approval import approve_file
    store = isolated_store; job = seed(store, monkeypatch)
    monkeypatch.setattr(blob, 'download_remediated', lambda *a: BYTES)
    with run_context(store, job['payload'], job) as ctx:
        store.enqueue_proposals(SID, FILE, '2.4.6', [proposal(store, review=None)])
        with store._db.cursor() as cur:
            store._db.execute(cur, 'SELECT policy_json FROM ai_spending_run_policies WHERE run_id=%s', (ctx.run_id,))
            policy = __import__('json').loads(store._db.fetchone(cur)['policy_json'])
            policy.update(quality_first=True, ai_review={'enabled':False})
            store._db.execute(cur, 'UPDATE ai_spending_run_policies SET policy_json=%s WHERE run_id=%s',
                              (__import__('json').dumps(policy), ctx.run_id))
        approve_file(store, ctx)
    assert not apply_jobs(store)
    assert any(quality.REQUIRED in row.get('detail','') for row in rows(store,'decision_log'))


def source_review_receipt(caption, image):
    return dict(verdict='accept', reason='Direct source evidence supports the caption',
                observations=['A brown dog walking beside a tree'], unsupported_claims=[],
                model='reviewer', draft_model='draft', model_call_id='review-call', operation_id='review-op',
                proposal_sha256=hashlib.sha256(caption.encode()).hexdigest(),
                image_sha256=hashlib.sha256(image).hexdigest(), semantic_certification=False)


def test_supported_natural_language_can_receive_review_assisted_confidence_approval():
    caption = 'A brown dog walking beside a tree'
    review = source_review_receipt(caption, picture())
    assert quality.supported_review(caption, picture(), review)
    assert not review['semantic_certification']


@pytest.mark.parametrize('caption', ['A patient receiving medical treatment', 'Revenue increased 40%',
    'A doctor beside a tree', 'A dog named Peter', 'Two brown dogs walking',
    'A brown dog possibly walking beside a tree', 'A brown dog driving a car',
    'A chart with revenue by year'])
def test_unsupported_numeric_clinical_identity_uncertain_or_unobserved_claims_are_rejected(caption):
    assert not quality.supported_review(caption, picture(), source_review_receipt(caption, picture()))


def test_natural_caption_generates_review_assisted_proposal_without_inline_write(monkeypatch):
    import ai, ocr, llm_waterfall_provider
    caption = 'A brown dog walking beside a tree'
    monkeypatch.setattr(llm_waterfall_provider, 'managed_context', lambda:SimpleNamespace(
        policy={'quality_first':True,'auto_approve_ai':True,'ai_review':{'enabled':False}}, enabled=True))
    monkeypatch.setattr(ocr,'ocr_text',lambda *a:'')
    monkeypatch.setattr(ai,'_vision_generate',lambda *a, **kw:caption)
    monkeypatch.setattr(quality,'cloud_review',lambda *a: source_review_receipt(caption,natural_picture()))
    result = ai.describe_image_structured(natural_picture())
    assert not result.get('automatic_write_blocked')
    assert not result['grounded'] and result['approval_required']
    assert result['quality_source_review']['status'] == 'ai_reviewed'
    assert not result['quality_source_review']['semantic_certification']


@pytest.mark.parametrize('ext', ['docx','pdf'])
@pytest.mark.parametrize('mutation', [None,'missing_receipt','changed_caption','changed_image','unknown_spending'])
def test_natural_caption_standing_approval_requires_retained_exact_settled_source_review(isolated_store, monkeypatch, mutation, ext, tmp_path):
    import json, blob
    import test_ai_standing_approval as fixture
    from ai_run_policy import run_context
    from ai_standing_approval import approve_file
    from ai_attempt_history import AttemptHistory
    from ai_review_chain import _save_review
    source_image = natural_picture()
    if ext == 'pdf':
        from test_pdf_figure_evidence import raster_pdf, saved_bytes
        pdf, figure, _ = raster_pdf(size=80, pixels=Image.open(io.BytesIO(source_image)).tobytes())
        data = saved_bytes(pdf); pdf.close()
        association = quality.pdf_image(data,'pdf:fig:1:0')
        source_image = association['image_bytes']
    else:
        data = package(image=source_image)
    digest = hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(fixture, 'FILE', 'file.' + ext)
    monkeypatch.setattr(fixture, 'DIGEST', digest)
    monkeypatch.setattr(fixture, 'BYTES', data)
    monkeypatch.setattr(blob, 'download_remediated', lambda *a:data)
    store = isolated_store; job = fixture.seed(store, monkeypatch)
    caption = 'A brown dog walking beside a tree'
    with run_context(store, job['payload'], job) as ctx:
        p = fixture.proposal(store, rule='1.1.1', locator='pdf:fig:1:0' if ext == 'pdf' else 'word/document.xml#Picture 1',
                             value=caption, model='draft', review=None)
        if ext == 'pdf':
            p.update(kind='pdf-figure-alt',figure_image_sha256=association['image_sha256'],
                     figure_association_method=association['method'])
        reviewer_call = store.record_ai_call(surface='vision',provider='synthetic',model='reviewer',
            zone='cloud',latency_ms=0,ok=True,scan_id=fixture.SID,file=fixture.FILE)
        review = source_review_receipt(caption, source_image); review['model_call_id'] = reviewer_call
        history = AttemptHistory(store._db)
        ctx.ledger.reserve(ctx.owner_id, ctx.run_id, 'review-attempt', 10, 'fixture-price')
        history.begin(ctx.owner_id, ctx.scan_id, ctx.run_id, 'review-op','review-attempt',
            file=fixture.FILE,input_sha256=digest,model='reviewer',provider='synthetic',purpose='review')
        history.finish(ctx.owner_id,ctx.scan_id,ctx.run_id,'review-attempt', status='drafted',
            result={'text':json.dumps(review),'model':'reviewer','provider':'synthetic'})
        ctx.ledger.claim_dispatch(ctx.owner_id,ctx.run_id,'review-attempt')
        ctx.ledger.settle(ctx.owner_id,ctx.run_id,'review-attempt',1)
        history.bind_trace(ctx.owner_id,ctx.scan_id,ctx.run_id,'review-op',reviewer_call,file=fixture.FILE)
        if mutation != 'missing_receipt':
            _save_review(ctx,'review-op',review['proposal_sha256'],review)
        if mutation == 'changed_caption': p['proposed_value'] = 'A brown dog driving a car'
        if mutation == 'changed_image': review['image_sha256'] = 'changed'
        if mutation == 'unknown_spending':
            with store._db.cursor() as cur:
                store._db.execute(cur,"UPDATE ai_spending_attempts SET state='uncertain' WHERE attempt_id='review-attempt'")
        p.update(source_sha256=digest, quality_source_review={'status':'ai_reviewed','cloud_review':review})
        store.enqueue_proposals(fixture.SID,fixture.FILE,'1.1.1',[p])
        with store._db.cursor() as cur:
            store._db.execute(cur,'SELECT policy_json FROM ai_spending_run_policies WHERE run_id=%s',(ctx.run_id,))
            policy = json.loads(store._db.fetchone(cur)['policy_json'])
            policy.update(quality_first=True,ai_review={'enabled':False})
            store._db.execute(cur,'UPDATE ai_spending_run_policies SET policy_json=%s WHERE run_id=%s',
                              (json.dumps(policy),ctx.run_id))
        approve_file(store,ctx)
    assert bool(fixture.apply_jobs(store)) is (mutation is None)
    if mutation is None:
        from ai_standing_approval import check_application
        from unverified_changes import structurally_readable
        writer = fixture.apply_jobs(store)[0]
        intent = json.loads(writer['payload']) if isinstance(writer['payload'],str) else writer['payload']
        check_application(store,intent,working=data)
        original_path=tmp_path/('original.'+ext); original_path.write_bytes(data)
        if ext == 'pdf':
            from remediate_pdf import apply_pdf_approved
            corrected, written, unresolved = apply_pdf_approved(data,{p['locator']:caption})
            assert structurally_readable(data,corrected,'file.pdf',pdf_semantic_targets={p['locator']:caption})
        else:
            from apply_alt import apply_alt_text
            from office_alt_integrity import verify_alt_write
            corrected, written, unresolved = apply_alt_text(data,{p['locator']:caption})
            assert verify_alt_write(data,corrected,{p['locator']:caption})
        saved_path=tmp_path/('corrected.'+ext); saved_path.write_bytes(corrected)
        assert saved_path.read_bytes()==corrected and written and not unresolved
        assert original_path.read_bytes()==data


def test_cloud_review_replay_keeps_first_immutable_receipt(isolated_store, monkeypatch):
    import json
    from test_ai_standing_approval import seed
    from ai_run_policy import run_context
    store = isolated_store; job = seed(store,monkeypatch)
    calls = []
    def generate(prompt,image,**kwargs):
        calls.append(1)
        return dict(model='reviewer', provider='synthetic', ai_call_id='trace-' + str(len(calls)),
            operation_id='replayed-review', image_processing={'original_sha256':hashlib.sha256(image).hexdigest()},
            text=json.dumps(dict(verdict='accept',reason='Direct source evidence',
                observations=['Brown dog walking beside a tree'],unsupported_claims=[])))
    with run_context(store,job['payload'],job):
        first = quality.cloud_review('A brown dog walking beside a tree',natural_picture(),'draft',
                                     generate=generate,models=['draft','reviewer'])
        second = quality.cloud_review('A brown dog walking beside a tree',natural_picture(),'draft',
                                      generate=generate,models=['draft','reviewer'])
    assert first['verdict'] == 'accept' and first == second
    assert second['model_call_id'] == 'trace-1'


def test_quality_recovery_feedback_is_bounded_and_does_not_replace_good_draft(isolated_store, monkeypatch):
    import json, blob, remediate_office, ai_standing_approval
    import vision_recovery as recovery
    from test_vision_recovery import seed, DATA, SID, FILE
    store=isolated_store; job,payload=seed(store)
    from contextlib import contextmanager
    import ai_run_policy
    original_context=ai_run_policy.run_context
    @contextmanager
    def quality_context(*args):
        with original_context(*args) as context:
            from dataclasses import replace
            yield replace(context, policy={**context.policy, 'quality_first':True,'auto_approve_ai':True})
    monkeypatch.setattr(ai_run_policy,'run_context',quality_context)
    monkeypatch.setattr(blob,'download_remediated',lambda *a:DATA)
    monkeypatch.setattr(ai_standing_approval,'approve_file',lambda *a:None)
    calls=[]
    def generate(*args,**kwargs):
        calls.append(kwargs)
        return [dict(locator='word/document.xml#r1',proposed_value='Uncertain image',automatic_write_blocked=True,
                     quality_source_review={'cloud_review':{'verdict':'revise','reason':'Claim unsupported'}})],[]
    monkeypatch.setattr(remediate_office,'alt_proposals_for_office',generate)
    recovery.process(store,payload)
    retries=store.list_scan_jobs_of_type(SID,'vision_proposal_retry')
    second=next(json.loads(r['payload']) for r in retries if json.loads(r['payload'])['retry']==2)
    recovery.process(store,second)
    assert len(store.list_scan_jobs_of_type(SID,'vision_proposal_retry')) == 2
    assert 'Quality recovery attempt 1' in calls[0]['guidance']
    assert 'Claim unsupported' in calls[1]['guidance']
    assert calls[0]['skip_locators'] == calls[1]['skip_locators'] == {'word/document.xml#r2'}
    assert store.get_hitl_item(payload['item_id'])['proposals'][1]['proposed_value']=='Author supplied caption'


def test_source_observations_cannot_support_swapped_or_negated_relationships():
    caption='A dog above a tree'
    review=source_review_receipt(caption,natural_picture())
    review['observations']=['A dog below a tree with a bird above']
    assert not quality.supported_review(caption,natural_picture(),review)
    review['observations']=['A dog is not above a tree']
    assert not quality.supported_review(caption,natural_picture(),review)


@pytest.mark.parametrize('mutation',['cancelled','artifact'])
def test_document_source_review_rechecks_run_and_artifact_after_reviewer_returns(monkeypatch, mutation):
    from dataclasses import replace
    import document_wide_workflow as workflow
    from test_document_wide_workflow import setup
    from experiments.document_wide_ai.contracts.v1 import DocumentFormat
    store,ctx,calls,logs,queued=setup(monkeypatch,sc='1.1.1')
    import blob, document_wide_manifest
    ctx.file='file.docx'; ctx.policy.update(quality_first=True,auto_approve_ai=True)
    data=package(image=natural_picture()); digest=hashlib.sha256(data).hexdigest()
    manifest=document_wide_manifest.build_manifest()
    locator=replace(manifest.findings[0].locator,format=DocumentFormat.DOCX,
                    part_name='word/document.xml',element_ref='Picture 1')
    manifest=replace(manifest,source_sha256=digest,document_format=DocumentFormat.DOCX,
                     findings=(replace(manifest.findings[0],locator=locator),))
    monkeypatch.setattr(document_wide_manifest,'build_manifest',lambda *a:manifest)
    monkeypatch.setattr(blob,'download_remediated',lambda *a:data)
    changed=[]
    store.get_file_record=lambda *a:{'corrected_sha256':'changed' if changed and mutation=='artifact' else digest}
    stage=store.get_stage_execution
    store.get_stage_execution=lambda *a,**k:{**stage(*a,**k),
        'cancel_requested_at':'now' if changed and mutation=='cancelled' else None}
    store.list_finding_dispositions=lambda *a:[dict(finding_id='real-finding',file=ctx.file,rule_id='1.1.1')]
    caption='A brown dog walking beside a tree'
    monkeypatch.setattr(workflow,'_saved',lambda *a:{'proposals':{'1.1.1':[
        dict(locator='word/document.xml#Picture 1',finding_ids=['real-finding'],
             proposed_value=caption,source_sha256=digest,model='draft')]}})
    def reviewer(*args):
        changed.append(True)
        return source_review_receipt(caption,natural_picture())
    monkeypatch.setattr(quality,'cloud_review',reviewer)
    workflow.process_file(store,ctx)
    assert changed and not queued and not calls
    assert any('changed during automatic source review' in entry[1].get('detail','') for entry in logs)


from test_vision_generation import setup as metered_vision_setup, specs  # noqa: E402,F401


def test_source_review_purpose_uses_actual_metered_ledger_and_trace_without_paid_replay(metered_vision_setup):
    import json
    from ai_run_policy import run_context
    from ai_attempt_history import AttemptHistory
    store,job,calls,outputs=metered_vision_setup
    outputs.append(json.dumps(dict(verdict='accept',reason='Direct source image evidence',
        observations=['Brown dog walking beside a tree'],unsupported_claims=[])))
    caption='A brown dog walking beside a tree'
    with run_context(store,job['payload'],job) as context:
        first=quality.cloud_review(caption,natural_picture(),'gpt-4.1-mini-2025-04-14')
        spent=context.ledger.snapshot(context.owner_id,context.run_id)['spent_units']
        second=quality.cloud_review(caption,natural_picture(),'gpt-4.1-mini-2025-04-14')
        history=AttemptHistory(store._db).list_run(context.owner_id,context.scan_id,context.run_id)
        assert context.ledger.snapshot(context.owner_id,context.run_id)['spent_units']==spent
    assert first==second and first['verdict']=='accept' and len(calls)==1
    assert history[0]['purpose']=='review' and history[0]['spending_state']=='settled'
    assert first['model_call_id'] in history[0]['trace_call_ids']
    assert calls[0]['messages'][0]['content'][-1]['image_url']['url'].startswith('data:image/png;base64,')


def test_review_assisted_acceptance_cannot_override_unsupported_color_profile_or_transparency():
    image=Image.open(io.BytesIO(natural_picture()))
    output=io.BytesIO(); image.save(output,format='PNG',icc_profile=b'unsupported profile')
    caption='A brown dog walking beside a tree'
    assert not quality.supported_review(caption,output.getvalue(),source_review_receipt(caption,output.getvalue()))
    image=image.convert('RGBA'); image.putalpha(128)
    output=io.BytesIO(); image.save(output,format='PNG')
    assert not quality.supported_review(caption,output.getvalue(),source_review_receipt(caption,output.getvalue()))
