"""Cumulative authorized delivery presentation, separate from an incremental job ledger."""
import json


def read(store, execution):
    try:
        return _read(store, execution)
    except Exception:
        # Optional presentation must never weaken or replace canonical accounting.
        return {'available': False}


def _read(store, execution):
    from automatic_release_store import get
    owner, scan = execution['owner_email'], execution['scan_id']
    with store._db.cursor() as cur:
        store._db.execute(cur, 'SELECT COALESCE(j.payload,o.payload) AS payload '
            'FROM stage_work_items w LEFT JOIN jobs j ON j.id=w.job_id '
            'LEFT JOIN stage_outbox o ON o.work_item_id=w.work_item_id '
            'WHERE w.execution_id=%s', (execution['execution_id'],))
        jobs = store._db.fetchall(cur)
    identities = set()
    for job in jobs:
        payload = json.loads(job['payload']) if isinstance(job['payload'], str) else job['payload']
        identity = payload.get('automatic_release_id')
        if not identity or payload.get('owner') != owner or payload.get('scan_id') != scan:
            return {'available': False}
        identities.add(identity)
    if len(identities) != 1:
        return {'available': False}
    row = get(store, next(iter(identities)), owner)
    if not row or row['scan_id'] != scan:
        return {'available': False}
    parent = store.get_stage_execution(row['run_id'], owner=owner)
    if (not parent or parent.get('stage') != 'remediate' or parent.get('scan_id') != scan
            or not parent.get('is_current')
            or parent.get('workflow_id') != execution.get('workflow_id')
            or parent.get('workflow_revision') != execution.get('workflow_revision')):
        return {'available': False}
    files = row['intent'].get('files')
    if not isinstance(files, list) or not files or any(not isinstance(f, str) or not f for f in files):
        return {'available': False}
    if len(set(files)) != len(files):
        return {'available': False}
    release = store.release_for_scan(scan, owner) or {}
    destination_matches = (release.get('parent_folder_id') == row['intent'].get('release_parent_id')
                           and release.get('folder_name') == row['intent'].get('release_folder_name'))
    receipts = {r['file']: r for r in release.get('documents', [])} if destination_matches else {}
    entries = row['progress'].get('files', {})
    delivered = 0
    for file in files:
        digest = entries.get(file, {}).get('artifact_digest')
        receipt = receipts.get(file, {})
        if (isinstance(digest, str) and digest.startswith('sha256:') and len(digest) == 71
                and all(c in '0123456789abcdef' for c in digest[7:])
                and receipt.get('status') == 'published' and receipt.get('artifact_digest') == digest):
            delivered += 1
    return {'available': True, 'authorization_id': row['id'], 'run_id': row['run_id'],
            'total': len(files), 'delivered': delivered, 'remaining': len(files) - delivered,
            'status': row['status'], 'revision': row['revision']}
