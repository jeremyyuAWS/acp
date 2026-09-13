"""Real managed handler -> exact pixels -> consent -> approved writer -> actual rescan.

Only the external transport and the model reply are synthetic. PDF association,
semantic validation, run authorization, snapshots, writers, and detectors are real.
"""
import hashlib
import io
import json

import pytest
from PIL import Image
import ai, blob, core, handlers, scanner
from ai_run_policy import optional_current_run_context
from test_pdf_figure_evidence import raster_pdf, saved_bytes
from test_remediation_source_cache_key import _FakeService

OWNER, SID, FILE = 'pdf-owner@example.test', 'managed-exact-pdf', 'figure.pdf'


def seed(store, monkeypatch, tmp_path, *, document_wide=False):
    monkeypatch.setattr(core, 'store', store)
    monkeypatch.setattr(core, 'get_scan_tokens', lambda sid: {})
    monkeypatch.setattr(blob, '_ENABLED', True)
    service = _FakeService()
    monkeypatch.setattr(blob, '_service_client', lambda: service)
    pdf, _, _ = raster_pdf(size=32)
    source = saved_bytes(pdf); pdf.close()
    checksum = hashlib.sha256(source).hexdigest()
    store.save_scan({'_scan_id': SID, 'started_at': '2026-09-13T00:00:00Z',
        'completed_at': '2026-09-13T00:01:00Z', 'source': 'local', 'owner': OWNER,
        'rubric': {'name': 'wcag-aa', 'hash': 'fixture'},
        'scope': {'scan_scope': {'1.1.1': ['pdf']}},
        'summary': {'files': 1, 'certifiable': 0, 'uncertain': 1, 'error': 0, 'avg_score': 50},
        'files': [{'file': FILE, 'engine': 'pdf', 'status': 'analysed', 'score': 50,
            'compliant': 0, 'skipped_rules': 0, 'issues': [{'ruleId': 'PDF_FIGURE_NO_ALT',
                'wcag': '1.1.1 Non-text Content', 'severity': 'CRITICAL'}]}]})
    store.add_inventory(SID, [{'file': FILE, 'checksum': checksum, 'owner': OWNER,
        'size_kb': 4, 'mime': 'application/pdf'}])
    (tmp_path/FILE).write_bytes(source)
    scanner.cache_source_bytes(tmp_path, FILE, SID, OWNER, checksum=checksum)
    batch = store.enqueue_stage_batch(SID, 'remediate', 'remediate_file', [{
        'scan_id': SID, 'file': FILE, 'owner': OWNER, 'source': 'local', 'checksum': checksum,
        'remediation_impact_allowed_rules': [],
        'remediation_impact_policy': {'rule_based': 0, 'ai': 1, 'ai_budget_usd': '1.00',
            'ai_zone': 'any' if document_wide else 'local', 'auto_approve_ai': True,
            'document_wide_ai': document_wide}}],
        snapshot_id=store.remediation_source_revision(SID), request_fingerprint='managed-exact')
    return store.get_job(batch['job_ids'][0]), source, service


