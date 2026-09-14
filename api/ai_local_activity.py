"""Explicit local request telemetry; no spending attempts, approvals or validation.

ai_calls lacks owner/execution identity, and managed trace links require a paid
attempt. Local-only calls need this separate producer-authenticated metadata link.
Legacy calls stay unbound; filenames and timestamps never infer an execution.
"""
import json
from datetime import datetime, timezone

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS ai_local_call_execution_links (
        trace_call_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, run_id TEXT NOT NULL,
        linked_at TEXT NOT NULL,
        FOREIGN KEY(trace_call_id) REFERENCES ai_calls(id) ON DELETE CASCADE,
        FOREIGN KEY(owner_id,run_id) REFERENCES ai_spending_run_policies(owner_id,run_id) ON DELETE CASCADE)""",
    "CREATE INDEX IF NOT EXISTS idx_ai_local_call_execution_run ON ai_local_call_execution_links(owner_id,run_id)",
)


def bind_local_call(store, context, trace_call_id):
    from ai_run_policy import RunContext, optional_current_run_context
    if (type(context) is not RunContext or optional_current_run_context() is not context
            or not context.local_drafting or not context.file
            or context.ledger.db is not store._db):
        return False
    db = store._db
    with db.cursor() as cur:
        db.execute(cur, """SELECT c.provider,c.zone,c.cost_usd,p.policy_json
            FROM ai_calls c JOIN ai_spending_run_policies p ON p.scan_id=c.scan_id
            JOIN stage_executions e ON e.execution_id=p.run_id AND e.scan_id=p.scan_id AND e.owner_email=p.owner_id
            JOIN scan_runs s ON s.id=p.scan_id AND s.owner_email=p.owner_id
            WHERE c.id=%s AND c.scan_id=%s AND c.file=%s
                AND p.owner_id=%s AND p.run_id=%s AND e.stage='remediate'""",
            (trace_call_id, context.scan_id, context.file, context.owner_id, context.run_id))
        row = db.fetchone(cur)
        if (not row or row['provider'] != 'ollama' or row['zone'] != 'local'
                or row['cost_usd'] != 0 or json.loads(row['policy_json']) != dict(context.policy)):
            return False
        db.execute(cur, """INSERT INTO ai_local_call_execution_links(trace_call_id,owner_id,run_id,linked_at)
            VALUES(%s,%s,%s,%s) ON CONFLICT(trace_call_id) DO NOTHING""",
            (trace_call_id, context.owner_id, context.run_id, datetime.now(timezone.utc).isoformat()))
        db.execute(cur, 'SELECT owner_id,run_id FROM ai_local_call_execution_links WHERE trace_call_id=%s', (trace_call_id,))
        if db.fetchone(cur) != {'owner_id': context.owner_id, 'run_id': context.run_id}:
            raise ValueError('Local call already belongs to another execution')
    return True


MAX_RECORDS = 1000


def read_local_activity(db, owner, scan_id, run_id):
    """Called only after the metrics route authenticates the exact execution.

    Requests include recorded unsuccessful requests. Response success is not
    semantic validation or verification of a repaired document.
    """
    from ollama_runtime import safe_timings
    with db.cursor() as cur:
        db.execute(cur, """SELECT c.id,c.provider,c.model,c.zone,c.cost_usd,c.ok,c.latency_ms,c.timing
            FROM ai_local_call_execution_links l JOIN ai_calls c ON c.id=l.trace_call_id
            WHERE l.owner_id=%s AND l.run_id=%s AND c.scan_id=%s
                AND c.provider='ollama' AND c.zone='local' AND c.cost_usd=0
            ORDER BY c.ts DESC,c.id DESC LIMIT %s""", (owner,run_id,scan_id,MAX_RECORDS+1))
        records = db.fetchall(cur)
    models = {}
    for row in records[:MAX_RECORDS]:
        if not row.get('id') or not row.get('model'):
            continue
        item = models.setdefault(row['model'], {'model':row['model'], 'requests':0,
            'successful_responses':0, 'unsuccessful_requests':0, 'outcome_unavailable':0,
            'latencies':[], 'timings':{}})
        item['requests'] += 1
        if row.get('ok') == 1:
            item['successful_responses'] += 1
        elif row.get('ok') == 0:
            item['unsuccessful_requests'] += 1
        else:
            item['outcome_unavailable'] += 1
        latency = row.get('latency_ms')
        if type(latency) in (int,float) and 0 <= latency <= 2**63-1:
            item['latencies'].append(latency)
        try:
            measured = safe_timings(json.loads(row.get('timing') or '{}'))
        except (TypeError,ValueError):
            measured = {}
        for field, value in measured.items():
            item['timings'].setdefault(field,[]).append(value)
    rows = []
    for item in models.values():
        latencies = item.pop('latencies')
        item['average_request_ms'] = sum(latencies)/len(latencies) if latencies else None
        item['measured_requests'] = len(latencies)
        item['timings'] = {field:{'average':sum(values)/len(values),'measured_requests':len(values)}
                          for field,values in item['timings'].items()}
        rows.append(item)
    return {'contract_version':'local-ai-activity.v1', 'complete':len(records)<=MAX_RECORDS,
        'record_limit':MAX_RECORDS, 'rows':sorted(rows,key=lambda r:(-r['requests'],r['model'])),
        'basis':'Recorded local requests linked by their authenticated producer. A successful response is not a verified repair; unlinked legacy calls and in-flight requests are excluded.'}
