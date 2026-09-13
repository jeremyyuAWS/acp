"""Freeze approval intent with a compare-and-set, independently of assessment scope."""
import json
from fix_approval_policy import normalize


def freeze(store, scan_id, choice):
    choice = normalize(choice)
    with store.transaction():
        with store._db.cursor() as cur:
            store._db.execute(cur, 'SELECT scope FROM scan_runs WHERE id=%s', (scan_id,))
            row = store._db.fetchone(cur)
            if not row:
                raise ValueError('Scan no longer exists; reload before starting.')
            raw = row.get('scope')
            scope = dict(raw) if isinstance(raw, dict) else json.loads(raw or '{}')
            if not isinstance(scope, dict):
                raise ValueError('Scan scope is unavailable; reload before starting.')
            previous = scope.get('fix_approval_policy')
            if previous is not None:
                if normalize(previous) != choice:
                    raise ValueError('Approval policy is frozen for this assessment; start a new scan to change it.')
                return choice
            scope['fix_approval_policy'] = choice
            if raw is None:
                sql = 'UPDATE scan_runs SET scope=%s WHERE id=%s AND scope IS NULL'
                params = (json.dumps(scope), scan_id)
            else:
                sql = 'UPDATE scan_runs SET scope=%s WHERE id=%s AND scope=%s'
                params = (json.dumps(scope), scan_id, raw)
            store._db.execute(cur, sql, params)
            if cur.rowcount != 1:
                raise ValueError('Scan or approval policy changed; reload before starting.')
    return choice


def request_fingerprint(level, include_lifecycle_flagged, choice=None):
    fields = {'level': level, 'include_lifecycle_flagged': include_lifecycle_flagged}
    # Keep equivalent retries of pre-policy deployed executions byte-for-byte stable.
    if choice is not None:
        fields['fix_approval_policy'] = normalize(choice)
    return json.dumps(fields, sort_keys=True)
