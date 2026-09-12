"""Explicit assessment failures block remediation; missing finding telemetry does not."""
import json


def classify(status, messages=()):
    if str(status).lower() not in {'error', 'unanalysable', 'uncertain'}:
        return None
    text = ' '.join(str(message.get('message', '')) if isinstance(message, dict) else str(message)
                    for message in messages).lower()
    unreadable = any(token in text for token in ('badzipfile', 'not a zip file', 'pdfreaderror',
        'invalid pdf', 'eof marker not found', 'word/document.xml', 'password-protected', 'file is corrupt'))
    if unreadable:
        return {'category': 'unreadable', 'reason': 'The document could not be read. It may be corrupt, incomplete, or password-protected. Replace it with a readable copy and assess again.'}
    if str(status).lower() == 'uncertain':
        return None
    if any(token in text for token in ('timeout', 'timed out', 'per-file limit', 'exceeded')):
        return {'category': 'assessment_timeout', 'reason': 'Assessment timed out for this file. Retry assessment before remediation; a timeout does not mean the file is corrupt.'}
    if any(token in text for token in ('authorization', 'credential', '401', '403', 'permission', 'access denied')):
        return {'category': 'source_access', 'reason': 'Assessment could not access this file. Restore source access and assess again before remediation.'}
    return {'category': 'assessment_failed', 'reason': 'Assessment could not complete for this file. Retry assessment before remediation; its findings are not yet fully known.'}


def record(store, scan_id, result, *, job=None):
    state = classify(result.get('status'), result.get('errors') or [])
    evidence = {**(state or {}), 'source_checksum': result.get('checksum'),
                'written_job': (job or {}).get('id'), 'written_attempt': (job or {}).get('attempts')}
    store.log_decision('system', 'scan.assessment_blocked' if state else 'scan.assessment_readable',
        scan_id=scan_id, file=result['file'], detail=json.dumps(evidence))


def read(store, scan_id, *, owner=None, scan=None):
    if scan is None and not callable(getattr(store, 'get_scan', None)):
        return []
    scan = scan if scan is not None else store.get_scan(scan_id, owner=owner)
    if not scan:
        return []
    diagnostics = {}
    identities = {}
    if hasattr(store, '_db'):
        with store._db.cursor() as cur:
            store._db.execute(cur, 'SELECT file,checksum,written_job,written_attempt FROM file_records WHERE scan_id=%s', (scan_id,))
            identities = {row['file']: row for row in store._db.fetchall(cur)}
            store._db.execute(cur, "SELECT file,action,detail FROM decision_log WHERE scan_id=%s "
                "AND action IN ('scan.assessment_blocked','scan.assessment_readable','scan.file_error','scan.file_timeout') "
                "ORDER BY ts DESC,id DESC", (scan_id,))
            for row in store._db.fetchall(cur):
                diagnostics.setdefault(row['file'], row)
    blocked = []
    for file in scan.get('files', []):
        diagnostic = diagnostics.get(file['file']) or {}
        state = None
        if diagnostic.get('action') == 'scan.assessment_blocked' and file.get('status') in {'error', 'unanalysable', 'uncertain'}:
            try:
                evidence = json.loads(diagnostic['detail'])
                identity = identities.get(file['file']) or {}
                if any(evidence.get(key) is not None and evidence[key] != identity.get(column)
                       for key, column in [('source_checksum', 'checksum'), ('written_job', 'written_job'), ('written_attempt', 'written_attempt')]):
                    diagnostic = {}
                elif isinstance(evidence.get('reason'), str) and isinstance(evidence.get('category'), str):
                    state = {key: evidence[key] for key in ('reason', 'category')}
            except (TypeError, ValueError):
                pass
        if state is None:
            messages = [diagnostic.get('detail') or ''] if diagnostic.get('action') != 'scan.assessment_readable' else []
            state = classify(file.get('status'), messages)
        if state:
            blocked.append({'file': file['file'], **state})
    return blocked


def annotate(scan, blocked):
    by_file = {row['file']: row for row in blocked}
    for file in scan.get('files', []):
        state = by_file.get(file['file'])
        if state:
            file.update(assessment_blocked=True, assessment_blocked_reason=state['reason'],
                        assessment_blocked_category=state['category'])
    return scan
