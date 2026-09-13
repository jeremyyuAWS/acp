"""Bounded proposal-only recovery against a frozen corrected artifact.

This never runs a document writer or changes assessed findings. Recovered drafts
still require the existing approval and verification lanes.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
import hashlib
import json

TRANSIENT = frozenset({'vision_timeout', 'timeout', 'capacity_busy', 'circuit_open',
    'assessment_vision_budget_exhausted', 'shared_capacity_busy',
    'shared_capacity_unavailable', 'shared_coordination_unavailable'})
_MISSES = ContextVar('vision_recovery_misses', default=None)


@contextmanager
def capture():
    misses = []
    token = _MISSES.set(misses)
    try:
        yield misses
    finally:
        _MISSES.reset(token)


def record(reason):
    misses = _MISSES.get()
    if misses is not None and reason in TRANSIENT:
        misses.append(reason)


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def _decision(store, sid, file, state, **detail):
    store.log_decision('system', 'vision.recovery.' + state, scan_id=sid,
                       file=file, detail=_encoded(detail))
    safe = {key: detail[key] for key in ('retry', 'run_after', 'drafts') if key in detail}
    if state == 'blocked':
        safe['reason_code'] = detail.get('reason_code') if detail.get('reason_code') in {'vision_spending_reconciliation_required', 'vision_permission_or_budget_blocked', 'vision_generated_output_unusable'} else 'vision_recovery_unresolved'
    store.append_scan_event(sid, 'remediate.vision_retry_' + state,
        phase='remediate', document=file, correlation_id=detail.get('run_id'),
        detail=safe or None)


def _pending(store, sid, file):
    with store._db.cursor() as cur:
        store._db.execute(cur, 'SELECT id,status,proposals FROM hitl_queue WHERE scan_id=%s AND file=%s AND rule_id=%s',
                          (sid, file, '1.1.1'))
        row = store._db.fetchone(cur)
    return row if row and row['status'] == 'pending' else None


def pending_for_file(store, sid, run_id, file):
    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT payload FROM jobs WHERE scan_id=%s AND batch_id=%s AND type='vision_proposal_retry' AND status IN ('queued','running','processing','retry')", (sid, run_id))
        for row in store._db.fetchall(cur):
            payload = row['payload']
            if isinstance(payload, str):
                payload = json.loads(payload)
            if payload.get('file') == file:
                return True
    return False


def _recovery_block(context):
    reasons = {item.get('reason') if isinstance(item, dict) else str(item)
               for item in context.deferred}
    if reasons & {'provider_usage_unknown', 'existing_draft_attempt_requires_reconciliation',
                  'budget_settlement_failed_or_breached', 'budget_release_failed'}:
        return 'vision_spending_reconciliation_required'
    if context.enabled:
        snapshot = context.ledger.snapshot(context.owner_id, context.run_id)
        if snapshot['blocked']:
            return 'vision_spending_reconciliation_required'
        if snapshot['available_units'] <= 0:
            return 'vision_permission_or_budget_blocked'
    # Settled, rejected output is not evidence of missing consent or funds.
    if 'attempts_exhausted' in reasons:
        return 'vision_generated_output_unusable'
    if any(reason not in TRANSIENT for reason in reasons):
        return 'vision_permission_or_budget_blocked'
    return None


def _block_description(reason_code):
    if reason_code == 'vision_generated_output_unusable':
        return 'Generated AI output could not be used; automatic attempts have stopped.'
    return 'AI spending or permission is unresolved; automatic vision retry is paused.'


def schedule(store, context, job, misses, *, inspect_pending=False):
    if context is None or (not misses and not inspect_pending):
        return
    sid, file = context.scan_id, context.file
    if not (context.enabled or context.local_drafting):
        return
    row = _pending(store, sid, file)
    if not misses:
        if not row:
            return
        proposals = json.loads(row.get('proposals') or '[]')
        if proposals and all(p.get('proposed_value') and not p.get('automatic_write_blocked') for p in proposals):
            return
    if not file.lower().endswith(('.docx', '.pptx', '.xlsx', '.pdf')):
        _decision(store, sid, file, 'blocked', run_id=context.run_id, reason='Proposal-only vision recovery is not available for this format.')
        return
    record_ = store.get_file_record(sid, file) or {}
    row = _pending(store, sid, file)
    if file.lower().endswith('.pdf') and row:
        proposals = json.loads(row.get('proposals') or '[]')
        if not any(p.get('figure_image_sha256') and p.get('figure_association_method') == 'unique-mcid-parenttree-sole-opaque-raster-v1' for p in proposals):
            _decision(store, sid, file, 'blocked', run_id=context.run_id, reason='PDF figure recovery needs an exact figure image association; review the figure individually.')
            return
    digest = record_.get('corrected_sha256')
    if not digest or not row:
        _decision(store, sid, file, 'blocked', run_id=context.run_id, reason='A stored corrected copy and pending review are required.')
        return
    payload = {'scan_id': sid, 'file': file, 'owner': context.owner_id,
        'parent_job_id': job['id'], 'run_id': context.run_id,
        'source_revision': store.remediation_source_revision(sid),
        'corrected_sha256': digest, 'item_id': row['id'],
        'proposals_before': row['proposals'], 'retry': 1}
    blocked = _recovery_block(context)
    if blocked:
        _decision(store, sid, file, 'blocked', run_id=context.run_id,
                  reason_code=blocked, reason=_block_description(blocked))
        if blocked == 'vision_spending_reconciliation_required':
            _enqueue(store, dict(payload, waiting_spending=True, wait_check=1))
        return
    _enqueue(store, payload)


def schedule_existing_pending(store, owner, sid, run_id):
    """Resume missing drafts in the current saved run without restarting remediation."""
    from ai_run_policy import run_context
    from ai_run_approval_override import run
    run(store, owner, sid, run_id)  # Owner, current execution, consent and revision.
    seen = set()
    for summary in store.list_scan_jobs_of_type(sid, 'remediate_file'):
        parent = store.get_job(summary['id']) or {}
        durable = parent.get('payload') or {}
        if isinstance(durable, str):
            durable = json.loads(durable)
        file = durable.get('file')
        if (parent.get('batch_id') != run_id or durable.get('owner') != owner
                or durable.get('scan_id') != sid or not file or file in seen):
            continue
        seen.add(file)
        with run_context(store, durable, parent) as context:
            schedule(store, context, parent, [], inspect_pending=True)


def _enqueue(store, payload):
    from store import job_priority
    # A deterministic database key elects one enqueue across parent retries and
    # replicas. Done/dead jobs retain the key, so the allowance cannot restart.
    identity = _encoded([payload[k] for k in ('owner', 'run_id', 'file', 'corrected_sha256', 'retry')])
    if payload.get('waiting_spending'):
        identity += _encoded(['spending-wait', payload['wait_check']])
    job_id = hashlib.sha256(identity.encode()).hexdigest()[:32]
    delay = 300 if payload.get('waiting_spending') else 60 * payload['retry']
    after = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    with store._db.cursor() as cur:
        store._db.execute(cur, "INSERT INTO jobs(id,type,payload,status,priority,attempts,max_attempts,run_after,batch_id,scan_id,created_at,updated_at) VALUES(%s,%s,%s,'queued',%s,0,1,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
            (job_id, 'vision_proposal_retry', _encoded(payload), job_priority('vision_proposal_retry'),
             after, payload['run_id'], payload['scan_id'], now, now))
        if cur.rowcount != 1:
            return
    if payload.get('waiting_spending'):
        return  # This is an admission check, not a scheduled model request.
    _decision(store, payload['scan_id'], payload['file'], 'pending',
              run_id=payload['run_id'], retry=payload['retry'], run_after=after)


def _validate(store, payload):
    from ai_standing_approval import require_access
    require_access(store, payload['owner'])
    if not store.get_ai_enabled():
        raise ValueError('AI is disabled; the pending review is preserved.')
    parent = store.get_job(payload['parent_job_id']) or {}
    durable = parent.get('payload') or {}
    if isinstance(durable, str):
        durable = json.loads(durable)
    execution = store.get_stage_execution(payload['run_id'], owner=payload['owner']) or {}
    if (parent.get('type') != 'remediate_file'
            or parent.get('batch_id') != payload['run_id']
            or durable.get('owner') != payload['owner']
            or durable.get('scan_id') != payload['scan_id']
            or durable.get('file') != payload['file']
            or not execution.get('is_current') or execution.get('cancel_requested_at')
            or execution.get('state') in {'failed', 'cancelled', 'stopped', 'superseded'}
            or store.remediation_source_revision(payload['scan_id']) != payload['source_revision']
            or (store.get_file_record(payload['scan_id'], payload['file']) or {}).get('corrected_sha256') != payload['corrected_sha256']):
        raise ValueError('The authorized run or saved input changed.')
    row = _pending(store, payload['scan_id'], payload['file'])
    if not row or row['id'] != payload['item_id'] or row['proposals'] != payload['proposals_before']:
        raise ValueError('The review changed; its current decision is preserved.')
    return parent, durable


def process(store, payload):
    import blob
    import ai
    from ai_run_policy import run_context
    from remediate_office import alt_proposals_for_office
    from remediation_run_insights import capture_proposals
    from ai_spending_budget import BudgetError
    sid, file = payload['scan_id'], payload['file']
    try:
        if payload.get('waiting_spending') and (type(payload.get('wait_check')) is not int
                or not 1 <= payload['wait_check'] <= 8):
            raise ValueError('The spending reconciliation check limit was reached.')
        if payload.get('retry') not in (1, 2):
            raise ValueError('The automatic retry limit was reached.')
        parent, durable = _validate(store, payload)
        data = blob.download_remediated(payload['owner'], sid, file)
        if not data or hashlib.sha256(data).hexdigest() != payload['corrected_sha256']:
            raise ValueError('The exact saved input is unavailable.')
        with run_context(store, durable, parent) as context:
            if context is None or not (context.enabled or context.local_drafting):
                raise ValueError('The saved AI permission or spending limit does not allow recovery.')
            blocked = _recovery_block(context)
            if blocked:
                _decision(store, sid, file, 'blocked', run_id=context.run_id, reason_code=blocked,
                          reason=_block_description(blocked))
                if (payload.get('waiting_spending') and payload['wait_check'] < 8
                        and blocked == 'vision_spending_reconciliation_required'):
                    _enqueue(store, dict(payload, wait_check=payload['wait_check'] + 1))
                return
            if payload.get('waiting_spending'):
                resumed = {k: v for k, v in payload.items() if k not in {'waiting_spending', 'wait_check'}}
                _enqueue(store, resumed)
                return  # Paid generation uses the normal deterministic retry job.
            with ai.assessment_vision_budget(60), capture() as misses:
                if file.lower().endswith('.pdf'):
                    from remediate_pdf import alt_proposals_for_pdf
                    proposals = alt_proposals_for_pdf(data, scan_id=sid, context_file=file)
                else:
                    proposals, _ = alt_proposals_for_office(data, file.rsplit('.', 1)[-1],
                        scan_id=sid, context_file=file, include_grounded=True)
            if any((item.get('reason') if isinstance(item, dict) else str(item)) not in TRANSIENT
                   for item in context.deferred):
                # Deferred managed attempts may have unknown billed usage. Never
                # manufacture a fresh reservation to repeat an uncertain paid call.
                raise ValueError('The saved spending authorization cannot safely complete vision recovery; remaining work stays in review.')
            if misses:
                if payload['retry'] < 2:
                    _validate(store, payload)
                    _enqueue(store, dict(payload, retry=2))
                    return
                raise ValueError('Vision is still unavailable after two automatic retries; remaining work stays in review.')
            if not proposals:
                raise ValueError('No usable vision draft was recovered; remaining work stays in review.')
            if file.lower().endswith('.pdf'):
                current_data = blob.download_remediated(payload['owner'], sid, file)
                if not current_data or hashlib.sha256(current_data).hexdigest() != payload['corrected_sha256']:
                    raise ValueError('The exact saved PDF changed while vision was recovering; drafts remain unresolved.')
            # Preserve non-image proposals and unresolved instances. Never silently
            # shrink the criterion's finding population to the recovered subset.
            prior = json.loads(payload['proposals_before'] or '[]')
            by_locator = {p.get('locator'): p for p in proposals if p.get('proposed_value')}
            merged = [by_locator.pop(p.get('locator'), p) for p in prior]
            merged.extend(by_locator.values())
            with store.transaction():
                from store import _PgAdapter
                if isinstance(store._db, _PgAdapter):
                    # Fence publication of drafts against cancellation, artifact
                    # replacement, and review decisions until the CAS commits.
                    with store._db.cursor() as cur:
                        for sql, parameters in (
                            ('SELECT execution_id FROM stage_executions WHERE execution_id=%s FOR UPDATE', (payload['run_id'],)),
                            ('SELECT file FROM file_records WHERE scan_id=%s AND file=%s FOR UPDATE', (sid, file)),
                            ('SELECT id FROM hitl_queue WHERE id=%s FOR UPDATE', (payload['item_id'],))):
                            store._db.execute(cur, sql, parameters)
                            store._db.fetchone(cur)
                _validate(store, payload)
                with store._db.cursor() as cur:
                    store._db.execute(cur, 'UPDATE hitl_queue SET proposals=%s,validated=0 WHERE id=%s AND status=%s AND proposals IS NOT DISTINCT FROM %s',
                        (_encoded(merged), payload['item_id'], 'pending', payload['proposals_before']))
                    if cur.rowcount != 1:
                        raise ValueError('The review changed while vision was recovering.')
                    snapshots = capture_proposals(store._db, cur, context, scan_id=sid,
                        file=file, rule_id='1.1.1', item_id=payload['item_id'], proposals=merged)
                    store._db.execute(cur, 'UPDATE hitl_queue SET proposal_snapshot_ids=%s WHERE id=%s',
                                      (_encoded(snapshots), payload['item_id']))
            _decision(store, sid, file, 'recovered', run_id=payload['run_id'], drafts=len(proposals))
            from ai_standing_approval import approve_file
            approve_file(store, context)
    except (ValueError, BudgetError) as exc:
        _decision(store, sid, file, 'blocked', run_id=payload.get('run_id'), reason=str(exc))
