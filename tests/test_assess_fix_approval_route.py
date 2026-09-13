"""Assess approval intent is durable and distinct from the selected criterion scope."""
from fastapi.testclient import TestClient


def prepare(monkeypatch, isolated_store):
    import core, handlers, scanner
    from app import app
    monkeypatch.setattr(core, 'store', isolated_store)
    monkeypatch.setenv('ACP_DEFER_ANALYSIS_TO_ASSESS', '1')
    monkeypatch.setattr(scanner, '_list', lambda *a, **k: [{'name': 'a.docx', 'id': 'a', 'mime': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}])
    handlers._scan_discover({'scan_id': 'approval-scan', 'source': 'local', 'user': 'demo'}, {'scan_id': 'approval-scan'})
    return TestClient(app)


def test_assessment_saves_approval_without_replacing_discovery_scope(monkeypatch, isolated_store):
    client = prepare(monkeypatch, isolated_store)
    before = isolated_store.get_scan('approval-scan')['run']['scope']
    choice = {'mode': 'custom', 'review_scs': ['1.1.1']}
    response = client.post('/scans/approval-scan/assess', json={'fix_approval_policy': choice})
    assert response.status_code == 200, response.text
    after = isolated_store.get_scan('approval-scan')['run']['scope']
    assert after['fix_approval_policy'] == choice
    assert {k: v for k, v in after.items() if k != 'fix_approval_policy'} == before
    repeat = client.post('/scans/approval-scan/assess', json={'fix_approval_policy': choice})
    assert repeat.status_code == 200 and repeat.json()['reused'] is True


def test_invalid_policy_cannot_start_assessment(monkeypatch, isolated_store):
    client = prepare(monkeypatch, isolated_store)
    response = client.post('/scans/approval-scan/assess', json={'fix_approval_policy': {'mode': 'force'}})
    assert response.status_code == 422
    assert not isolated_store.get_scan('approval-scan')['run'].get('assessed_at')


def test_completed_assessment_cannot_silently_change_policy(monkeypatch, isolated_store):
    client = prepare(monkeypatch, isolated_store)
    isolated_store.merge_scan_scope('approval-scan', {'fix_approval_policy': {'mode': 'automatic', 'review_scs': []}})
    isolated_store.mark_assessed('approval-scan', '2026-09-13T23:00:00Z')
    response = client.post('/scans/approval-scan/assess', json={'fix_approval_policy': {'mode': 'review', 'review_scs': []}})
    assert response.status_code == 409
    assert isolated_store.get_scan('approval-scan')['run']['scope']['fix_approval_policy']['mode'] == 'automatic'


def test_legacy_retry_fingerprint_is_unchanged_without_approval_intent():
    import json
    from assess_approval_intent import request_fingerprint
    assert request_fingerprint('AA', False) == json.dumps({'level': 'AA', 'include_lifecycle_flagged': False}, sort_keys=True)


def test_started_approval_intent_cannot_change_during_active_assessment(monkeypatch, isolated_store):
    client = prepare(monkeypatch, isolated_store)
    initial={'mode':'custom','review_scs':['1.1.1']}
    assert client.post('/scans/approval-scan/assess', json={'fix_approval_policy':initial}).status_code == 200
    response=client.post('/scans/approval-scan/assess', json={'fix_approval_policy':{'mode':'automatic','review_scs':[]}})
    assert response.status_code == 409
    assert isolated_store.get_scan('approval-scan')['run']['scope']['fix_approval_policy'] == initial
