"""Owner-scoped, bounded records of actual model outputs; never a model caller.

Records share the durable spending identity. Only a successfully retained draft
whose reservation is settled can be replayed; absent history never permits a
second purchase. Prompts and credentials are deliberately not retained here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import re

from ai_spending_budget import BudgetLedger, AttemptConflict, _identifier

MAX_OUTPUT_BYTES = 128 * 1024
SCHEMA = (
    """CREATE TABLE IF NOT EXISTS ai_attempt_history (
        owner_id TEXT NOT NULL, scan_id TEXT NOT NULL, run_id TEXT NOT NULL,
        operation_id TEXT NOT NULL, attempt_id TEXT NOT NULL, file TEXT NOT NULL,
        input_sha256 TEXT NOT NULL, model TEXT NOT NULL, provider TEXT NOT NULL,
        purpose TEXT NOT NULL, status TEXT NOT NULL, result_json TEXT,
        output_sha256 TEXT, output_retention TEXT NOT NULL, reason TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        PRIMARY KEY(owner_id,run_id,attempt_id),
        FOREIGN KEY(owner_id,run_id) REFERENCES ai_spending_budgets(owner_id,run_id))""",
    "CREATE INDEX IF NOT EXISTS idx_ai_attempt_history_run ON ai_attempt_history(owner_id,scan_id,run_id,operation_id)",
    """CREATE TABLE IF NOT EXISTS ai_attempt_trace_links (
        owner_id TEXT NOT NULL,run_id TEXT NOT NULL,attempt_id TEXT NOT NULL,trace_call_id TEXT NOT NULL,
        PRIMARY KEY(owner_id,run_id,trace_call_id),
        FOREIGN KEY(owner_id,run_id,attempt_id) REFERENCES ai_attempt_history(owner_id,run_id,attempt_id))""",
)
PURPOSES = frozenset({'draft', 'fallback', 'review', 'final_review'})
STATUSES = frozenset({'drafted', 'unusable_response', 'empty_response', 'refused',
                     'usage_unknown', 'rejected_before_dispatch', 'settlement_failed_or_breached',
                     'provider_limit_exceeded', 'accepted', 'revision_requested', 'unable_to_judge'})
RESULT_KEYS = frozenset({'text', 'response_issue', 'cost_usd', 'call_id', 'model',
                         'provider', 'zone', 'prompt_tokens', 'completion_tokens', 'bounds_exceeded'})


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError('SHA-256 digest required')
    return value


def _result(value):
    if value is None:
        return None, None, 'unavailable'
    if not isinstance(value, dict):
        raise ValueError('result must be an object')
    retained = {key: value[key] for key in RESULT_KEYS if key in value}
    output = retained.get('text')
    if output is not None and not isinstance(output, str):
        raise ValueError('output must be text')
    digest = sha256(output.encode('utf-8')).hexdigest() if output is not None else None
    retention = 'full' if output is not None else 'unavailable'
    if output is not None and len(output.encode('utf-8')) > MAX_OUTPUT_BYTES:
        retained['text'] = None
        retention = 'omitted_size_limit'
    encoded = json.dumps(retained, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    # Never allow metadata to smuggle unbounded/provider-private payloads in.
    if len(encoded.encode('utf-8')) > MAX_OUTPUT_BYTES + 8192:
        raise ValueError('result metadata exceeds retention limit')
    return encoded, digest, retention


class AttemptHistory:
    def __init__(self, db):
        self.db = db
        self.ledger = BudgetLedger(db)

    def init_schema(self):
        self.ledger._standalone()
        with self.db.cursor() as cur:
            for statement in SCHEMA:
                self.db.execute(cur, statement)

    def begin(self, owner_id, scan_id, run_id, operation_id, attempt_id, *,
              file, input_sha256, model, provider, purpose='draft'):
        for value in (owner_id, scan_id, run_id, operation_id, attempt_id, model, provider):
            _identifier(value)
        if not isinstance(file, str) or not file or len(file) > 4096:
            raise ValueError('bounded source file identity required')
        _hash(input_sha256)
        if purpose not in PURPOSES:
            raise ValueError('unsupported attempt purpose')
        now = datetime.now(timezone.utc).isoformat()
        identity = dict(scan_id=scan_id, operation_id=operation_id, file=file,
                        input_sha256=input_sha256, model=model, provider=provider, purpose=purpose)
        with self.ledger._locked(owner_id, run_id) as (cur, _budget):
            self.db.execute(cur, """INSERT INTO ai_attempt_history
                (owner_id,scan_id,run_id,operation_id,attempt_id,file,input_sha256,model,provider,
                 purpose,status,output_retention,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'started','unavailable',%s,%s)
                ON CONFLICT(owner_id,run_id,attempt_id) DO NOTHING""",
                (owner_id,scan_id,run_id,operation_id,attempt_id,file,input_sha256,model,provider,purpose,now,now))
            self.db.execute(cur, 'SELECT * FROM ai_attempt_history WHERE owner_id=%s AND run_id=%s AND attempt_id=%s',
                            (owner_id,run_id,attempt_id))
            row = self.db.fetchone(cur)
            if any(row[key] != value for key, value in identity.items()):
                raise AttemptConflict('attempt history identity is immutable')
        return self._decode(row)

    def finish(self, owner_id, scan_id, run_id, attempt_id, *, status, result=None, reason=None):
        for value in (scan_id, attempt_id):
            _identifier(value)
        if status not in STATUSES:
            raise ValueError('unsupported terminal history status')
        if reason is not None and (not isinstance(reason, str) or len(reason) > 512):
            raise ValueError('bounded reason required')
        encoded, digest, retention = _result(result)
        with self.ledger._locked(owner_id, run_id) as (cur, _budget):
            self.db.execute(cur, 'SELECT * FROM ai_attempt_history WHERE owner_id=%s AND scan_id=%s AND run_id=%s AND attempt_id=%s',
                            (owner_id,scan_id,run_id,attempt_id))
            row = self.db.fetchone(cur)
            if row is None:
                raise AttemptConflict('attempt history does not exist in this scope')
            if result is not None and (result.get('model') != row['model'] or result.get('provider') != row['provider']):
                raise AttemptConflict('recorded model identity differs from the actual result')
            values = dict(status=status,result_json=encoded,output_sha256=digest,output_retention=retention,reason=reason)
            if row['status'] != 'started':
                if any(row[key] != value for key,value in values.items()):
                    raise AttemptConflict('completed attempt output is immutable')
                return self._decode(row)
            self.db.execute(cur, """UPDATE ai_attempt_history SET status=%s,result_json=%s,output_sha256=%s,
                output_retention=%s,reason=%s,updated_at=%s WHERE owner_id=%s AND scan_id=%s AND run_id=%s AND attempt_id=%s""",
                (status,encoded,digest,retention,reason,datetime.now(timezone.utc).isoformat(),owner_id,scan_id,run_id,attempt_id))
            row.update(values)
        return self._decode(row)

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        result = dict(row)
        result['result'] = json.loads(result.pop('result_json') or 'null')
        return result

    def list_run(self, owner_id, scan_id, run_id, *, limit=1000):
        for value in (owner_id,scan_id,run_id):
            _identifier(value)
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise ValueError('limit must be between 1 and 10000')
        with self.db.cursor() as cur:
            self.db.execute(cur, """SELECT h.*,a.state AS spending_state,a.actual_cost_units
                FROM ai_attempt_history h LEFT JOIN ai_spending_attempts a
                ON a.owner_id=h.owner_id AND a.run_id=h.run_id AND a.attempt_id=h.attempt_id
                WHERE h.owner_id=%s AND h.scan_id=%s AND h.run_id=%s
                ORDER BY h.created_at,h.attempt_id LIMIT %s""", (owner_id,scan_id,run_id,limit))
            rows = [self._decode(row) for row in self.db.fetchall(cur)]
            return self._with_traces(cur, owner_id, run_id, rows)

    def list_operation(self, owner_id, scan_id, run_id, operation_id, *, file=None):
        for value in (owner_id,scan_id,run_id,operation_id):
            _identifier(value)
        with self.db.cursor() as cur:
            self.db.execute(cur, """SELECT h.*,a.state AS spending_state,a.actual_cost_units
                FROM ai_attempt_history h LEFT JOIN ai_spending_attempts a
                ON a.owner_id=h.owner_id AND a.run_id=h.run_id AND a.attempt_id=h.attempt_id
                WHERE h.owner_id=%s AND h.scan_id=%s AND h.run_id=%s AND h.operation_id=%s
                ORDER BY h.created_at,h.attempt_id LIMIT 100""", (owner_id,scan_id,run_id,operation_id))
            rows = [self._decode(row) for row in self.db.fetchall(cur) if file is None or row['file'] == file]
            return self._with_traces(cur, owner_id, run_id, rows)

    def _with_traces(self, cur, owner_id, run_id, rows):
        if not rows:
            return rows
        self.db.execute(cur, 'SELECT attempt_id,trace_call_id FROM ai_attempt_trace_links WHERE owner_id=%s AND run_id=%s',
                        (owner_id,run_id))
        links = self.db.fetchall(cur)
        for row in rows:
            row['trace_call_ids'] = sorted(link['trace_call_id'] for link in links if link['attempt_id'] == row['attempt_id'])
            row['trace_call_id'] = row['trace_call_ids'][0] if row['trace_call_ids'] else None
        return rows

    def bind_trace(self, owner_id, scan_id, run_id, operation_id, trace_call_id, *, file=None, output_sha256=None):
        """Bind the trace emitted for this exact output; retries may emit new traces.

        No time/file-based discovery. Conflicting or ambiguous outputs are never
        attributed. Caller must supply the actual trace id it just persisted.
        """
        _identifier(trace_call_id)
        if output_sha256 is not None:
            _hash(output_sha256)
        with self.ledger._locked(owner_id, run_id) as (cur, _budget):
            self.db.execute(cur, """SELECT h.* FROM ai_attempt_history h JOIN ai_spending_attempts a
                ON a.owner_id=h.owner_id AND a.run_id=h.run_id AND a.attempt_id=h.attempt_id
                WHERE h.owner_id=%s AND h.scan_id=%s AND h.run_id=%s AND h.operation_id=%s
                AND h.status='drafted' AND a.state='settled'""", (owner_id,scan_id,run_id,operation_id))
            rows = [row for row in self.db.fetchall(cur)
                    if (file is None or row['file'] == file)
                    and (output_sha256 is None or row['output_sha256'] == output_sha256)]
            if len(rows) != 1:
                return None
            attempt = rows[0]['attempt_id']
            self.db.execute(cur, """INSERT INTO ai_attempt_trace_links(owner_id,run_id,attempt_id,trace_call_id)
                VALUES(%s,%s,%s,%s) ON CONFLICT(owner_id,run_id,trace_call_id) DO NOTHING""",
                (owner_id,run_id,attempt,trace_call_id))
            self.db.execute(cur, 'SELECT attempt_id FROM ai_attempt_trace_links WHERE owner_id=%s AND run_id=%s AND trace_call_id=%s',
                            (owner_id,run_id,trace_call_id))
            if self.db.fetchone(cur)['attempt_id'] != attempt:
                raise AttemptConflict('trace already belongs to another attempt')
            return attempt
