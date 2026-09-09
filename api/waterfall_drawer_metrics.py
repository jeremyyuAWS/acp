"""Bounded read-only drawer charts. No prompts, outputs or filenames leave this view."""
from datetime import datetime, timedelta, timezone
import hashlib
import json

MAX_RECORDS = 1000
STAGES = frozenset(('primary', 'fallback_1', 'fallback_2', 'review', 'final_review'))


def _time(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (AttributeError, TypeError, ValueError):
        return None


def read_metrics(store, owner, scan_id, run_id, *, stage=None, provider=None, model=None):
    if stage is not None and stage not in STAGES:
        raise ValueError('unsupported chart stage')
    if any(value is not None and (not isinstance(value, str) or not value or len(value) > 256) for value in (provider, model)):
        raise ValueError('invalid model filter')
    execution = store.get_stage_execution(run_id, owner=owner) if owner else None
    if (not execution or execution.get('owner_email') != owner or execution.get('scan_id') != scan_id
            or execution.get('stage') != 'remediate' or store.get_scan(scan_id, owner=owner) is None):
        raise LookupError('remediation execution not found')
    db = store._db
    with db.cursor() as cur:
        db.execute(cur, '''SELECT h.attempt_id,h.provider,h.model,h.purpose,h.status,h.created_at,h.updated_at,h.result_json,
            a.state AS spending_state,a.actual_cost_units,a.max_cost_units FROM ai_attempt_history h
            LEFT JOIN ai_spending_attempts a ON a.owner_id=h.owner_id AND a.run_id=h.run_id AND a.attempt_id=h.attempt_id
            WHERE h.owner_id=%s AND h.scan_id=%s AND h.run_id=%s ORDER BY h.created_at DESC,h.attempt_id DESC LIMIT %s''',
            (owner, scan_id, run_id, MAX_RECORDS + 1))
        records = db.fetchall(cur)
        db.execute(cur, 'SELECT currency FROM ai_spending_budgets WHERE owner_id=%s AND run_id=%s', (owner, run_id))
        currency = (db.fetchone(cur) or {}).get('currency')
        db.execute(cur, 'SELECT COUNT(*) AS n FROM ai_spending_attempts WHERE owner_id=%s AND run_id=%s', (owner, run_id))
        ledger_count = (db.fetchone(cur) or {}).get('n', 0)
    result = aggregate_metrics(records[:MAX_RECORDS], stage=stage, provider=provider, model=model,
        now=datetime.now(timezone.utc), terminal=execution.get('state') in ('completed', 'succeeded', 'failed', 'cancelled'),
        complete=len(records) <= MAX_RECORDS, currency=currency, ledger_complete=ledger_count == len(records))
    result.update(scan_id=scan_id, run_id=run_id, batch_id=run_id)
    result['revision'] = hashlib.sha256(json.dumps({k:v for k,v in result.items() if k != 'generated_at'}, sort_keys=True).encode()).hexdigest()[:20]
    return result


def aggregate_metrics(records, *, stage=None, provider=None, model=None, now, terminal=False,
                      complete=True, currency=None, ledger_complete=True):
    selected, missing_lineage = [], False
    for row in records:
        try:
            result = json.loads(row.get('result_json') or '{}')
            result = result if isinstance(result, dict) else {}
        except (TypeError, ValueError):
            result = {}
        lineage = result.get('execution') or {}
        lineage = lineage if isinstance(lineage, dict) else {}
        position = lineage.get('generation_position')
        step = lineage.get('step_id')
        valid = step in ('primary', 'fallback_1', 'fallback_2') and type(position) is int and position == ('primary', 'fallback_1', 'fallback_2').index(step)
        key = step if valid else row.get('purpose') if row.get('purpose') in ('review', 'final_review') else None
        if key is None:
            missing_lineage = True
        if stage and key != stage or provider and row.get('provider') != provider or model and row.get('model') != model:
            continue
        selected.append({**row, 'validation': result.get('validation_outcome')})
    covered = complete and not (stage and missing_lineage)
    completions = [r for r in selected if r.get('status') != 'started' and r.get('spending_state') == 'settled']
    dated = [(r, _time(r.get('updated_at'))) for r in completions]
    timestamps_complete = all(t is not None for _, t in dated)
    dated = [(r, t) for r, t in dated if t is not None]
    end = max((t for _, t in dated), default=now) if terminal else now
    start = end - timedelta(minutes=10)
    starts = [_time(r.get('created_at')) for r in selected]
    valid_starts = [t for t in starts if t is not None]
    observed = max(0, (end - min(valid_starts)).total_seconds()) if valid_starts else 0
    rate_available = covered and timestamps_complete and observed >= 60
    points = []
    for i in range(10):
        lower, upper = start + timedelta(minutes=i), start + timedelta(minutes=i+1)
        value = sum(lower < t <= upper for _, t in dated) if covered and timestamps_complete and valid_starts and lower >= min(valid_starts) else None
        points.append({'timestamp': upper.isoformat(), 'value': value})
    costs, unknown_cost = {}, False
    for row in selected:
        if row.get('spending_state') != 'settled':
            continue
        amount = row.get('actual_cost_units')
        if type(amount) is not int or amount < 0 or not row.get('provider') or not row.get('model'):
            unknown_cost = True
            continue
        key = (row['provider'], row['model'])
        costs[key] = costs.get(key, 0) + amount
    spend_complete = covered and ledger_complete and not unknown_cost and currency is not None
    cost_rows = [{'id': p + ':' + m, 'label': p + ' · ' + m, 'value': n / 1_000_000} for (p,m),n in sorted(costs.items(), key=lambda item: -item[1])]
    if len(cost_rows) > 6:
        cost_rows = cost_rows[:5] + [{'id':'other','label':'Other','value':sum(r['value'] for r in cost_rows[5:])}]
    usable = sum(r.get('validation') == 'usable' for r in completions)
    no_output = sum(r.get('validation') != 'usable' and r.get('status') in ('empty_response','unusable_response','refused') for r in completions)
    unknown = len(completions) - usable - sum(r.get('validation') != 'usable' and r.get('status') in ('empty_response','unusable_response','refused') for r in completions)
    reason = None if covered else 'Complete stage attribution is unavailable for this retained record window.'
    return {'contract_version':'waterfall-drawer-metrics.v1', 'generated_at':now.isoformat(),
        'scope':{'stage':stage,'provider':provider,'model':model}, 'complete':covered, 'record_limit':MAX_RECORDS,
        'mode':'recorded' if terminal else 'live',
        'pace':{'value':sum(end-timedelta(seconds=60) < t <= end for _,t in dated) if rate_available else None,
                'unit':'recorded completions/min','windowLabel':'Final recorded 60 seconds' if terminal else 'Last 60 seconds',
                'observedSeconds':observed,'reason':reason or (None if rate_available else 'Collecting pace data; a complete 60-second observation is required.')},
        'trend':{'unit':'recorded completions/min','windowLabel':'Final recorded 10 minutes' if terminal else 'Last 10 minutes',
                 'bucketLabel':'60-second buckets','timeZone':'UTC','points':points,'reason':reason},
        'contribution':{'title':'Recorded attempt outcomes','unit':'attempts','basis':'Settled attempts; usable validation is not a count of proposals or findings.',
            'rows': [{'id':'usable','label':'Validated usable', 'value':usable}, {'id':'no_output','label':'No usable output','value':no_output},
                     {'id':'unknown','label':'Validation unavailable','value':unknown}] if covered else [], 'reason':reason},
        'spend':{'unit':currency,'complete':spend_complete,'partition':True,'total':sum(r['value'] for r in cost_rows) if spend_complete else None,
                 'rows':cost_rows,'reason':None if spend_complete else 'Complete model-linked settled charges are unavailable. Reservations are excluded.'}}
