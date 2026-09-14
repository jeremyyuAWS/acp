"""Immutable, owner-scoped evidence for one narrated saved-copy assessment."""
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

MAX_CHANGES = 20
MAX_TEXT = 2000
ACTION = 'remediate.activity_evidence'


def record(store, sid, filename, job, data, diffs, *, verified, verification_ok):
    """Append content to the audit ledger, never to the broadly replayed event log."""
    try:
        # Durable job payload is the authenticated writer identity; don't invent one.
        payload = (job or {}).get('payload') or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        owner = payload.get('owner')
        if not owner or not store.get_scan_head(sid, owner=owner) or not data:
            return {}
        rows = []
        criteria = sorted({str(d.get('rule_id')) for d in diffs
                           if re.fullmatch(r'\d+\.\d+\.\d+', str(d.get('rule_id', '')))})
        for d in diffs[:MAX_CHANGES]:
            criterion = str(d.get('rule_id', ''))
            if criterion not in criteria:
                continue
            loc = d.get('location') or d.get('locator')
            before, after = d.get('before'), d.get('after')
            rows.append({'criterion': criterion,
                         'location': loc[:1000] if isinstance(loc, str) and loc else None,
                         'before': before[:MAX_TEXT] if isinstance(before, str) else None,
                         'after': after[:MAX_TEXT] if isinstance(after, str) else None,
                         'text_truncated': any(isinstance(v, str) and len(v) > MAX_TEXT for v in (before, after)),
                         'verification': 'verified' if verified else 'not_verified'})
        evidence_id = uuid.uuid4().hex[:12]
        digest = hashlib.sha256(data).hexdigest()
        body = {'artifact_sha256': digest, 'job_id': (job or {}).get('id'),
                'criteria': criteria, 'changes': rows, 'change_count': len(diffs),
                'changes_truncated': len(diffs) > MAX_CHANGES,
                'verification': {'status': 'verified' if verified else 'failed' if verification_ok else 'unavailable',
                                 'artifact_sha256': digest}}
        with store._db.cursor() as cur:
            store._db.execute(cur, 'INSERT INTO decision_log(id,ts,actor,action,scan_id,file,rule_id,detail) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
                              (evidence_id, datetime.now(timezone.utc).isoformat(), owner, ACTION, sid, filename, None,
                               json.dumps(body, sort_keys=True)))
        return {'evidence_id': evidence_id, 'artifact_sha256': digest, 'criteria': criteria}
    except Exception:
        # Supplementary evidence must not fail a completed document operation.
        from swallowed import swallowed
        swallowed('activity evidence: immutable snapshot could not be recorded', sid)
        return {}


def _bound_record(store, sid, seq, owner):
    if not store.get_scan_head(sid, owner=owner):
        raise LookupError('scan not found')
    if store.remediation_filename_privacy(sid) == 'suppressed':
        return None, 'content_suppressed'
    with store._db.cursor() as cur:
        store._db.execute(cur, 'SELECT job_id,document,detail FROM scan_events WHERE scan_id=%s AND seq=%s', (sid, seq))
        event = store._db.fetchone(cur)
        if not event:
            raise LookupError('activity not found')
        detail = json.loads(event['detail']) if isinstance(event.get('detail'), str) else event.get('detail') or {}
        evidence_id = detail.get('evidence_id')
        digest = detail.get('artifact_sha256')
        if not evidence_id or not re.fullmatch(r'[0-9a-f]{64}', str(digest or '')):
            return None, 'historical_version_not_recorded'
        store._db.execute(cur, 'SELECT file,detail FROM decision_log WHERE id=%s AND actor=%s AND action=%s AND scan_id=%s AND file=%s',
                          (evidence_id, owner, ACTION, sid, event.get('document')))
        ledger = store._db.fetchone(cur)
    if not ledger:
        return None, 'evidence_not_available'
    body = json.loads(ledger['detail'])
    if body.get('artifact_sha256') != digest or body.get('job_id') != event.get('job_id'):
        return None, 'evidence_binding_changed'
    return {'file': ledger['file'], **body}, None


def read(store, sid, seq, owner):
    body, reason = _bound_record(store, sid, seq, owner)
    if body is None:
        return {'available': False, 'reason': reason}
    current = store.get_file_record(sid, body['file']) or {}
    matches = current.get('corrected_sha256') == body['artifact_sha256']
    return {'available': True, 'artifact_sha256': body['artifact_sha256'],
            'criteria': body['criteria'], 'changes': body['changes'],
            'change_count': body['change_count'], 'changes_truncated': body['changes_truncated'],
            'verification': body['verification'],
            'saved_copy': {'matches_event': matches,
                           'download_url': f'/scans/{sid}/remediation/activity/{seq}/copy' if matches else None,
                           'reason': None if matches else 'saved_version_changed'}}


def exact_copy(store, sid, seq, owner, download):
    body, reason = _bound_record(store, sid, seq, owner)
    if body is None:
        raise LookupError(reason)
    data = download(owner, sid, body['file'])
    if not data or hashlib.sha256(data).hexdigest() != body['artifact_sha256']:
        raise ValueError('The recorded saved version is no longer available')
    return data
