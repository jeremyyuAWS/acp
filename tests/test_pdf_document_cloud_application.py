"""Production PDF proposal/standing approval/writer/delivery path, offline only."""
import io
import json
from hashlib import sha256
import pikepdf
import pytest

import handlers
import document_wide_workflow
import document_wide_provider
from ai_run_policy import run_context
from ai_standing_approval import approve_file
from experiments.document_wide_ai.contracts.v1 import EditResponseEnvelope, ProposedEdit, CONTRACT_VERSION
from remediation_contribution import SOURCE, bind_assessed_input, freeze_baseline
from test_apply_approved_values import _Blob
from test_document_wide_pdf_context import pdf_context
import test_ai_standing_approval as base


@pytest.mark.parametrize('input_mode', ['extracted', 'native_pdf'])
@pytest.mark.parametrize('corrupt_writer', [False, True])
def test_pdf_document_figure_reaches_real_writer_and_exact_saved_delivery(isolated_store, monkeypatch, tmp_path, corrupt_writer, input_mode):
    store = isolated_store
    monkeypatch.setattr(base, 'FILE', 'file.pdf')
    original = pdf_context()
    with pikepdf.open(io.BytesIO(original)) as pdf:
        pdf.docinfo['/Title'] = 'Previously corrected title'
        pdf.Root.AcroForm.Fields[0].V = pikepdf.String('Alice Patient')
        stream = io.BytesIO(); pdf.save(stream); candidate = stream.getvalue()
    job = base.seed(store, monkeypatch)
    sid, filename = base.SID, base.FILE
    with store._db.cursor() as cur:
        store._db.execute(cur, 'UPDATE file_records SET corrected_sha256=%s WHERE scan_id=%s', (sha256(candidate).hexdigest(), sid))
        store._db.execute(cur, 'SELECT execution_id,input_snapshot_id FROM stage_executions WHERE scan_id=%s', (sid,))
        stage = store._db.fetchone(cur)
        rows = [{'finding_id':'assessed-pdf-figure', 'file':filename, 'rule_id':'1.1.1', 'instance_key':'pdf:fig:1:0'}]
        freeze_baseline(store._db, cur, base.OWNER, sid, stage['execution_id'], stage['input_snapshot_id'], rows, [filename])
    monkeypatch.setattr(store, 'get_scan_scope', lambda *a: {'1.1.1':frozenset({'pdf'})})
    monkeypatch.setattr(store, 'scope_for_file', lambda s,f,scope: scope)
    monkeypatch.setattr(store, 'list_finding_dispositions', lambda *a: rows)
    import sys
    blob = _Blob(candidate); monkeypatch.setitem(sys.modules, 'blob', blob)
    from proposals import Verification
    from formats.pdf.detectors.non_text_content import detect
    def verify(data, file, **kwargs):
        path = tmp_path / 'recheck.pdf'; path.write_bytes(data)
        return Verification(True, {'1.1.1'} if detect(path) else set())
    monkeypatch.setattr(handlers, '_verify_residual', verify)
    captured = []
    token = SOURCE.set(None)
    try:
        with run_context(store, job['payload'], job) as ctx:
            object.__setattr__(ctx, 'policy', {**ctx.policy, 'document_wide_ai':True, 'document_wide_input_mode':input_mode})
            with store._db.cursor() as cur:
                store._db.execute(cur, 'UPDATE ai_spending_run_policies SET policy_json=%s WHERE run_id=%s', (json.dumps(dict(ctx.policy)), ctx.run_id))
            assert bind_assessed_input(sid, filename, original, original)
            def generate(request, **kwargs):
                captured.append(request)
                assert request.manifest.selected_criteria == ('1.1.1',)
                assert len(request.manifest.findings) == 1  # no duplicate aggregate/target
                f = request.manifest.findings[0]
                assert f.finding_id == 'assessed-pdf-figure' and f.locator.element_ref == 'pdf:fig:1:0'
                if input_mode == 'native_pdf':
                    assert kwargs == {'pdf_bytes': candidate}
                    assert sha256(kwargs['pdf_bytes']).hexdigest() == request.manifest.source_sha256
                    assert kwargs['pdf_bytes'] != original  # retain previous deterministic fixes
                else:
                    assert kwargs['images']  # real bounded PDF visual context was supplied
                p = base.proposal(store, rule='1.1.1', locator=f.locator.element_ref, value='Red circle')
                with store._db.cursor() as cur:
                    store._db.execute(cur, "UPDATE ai_attempt_history SET status='drafted' WHERE run_id=%s", (ctx.run_id,))
                return {'envelope':EditResponseEnvelope(CONTRACT_VERSION, request.request_id, request.manifest.source_sha256,
                    (ProposedEdit('edit', (f.finding_id,), f.locator, 'set_pdf_figure_alt_text', 'Red circle', None),), ()),
                    'model':p['model'], 'model_call_id':p['model_call_id']}
            monkeypatch.setattr(document_wide_provider, 'generate_document', generate)
            document_wide_workflow.process_file(store, ctx)
            queue = store.list_hitl_queue(scan_id=sid, owner=base.OWNER)
            assert len(queue) == 1 and queue[0]['rule_id'] == '1.1.1'
            assert queue[0]['proposals'][0]['locator'] == 'pdf:fig:1:0'
            contributions = base.rows(store, 'remediation_contribution_proposals')
            assert len(contributions) == 1
            assert json.loads(contributions[0]['finding_ids_json']) == ['assessed-pdf-figure']
            assert contributions[0]['source_sha256'] == sha256(candidate).hexdigest()
            approve_file(store, ctx)
        jobs = base.apply_jobs(store)
        assert len(jobs) == 1 and len(captured) == 1
        if corrupt_writer:
            import remediate_pdf
            actual_writer = remediate_pdf.apply_pdf_approved
            def lose_form_value(data, values):
                fixed, applied, unresolved = actual_writer(data, values)
                with pikepdf.open(io.BytesIO(fixed)) as pdf:
                    del pdf.Root.AcroForm.Fields[0]['/V']
                    out = io.BytesIO(); pdf.save(out)
                return out.getvalue(), applied, unresolved
            monkeypatch.setattr(remediate_pdf, 'apply_pdf_approved', lose_form_value)
        handlers._apply_approved_values(json.loads(jobs[0]['payload']), {})
        if corrupt_writer:
            assert not blob.uploads
            assert blob.data == candidate
            assert any(r['action'] == 'apply.integrity_failed' for r in base.rows(store, 'decision_log'))
            return
        assert blob.uploads and blob.data != candidate, [(r['action'],r['detail']) for r in base.rows(store,'decision_log')]
        with pikepdf.open(io.BytesIO(blob.data)) as pdf:
            assert str(pdf.Root.StructTreeRoot.K[0].Alt) == 'Red circle'
            assert str(pdf.docinfo['/Title']) == 'Previously corrected title'
            assert len(pdf.pages) == 2
            assert len(pdf.Root.AcroForm.Fields) == 2
            assert str(pdf.Root.AcroForm.Fields[0].V) == 'Alice Patient'
            assert '/TU' not in pdf.Root.AcroForm.Fields[0]  # unselected SC4.1.2 untouched
        with pikepdf.open(io.BytesIO(original)) as pdf:
            assert '/Alt' not in pdf.Root.StructTreeRoot.K[0]
        from remediation_delivery import load_artifact
        delivered = load_artifact(owner=base.OWNER, scan_id=sid, file=filename,
            expected_digest=sha256(blob.data).hexdigest(), download=blob.download_remediated)
        assert delivered == blob.data
        from unverified_changes import blocks_certification
        assert blocks_certification(store, sid, filename)  # semantic review was not invented
        receipts = base.rows(store, 'ai_validation_outcomes')
        assert any(r['outcome']=='could_not_verify' and r.get('actual_source_sha256')==sha256(candidate).hexdigest() for r in receipts)
    finally:
        SOURCE.reset(token)


