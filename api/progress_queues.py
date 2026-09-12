"""Read-only queue membership behind one immutable workflow execution."""
import json
from collections import Counter

FINDING_GROUPS = {
    None: 'queued',
    'resolved_verified': 'verified',
    'approved_pending_verification': 'processing',
    'approved_awaiting_verification': 'processing',
    'excluded_by_policy': 'excluded', 'superseded_by_reassessment': 'excluded',
    'excluded': 'excluded', 'superseded': 'excluded',
    'awaiting_recorded_outcome': 'queued', 'not_in_remediation_breakdown': 'queued',
    'awaiting_review': 'attention', 'unchanged_no_fix': 'attention',
    'remediation_failed': 'attention', 'failed': 'attention',
}
RELEASE_GROUPS = {'queued': 'queued', 'waiting': 'queued', 'processing': 'processing',
                  'completed': 'published', 'failed': 'attention',
                  'cancelled': 'attention', 'skipped': 'skipped'}
LABELS = {'queued': 'Queued', 'processing': 'Applying & checking',
          'verified': 'Verified fixes', 'attention': 'Needs attention',
          'excluded': 'Excluded', 'published': 'Published', 'skipped': 'Skipped'}


def read(store, execution_id, owner, bucket):
    execution = store.get_stage_execution(execution_id, owner=owner)
    if not execution or execution.get('stage') not in {'remediate', 'release'}:
        raise PermissionError('Queue not found')
    stage = execution['stage']
    allowed = {'queued', 'processing', 'attention', 'verified', 'excluded'} if stage == 'remediate' else set(RELEASE_GROUPS.values())
    if bucket not in allowed:
        raise ValueError('Unknown queue')
    snapshot = store.stage_execution_snapshot(execution_id, owner=owner) or {}
    domain = snapshot.get('domain_reconciliation') or {}
    total = domain.get('total')
    result = {'execution_id': execution_id, 'scan_id': execution['scan_id'],
              'stage': stage, 'bucket': bucket, 'revision': snapshot.get('revision'),
              'unit': 'findings' if stage == 'remediate' else 'files', 'files': [],
              'available': False, 'count': None}
    def unavailable():
        return {**result, 'reason': 'Exact queue membership is unavailable for this execution. Counts are being reconciled.'}
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        return unavailable()
    if stage == 'remediate':
        rows = store.finding_disposition_drilldown(execution['scan_id'], execution_id)
        with store._db.cursor() as cur:
            store._db.execute(cur, 'SELECT baseline_json FROM remediation_contribution_runs WHERE owner_id=%s AND scan_id=%s AND run_id=%s', (owner, execution['scan_id'], execution_id))
            admission = store._db.fetchone(cur)
            store._db.execute(cur, 'SELECT input_id FROM stage_work_items WHERE execution_id=%s', (execution_id,))
            admitted_files = {row['input_id'] for row in store._db.fetchall(cur)}
        by_id = {row['finding_id']: dict(row) for row in rows}
        if len(by_id) != len(rows):
            return unavailable()
        if admission or len(rows) < total:
            try:
                baseline = json.loads((admission or {})['baseline_json'])
                if len(baseline) != total or len({row['finding_id'] for row in baseline}) != total:
                    return unavailable()
                if not set(by_id).issubset({row['finding_id'] for row in baseline}):
                    return unavailable()
                for row in baseline:
                    by_id.setdefault(row['finding_id'], {**row, 'disposition': 'awaiting_recorded_outcome'})
            except (KeyError, TypeError, ValueError):
                return unavailable()
        rows = list(by_id.values())
        if len(rows) != total or any(not row.get('file') or row['file'] not in admitted_files or row.get('disposition') not in FINDING_GROUPS for row in rows):
            return unavailable()
        selected = [row for row in rows if FINDING_GROUPS.get(row.get('disposition'), 'attention') == bucket]
        counts = Counter(row['file'] for row in selected)
        files = [{'file': file, 'status': bucket, 'label': LABELS[bucket],
                  'findingCount': count} for file, count in sorted(counts.items())]
    else:
        with store._db.cursor() as cur:
            store._db.execute(cur, 'SELECT work_item_id,input_id,state,terminal_reason FROM stage_work_items WHERE execution_id=%s ORDER BY input_id', (execution_id,))
            rows = store._db.fetchall(cur)
            store._db.execute(cur, "SELECT work_item_id,receipt FROM side_effect_receipts WHERE execution_id=%s AND status='completed'", (execution_id,))
            receipt_rows = store._db.fetchall(cur)
        verified = set()
        for receipt in receipt_rows:
            data = receipt['receipt']
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except (TypeError, ValueError):
                    data = None
            if isinstance(data, dict) and data.get('verified') is True:
                verified.add(receipt['work_item_id'])
        if len(rows) != total or len({row['input_id'] for row in rows}) != total or any(row['state'] not in RELEASE_GROUPS for row in rows):
            return unavailable()
        selected = [row for row in rows if RELEASE_GROUPS[row['state']] == bucket]
        files = [{'file': row['input_id'], 'status': bucket,
                  'label': ('Published · delivery verified' if row['work_item_id'] in verified else 'Completed · delivery check pending') if row['state'] == 'completed' else 'Publishing' if row['state'] == 'processing' else LABELS[bucket],
                  **({'deliveryVerified': row['work_item_id'] in verified} if row['state'] == 'completed' else {}),
                  'reason': row.get('terminal_reason') or ''} for row in selected]
    return {**result, 'available': True, 'count': len(selected), 'files': files}
