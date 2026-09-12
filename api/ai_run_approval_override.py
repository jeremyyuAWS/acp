"""A revisioned approval-only override; immutable run models and budgets never change."""
import hashlib
import json
from types import SimpleNamespace


def _key(owner, sid, run_id):
    digest = hashlib.sha256(json.dumps([owner, sid, run_id]).encode()).hexdigest()
    return f'ai-run-approval:{digest}'


def run(store, owner, sid, run_id, *, require_ai=True):
    from ai_standing_approval import require_access
    require_access(store, owner)
    # Serialize an override with every exact decision authorization, including
    # the first override when no settings row exists yet.
    lock = ' FOR UPDATE OF e' if getattr(store._db, 'supports_for_update', False) else ''
    with store._db.cursor() as cur:
        store._db.execute(cur, '''SELECT p.policy_json,e.input_snapshot_id,e.is_current,e.cancel_requested_at
          FROM ai_spending_run_policies p JOIN stage_executions e
          ON e.execution_id=p.run_id AND e.scan_id=p.scan_id AND e.owner_email=p.owner_id
          JOIN scan_runs s ON s.id=p.scan_id AND s.owner_email=p.owner_id
          WHERE p.owner_id=%s AND p.scan_id=%s AND p.run_id=%s AND e.stage='remediate' ''' + lock, (owner, sid, run_id))
        row = store._db.fetchone(cur)
    if not row or not row['is_current'] or row['cancel_requested_at']:
        raise ValueError('No current uncancelled remediation run')
    policy = json.loads(row['policy_json'])
    if require_ai and policy.get('ai') != 1:
        raise ValueError('This run did not authorize AI suggestions')
    if row['input_snapshot_id'] != store.remediation_source_revision(sid):
        raise ValueError('Remediation source revision changed')
    return policy, row['input_snapshot_id']


def read(store, owner, sid, run_id):
    policy, source = run(store, owner, sid, run_id, require_ai=False)
    saved = json.loads(store.get_setting(_key(owner, sid, run_id)) or '{}')
    if saved and saved.get('source_revision') != source:
        raise ValueError('Automatic approval override source revision changed')
    supported = policy.get('ai') == 1
    return {'supported': supported, 'reason': None if supported else 'This run did not authorize AI suggestions. Enable AI in a new remediation plan.', 'run_id': run_id, 'source_revision': source, 'revision': saved.get('revision', 0),
            'enabled': supported and saved.get('enabled', policy.get('auto_approve_ai') is True),
            'granted_ever': policy.get('auto_approve_ai') is True or saved.get('granted_ever') is True}


def save(store, owner, sid, run_id, enabled, expected_revision, expected_source_revision):
    if type(enabled) is not bool or type(expected_revision) is not int or expected_revision < 0:
        raise ValueError('Explicit approval setting and revision are required')
    with store.transaction():
        current = read(store, owner, sid, run_id)
        if not current['supported']:
            raise ValueError(current['reason'])
        if current['source_revision'] != expected_source_revision:
            raise ValueError('Remediation source revision changed')
        if current['revision'] != expected_revision:
            raise ValueError('Automatic approval setting changed; refresh and try again')
        updated = {**current, 'enabled': enabled, 'revision': current['revision'] + 1,
                   'granted_ever': current['granted_ever'] or enabled}
        # Compare-and-set the JSON instead of relying on a process-local mutex.
        key = _key(owner, sid, run_id)
        previous = store.get_setting(key)
        value = json.dumps(updated, sort_keys=True)
        with store._db.cursor() as cur:
            if previous is None:
                store._db.execute(cur, 'INSERT INTO app_settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO NOTHING', (key, value))
            else:
                store._db.execute(cur, 'UPDATE app_settings SET value=%s WHERE key=%s AND value=%s', (value, key, previous))
            if cur.rowcount != 1:
                raise ValueError('Automatic approval setting changed; refresh and try again')
        store.log_decision(owner, 'ai.run_approval_override', scan_id=sid,
                           detail=json.dumps(updated, sort_keys=True))
        if enabled:
            store.enqueue_job('apply_approved_values', {'phase': 'approve_current_run_ai', 'scan_id': sid, 'owner': owner, 'run_id': run_id,
                                                'source_revision': current['source_revision']}, scan_id=sid)
    return updated


def process_pending(store, payload):
    owner, sid, run_id = payload['owner'], payload['scan_id'], payload['run_id']
    current = read(store, owner, sid, run_id)
    if not current['enabled']:
        return
    if payload['source_revision'] != current['source_revision']:
        raise ValueError('Automatic approval source changed')
    policy, _ = run(store, owner, sid, run_id)
    with store._db.cursor() as cur:
        store._db.execute(cur, '''SELECT DISTINCT p.file FROM ai_proposal_snapshots p JOIN hitl_queue q
          ON q.id=p.item_id AND q.scan_id=p.scan_id AND q.file=p.file
          WHERE p.owner_id=%s AND p.scan_id=%s AND p.run_id=%s AND q.status='pending' ''', (owner, sid, run_id))
        files = [row['file'] for row in store._db.fetchall(cur)]
    from ai_standing_approval import approve_file
    for file in files:
        if not read(store, owner, sid, run_id)['enabled']:
            break
        ctx = SimpleNamespace(owner_id=owner, scan_id=sid, run_id=run_id, file=file, policy=policy)
        try:
            approve_file(store, ctx)
        except ValueError as exc:
            store.log_decision('system', 'ai.standing_approval.deferred', scan_id=sid, file=file, detail=str(exc))