@pytest.mark.parametrize('document_wide', [False, True])
def test_managed_run_generates_once_and_standing_approval_rechecks_exact_artifact(isolated_store, monkeypatch, tmp_path, document_wide):
    from ai_standing_approval import check_application
    from formats.pdf.detectors import non_text_content
    import remediate_pdf
    s = isolated_store
    job, source, transport = seed(s, monkeypatch, tmp_path, document_wide=document_wide)
    calls = []
    def describe(png, **kw):
        ctx = optional_current_run_context()
        assert ctx and ctx.policy['auto_approve_ai'] is True
        assert ctx.policy.get('document_wide_ai') is document_wide
        pixels = Image.open(io.BytesIO(png))
        assert pixels.size == (32, 32) and pixels.getpixel((0, 0)) == (255, 0, 0)
        calls.append(png)
        call_id = s.record_ai_call(surface='synthetic', provider='synthetic', model='fixture-local',
            zone='local', latency_ms=0, ok=True, scan_id=SID, file=FILE)
        return {'alt': 'A solid red image.', 'grounded': False, 'model': 'fixture-local', 'ai_call_id': call_id}
    monkeypatch.setattr(ai, 'describe_image_structured', describe)
    if document_wide:
        import document_wide_provider
        monkeypatch.setattr(document_wide_provider, 'generate_document', lambda *a, **k: pytest.fail('Already proved figure must not charge a second model'))
    handlers._remediate_file(job['payload'], job)
    assert len(calls) == 1  # no inline + proposal duplicate
    items = s.list_hitl_queue(scan_id=SID, owner=OWNER)
    row = next(row for row in items if row['rule_id'] == '1.1.1')
    with s._db.cursor() as cur:
        s._db.execute(cur, 'SELECT action,detail FROM decision_log WHERE scan_id=%s', (SID,))
        audit = s._db.fetchall(cur)
    assert row['status'] == 'approved' and not row['applied'], json.dumps({'audit': audit, 'proposals': row['proposals']})
    proposal = row['proposals'][0]
    corrected = blob.download_remediated(OWNER, SID, FILE)
    assert corrected and proposal['source_sha256'] == hashlib.sha256(corrected).hexdigest()
    assert proposal['caption_validation']['approved'] is True
    assert proposal['proposed_value'] == 'The image is a solid red color.'
    jobs = s.list_scan_jobs_of_type(SID, 'apply_approved_values')
    assert len(jobs) == 1
    payload = json.loads(jobs[0]['payload']) if isinstance(jobs[0]['payload'], str) else jobs[0]['payload']
    check_application(s, payload, working=corrected)
    if document_wide:
        from remediate_pdf import validate_exact_pdf_finding_bindings
        assert proposal['finding_ids'] and proposal['assessment_revision']
        for field, wrong in [('finding_ids', ['invented']), ('baseline_finding_ids', ['invented']), ('assessment_revision', 'stale')]:
            altered = {**proposal, field: wrong}
            assert not validate_exact_pdf_finding_bindings(s, OWNER, SID, job['payload']['stage_execution_id'], FILE, corrected, [altered])
    if document_wide:
        run_id = job['payload']['stage_execution_id']
        with s._db.cursor() as cur:
            s._db.execute(cur, 'SELECT baseline_json FROM remediation_contribution_runs WHERE owner_id=%s AND scan_id=%s AND run_id=%s', (OWNER, SID, run_id))
            original_baseline = s._db.fetchone(cur)['baseline_json']
            bad = json.loads(original_baseline)
            bad[0]['instance_key'] = 'pdf:fig:2:0'
            s._db.execute(cur, 'UPDATE remediation_contribution_runs SET baseline_json=%s WHERE owner_id=%s AND scan_id=%s AND run_id=%s', (json.dumps(bad), OWNER, SID, run_id))
        assert not validate_exact_pdf_finding_bindings(s, OWNER, SID, run_id, FILE, corrected, [proposal])
        with s._db.cursor() as cur:
            s._db.execute(cur, 'UPDATE remediation_contribution_runs SET baseline_json=%s WHERE owner_id=%s AND scan_id=%s AND run_id=%s', (original_baseline, OWNER, SID, run_id))
        assert not validate_exact_pdf_finding_bindings(s, OWNER, SID, run_id, FILE, corrected + b'changed', [proposal])
    tampered = dict(proposal); tampered.pop('kind')
    with s._db.cursor() as cur:
        s._db.execute(cur, 'UPDATE hitl_queue SET proposals=%s WHERE id=%s', (json.dumps([tampered]), row['id']))
    with pytest.raises(ValueError, match='Document-wide automatic approval|exact output'):
        check_application(s, payload, working=corrected)
    with s._db.cursor() as cur:
        s._db.execute(cur, 'UPDATE hitl_queue SET proposals=%s WHERE id=%s', (json.dumps([proposal]), row['id']))
    handlers._apply_approved_values(payload, jobs[0])
    stored_written = blob.download_remediated(OWNER, SID, FILE)
    assert stored_written != corrected
    assert bool(s.get_hitl_item(row['id'])['applied'])
    assert handlers._verify_residual(stored_written, FILE, scan_id=SID).cleared({'1.1.1'})
    written, applied, unresolved = remediate_pdf.apply_pdf_approved(corrected,
        {proposal['locator']: proposal['proposed_value']})
    assert len(applied) == 1 and not unresolved
    before = tmp_path/'working.pdf'; before.write_bytes(corrected)
    after = tmp_path/'written.pdf'; after.write_bytes(written)
    assert non_text_content.detect(before) and non_text_content.detect(after) == []
    assert remediate_pdf._render_page_png(str(before), 1) == remediate_pdf._render_page_png(str(after), 1)
    assert (tmp_path/FILE).read_bytes() == source
    assert scanner.read_cached_source(SID, FILE, OWNER, checksum=hashlib.sha256(source).hexdigest()) == source
    with s._db.cursor() as cur:
        s._db.execute(cur, 'SELECT proposal_json FROM ai_proposal_snapshots WHERE item_id=%s', (row['id'],))
        retained = json.loads(s._db.fetchone(cur)['proposal_json'])
    assert retained['caption_validation']['evidence']['image_sha256'] == proposal['figure_image_sha256']
    # Altering text while retaining a validated flag cannot inherit authorization.
    proposal['proposed_value'] = 'The image is a solid blue color.'
    assert remediate_pdf.validate_exact_figure_proposals(corrected, [proposal]) is False


