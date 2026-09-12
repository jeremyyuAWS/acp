"""Project admitted automatic checks into the inbox without changing approvals."""
import json


def annotate(store, rows, owner):
    if not owner:
        return rows
    from ai_run_approval_override import read
    from ai_standing_approval import eligible_item
    result = []
    contexts = {}
    for item in rows:
        item = {key: value for key, value in item.items() if not key.startswith('auto_approval_')}
        if item.get('status') != 'pending' or not item.get('proposals'):
            result.append(item)
            continue
        sid = item.get('scan_id')
        if sid not in contexts:
            contexts[sid] = None
            with store._db.cursor() as cur:
                store._db.execute(cur, '''SELECT execution_id FROM stage_executions
                    WHERE scan_id=%s AND owner_email=%s AND stage='remediate'
                      AND is_current=1 AND cancel_requested_at IS NULL''', (sid, owner))
                execution = store._db.fetchone(cur)
            if execution:
                run_id = execution['execution_id']
                try:
                    setting = read(store, owner, sid, run_id)
                except ValueError:
                    setting = None
                if setting and setting['enabled']:
                    with store._db.cursor() as cur:
                        store._db.execute(cur, '''SELECT payload FROM jobs WHERE scan_id=%s
                            AND type='apply_approved_values'
                            AND status IN ('queued','running','processing','retry')''', (sid,))
                        jobs = store._db.fetchall(cur)
                    for job in jobs:
                        payload = json.loads(job['payload']) if isinstance(job['payload'], str) else job['payload']
                        if (payload.get('phase') == 'approve_current_run_ai' and
                                payload.get('owner') == owner and payload.get('run_id') == run_id and
                                payload.get('source_revision') == setting['source_revision']):
                            contexts[sid] = setting
                            break
        setting = contexts[sid]
        if setting and item.get('status') == 'pending' and item.get('proposals'):
            try:
                # Database/proposal checks only. Provider freshness and saved bytes are
                # checked by the queued coordinator, never by this polling read.
                eligible_item(store, owner, sid, setting['run_id'], item)
            except ValueError:
                pass
            else:
                item = {**item, 'auto_approval_status': 'checking',
                        'auto_approval_run_id': setting['run_id'],
                        'auto_approval_source_revision': setting['source_revision']}
        result.append(item)
    return result
