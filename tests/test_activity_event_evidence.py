import hashlib
import json

import pytest
from activity_event_evidence import record, read, exact_copy
from test_scan_history_route import client, _seed

OWNER = 'demo'
DATA = b'exact saved bytes'


def _record_event(store, *, sid='evidence', verified=True):
    _seed(store, sid)
    with store._db.cursor() as cur:
        store._db.execute(cur, 'INSERT INTO file_records(scan_id,file,status,corrected_sha256) VALUES(%s,%s,%s,%s)',
                          (sid, 'document.docx', 'done', hashlib.sha256(DATA).hexdigest()))
    detail = record(store, sid, 'document.docx', {'id': 'writer', 'payload': {'owner': OWNER}}, DATA,
                    [{'rule_id': '1.3.1', 'location': 'Paragraph 4', 'before': 'Body', 'after': 'Heading 1'}],
                    verified=verified, verification_ok=True)
    seq = store.append_scan_event(sid, 'remediate.verified' if verified else 'remediate.verification_failed',
                                  job_id='writer', document='document.docx', detail=detail)
    return seq, detail


def test_snapshot_is_content_free_in_narration_and_exactly_bound(isolated_store):
    seq, detail = _record_event(isolated_store)
    assert 'before' not in json.dumps(detail)
    body = read(isolated_store, 'evidence', seq, OWNER)
    assert body['changes'][0] == {'criterion': '1.3.1', 'location': 'Paragraph 4', 'before': 'Body', 'after': 'Heading 1',
                                  'text_truncated': False, 'verification': 'verified'}
    assert body['saved_copy']['matches_event'] is True
    assert body['verification']['artifact_sha256'] == hashlib.sha256(DATA).hexdigest()
    assert exact_copy(isolated_store, 'evidence', seq, OWNER, lambda *_: DATA) == DATA


def test_newer_saved_copy_never_substitutes_for_event_version(isolated_store):
    seq, _ = _record_event(isolated_store)
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur, 'UPDATE file_records SET corrected_sha256=%s WHERE scan_id=%s', ('f' * 64, 'evidence'))
    body = read(isolated_store, 'evidence', seq, OWNER)
    assert body['available'] is True
    assert body['saved_copy']['download_url'] is None
    assert body['changes'][0]['after'] == 'Heading 1'
    with pytest.raises(ValueError):
        exact_copy(isolated_store, 'evidence', seq, OWNER, lambda *_: b'new bytes')


def test_owner_and_suppression_gate_all_rich_content(isolated_store):
    seq, _ = _record_event(isolated_store)
    with pytest.raises(LookupError):
        read(isolated_store, 'evidence', seq, 'someone@example.com')
    isolated_store.set_setting('remediation_filename_privacy', 'suppressed')
    assert read(isolated_store, 'evidence', seq, OWNER) == {'available': False, 'reason': 'content_suppressed'}
    with pytest.raises(LookupError):
        exact_copy(isolated_store, 'evidence', seq, OWNER, lambda *_: DATA)


def test_legacy_event_does_not_borrow_current_ledger(isolated_store):
    seq, _ = _record_event(isolated_store)
    old = isolated_store.append_scan_event('evidence', 'remediate.verified', document='document.docx', detail={'fixes': 1})
    assert read(isolated_store, 'evidence', old, OWNER) == {'available': False, 'reason': 'historical_version_not_recorded'}


def test_wrong_event_job_cannot_reuse_another_evidence_record(isolated_store):
    _, detail = _record_event(isolated_store)
    seq = isolated_store.append_scan_event('evidence', 'remediate.verified', document='document.docx', job_id='other-writer', detail=detail)
    assert read(isolated_store, 'evidence', seq, OWNER)['reason'] == 'evidence_binding_changed'


def test_missing_location_and_failed_verification_remain_explicit(isolated_store):
    seq, _ = _record_event(isolated_store, verified=False)
    body = read(isolated_store, 'evidence', seq, OWNER)
    assert body['verification']['status'] == 'failed'
    assert body['changes'][0]['verification'] == 'not_verified'


def test_snapshot_previews_are_bounded_with_coverage_explicit(isolated_store):
    _seed(isolated_store, 'bounded')
    detail = record(isolated_store, 'bounded', 'document.docx', {'id': 'writer', 'payload': {'owner': OWNER}}, DATA,
                    [{'rule_id': '1.1.1', 'before': 'x' * 2500, 'after': 'y'}] * 25,
                    verified=False, verification_ok=False)
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur, 'SELECT detail FROM decision_log WHERE id=%s', (detail['evidence_id'],))
        body = json.loads(isolated_store._db.fetchone(cur)['detail'])
    assert len(body['changes']) == 20
    assert body['change_count'] == 25 and body['changes_truncated'] is True
    assert len(body['changes'][0]['before']) == 2000 and body['changes'][0]['text_truncated'] is True
    assert body['changes'][0]['location'] is None


def test_protected_routes_return_exact_bytes_or_conflict(client, isolated_store, monkeypatch):
    import blob
    seq, _ = _record_event(isolated_store)
    monkeypatch.setattr(blob, 'download_remediated', lambda *_: DATA)
    path = f'/scans/evidence/remediation/activity/{seq}'
    assert client.get(path + '/evidence').json()['available'] is True
    assert client.get(path + '/copy').content == DATA
    monkeypatch.setattr(blob, 'download_remediated', lambda *_: b'newer')
    assert client.get(path + '/copy').status_code == 409
