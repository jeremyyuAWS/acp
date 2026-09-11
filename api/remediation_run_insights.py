"""Immutable, owner-scoped proposal snapshots and measured AI run activity.

No finding counts are inferred from calls, queue cards or proposal versions. Existing
post-write events identify a call and queue item, not a proposal digest; they remain
recorded evidence rather than proof that this exact saved version was fixed.
"""
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json

from ai_attempt_history import AttemptHistory
from remediation_impact_estimates import build_impact_estimate

MAX_PROPOSAL_BYTES = 128 * 1024
PROPOSAL_KEYS = frozenset({'locator', 'before', 'proposed_value', 'rationale', 'source', 'model', 'model_call_id'})
SCHEMA = RUN_INSIGHTS_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS ai_proposal_snapshots (
      snapshot_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, scan_id TEXT NOT NULL,
      run_id TEXT NOT NULL, file TEXT NOT NULL, rule_id TEXT NOT NULL, item_id TEXT NOT NULL,
      proposal_index INT NOT NULL, proposal_sha256 TEXT NOT NULL, source_excerpt_sha256 TEXT,
      attempt_id TEXT, model_call_id TEXT, proposal_json TEXT, retention TEXT NOT NULL,
      created_at TEXT NOT NULL,
      UNIQUE(owner_id,run_id,item_id,proposal_index,proposal_sha256))""",
    "CREATE INDEX IF NOT EXISTS idx_ai_proposal_snapshots_run ON ai_proposal_snapshots(owner_id,scan_id,run_id)",
)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _ctx(ctx, key):
    return ctx.get(key) if isinstance(ctx, dict) else getattr(ctx, key, None)


def capture_proposals(db, cur, ctx, *, scan_id, file, rule_id, item_id, proposals):
    """Called within enqueue's transaction. Replays retain the original snapshot.

    Only an exact trace link in the same owner/execution/scan/file binds an attempt.
    The before-value digest is labelled an excerpt digest, never a document revision.
    Unlinked legacy proposals remain inspectable without guessed model lineage.
    """
    owner, run_id = _ctx(ctx, 'owner_id'), _ctx(ctx, 'run_id')
    if not owner or not run_id or _ctx(ctx, 'scan_id') != scan_id or _ctx(ctx, 'file') != file:
        return []
    db.execute(cur, 'SELECT execution_id FROM stage_executions WHERE execution_id=%s AND owner_email=%s AND scan_id=%s AND stage=%s',
               (run_id, owner, scan_id, 'remediate'))
    if db.fetchone(cur) is None:
        return []
    if not isinstance(proposals, (list, tuple)):
        return []
    captured = []
    for index, proposal in enumerate(proposals):
        if not isinstance(proposal, dict):
            continue
        content = {key: proposal[key] for key in PROPOSAL_KEYS if key in proposal}
        try:
            encoded = _json(content)
            before = _json(content['before']) if 'before' in content else None
        except (TypeError, ValueError):
            continue
        digest = sha256(encoded.encode()).hexdigest()
        identity = _json([owner, scan_id, run_id, file, rule_id, item_id, index, digest])
        snapshot_id = sha256(identity.encode()).hexdigest()
        call_id = proposal.get('model_call_id')
        if not isinstance(call_id, str) or not call_id:
            call_id = None
        attempt_id = None
        if call_id:
            db.execute(cur, """SELECT h.attempt_id FROM ai_attempt_history h JOIN ai_attempt_trace_links t
                ON t.owner_id=h.owner_id AND t.run_id=h.run_id AND t.attempt_id=h.attempt_id
                WHERE h.owner_id=%s AND h.scan_id=%s AND h.run_id=%s AND h.file=%s
                AND t.trace_call_id=%s AND h.purpose IN ('draft','fallback')""",
                (owner, scan_id, run_id, file, call_id))
            linked = db.fetchone(cur)
            attempt_id = linked['attempt_id'] if linked else None
        retention = 'full' if len(encoded.encode()) <= MAX_PROPOSAL_BYTES else 'omitted_size_limit'
        db.execute(cur, """INSERT INTO ai_proposal_snapshots
            (snapshot_id,owner_id,scan_id,run_id,file,rule_id,item_id,proposal_index,proposal_sha256,
             source_excerpt_sha256,attempt_id,model_call_id,proposal_json,retention,created_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(owner_id,run_id,item_id,proposal_index,proposal_sha256) DO NOTHING""",
            (snapshot_id, owner, scan_id, run_id, file, rule_id, item_id, index, digest,
             sha256(before.encode()).hexdigest() if before is not None else None,
             attempt_id, call_id, encoded if retention == 'full' else None, retention,
             datetime.now(timezone.utc).isoformat()))
        from remediation_contribution import capture
        capture(db, cur, ctx, snapshot_id=snapshot_id, proposal=proposal, scan_id=scan_id,
                file=file, rule_id=rule_id, item_id=item_id, attempt_id=attempt_id)
        captured.append(snapshot_id)
    return captured


def read_insights(store, owner, scan_id, run_id, *, offset=0, limit=100):
    """Page retained activity; full-run contribution totals never depend on the page.

    Each of the three record collections uses the same bounded offset/limit. Records
    are append-only and ordered by time plus immutable identity. Live writes can add
    pages; callers must not treat one page as a complete run's record population.
    """
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError('offset must be nonnegative and limit must be between 1 and 200')
    if not owner:
        raise PermissionError('An owner is required')
    execution = store.get_stage_execution(run_id, owner=owner)
    if not execution or execution.get('owner_email') != owner or execution.get('scan_id') != scan_id or execution.get('stage') != 'remediate':
        raise PermissionError('Remediation execution not found in this scope')
    db = store._db
    scope = (owner, scan_id, run_id)
    with db.cursor() as cur:
        db.execute(cur, 'SELECT policy_json FROM ai_spending_run_policies WHERE owner_id=%s AND scan_id=%s AND run_id=%s', scope)
        saved_policy = db.fetchone(cur)
        standing_approval = json.loads(saved_policy['policy_json']).get('auto_approve_ai') is True if saved_policy else False
        totals = {}
        for table, key in (('ai_attempt_history', 'total_attempts'),
                           ('ai_proposal_snapshots', 'total_proposals'),
                           ('ai_review_receipts', 'total_review_receipts')):
            db.execute(cur, f'SELECT COUNT(*) AS n FROM {table} WHERE owner_id=%s AND scan_id=%s AND run_id=%s', scope)
            totals[key] = db.fetchone(cur)['n']
        db.execute(cur, '''SELECT h.*,a.state AS spending_state,a.actual_cost_units
            FROM ai_attempt_history h LEFT JOIN ai_spending_attempts a
            ON a.owner_id=h.owner_id AND a.run_id=h.run_id AND a.attempt_id=h.attempt_id
            WHERE h.owner_id=%s AND h.scan_id=%s AND h.run_id=%s
            ORDER BY h.created_at,h.attempt_id LIMIT %s OFFSET %s''', (*scope, limit, offset))
        attempts = [AttemptHistory._decode(row) for row in db.fetchall(cur)]
        if attempts:
            marks = ','.join(['%s'] * len(attempts))
            db.execute(cur, f'SELECT attempt_id,trace_call_id FROM ai_attempt_trace_links WHERE owner_id=%s AND run_id=%s AND attempt_id IN ({marks})',
                       (owner, run_id, *(row['attempt_id'] for row in attempts)))
            links = db.fetchall(cur)
            for attempt in attempts:
                attempt['trace_call_ids'] = sorted(row['trace_call_id'] for row in links if row['attempt_id'] == attempt['attempt_id'])
                attempt['trace_call_id'] = attempt['trace_call_ids'][0] if attempt['trace_call_ids'] else None
        db.execute(cur, 'SELECT * FROM ai_proposal_snapshots WHERE owner_id=%s AND scan_id=%s AND run_id=%s ORDER BY created_at,snapshot_id LIMIT %s OFFSET %s',
                   (*scope, limit, offset))
        proposals = [dict(row) for row in db.fetchall(cur)]
        db.execute(cur, '''SELECT operation_id,proposal_sha256,review_json,created_at
            FROM ai_review_receipts WHERE owner_id=%s AND scan_id=%s AND run_id=%s
            ORDER BY created_at,operation_id,proposal_sha256 LIMIT %s OFFSET %s''', (*scope, limit, offset))
        reviews = [{**row, 'review': json.loads(row['review_json'])} for row in db.fetchall(cur)]
        # Aggregate separately from pagination. The exact trace association prevents
        # same-file, same-model or nearby attempts from acquiring contribution credit.
        db.execute(cur, '''SELECT CASE WHEN h.purpose IN ('draft','fallback') AND t.trace_call_id IS NOT NULL
                THEN h.purpose ELSE 'unattributed' END AS tier,COUNT(*) AS n
            FROM ai_proposal_snapshots p LEFT JOIN ai_attempt_history h
            ON h.owner_id=p.owner_id AND h.scan_id=p.scan_id AND h.run_id=p.run_id
                AND h.file=p.file AND h.attempt_id=p.attempt_id
            LEFT JOIN ai_attempt_trace_links t ON t.owner_id=p.owner_id AND t.run_id=p.run_id
                AND t.attempt_id=p.attempt_id AND t.trace_call_id=p.model_call_id
            WHERE p.owner_id=%s AND p.scan_id=%s AND p.run_id=%s
            GROUP BY CASE WHEN h.purpose IN ('draft','fallback') AND t.trace_call_id IS NOT NULL
                THEN h.purpose ELSE 'unattributed' END''', scope)
        counts = {'draft': 0, 'fallback': 0, 'unattributed': 0}
        for row in db.fetchall(cur):
            counts[row['tier']] = row['n']
        complete = sum(counts.values()) == totals['total_proposals']
        events = {}
        event_details_complete = True
        if proposals:
            marks = ','.join(['%s'] * len(proposals))
            for table, fields, key in (
                ('hitl_events', 'e.id,e.action,e.edited,e.proposal_snapshot_ids,e.created_at', 'human_reviews'),
                ('ai_validation_outcomes', 'e.id,e.outcome,e.detail,e.regressions,e.proposal_snapshot_id,e.source_revision,e.approved_value_sha256,e.created_at', 'validation_events'),
            ):
                attempt_filter = '' if table == 'hitl_events' else 'AND p.attempt_id IS NOT NULL'
                query = f'''SELECT p.snapshot_id,{fields} FROM ai_proposal_snapshots p
                    JOIN {table} e ON e.model_call_id=p.model_call_id AND e.scan_id=p.scan_id
                    AND e.file=p.file AND e.item_id=p.item_id AND e.rule_id=p.rule_id
                    WHERE p.owner_id=%s AND p.scan_id=%s AND p.run_id=%s {attempt_filter}
                    AND p.snapshot_id IN ({marks}) ORDER BY e.created_at DESC,e.id,p.snapshot_id LIMIT 1001'''
                try:
                    db.execute(cur, query, (*scope, *(row['snapshot_id'] for row in proposals)))
                except Exception:
                    # Older isolated databases and pre-lineage replicas may not have the
                    # additive verification columns yet. Preserve their historical events, but
                    # deliberately leave exact-version verification unavailable.
                    if table != 'ai_validation_outcomes':
                        raise
                    db.execute(cur, f'''SELECT p.snapshot_id,e.id,e.outcome,e.detail,e.regressions,
                        NULL AS proposal_snapshot_id,NULL AS source_revision,
                        NULL AS approved_value_sha256,e.created_at FROM ai_proposal_snapshots p
                        JOIN {table} e ON e.model_call_id=p.model_call_id AND e.scan_id=p.scan_id
                        AND e.file=p.file AND e.item_id=p.item_id AND e.rule_id=p.rule_id
                        WHERE p.owner_id=%s AND p.scan_id=%s AND p.run_id=%s AND p.attempt_id IS NOT NULL
                        AND p.snapshot_id IN ({marks}) ORDER BY e.created_at DESC,e.id,p.snapshot_id LIMIT 1001''',
                        (*scope, *(row['snapshot_id'] for row in proposals)))
                rows = db.fetchall(cur)
                if len(rows) > 1000:
                    event_details_complete = False
                for event in rows[:1000]:
                    value = dict(event)
                    snapshot_id = value.pop('snapshot_id')
                    event_key = key
                    if key == 'human_reviews' and value.get('action') == 'standing_approve':
                        if snapshot_id not in json.loads(value.get('proposal_snapshot_ids') or '[]'):
                            continue
                        event_key = 'system_approvals'
                    events.setdefault(snapshot_id, {}).setdefault(event_key, []).append(value)
    from remediation_contribution import read_contribution
    measured_contribution = read_contribution(store, owner, scan_id, run_id)
    verified_ids = {f['proposal_id'] for f in measured_contribution.get('findings', []) if f['state'] == 'fixed'}
    for proposal in proposals:
        proposal['proposal'] = json.loads(proposal.pop('proposal_json') or 'null')
        proposal.update(events.get(proposal['snapshot_id'], {}))
        # Approval metadata copied to a result is not actual writer evidence. Until
        # the writer records the bytes/value it used, even a cleared event cannot
        # prove this exact version. Keep historical evidence inspectable only.
        proposal['version_verified'] = proposal['snapshot_id'] in verified_ids
        proposal['verification_reason'] = ('Exact approved values and source were written and verified in the saved artifact.'
            if proposal['version_verified'] else 'Actual writer source and approved-value proof unavailable.')

    # ── Concise AI activity summary — the "was AI actually used, and what happened" line, over
    #    the FULL run population, never just the current page of `attempts`/`proposals` above.
    #    Aggregated with its own queries rather than reduced from the paginated lists, so the
    #    summary is exact regardless of which page a caller happens to be viewing.
    with db.cursor() as cur:
        db.execute(cur, '''SELECT provider,model,COUNT(*) AS attempts,
                SUM(CASE WHEN status IN ('drafted','accepted') THEN 1 ELSE 0 END) AS completed
            FROM ai_attempt_history WHERE owner_id=%s AND scan_id=%s AND run_id=%s
            GROUP BY provider,model ORDER BY attempts DESC''', scope)
        by_model = [dict(row) for row in db.fetchall(cur)]
        # A proposal counts as APPLIED only once a real decision event accepted it — standing
        # approval included, since that IS the automatic-release path's own acceptance record.
        # Awaiting review, rejected and superseded proposals are the remainder, never inferred.
        db.execute(cur, '''SELECT COUNT(DISTINCT p.snapshot_id) AS n FROM ai_proposal_snapshots p
            JOIN hitl_events e ON e.model_call_id=p.model_call_id AND e.scan_id=p.scan_id
              AND e.file=p.file AND e.item_id=p.item_id AND e.rule_id=p.rule_id
            WHERE p.owner_id=%s AND p.scan_id=%s AND p.run_id=%s
              AND e.action IN ('approve','edit','standing_approve')''', scope)
        applied_row = db.fetchone(cur)
    attempted_total = totals['total_attempts']
    completed_total = sum(row['completed'] or 0 for row in by_model)
    generated_total = totals['total_proposals']
    suggestions_applied = applied_row['n'] if applied_row else 0
    policy = json.loads(saved_policy['policy_json']) if saved_policy else {}
    ai_level = policy.get('ai')
    ai_zone = policy.get('ai_zone', 'any')
    budget_usd = policy.get('ai_budget_usd')
    # Populated ONLY when nothing was attempted — an explanation is a claim about an ABSENCE, and
    # must not be guessed when there were real, if unsuccessful, attempts to point to instead.
    not_used_reason = None
    if attempted_total == 0:
        if not ai_level:
            not_used_reason = "AI suggestions were not enabled for this run's plan."
        elif ai_zone != 'local' and (budget_usd is None or Decimal(budget_usd) <= 0):
            not_used_reason = 'Cloud AI not used: the run spending limit prevents a request.'
        else:
            not_used_reason = 'AI was enabled for this run, but no eligible findings needed a suggestion.'
    activity_summary = {
        'by_model': by_model, 'attempted': attempted_total, 'completed': completed_total,
        'suggestions_generated': generated_total, 'suggestions_applied': suggestions_applied,
        'suggestions_needs_input': max(0, generated_total - suggestions_applied),
        'verified': measured_contribution.get('outcomes', {}).get('fixed'),
        'ai_policy': {'level': ai_level, 'zone': ai_zone, 'budget_usd': budget_usd},
        'not_used_reason': not_used_reason,
    }

    return {
        'contract_version': 'remediation-run-insights.v1', 'scan_id': scan_id, 'run_id': run_id, 'batch_id': run_id,
        'standing_approval': {'enabled': standing_approval, 'authorized_by': owner if standing_approval else None},
        'attempts': attempts, 'proposals': proposals, 'review_receipts': reviews,
        'pagination': {'offset': offset, 'limit': limit, 'has_more': any(offset + limit < total for total in totals.values()), **totals},
        'coverage': 'complete' if complete else 'partial', 'event_details_complete': event_details_complete,
        'history_note': 'Only retained activity is shown. Older runs may not have recorded model or proposal history.',
        'contribution': {'unit': 'proposal_versions', **counts, 'total': totals['total_proposals'],
                         'complete': complete,
                         'note': 'Saved proposal versions, not unique findings or verified fixes. Revisions may cover the same issue.'},
        'measured_contribution': measured_contribution,
        'outcomes': {'verified_fix_count': measured_contribution.get('outcomes', {}).get('fixed'),
                     'unit':'baseline_findings', 'reason': 'exact_writer_proof_required'},
        'estimate': build_impact_estimate([], config_id='unavailable', change_family='unavailable'),
        'activity_summary': activity_summary,
    }
