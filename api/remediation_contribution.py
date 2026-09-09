"""Exact, owner-scoped finding contribution. Missing joins are never success.

The baseline is frozen at admission. Proposal membership is explicit; detector
ordinals are not guessed from proposal positions. Events identify an immutable
proposal, source bytes and approval. Existing card-level telemetry is not used.
"""
from contextvars import ContextVar
from datetime import datetime, timezone
from hashlib import sha256
import json

SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS remediation_contribution_runs (
       owner_id TEXT NOT NULL, scan_id TEXT NOT NULL, run_id TEXT NOT NULL,
       snapshot_id TEXT NOT NULL, baseline_json TEXT NOT NULL, files_json TEXT NOT NULL,
       created_at TEXT NOT NULL, PRIMARY KEY(owner_id,run_id))''',
    '''CREATE TABLE IF NOT EXISTS remediation_contribution_proposals (
       owner_id TEXT NOT NULL, scan_id TEXT NOT NULL, run_id TEXT NOT NULL,
       proposal_id TEXT NOT NULL, proposal_sha256 TEXT NOT NULL, source_sha256 TEXT NOT NULL,
       assessment_revision TEXT NOT NULL,
       file TEXT NOT NULL, rule_id TEXT NOT NULL, item_id TEXT NOT NULL,
       finding_ids_json TEXT NOT NULL, origin TEXT, attempt_id TEXT, operation_id TEXT,
       created_at TEXT NOT NULL, PRIMARY KEY(owner_id,run_id,proposal_id))''',
    "ALTER TABLE ai_validation_outcomes ADD COLUMN IF NOT EXISTS actual_source_sha256 TEXT",
    "ALTER TABLE ai_validation_outcomes ADD COLUMN IF NOT EXISTS actual_approved_value_sha256 TEXT",
    "ALTER TABLE ai_validation_outcomes ADD COLUMN IF NOT EXISTS artifact_sha256 TEXT",
    "ALTER TABLE ai_validation_outcomes ADD COLUMN IF NOT EXISTS approval_event_id TEXT",
)
SOURCE = ContextVar('contribution_source', default=None)
OUTCOMES = ('fixed', 'awaiting_review', 'approved', 'unresolved', 'processing', 'unavailable')


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return sha256(encoded(value).encode()).hexdigest()


def proposal_digest(proposal):
    from remediation_run_insights import PROPOSAL_KEYS
    return digest({key: proposal[key] for key in PROPOSAL_KEYS if key in proposal})


def now():
    return datetime.now(timezone.utc).isoformat()


def freeze_baseline(db, cur, owner, scan_id, run_id, snapshot_id, findings, files):
    """Admission-only transaction seam, including the empty-baseline case."""
    baseline = [{key: row.get(key) for key in ('finding_id', 'file', 'rule_id', 'instance_key')}
                for row in findings if row.get('file') in files]
    baseline.sort(key=lambda row: row['finding_id'])
    if len({row['finding_id'] for row in baseline}) != len(baseline):
        raise ValueError('duplicate baseline identity')
    values = (snapshot_id, encoded(baseline), encoded(sorted(set(files))))
    db.execute(cur, '''INSERT INTO remediation_contribution_runs
        (owner_id,scan_id,run_id,snapshot_id,baseline_json,files_json,created_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(owner_id,run_id) DO NOTHING''',
        (owner, scan_id, run_id, *values, now()))
    db.execute(cur, 'SELECT * FROM remediation_contribution_runs WHERE owner_id=%s AND run_id=%s', (owner, run_id))
    prior = db.fetchone(cur)
    if (prior['scan_id'], prior['snapshot_id'], prior['baseline_json'], prior['files_json']) != (scan_id, *values):
        raise ValueError('contribution baseline is immutable')


def capture(db, cur, ctx, *, snapshot_id, proposal, scan_id, file, rule_id, item_id, attempt_id):
    """Capture only usable structured values with exact source and baseline links."""
    from remediation_run_insights import _ctx
    owner, run = _ctx(ctx, 'owner_id'), _ctx(ctx, 'run_id')
    source = SOURCE.get()
    if not owner or not run or not source or source[:2] != (scan_id, file):
        return
    value, locator = proposal.get('proposed_value'), proposal.get('locator')
    if not isinstance(value, str) or not value.strip() or not isinstance(locator, str) or not locator.strip():
        return
    db.execute(cur, 'SELECT baseline_json,snapshot_id FROM remediation_contribution_runs WHERE owner_id=%s AND scan_id=%s AND run_id=%s', (owner, scan_id, run))
    baseline = db.fetchone(cur)
    if not baseline:
        return
    candidates = [row for row in json.loads(baseline['baseline_json']) if row['file'] == file and row['rule_id'] == rule_id]
    supplied = proposal.get('baseline_finding_ids')
    # A sole finding is unambiguous. Multiple aggregate ordinals need an explicit
    # detector/writer binding, never a positional zip with generated suggestions.
    if supplied is None:
        supplied = [candidates[0]['finding_id']] if len(candidates) == 1 else []
    if not isinstance(supplied, list) or not supplied or any(not isinstance(x, str) for x in supplied):
        return
    ids = sorted(set(supplied))
    if not set(ids) <= {row['finding_id'] for row in candidates}:
        raise ValueError('proposal finding membership outside immutable baseline')
    origin, operation = None, None
    if attempt_id:
        db.execute(cur, '''SELECT purpose,operation_id,status FROM ai_attempt_history
            WHERE owner_id=%s AND scan_id=%s AND run_id=%s AND file=%s AND attempt_id=%s''',
            (owner, scan_id, run, file, attempt_id))
        attempt = db.fetchone(cur)
        if attempt and attempt['status'] == 'drafted':
            operation = attempt['operation_id']
            if attempt['purpose'] == 'draft':
                origin = 'first_ai'
            elif attempt['purpose'] == 'fallback':
                db.execute(cur, '''SELECT purpose,status FROM ai_attempt_history WHERE owner_id=%s
                    AND scan_id=%s AND run_id=%s AND operation_id=%s AND file=%s AND purpose='draft' ''',
                    (owner, scan_id, run, operation, file))
                earlier = db.fetchall(cur)
                if earlier and all(row['status'] in ('unusable_response', 'empty_response') for row in earlier):
                    origin = 'fallback_ai'
    elif proposal.get('source') in ('derived', 'rule', 'rules', 'deterministic'):
        origin = 'rules'
    db.execute(cur, '''INSERT INTO remediation_contribution_proposals
        (owner_id,scan_id,run_id,proposal_id,proposal_sha256,source_sha256,assessment_revision,file,rule_id,item_id,
         finding_ids_json,origin,attempt_id,operation_id,created_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
        (owner, scan_id, run, snapshot_id, proposal_digest(proposal), source[2], baseline['snapshot_id'], file, rule_id,
         item_id, encoded(ids), origin, attempt_id, operation, now()))


def _authorized(store, owner, scan_id, run_id):
    execution = store.get_stage_execution(run_id, owner=owner) if owner else None
    if not execution or execution.get('scan_id') != scan_id or execution.get('owner_email') != owner or execution.get('stage') != 'remediate':
        raise PermissionError('Remediation execution not found in this scope')
    return execution


def read_contribution(store, owner, scan_id, run_id):
    execution = _authorized(store, owner, scan_id, run_id)
    db = store._db
    scope = (owner, scan_id, run_id)
    with db.cursor() as cur:
        db.execute(cur, 'SELECT * FROM remediation_contribution_runs WHERE owner_id=%s AND scan_id=%s AND run_id=%s', scope)
        baseline = db.fetchone(cur)
        if not baseline:
            return {'contract_version': 'remediation-contribution.v1', 'coverage': 'unavailable',
                    'baseline_total': None, 'available':False, 'first_model_findings':None, 'fallback_additional_findings':None, 'reviewed_findings':None, 'baseline_findings':None, 'contributions': {key: None for key in ('rules','first_ai','fallback_ai')},
                    'findings': [], 'note': 'AI step breakdown unavailable for this run. No immutable contribution baseline was retained.'}
        db.execute(cur, 'SELECT * FROM remediation_contribution_proposals WHERE owner_id=%s AND scan_id=%s AND run_id=%s ORDER BY created_at,proposal_id', scope)
        proposals = db.fetchall(cur)
        db.execute(cur, """SELECT v.*,p.owner_id,p.run_id,p.proposal_id,p.proposal_sha256,p.source_sha256,
            a.source_revision AS approval_source_revision,a.approved_value_sha256 AS approval_value_sha256,
            a.proposal_snapshot_ids,a.action AS approval_action
            FROM ai_validation_outcomes v JOIN remediation_contribution_proposals p
            ON p.proposal_id=v.proposal_snapshot_id AND p.scan_id=v.scan_id AND p.file=v.file AND p.item_id=v.item_id
            LEFT JOIN hitl_events a ON a.id=v.approval_event_id AND a.scan_id=v.scan_id AND a.file=v.file
            AND a.item_id=v.item_id AND COALESCE(a.model_call_id,'')=COALESCE(v.model_call_id,'')
            WHERE p.owner_id=%s AND p.scan_id=%s AND p.run_id=%s ORDER BY v.created_at,v.id""", scope)
        events = db.fetchall(cur)
        db.execute(cur, 'SELECT operation_id,proposal_sha256 FROM ai_review_receipts WHERE owner_id=%s AND scan_id=%s AND run_id=%s', scope)
        reviews = db.fetchall(cur)
        reviewed = {p['proposal_id'] for p in proposals for r in reviews
                    if p.get('operation_id') == r['operation_id'] and p['proposal_sha256'] == r['proposal_sha256']}
        review_count = len(reviewed) if not reviews or reviewed else None
        db.execute(cur, """SELECT p.proposal_id,q.status,q.approved_proposal_snapshot_ids,
            q.approved_value_sha256,q.approved_source_revision,e.id AS human_approval_id,e.proposal_snapshot_ids AS approval_snapshot_ids FROM remediation_contribution_proposals p
            JOIN hitl_queue q ON q.id=p.item_id AND q.scan_id=p.scan_id AND q.file=p.file
            LEFT JOIN hitl_events e ON e.item_id=q.id AND e.scan_id=q.scan_id AND e.file=q.file
                AND e.action IN ('approve','edit') AND e.source_revision=q.approved_source_revision
                AND e.approved_value_sha256=q.approved_value_sha256
            WHERE p.owner_id=%s AND p.scan_id=%s AND p.run_id=%s""", scope)
        approvals = {r['proposal_id']:r for r in db.fetchall(cur)}
        db.execute(cur, 'SELECT finding_id,disposition FROM finding_disposition WHERE scan_id=%s AND batch_id=%s', (scan_id,run_id))
        dispositions = {r['finding_id']:r['disposition'] for r in db.fetchall(cur)}
        db.execute(cur, 'SELECT input_id,state FROM stage_work_items WHERE execution_id=%s', (run_id,))
        active_files = {r['input_id'] for r in db.fetchall(cur) if r['state'] in ('queued','processing','retry_scheduled')}
    return aggregate(baseline, proposals, events, dispositions=dispositions, active_files=active_files,
                     revision=execution.get('revision'), approvals=approvals, review_count=review_count)


def aggregate(baseline, proposals, events, *, dispositions=None, active_files=(), revision=None, approvals=None, review_count=None):
    findings = json.loads(baseline['baseline_json'])
    membership, event_map = {}, {}
    scope = tuple(baseline[k] for k in ('owner_id','scan_id','run_id'))
    for p in proposals:
        if tuple(p[k] for k in ('owner_id','scan_id','run_id')) != scope:
            continue
        for fid in json.loads(p['finding_ids_json']):
            membership.setdefault(fid, []).append(p)
        event_map[p['proposal_id']] = [e for e in events if all(e.get(k) == p.get(k) for k in
            ('owner_id','scan_id','run_id','proposal_id','proposal_sha256','source_sha256'))]
    counts = dict.fromkeys(OUTCOMES, 0)
    contributions = dict.fromkeys(('rules','first_ai','fallback_ai'), 0)
    for f in findings:
        options = membership.get(f['finding_id'], [])
        # The first usable source owns contribution; fallback revisions cannot add
        # a finding already covered by the first model.
        origin = next((p['origin'] for p in options if p.get('origin')), None)
        p = options[-1] if options else None
        state, reason, approval_kind = 'unavailable', 'Exact finding/proposal linkage unavailable', None
        if p:
            ev = event_map[p['proposal_id']]
            approval = (approvals or {}).get(p['proposal_id']) or {}
            approved = (approval.get('status') == 'approved' and p['proposal_id'] in
                        json.loads(approval.get('approved_proposal_snapshot_ids') or '[]')
                        and approval.get('approved_value_sha256') and approval.get('approved_source_revision') == baseline['snapshot_id']
                        and approval.get('human_approval_id') and p['proposal_id'] in json.loads(approval.get('approval_snapshot_ids') or '[]'))
            last = ev[-1] if ev else None
            if last and not exact_verification(p, last):
                state, reason = 'unresolved', 'Verification failed or exact source/value proof is missing'
            elif last:
                state, reason, approval_kind = 'fixed', 'Exact approved version applied and checked', 'human'
            elif approved:
                state, reason, approval_kind = 'approved', 'Exact proposal approved; completion not verified', 'human'
            elif approval.get('status') == 'rejected':
                state, reason = 'unresolved', 'Suggestion rejected'
            else:
                state, reason = 'awaiting_review', 'Usable proposal awaiting approval'
        elif f['file'] in active_files:
            state, reason = 'processing', 'Work is active for this file'
        elif (dispositions or {}).get(f['finding_id']) in ('unchanged_no_fix','remediation_failed','excluded_by_policy','superseded_by_reassessment'):
            state, reason = 'unresolved', 'Recorded unresolved disposition'
        if origin:
            contributions[origin] += 1
        f.update(state=state, origin=origin, proposal_id=p['proposal_id'] if p else None,
                 approval_kind=approval_kind, reason=reason)
        counts[state] += 1
    complete = counts['unavailable'] == 0 and all(f['origin'] for f in findings)
    return {'contract_version':'remediation-contribution.v1', 'coverage':'complete' if complete else 'partial',
            'available':complete, 'first_model_findings':contributions['first_ai'] if complete else None, 'fallback_additional_findings':contributions['fallback_ai'] if complete else None, 'reviewed_findings':None, 'baseline_findings':len(findings),
            'baseline_total':len(findings), 'snapshot_id':baseline['snapshot_id'], 'generated_at':now(),
            'revision':digest([revision,findings,counts,contributions,review_count]), 'selected_file_count':len(json.loads(baseline['files_json'])),
            'outcomes':counts, 'contributions':contributions, 'reviewer':{'checked_proposals':review_count},
            'findings':findings, 'note':'Unique baseline findings. Missing exact evidence remains unavailable. Reviewer activity overlaps suggestions and is counted separately.'}


def exact_verification(proposal, event):
    return bool(event.get('outcome') == 'verified_cleared' and event.get('regressions') in ('[]', [])
        and event.get('approval_action') in ('approve', 'edit') and event.get('approval_event_id')
        and event.get('artifact_sha256') and event.get('source_revision')
        and event['source_revision'] == event.get('approval_source_revision') == proposal.get('assessment_revision')
        and event.get('actual_source_sha256') == proposal.get('source_sha256')
        and event.get('actual_approved_value_sha256') and event['actual_approved_value_sha256']
        == event.get('approved_value_sha256') == event.get('approval_value_sha256')
        and proposal['proposal_id'] == event.get('proposal_snapshot_id')
        and proposal['proposal_id'] in json.loads(event.get('proposal_snapshot_ids') or '[]'))


def writer_tickets(store, scan_id, file, item_ids, source_sha256, *, actual_values):
    """Freeze exact queue values, approval and source BEFORE the writer executes."""
    db, tickets = store._db, []
    with db.cursor() as cur:
        for item_id in set(item_ids):
            db.execute(cur, "SELECT * FROM hitl_queue WHERE id=%s AND scan_id=%s AND file=%s AND status='approved'", (item_id, scan_id, file))
            queue = db.fetchone(cur)
            if not queue:
                continue
            values = json.loads(queue['proposals'] or '[]')
            approved_digest = digest([str(p.get('approved_value') or '').strip() for p in values if isinstance(p, dict)])
            if approved_digest != queue.get('approved_value_sha256') or any(
                actual_values.get(p.get('locator')) != p.get('approved_value')
                for p in values if isinstance(p, dict) and p.get('approved_value')):
                continue
            snapshots = json.loads(queue.get('approved_proposal_snapshot_ids') or '[]')
            db.execute(cur, "SELECT * FROM hitl_events WHERE scan_id=%s AND file=%s AND item_id=%s AND action IN ('approve','edit') ORDER BY created_at DESC,id", (scan_id, file, item_id))
            approvals = db.fetchall(cur)
            for index, proposal in enumerate(values):
                snapshot = snapshots[index] if index < len(snapshots) else None
                if not snapshot or not isinstance(proposal, dict):
                    continue
                db.execute(cur, "SELECT * FROM remediation_contribution_proposals WHERE scan_id=%s AND file=%s AND item_id=%s AND proposal_id=%s", (scan_id, file, item_id, snapshot))
                p = db.fetchone(cur)
                if not p or proposal_digest(proposal) != p['proposal_sha256'] or str(proposal.get('approved_value') or '').strip() != str(proposal.get('proposed_value') or '').strip():
                    continue
                approval = next((e for e in approvals if e.get('approved_value_sha256') == approved_digest
                    and snapshot in json.loads(e.get('proposal_snapshot_ids') or '[]')
                    and e.get('source_revision') == queue.get('approved_source_revision')
                    and e.get('model_call_id') == proposal.get('model_call_id')), None)
                if not approval or approval['source_revision'] != p['assessment_revision']:
                    continue
                tickets.append({**p, 'approval_event_id':approval['id'], 'model_call_id':approval['model_call_id'],
                    'source_revision':approval['source_revision'], 'approved_value_sha256':approved_digest,
                    'actual_source_sha256':source_sha256, 'locator':proposal.get('locator'), 'approved_value':proposal.get('approved_value')})
    return tickets


def record_writer_result(store, tickets, *, outcome, artifact_sha256, reference, writer_attempt_id):
    """Append actual writer evidence to the shared feed; never copy proof from approval."""
    with store._db.cursor() as cur:
        for t in tickets:
            identity = digest([t['proposal_id'], t['approval_event_id'], t['actual_source_sha256'], artifact_sha256, outcome, reference, writer_attempt_id])
            store._db.execute(cur, """INSERT INTO ai_validation_outcomes
                (id,model_call_id,scan_id,file,rule_id,item_id,outcome,detail,created_at,regressions,
                 proposal_snapshot_id,source_revision,approved_value_sha256,actual_source_sha256,
                 actual_approved_value_sha256,artifact_sha256,approval_event_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING""",
                (identity, t['model_call_id'],t['scan_id'],t['file'],t['rule_id'],t['item_id'],outcome,
                 reference,now(),'[]' if outcome == 'verified_cleared' else None,t['proposal_id'],
                 t['source_revision'],t['approved_value_sha256'],t['actual_source_sha256'],
                 t['approved_value_sha256'],artifact_sha256,t['approval_event_id']))
