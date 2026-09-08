"""Read-only, owner-scoped presentation of durable waterfall activity.

A settled provider charge is NOT a usable suggestion. The current ledger records
attempt identity and cost, but no finding/proposal join or historical model ID.
Keep that contribution explicitly unavailable instead of deriving it from calls.
"""
import datetime as dt
import hashlib
import json
import re

_TEXT_ATTEMPT = re.compile(r'^text:([0-9a-f]{64}):([12]):([0-9]+)$')


def read_waterfall(store, owner, scan_id, batch_id):
    if store.get_scan(scan_id, owner=owner) is None:
        raise LookupError('scan not found')
    db = store._db
    # One SELECT supplies policy, costs and attempts from the same database snapshot.
    # No ledger admission, provider call, source content, prompt hash or pricing ref is exposed.
    with db.cursor() as cur:
        db.execute(cur, """SELECT p.policy_json,b.cap_units,b.currency,
            a.attempt_id,a.state,a.max_cost_units,a.actual_cost_units
            FROM ai_spending_run_policies p
            JOIN scan_runs s ON s.id=p.scan_id AND s.owner_email=p.owner_id
            JOIN stage_executions e ON e.execution_id=p.run_id AND e.scan_id=p.scan_id
                AND e.owner_email=p.owner_id AND e.stage='remediate'
            JOIN ai_spending_budgets b ON b.owner_id=p.owner_id AND b.run_id=p.run_id
            LEFT JOIN ai_spending_attempts a ON a.owner_id=p.owner_id AND a.run_id=p.run_id
            WHERE p.owner_id=%s AND p.scan_id=%s AND p.run_id=%s""",
            (owner, scan_id, batch_id))
        rows = db.fetchall(cur)
    result = {'scan_id': scan_id, 'batch_id': batch_id,
              'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(),
              'available': bool(rows), 'contribution_available': False,
              'contribution_reason': 'AI step breakdown unavailable for this run. Recorded calls are not evidence of usable suggestions.',
              'reviewer_available': False}
    if rows:
        policy = json.loads(rows[0]['policy_json'])
        stages = {tier: {'tier': tier, 'operations': 0, 'active': 0, 'settled': 0,
                         'reserved': 0, 'uncertain': 0, 'released': 0, 'breached': 0}
                  for tier in (1, 2)}
        operations = {1: set(), 2: set()}
        spent = held = unknown = other = 0
        blocked = False
        for row in rows:
            if row['attempt_id'] is None:
                continue
            state = row['state']
            if state in ('settled', 'breached'):
                spent += row['actual_cost_units']
            if state in ('reserved', 'dispatched', 'uncertain'):
                held += row['max_cost_units']
            if state == 'uncertain':
                unknown += 1
            blocked |= state in ('uncertain', 'breached')
            match = _TEXT_ATTEMPT.fullmatch(row['attempt_id'])
            if not match:
                other += 1
                continue
            tier = int(match[2])
            operations[tier].add(match[1])
            stages[tier]['active' if state == 'dispatched' else state] += 1
        for tier in stages:
            stages[tier]['operations'] = len(operations[tier])
        result.update(stages=list(stages.values()), other_attempts=other,
                      ai_enabled=policy['ai'] > 0 and rows[0]['cap_units'] > 0,
                      spending={'cap_units': rows[0]['cap_units'], 'currency': rows[0]['currency'],
                                'spent_units': spent, 'held_units': held,
                                'available_units': max(0, rows[0]['cap_units'] - spent - held),
                                'unknown_charges': unknown, 'blocked': blocked})
    result['revision'] = hashlib.sha256(json.dumps(
        {k: v for k, v in result.items() if k != 'generated_at'}, sort_keys=True).encode()).hexdigest()[:20]
    return result
