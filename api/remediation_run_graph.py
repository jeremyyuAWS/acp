"""Complete retained run activity, with explicit rather than chronological causality.

This projection never dispatches a model. Legacy purpose is retained verbatim;
only durable generation metadata assigns an attempt to a configured position.
"""
import hashlib
import json


def _object(value):
    try:
        result = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return {}
    return result if isinstance(result, dict) else {}


def read_run_graph(store, owner, scan_id, run_id):
    execution = store.get_stage_execution(run_id, owner=owner) if owner else None
    if not execution or execution.get('owner_email') != owner or execution.get('scan_id') != scan_id or execution.get('stage') != 'remediate':
        raise LookupError('remediation execution not found')
    db = store._db
    scope = (owner, scan_id, run_id)
    with db.cursor() as cur:
        db.execute(cur, 'SELECT policy_json FROM ai_spending_run_policies WHERE owner_id=%s AND scan_id=%s AND run_id=%s', scope)
        policy = _object((db.fetchone(cur) or {}).get('policy_json'))
        # Deliberately no page limit: a page of history is not the run graph.
        db.execute(cur, '''SELECT h.*,a.state AS spending_state,a.actual_cost_units,a.max_cost_units
            FROM ai_attempt_history h LEFT JOIN ai_spending_attempts a
            ON a.owner_id=h.owner_id AND a.run_id=h.run_id AND a.attempt_id=h.attempt_id
            WHERE h.owner_id=%s AND h.scan_id=%s AND h.run_id=%s
            ORDER BY h.created_at,h.attempt_id''', scope)
        records = db.fetchall(cur)
        db.execute(cur, '''SELECT operation_id,proposal_sha256,review_json,created_at
            FROM ai_review_receipts WHERE owner_id=%s AND scan_id=%s AND run_id=%s
            ORDER BY created_at,operation_id,proposal_sha256''', scope)
        receipts = db.fetchall(cur)
    return project_run_graph(policy, records, receipts)


