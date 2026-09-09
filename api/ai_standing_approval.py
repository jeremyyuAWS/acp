"""Explicit run-level advance authorization, separate from calibrated AI review.

Only the owner-approved immutable run can authorize its complete, current AI
proposals. This records a system decision, then uses the normal verified writer;
it never publishes and never treats model agreement as correctness evidence.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal

KEY = 'auto_approve_ai'
ACTION = 'standing_approve'
RULES = {'1.1.1', '2.4.4', '2.4.9', '4.1.2', '1.3.3', '3.1.2', '2.4.6'}


def normalize(value):
    if type(value) is not bool:
        raise ValueError('Automatic AI approval must be explicitly on or off')
    return value


def require_access(store, owner):
    import core
    import workspace_roles
    import workspace_rollout
    if workspace_rollout.enforcement_active():
        access = workspace_roles.access_for_email(store, owner, owner_email=core.OWNER_EMAIL,
                                                  is_suspended=core.is_suspended)
        if 'remediate.review' not in set(access.get('capabilities') or ()):
            raise ValueError('Review permission is required for automatic AI approval')


def capabilities(store, owner):
    try:
        require_access(store, owner)
    except ValueError as exc:
        return {'supported': False, 'reason': str(exc)}
    return {'supported': True, 'reason': 'New runs only. Complete, current AI proposals with a supported writer and tracked source can be approved and applied. Verification and manual blockers remain; publishing stays separate.'}


def authorization(store, owner, sid, run_id):
    require_access(store, owner)
    with store._db.cursor() as cur:
        store._db.execute(cur, '''SELECT p.policy_json,e.input_snapshot_id,e.is_current,e.cancel_requested_at
            FROM ai_spending_run_policies p JOIN stage_executions e
              ON e.execution_id=p.run_id AND e.scan_id=p.scan_id AND e.owner_email=p.owner_id
            JOIN scan_runs s ON s.id=p.scan_id AND s.owner_email=p.owner_id
            WHERE p.owner_id=%s AND p.scan_id=%s AND p.run_id=%s AND e.stage='remediate' ''',
            (owner, sid, run_id))
        row = store._db.fetchone(cur)
    policy = json.loads(row['policy_json']) if row else {}
    if (not row or not row['is_current'] or row['cancel_requested_at']
            or policy.get(KEY) is not True or policy.get('ai') != 1
            or Decimal(policy.get('ai_budget_usd', '0')) <= 0):
        raise ValueError('No current standing AI approval authorization for this run')
    if row['input_snapshot_id'] != store.remediation_source_revision(sid):
        raise ValueError('Standing approval source revision changed')
    return row['input_snapshot_id']


def _source(store, owner, sid, file):
    import core
    import handlers
    from release_artifacts import require_current_source
    scan = store.get_scan(sid, owner=owner)
    record = store.get_file_record(sid, file) or {}
    source = (scan or {}).get('run', {}).get('source')
    if (not scan or source not in {'drive', 'sharepoint'} or not record.get('source_modified')
            or not record.get('drive_file_id') or not record.get('remediated_at')
            or not record.get('corrected_sha256')):
        raise ValueError('Tracked source and stored corrected copy are required for automatic approval')
    tokens = core.get_scan_tokens(sid)
    svc = handlers._drive_client(tokens.get('drive')) if source == 'drive' else None
    require_current_source(source, record, drive_service=svc, sp_token=tokens.get('sp'))
    return record


def _identity(record):
    return {k: record.get(k) for k in ('drive_file_id', 'source_modified', 'checksum', 'drive_id',
                                       'source_relative_path', 'corrected_sha256')}


def eligible_item(store, owner, sid, run_id, item, *, approved=False):
    from release_continuation import eligibility
    from remediation_run_insights import PROPOSAL_KEYS
    row = {**item, 'status': 'pending', 'applied': False} if approved else item
    reason = eligibility(row, row.get('file', ''))
    if reason or row.get('rule_id') not in RULES:
        raise ValueError(reason or 'This change requires individual review')
    for p in row['proposals']:
        if (p.get('explain_only') or p.get('companion_file') or p.get('kind')
                or not p.get('model_call_id') or not p.get('model')
                or p.get('describable') is False):
            raise ValueError('Proposal requires individual judgment or has no exact AI provenance')
    with store._db.cursor() as cur:
        store._db.execute(cur, 'SELECT policy_json FROM ai_spending_run_policies WHERE owner_id=%s AND scan_id=%s AND run_id=%s',
                          (owner, sid, run_id))
        policy_row = store._db.fetchone(cur)
        review_required = json.loads(policy_row['policy_json']).get('ai_review', {}).get('enabled') is True if policy_row else False
        for i, (snapshot_id, p) in enumerate(zip(row['proposal_snapshot_ids'], row['proposals'])):
            store._db.execute(cur, 'SELECT * FROM ai_proposal_snapshots WHERE snapshot_id=%s', (snapshot_id,))
            snapshot = store._db.fetchone(cur)
            digest = hashlib.sha256(json.dumps({k: p[k] for k in PROPOSAL_KEYS if k in p},
                ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
            if (not snapshot or snapshot['owner_id'] != owner or snapshot['scan_id'] != sid
                    or snapshot['run_id'] != run_id or snapshot['item_id'] != row['id']
                    or snapshot['file'] != row['file'] or snapshot['rule_id'] != row['rule_id']
                    or snapshot['proposal_index'] != i or snapshot['proposal_sha256'] != digest
                    or snapshot['model_call_id'] != p['model_call_id']
                    or not store.ai_call_belongs_to_file(p['model_call_id'], sid, row['file'])):
                raise ValueError('AI proposal is not an exact output of this authorized run')
            store._db.execute(cur, '''SELECT c.model,c.ok,c.ts,e.created_at FROM ai_calls c
                JOIN stage_executions e ON e.execution_id=%s
                WHERE c.id=%s AND c.scan_id=%s AND c.file=%s''',
                (run_id, p['model_call_id'], sid, row['file']))
            call = store._db.fetchone(cur)
            from datetime import datetime
            if (not call or not call['ok'] or call['model'] != p['model']
                    or datetime.fromisoformat(call['ts'].replace('Z', '+00:00'))
                    < datetime.fromisoformat(call['created_at'].replace('Z', '+00:00'))):
                raise ValueError('AI call does not belong to the current proposal generation')
            if review_required:
                store._db.execute(cur, '''SELECT h.result_json,r.proposal_sha256,r.review_json
                    FROM ai_attempt_history h JOIN ai_review_receipts r
                      ON r.owner_id=h.owner_id AND r.scan_id=h.scan_id AND r.run_id=h.run_id
                      AND r.operation_id=h.operation_id
                    WHERE h.owner_id=%s AND h.scan_id=%s AND h.run_id=%s AND h.attempt_id=%s''',
                    (owner, sid, run_id, snapshot['attempt_id']))
                reviews = store._db.fetchall(cur)
                accepted = False
                for receipt in reviews:
                    draft = json.loads(receipt['result_json'] or '{}').get('text')
                    review = json.loads(receipt['review_json'])
                    if (isinstance(draft, str) and hashlib.sha256(draft.encode()).hexdigest() == receipt['proposal_sha256']
                            and review.get('verdict') == 'accept'):
                        accepted = True
                if not accepted:
                    raise ValueError('The optional AI review is missing or unresolved; individual review is required')
    return row


def approve_file(store, ctx):
    if ctx is None or ctx.policy.get(KEY) is not True:
        return
    owner, sid, run_id, file = ctx.owner_id, ctx.scan_id, ctx.run_id, ctx.file
    revision = authorization(store, owner, sid, run_id)
    record = _source(store, owner, sid, file)
    # Fetch only this file's run-bound rows, not the entire scan queue once per file.
    with store._db.cursor() as cur:
        store._db.execute(cur, '''SELECT DISTINCT q.* FROM hitl_queue q JOIN ai_proposal_snapshots p
            ON p.item_id=q.id AND p.scan_id=q.scan_id AND p.file=q.file
            WHERE p.owner_id=%s AND p.scan_id=%s AND p.run_id=%s AND p.file=%s
              AND q.status='pending' ORDER BY q.id''', (owner, sid, run_id, file))
        rows = [store._decode_proposals(r) for r in store._db.fetchall(cur)]
    selected = []
    for row in rows:
        try:
            eligible_item(store, owner, sid, run_id, row)
            selected.append(row)
        except ValueError as exc:
            store.log_decision('system', 'ai.standing_approval.deferred', scan_id=sid, file=file,
                               rule_id=row.get('rule_id'), detail=str(exc))
    if not selected:
        return
    with store.transaction():
        authorization(store, owner, sid, run_id)
        if _identity(store.get_file_record(sid, file) or {}) != _identity(record):
            raise ValueError('Corrected copy or source changed before automatic approval')
        approved = []
        for row in selected:
            request_id = f'standing:{run_id}:{row["id"]}'
            note = f'Automatically approved under the run plan authorized by {owner}; not an individual human review.'
            updated, replay = store.complete_hitl_decision(row['id'], 'approved', note, None,
                resolution=None, approved_values=[p['proposed_value'] for p in row['proposals']],
                actor=owner, detail=json.dumps({'authorized_by': owner, 'executed_by': 'system', 'run_id': run_id}),
                request_id=request_id, expected_version=row['decision_version'],
                expected_proposal_snapshot_ids=row['proposal_snapshot_ids'], expected_source_revision=revision,
                standing_approval_run_id=run_id)
            if not updated or replay:
                continue
            approved.append({'id': row['id'], 'version': updated['decision_version'],
                             'request_id': request_id, 'snapshots': row['proposal_snapshot_ids'],
                             'value_sha256': updated['approved_value_sha256']})
            for p in row['proposals']:
                store.record_hitl_event(sid, file, row['rule_id'], row['id'], ACTION,
                    ai_value=p['proposed_value'], final_value=p['proposed_value'], reviewer='system',
                    model_call_id=p['model_call_id'], proposal_snapshot_ids=row['proposal_snapshot_ids'],
                    source_revision=revision, approved_value_sha256=updated['approved_value_sha256'])
        if approved:
            store.enqueue_job('apply_approved_values', {'scan_id': sid, 'file': file,
                'standing_approval': {'owner': owner, 'run_id': run_id, 'source_revision': revision,
                                      'artifact': record['corrected_sha256'], 'items': approved}}, scan_id=sid)


def check_application(store, payload, *, working=None):
    intent = payload.get('standing_approval')
    if not intent:
        return
    owner, sid, file = intent['owner'], payload['scan_id'], payload['file']
    revision = authorization(store, owner, sid, intent['run_id'])
    if not intent['items']:
        raise ValueError('No exact automatic approvals to apply')
    applied = []
    for expected in intent['items']:
        item = store.get_hitl_item(expected['id']) or {}
        eligible_item(store, owner, sid, intent['run_id'], item, approved=True)
        if (item.get('scan_id') != sid or item.get('file') != file or item.get('status') != 'approved'
                or item.get('decision_version') != expected['version']
                or item.get('last_decision_request_id') != expected['request_id']
                or item.get('approved_proposal_snapshot_ids') != expected['snapshots']
                or item.get('approved_value_sha256') != expected['value_sha256']
                or item.get('approved_source_revision') != revision):
            raise ValueError('Automatic approval changed before application')
        applied.append(bool(item.get('applied')))
    # A coalesced file writer may already have completed a later queued batch too.
    # Replays must not attempt another write against its now-replaced artifact.
    if all(applied):
        return True
    record = _source(store, owner, sid, file)
    if revision != intent['source_revision'] or record['corrected_sha256'] != intent['artifact']:
        raise ValueError('Source or corrected artifact changed since automatic approval')
    if working is not None and hashlib.sha256(working).hexdigest() != intent['artifact']:
        raise ValueError('Stored corrected bytes do not match the authorized artifact')


def check_file_approvals(store, sid, file):
    """Every existing writer job must respect standing approvals it would coalesce.

    Human-only jobs remain unchanged. A late manual job must never accidentally
    apply an automatic approval from an obsolete or cancelled remediation run.
    """
    automatic = [r for r in store._approved_unapplied_rows(sid, file)
                 if str(r.get('last_decision_request_id') or '').startswith('standing:')]
    if not automatic:
        return
    owner = (store.get_scan(sid) or {}).get('run', {}).get('owner_email')
    _source(store, owner, sid, file)
    for row in automatic:
        with store._db.cursor() as cur:
            store._db.execute(cur, 'SELECT run_id FROM ai_proposal_snapshots WHERE snapshot_id=%s',
                              ((row.get('proposal_snapshot_ids') or [''])[0],))
            snapshot = store._db.fetchone(cur)
        run_id = (snapshot or {}).get('run_id')
        revision = authorization(store, owner, sid, run_id)
        eligible_item(store, owner, sid, run_id, row, approved=True)
        values = [str(p.get('approved_value') or '').strip() for p in row['proposals']]
        digest = hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        if (row.get('approved_source_revision') != revision
                or row.get('last_decision_request_id') != f'standing:{run_id}:{row["id"]}'
                or row.get('approved_proposal_snapshot_ids') != row.get('proposal_snapshot_ids')
                or row.get('approved_value_sha256') != digest):
            raise ValueError('Standing approval no longer matches the proposed write')