def test_pdf_integrity_uses_deployed_runtime_and_rejects_lost_pages_or_corruption():
    from unverified_changes import structurally_readable
    original = pdf_context()
    assert structurally_readable(original, original, 'file.pdf')
    assert not structurally_readable(original, b'not a PDF', 'file.pdf')
    assert not structurally_readable(original, original[:-80], 'file.pdf')
    with pikepdf.open(io.BytesIO(original)) as pdf:
        del pdf.pages[1]
        stream = io.BytesIO(); pdf.save(stream)
    assert not structurally_readable(original, stream.getvalue(), 'file.pdf')
    with pikepdf.open(io.BytesIO(original)) as pdf:
        stream = io.BytesIO(); pdf.save(stream, encryption=pikepdf.Encryption(owner='fixture-owner', user=''))
    assert not structurally_readable(original, stream.getvalue(), 'file.pdf')


def test_pdf_semantic_guard_checks_exact_value_and_unselected_targets():
    from unverified_changes import structurally_readable
    from remediate_pdf import apply_pdf_approved
    original = pdf_context()
    expected = {'pdf:fig:1:0': 'Red circle'}
    corrected, applied, unresolved = apply_pdf_approved(original, expected)
    assert applied and not unresolved
    assert structurally_readable(original, corrected, 'file.pdf', pdf_semantic_targets=expected)
    assert not structurally_readable(original, corrected, 'file.pdf',
                                     pdf_semantic_targets={'pdf:fig:1:0': 'Blue circle'})
    with pikepdf.open(io.BytesIO(corrected)) as pdf:
        pdf.Root.AcroForm.Fields[0].TU = pikepdf.String('Unapproved field label')
        out = io.BytesIO(); pdf.save(out)
    assert not structurally_readable(original, out.getvalue(), 'file.pdf', pdf_semantic_targets=expected)