def project_run_graph(policy, records, receipts):
    chain = _object(policy.get('generation_chain'))
    configured = chain.get('steps') if chain.get('version') == 1 else []
    configured = configured if isinstance(configured, list) else []
    steps = []
    for position, key in enumerate(('primary', 'fallback_1', 'fallback_2')):
        matches = [s for s in configured if isinstance(s, dict) and s.get('step_id') == key and type(s.get('position')) is int and s['position'] == position]
        if len(matches) == 1:
            s = matches[0]
            steps.append(dict(step_id=key, position=position, purpose='generation',
                              provider=s.get('provider'), model=s.get('model'),
                              configured=True, enabled=s.get('enabled') is True, in_flight=False,
                              state='outcome_unknown', reason='No recorded dispatch decision for this position.', attempt_ids=[]))
    index = {s['step_id']: s for s in steps}
    attempts = []
    ambiguous = not steps
    for record in records:
        result = _object(record.get('result_json'))
        # This object is supplied by server recording, never parsed from model text.
        lineage = _object(result.get('execution'))
        step_id = lineage.get('step_id')
        position = lineage.get('generation_position')
        parent = lineage.get('parent_attempt_id')
        purpose = record.get('purpose')
        step = index.get(step_id) if isinstance(step_id, str) else None
        linked = (purpose in ('draft', 'fallback') and step is not None
                  and lineage.get('chain_version') == chain.get('version')
                  and type(position) is int and position == step['position']
                  and record.get('provider') == step['provider'] and record.get('model') == step['model'])
        if purpose in ('draft', 'fallback') and not linked:
            ambiguous = True
        if purpose not in ('draft', 'fallback', 'review', 'final_review'):
            ambiguous = True
        attempt = {key: record.get(key) for key in (
            'attempt_id', 'operation_id', 'file', 'purpose', 'provider', 'model',
            'status', 'spending_state', 'actual_cost_units', 'max_cost_units', 'created_at', 'updated_at', 'reason', 'output_retention')}
        attempt.update(step_id=step_id if linked else None,
                       generation_position=position if linked else None,
                       parent_attempt_id=parent if isinstance(parent, str) else None,
                       escalation_reason=lineage.get('escalation_reason'),
                       lineage_available=linked if purpose in ('draft', 'fallback') else False,
                       validation_outcome=result.get('validation_outcome'),
                       source_sha256=lineage.get('source_sha256'),
                       assessment_revision=lineage.get('assessment_revision'),
                       finding_ids=lineage.get('finding_ids') if isinstance(lineage.get('finding_ids'), list) else [])
        # A reservation identifies a planned model, not an actual provider call.
        if record.get('spending_state') in ('reserved', 'released'):
            attempt['provider'] = attempt['model'] = None
        attempts.append(attempt)
        if linked:
            step['attempt_ids'].append(attempt['attempt_id'])
    by_id = {a['attempt_id']: a for a in attempts}
    edges = []
    for attempt in attempts:
        parent = by_id.get(attempt['parent_attempt_id'])
        # Same operation/file and an explicit reference are mandatory. Created-at
        # order is never treated as proof of an escalation or review dependency.
        if parent and parent is not attempt and parent['operation_id'] == attempt['operation_id'] and parent['file'] == attempt['file'] and parent['source_sha256'] == attempt['source_sha256'] and parent['assessment_revision'] == attempt['assessment_revision']:
            edges.append({'source': parent['attempt_id'], 'target': attempt['attempt_id'], 'kind': 'parent_attempt'})
        elif attempt['parent_attempt_id']:
            ambiguous = True
            attempt['parent_attempt_id'] = None
    for step in steps:
        linked = [by_id[aid] for aid in step['attempt_ids']]
        if any(a['spending_state'] == 'uncertain' or a['status'] == 'usage_unknown' for a in linked):
            step.update(state='outcome_unknown', reason='An attempt outcome or charge needs reconciliation.')
        elif any(a['spending_state'] == 'dispatched' and a['status'] == 'started' for a in linked):
            step.update(state='outcome_unknown', reason='Dispatch is recorded, but a current worker lease is not linked to this attempt.')
        elif linked and all(a['validation_outcome'] == 'usable' and a['spending_state'] == 'settled' for a in linked):
            step.update(state='suggestions_ready', reason='Recorded validation found usable proposals for these attempts.')
        elif any(a['status'] == 'drafted' for a in linked):
            step.update(state='outcome_unknown', reason='Generated output is recorded; exact usable-proposal evidence is separate.')
        elif linked and all(a['status'] in ('refused', 'rejected_before_dispatch', 'provider_limit_exceeded') for a in linked):
            step.update(state='stopped', reason='Recorded attempts were refused or blocked before completion.')
        elif linked and all(a['status'] in ('empty_response', 'unusable_response', 'settlement_failed_or_breached') for a in linked):
            step.update(state='failed', reason='Recorded attempts did not produce a usable result.')
    reviews = []
    for receipt in receipts:
        review = _object(receipt.get('review_json'))
        saved_steps = review.get('steps')
        # Preserve receipt order, independent of history ordering and model names.
        reviews.append({key: receipt.get(key) for key in ('operation_id', 'proposal_sha256', 'created_at')} | {
            'verdict': review.get('verdict'),
            'steps': [{key: item.get(key) for key in ('attempt_id', 'purpose', 'provider', 'model', 'verdict', 'reason')}
                      for item in saved_steps if isinstance(item, dict)] if isinstance(saved_steps, list) else []})
    graph = dict(contract_version='remediation-run-graph.v1',
                 coverage='partial' if ambiguous else 'complete', chain_version=chain.get('version'),
                 steps=steps, attempts=attempts, review_receipts=reviews, edges=edges,
                 note='All retained attempts are included. Time order does not establish causality. Missing historical generation positions remain unavailable.')
    if not steps and not attempts and not reviews:
        graph['coverage'] = 'unavailable'
    graph['revision'] = hashlib.sha256(json.dumps(graph, sort_keys=True).encode()).hexdigest()[:20]
    return graph
