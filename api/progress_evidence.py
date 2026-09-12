"""Read admission baselines and actual file attempts; never capture browser-time baselines."""
import json
import logging


def capture_documents(store, scan, selected, *, owner, snapshot_id, request_fingerprint):
    """Capture only a fully evidenced partition, before admission exposes queued work.

    Exact replay keeps its original capture, including an unavailable old capture.
    Verified-versus-ready requires freshness evidence not retained by this seam, so
    ambiguous previously corrected files deliberately keep Before unavailable.
    """
    if not hasattr(store, '_db'):
        return None
    scan_id = (scan.get('run') or {}).get('id')
    if not scan_id:
        return None
    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT execution_id FROM stage_executions WHERE scan_id=%s "
            "AND owner_email=%s AND stage='remediate' AND input_snapshot_id=%s "
            "AND request_fingerprint=%s ORDER BY created_at LIMIT 1",
            (scan_id, owner, snapshot_id, request_fingerprint))
        existing = store._db.fetchone(cur)
        if existing:
            store._db.execute(cur, 'SELECT payload FROM jobs WHERE batch_id=%s ORDER BY created_at,id LIMIT 1',
                (existing['execution_id'],))
            job = store._db.fetchone(cur)
            payload = json.loads(job['payload']) if job and isinstance(job['payload'], str) else (job or {}).get('payload', {})
            return (payload or {}).get('document_progress_baseline')
        store._db.execute(cur, "SELECT w.input_id FROM stage_work_items w JOIN stage_executions e "
            "ON e.execution_id=w.execution_id WHERE e.scan_id=%s AND e.owner_email=%s "
            "AND e.stage='remediate' AND w.state IN ('queued','processing')", (scan_id, owner))
        active = {row['input_id'] for row in store._db.fetchall(cur)}
    rows = {row['file']: row for row in scan.get('files', [])}
    review = store.list_hitl_queue(scan_id=scan_id, owner=owner)
    release = store.release_for_scan(scan_id, owner) or {}
    receipts = {row['file']: row for row in release.get('documents', [])}
    counts = dict(processing=0, verified=0, attention=0, ready=0, published=0)
    for name in selected:
        row = rows.get(name)
        if not row or not isinstance(row.get('issues'), list):
            return None
        receipt = receipts.get(name) or {}
        digest = row.get('corrected_sha256')
        if name in active:
            state = 'processing'
        elif row.get('remediated_at') and digest and receipt.get('status') == 'published' and receipt.get('artifact_digest') == f'sha256:{digest}':
            state = 'published'
        elif receipt.get('status') in {'queued', 'running'}:
            state = 'processing'
        elif any(item.get('file') == name and item.get('status') == 'approved'
                 and not item.get('applied') and not item.get('apply_outcome') for item in review):
            state = 'processing'
        elif row.get('remediated_at') and row.get('compliant'):
            return None
        else:
            state = 'attention'
        counts[state] += 1
    return {'scope_files': sorted(selected), 'counts': counts}


def read(store, execution_id, *, owner=None):
    try:
        return _read(store, execution_id, owner=owner)
    except Exception:
        # Optional presentation evidence must not take down the authoritative snapshot
        # during rolling schema upgrades or when old retained JSON is incomplete.
        logging.getLogger(__name__).warning('Progress baseline evidence unavailable', exc_info=True)
        return {'progress_baseline': {'available': False},
                'file_processing': {'available': False}}


def _read(store, execution_id, *, owner=None):
    unavailable = {'progress_baseline': {'available': False},
                   'file_processing': {'available': False}}
    if not execution_id or not hasattr(store, '_db'):
        return unavailable
    execution = store.get_stage_execution(execution_id, owner=owner)
    if not execution or execution.get('provenance') == 'inferred':
        return unavailable
    owner = execution.get('owner_email')
    if not owner:
        return unavailable
    baseline = {'available': False, 'run_id': execution_id}
    if execution['stage'] == 'release':
        total = execution.get('expected_items')
        if type(total) is int and total >= 0:
            baseline = {'available': True, 'run_id': execution_id,
                        'snapshot_id': execution['input_snapshot_id'],
                        'started_at': execution['created_at'],
                        'publication': {'queued': total, 'processing': 0,
                                        'published': 0, 'attention': 0, 'skipped': 0}}
        return {**unavailable, 'progress_baseline': baseline}
    if execution['stage'] != 'remediate':
        return unavailable
    with store._db.cursor() as cur:
        store._db.execute(cur, 'SELECT * FROM remediation_contribution_runs '
            'WHERE owner_id=%s AND scan_id=%s AND run_id=%s',
            (owner, execution['scan_id'], execution_id))
        frozen = store._db.fetchone(cur)
        if not frozen or frozen['snapshot_id'] != execution['input_snapshot_id']:
            return unavailable
        findings = json.loads(frozen['baseline_json'])
        files = json.loads(frozen['files_json'])
        affected = {row['file'] for row in findings}
        store._db.execute(cur, 'SELECT w.input_id,w.state,w.attempt, '
            '(SELECT COUNT(*) FROM stage_attempts a WHERE a.work_item_id=w.work_item_id) AS claims '
            'FROM stage_work_items w WHERE w.execution_id=%s ORDER BY w.input_id', (execution_id,))
        items = store._db.fetchall(cur)
        store._db.execute(cur, 'SELECT payload FROM jobs WHERE batch_id=%s ORDER BY created_at,id LIMIT 1', (execution_id,))
        job = store._db.fetchone(cur)
        payload = json.loads(job['payload']) if job and isinstance(job['payload'], str) else (job or {}).get('payload', {})
        document_baseline = (payload or {}).get('document_progress_baseline')
    attempts = [{'file': row['input_id'], 'state': row['state'],
                 'attempted': int(row.get('attempt') or 0) > 0 or int(row['claims']) > 0,
                 'retryScheduled': row['state'] == 'queued' and
                    (int(row.get('attempt') or 0) > 0 or int(row['claims']) > 0)}
                for row in items]
    terminal = {'completed', 'failed', 'cancelled', 'skipped'}
    processed = {row['file'] for row in attempts
                 if row['file'] in affected and row['attempted'] and row['state'] in terminal}
    coverage_before = {'withFindings': len(affected), 'processed': 0, 'remaining': len(affected)}
    baseline = {'available': True, 'run_id': execution_id, 'snapshot_id': frozen['snapshot_id'],
                'started_at': frozen['created_at'],
                'documents': document_baseline.get('counts') if isinstance(document_baseline, dict)
                    and document_baseline.get('scope_files') == sorted(files) else None,
                'findings': {'queued': len(findings), 'processing': 0, 'attention': 0,
                             'verified': 0, 'excluded': 0}, 'file_coverage': coverage_before}
    return {'progress_baseline': baseline, 'file_processing': {
        'available': True, 'run_id': execution_id,
        'files': [{'file': name, 'hasFindings': name in affected} for name in files],
        'attempts': attempts, 'baseline': coverage_before,
        'counts': {'withFindings': len(affected), 'processed': len(processed),
                   'remaining': len(affected) - len(processed)}}}
