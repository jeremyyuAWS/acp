"""Forecast fixtures count instances, exercise full-population loading and owner gates."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from remediation_impact import build_impact_preview, load_run_findings


def rule(file, count, **extra):
    return {'file': file, 'rule_id': 'WCAG_1_3_1', 'finding_count': count,
            'origin': 'rule_based', 'remediation_supported': True, **extra}


def test_prd_seven_findings_three_files():
    rows = [rule('a.docx', 3), rule('b.docx', 2, origin='ai'),
            rule('c.docx', 1), rule('c.docx', 1, rule_id='WCAG_1_1_1', human_only=True)]
    coverage = [{'file': f, 'complete': True} for f in ('a.docx', 'b.docx', 'c.docx')]
    result = build_impact_preview(rows, {'rule_based': 2, 'ai': 1}, files=coverage,
                                  active_policy={'rule_based': 0, 'ai': 0})
    assert result['open'] == {'findings': 7, 'files': 3}
    assert result['lanes']['automatic']['findings'] == 4
    assert result['lanes']['automatic']['files'] == 2
    assert result['lanes']['automatic']['delta'] == 4
    assert result['lanes']['review']['findings'] == 2
    assert result['lanes']['manual']['findings'] == 1
    assert result['file_outlook']['could_complete']['files'] == 1
    assert result['file_outlook']['human_work']['files'] == 2
    assert sum(v['findings'] for v in result['lanes'].values()) == 7


def test_same_criterion_human_item_blocks_writer_for_entire_criterion():
    result = build_impact_preview([rule('a', 3), rule('a', 1, human_only=True)],
                                  {'rule_based': 2, 'ai': 1})
    assert result['lanes']['automatic']['findings'] == 0
    assert result['lanes']['review']['findings'] == 3
    assert result['findings'][0]['primary_reason'] == 'shared_criterion_requires_review'


def test_ai_drafts_never_count_as_automatic_even_at_unsupported_stops():
    result = build_impact_preview([rule('a', 2, origin='ai', validated=True, has_proposal=True)],
                                  {'rule_based': 2, 'ai': 3})
    assert result['lanes']['automatic']['findings'] == 0
    assert result['lanes']['review']['findings'] == 2
    assert result['capabilities']['execute'] is False


def test_unknown_coverage_never_claims_completion():
    result = build_impact_preview([rule('a', 2)], {'rule_based': 2, 'ai': 0})
    assert result['file_outlook']['unavailable']['files'] == 1
    assert result['file_outlook']['could_complete']['files'] == 0
    assert result['integrity']['complete']


def test_verified_requires_evidence_and_protected_stays_manual():
    result = build_impact_preview([rule('a', 3), rule('b', 2, validated=True),
                                   rule('c', 1, verification_failed=True)],
                                  {'rule_based': 1, 'ai': 1})
    assert result['lanes']['automatic']['findings'] == 2
    assert result['lanes']['review']['findings'] == 3
    assert result['lanes']['manual']['findings'] == 1


class Facts:
    def get_ai_enabled(self):
        return True
    def get_scan(self, sid, owner=None):
        return {'run': {'assessed_at': '2026-09-08T12:00:00Z'}, 'files': [{'file': 'a.docx'}, {'file': 'b.docx'}]} if owner == 'demo' else None
    def get_scan_traces(self, sid):
        return [{'file': 'a.docx', 'rule_id': '1.3.1', 'finding_count': 10653, 'outcome': 'FAIL', 'fix_mode': 'auto'},
                {'file': 'b.docx', 'rule_id': '1.1.1', 'finding_count': 17164, 'outcome': 'FAIL', 'fix_mode': 'ai-assisted'},
                {'file': 'b.docx', 'rule_id': '2.1.1', 'finding_count': 1, 'outcome': 'PASS', 'fix_mode': 'auto'}]
    def list_hitl_queue(self, **kwargs):
        return [{'file': 'b.docx', 'rule_id': '1.1.1', 'finding_count': 17164, 'validated': True,
                 'proposals': [{'text': 'draft'}]}]
    def get_scan_manifest(self, sid):
        return {'files': [{'file': 'a.docx', 'complete': True}, {'file': 'b.docx', 'complete': False}]}


def test_loader_uses_all_fail_instances_not_only_queue_and_ignores_stale_validation():
    rows, files = load_run_findings(Facts(), 's', 'demo')
    result = build_impact_preview(rows, {'rule_based': 2, 'ai': 1}, files=files)
    assert result['open']['findings'] == 27817
    assert result['lanes']['automatic']['findings'] == 10653
    assert result['lanes']['review']['findings'] == 17164
    assert not any(r['validated'] for r in rows)
    assert result['file_outlook']['blocked_incomplete']['files'] == 1
    with pytest.raises(LookupError):
        load_run_findings(Facts(), 's', 'another-owner')


def test_http_owner_gate_and_server_population(monkeypatch):
    import core
    from routes.remediation_policy import router
    import remediation_impact_settings
    monkeypatch.setattr(core, 'store', Facts())
    monkeypatch.setattr(remediation_impact_settings, 'read_impact_policy', lambda *a: {'rule_based': 2, 'ai': 1})
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.post('/scans/s/remediation/impact-preview', json={'rule_based': 2, 'ai': 1, 'findings': []})
    assert response.status_code == 200
    assert response.json()['open']['findings'] == 27817
    assert response.headers['cache-control'] == 'no-store'
    app = FastAPI()
    app.include_router(router)
    @app.middleware('http')
    async def owner(request, call_next):
        request.state.user_email = 'another-owner'
        return await call_next(request)
    with TestClient(app) as scoped:
        assert scoped.post('/scans/s/remediation/impact-preview', json={'rule_based': 2, 'ai': 1}).status_code == 404


def test_verified_credits_need_matching_snapshot_population(monkeypatch):
    import remediation_impact
    monkeypatch.setattr(remediation_impact, '_verified_credits', lambda *a: {
        ('a.docx', '1.3.1'): {'total': 10653, 'verified': 100},
        ('b.docx', '1.1.1'): {'total': 9, 'verified': 9}})
    rows, _ = load_run_findings(Facts(), 's', 'demo')
    assert rows[0]['finding_count'] == 10553
    assert rows[1]['finding_count'] == 17164


def test_global_ai_switch_blocks_execution_but_preserves_rule_forecast(monkeypatch):
    from remediation_impact import build_run_impact
    import remediation_impact_settings
    monkeypatch.setattr(remediation_impact_settings, 'read_impact_policy', lambda *a: {'rule_based': 2, 'ai': 1})
    facts = Facts()
    facts.get_ai_enabled = lambda: False
    result = build_run_impact(facts, 's', 'demo')
    assert not result['capabilities']['execute']
    assert result['lanes']['automatic']['findings'] == 10653
    assert build_run_impact(facts, 's', 'demo', {'rule_based': 2, 'ai': 0})['capabilities']['execute']


def test_selected_scope_filters_files_and_findings_together(monkeypatch):
    from remediation_impact import build_run_impact
    import remediation_impact_settings
    monkeypatch.setattr(remediation_impact_settings, 'read_impact_policy', lambda *a: {'rule_based': 2, 'ai': 1})
    result = build_run_impact(Facts(), 's', 'demo', scope=['a.docx'])
    assert result['open'] == {'findings': 10653, 'files': 1}
    assert result['scope'] == {'type': 'selected_files', 'files': 1}
    assert [f['file'] for f in result['files']] == ['a.docx']


def test_no_assessment_is_unavailable_not_a_clean_zero(monkeypatch):
    from remediation_impact import build_run_impact
    import remediation_impact_settings
    monkeypatch.setattr(remediation_impact_settings, 'read_impact_policy', lambda *a: {'rule_based': 2, 'ai': 1})
    facts = Facts()
    facts.get_scan = lambda *a, **kw: {'run': {'status': 'running'}, 'files': [{'file': 'a.docx'}]}
    facts.get_scan_traces = lambda *a: []
    facts.get_scan_manifest = lambda *a: {'files': []}
    result = build_run_impact(facts, 's', 'demo')
    assert not result['integrity']['complete']
    assert not result['capabilities']['execute']


def test_http_default_policy_and_strict_validation(monkeypatch):
    import core
    from routes.remediation_policy import router
    import remediation_impact_settings
    monkeypatch.setattr(core, 'store', Facts())
    monkeypatch.setattr(remediation_impact_settings, 'read_impact_policy', lambda *a: {'rule_based': 2, 'ai': 1})
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        assert client.post('/scans/s/remediation/impact-preview', json={}).status_code == 200
        for body in ({'rule_based': True, 'ai': 1}, {'rule_based': 2}, {'ai': 1}, {'rule_based': 3, 'ai': 1}):
            assert client.post('/scans/s/remediation/impact-preview', json=body).status_code == 422


@pytest.fixture
def assignment_store(isolated_store, monkeypatch):
    s = isolated_store
    s.init_scan_run('assign', 'local', 2, 't0', 'r', 'h', owner='demo')
    s.init_scan_run('foreign', 'local', 1, 't0', 'r', 'h', owner='other')
    original = s.get_scan
    def scan(sid, owner=None):
        result = original(sid, owner=owner)
        if result:
            result['run']['assessed_at'] = '2026-09-08'
            result['files'] = [{'file': 'a.docx'}, {'file': 'b.docx'}]
        return result
    monkeypatch.setattr(s, 'get_scan', scan)
    monkeypatch.setattr(s, 'get_scan_traces', lambda sid: [
        {'file': 'a.docx', 'rule_id': '1.1.1', 'fix_mode': 'ai-assisted', 'outcome': 'FAIL', 'finding_count': 5},
        {'file': 'a.docx', 'rule_id': '1.3.1', 'fix_mode': 'auto', 'outcome': 'FAIL', 'finding_count': 2},
        {'file': 'b.docx', 'rule_id': '1.1.1', 'fix_mode': 'ai-assisted', 'outcome': 'FAIL', 'finding_count': 3}])
    monkeypatch.setattr(s, 'get_scan_manifest', lambda sid: {'files': []})
    return s


def test_assignment_persists_only_selected_nonautomatic_work(assignment_store):
    from remediation_impact import assign_impact_work
    s = assignment_store
    result = assign_impact_work(s, 'assign', 'demo', ['a.docx'], 'reviewer@example.com')
    assert result['tasks_assigned'] == 1
    assert result['findings_assigned'] == 5
    rows = s.list_hitl_queue(scan_id='assign', owner='demo')
    assert len(rows) == 1
    assert rows[0]['rule_id'] == '1.1.1'
    assert rows[0]['assignee'] == 'reviewer@example.com'
    assert rows[0]['status'] == 'pending'
    # Exact repeat updates the existing assignment, without another task.
    assign_impact_work(s, 'assign', 'demo', ['a.docx'], 'reviewer@example.com')
    assert len(s.list_hitl_queue(scan_id='assign')) == 1


def test_assignment_preserves_terminal_and_foreign_work(assignment_store):
    from remediation_impact import assign_impact_work
    s = assignment_store
    s.queue_hitl_review_for_file('assign', 'a.docx', [{'rule_id': '1.1.1', 'finding_count': 1}])
    row = s.list_hitl_queue(scan_id='assign')[0]
    with s._db.cursor() as cur:
        s._db.execute(cur, "UPDATE hitl_queue SET status='approved',assignee='original@example.com' WHERE id=%s", (row['id'],))
    result = assign_impact_work(s, 'assign', 'demo', ['a.docx'], 'new@example.com')
    assert result['tasks_assigned'] == 0
    unchanged = s.get_hitl_item(row['id'])
    assert unchanged['assignee'] == 'original@example.com'
    assert unchanged['finding_count'] == 1
    assert unchanged['status'] == 'approved'
    with pytest.raises(LookupError):
        assign_impact_work(s, 'foreign', 'demo', ['a.docx'], 'new@example.com')
    assert not s.list_hitl_queue(scan_id='foreign')


def test_credits_bind_real_stage_snapshot_not_scan_identifier(isolated_store, monkeypatch):
    from remediation_impact import _verified_credits
    s = isolated_store
    s.init_scan_run('credits', 'local', 1, 't0', 'r', 'h', owner='demo')
    s.enqueue_job('remediate_file', {'file': 'a.docx'}, scan_id='credits', batch_id='batch-credit')
    snapshot = s.stage_snapshot_id('credits')
    assert snapshot != 'credits'
    monkeypatch.setattr(s, 'list_finding_dispositions', lambda *a: [
        {'file': 'a.docx', 'rule_id': '1.1.1', 'snapshot_id': snapshot,
         'disposition': 'resolved_verified', 'verified_at': 'now', 'fix_evidence_ids': ['evidence']},
        {'file': 'a.docx', 'rule_id': '1.1.1', 'snapshot_id': snapshot,
         'disposition': 'resolved_verified', 'verified_at': None, 'fix_evidence_ids': []}])
    assert _verified_credits(s, 'credits') == {('a.docx', '1.1.1'): {'total': 2, 'verified': 1}}
    monkeypatch.setattr(s, 'current_stage_output_manifest', lambda *a: {'manifest_id': 'new-assessment'})
    assert _verified_credits(s, 'credits') == {}


def test_provider_summary_allowlists_fields_without_probing(monkeypatch):
    import json
    from types import SimpleNamespace
    from remediation_impact import provider_summary
    import providers
    monkeypatch.setattr(providers, 'text_provider_provenance', lambda: {
        'provider': 'openai', 'model': 'text-model', 'zone': 'cloud', 'key': 'secret-text'})
    def forbidden(*a, **kw):
        pytest.fail('Provider summary must not generate or probe')
    monkeypatch.setattr(providers, 'active_vision_provider', lambda: SimpleNamespace(
        name='anthropic', model='vision-model', zone='cloud', api_key='secret-vision', generate=forbidden))
    monkeypatch.setattr(providers, 'test_connection', forbidden)
    result = provider_summary(True)
    assert result['text']['provider'] == 'openai'
    assert result['vision']['model'] == 'vision-model'
    assert result['vision']['connection'] == 'not_tested'
    assert result['global_ai_enabled']
    assert 'secret' not in json.dumps(result)
    assert 'key' not in json.dumps(result)