def test_unknown_caption_remains_optional_draft_without_automatic_write_or_credit(isolated_store, monkeypatch, tmp_path):
    s = isolated_store
    job, source, transport = seed(s, monkeypatch, tmp_path)
    calls = []
    def describe(png, **kw):
        calls.append(png)
        call_id = s.record_ai_call(surface='synthetic', provider='synthetic', model='fixture-local',
            zone='local', latency_ms=0, ok=True, scan_id=SID, file=FILE)
        return {'alt': 'A patient chart showing improved results.', 'grounded': True,
            'model': 'fixture-local', 'ai_call_id': call_id}
    monkeypatch.setattr(ai, 'describe_image_structured', describe)
    handlers._remediate_file(job['payload'], job)
    row = next(row for row in s.list_hitl_queue(scan_id=SID, owner=OWNER) if row['rule_id'] == '1.1.1')
    assert len(calls) == 1 and row['status'] == 'pending' and not row['applied']
    proposal = row['proposals'][0]
    assert proposal['proposed_value'] == 'A patient chart showing improved results.'
    assert proposal['automatic_write_blocked'] is True
    assert s.list_scan_jobs_of_type(SID, 'apply_approved_values') == []
    stored = blob.download_remediated(OWNER, SID, FILE)
    with __import__('pikepdf').open(io.BytesIO(stored)) as pdf:
        assert '/Alt' not in pdf.Root.StructTreeRoot.K.K[0]
    assert (tmp_path/FILE).read_bytes() == source


def test_exact_mapped_pdf_timeout_recovers_only_draft_and_queues_verified_writer(isolated_store, monkeypatch, tmp_path):
    import vision_recovery
    s = isolated_store
    job, source, _ = seed(s, monkeypatch, tmp_path)
    calls = []
    def describe(png, **kw):
        calls.append(png)
        if len(calls) == 1:
            vision_recovery.record('timeout')
            return None
        call_id = s.record_ai_call(surface='synthetic', provider='synthetic', model='fixture-local',
            zone='local', latency_ms=0, ok=True, scan_id=SID, file=FILE)
        return {'alt': 'A solid red image.', 'grounded': False, 'model': 'fixture-local', 'ai_call_id': call_id}
    monkeypatch.setattr(ai, 'describe_image_structured', describe)
    handlers._remediate_file(job['payload'], job)
    before = blob.download_remediated(OWNER, SID, FILE)
    record = dict(s.get_file_record(SID, FILE))
    retries = s.list_scan_jobs_of_type(SID, 'vision_proposal_retry')
    assert len(retries) == 1
    with s._db.cursor() as cur:
        s._db.execute(cur, 'SELECT run_after FROM jobs WHERE id=%s', (retries[0]['id'],))
        assert s._db.fetchone(cur)['run_after']
    payload = json.loads(retries[0]['payload']) if isinstance(retries[0]['payload'], str) else retries[0]['payload']
    assert payload['retry'] == 1 and payload['corrected_sha256'] == hashlib.sha256(before).hexdigest()
    vision_recovery.process(s, payload)
    row = next(row for row in s.list_hitl_queue(scan_id=SID, owner=OWNER) if row['rule_id'] == '1.1.1')
    assert len(calls) == 2 and row['status'] == 'approved' and not row['applied']
    assert row['proposals'][0]['caption_validation']['approved'] is True
    assert blob.download_remediated(OWNER, SID, FILE) == before
    assert dict(s.get_file_record(SID, FILE)) == record
    assert len(s.list_scan_jobs_of_type(SID, 'apply_approved_values')) == 1
    assert (tmp_path/FILE).read_bytes() == source
