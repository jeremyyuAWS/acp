"""Bounded, execution-scoped document AI history; never a finding total."""
import json


def read_document_wide(store, owner, scan_id, run_id, *, enabled=False):
    if not enabled:
        return None
    with store._db.cursor() as cur:
        store._db.execute(cur, '''SELECT id,ts,file,action,detail FROM decision_log
            WHERE scan_id=%s AND action IN ('document_wide.generated','document_wide.deferred')
            ORDER BY ts DESC,id DESC LIMIT 1001''', (scan_id,))
        events = store._db.fetchall(cur)
    files = {}
    for event in events[:1000]:
        try:
            detail = json.loads(event['detail'])
        except (TypeError, ValueError):
            continue
        if not isinstance(detail, dict) or detail.get('owner_id') != owner or detail.get('run_id') != run_id:
            continue
        file = event.get('file')
        if not file:
            continue
        prior = files.get(file)
        if prior and prior.get('request_id') != detail.get('request_id'):
            continue
        proposals = detail.get('proposals', {})
        proposals = proposals if isinstance(proposals, dict) else {}
        suggestions = sum(len(values) for values in proposals.values() if isinstance(values, list))
        reasons = list(prior['reasons']) if prior else []
        def add(reason):
            if isinstance(reason, str) and reason and reason not in reasons:
                reasons.append(reason[:300])
        add(detail.get('reason'))
        for key in ('unresolved', 'rejected', 'extraction_issues'):
            values = detail.get(key, [])
            for value in values if isinstance(values, list) else []:
                if isinstance(value, dict):
                    add(value.get('reason') or value.get('kind'))
        if detail.get('omitted_finding_ids'):
            add('findings_omitted')
        files[file] = {'file': file, 'request_id': detail.get('request_id'),
                       'suggestions': max(suggestions, prior['suggestions'] if prior else 0),
                       'status': 'generated' if event['action'] == 'document_wide.generated' or (prior and prior['status'] == 'generated') else 'deferred',
                       'reasons': reasons, 'recorded_at': prior['recorded_at'] if prior else event['ts']}
    return {'enabled': True, 'files': sorted(files.values(), key=lambda row: row['file']),
            'complete': len(events) <= 1000, 'unit': 'suggestions',
            'note': 'Saved document-wide suggestions, not applied or verified fixes. Other remediation steps may address these findings.'}
