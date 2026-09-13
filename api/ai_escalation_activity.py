"""Content-free narration for an admitted, frozen next-model attempt."""
import json


def emit(store, *, scan_id, owner_id, run_id, file, operation_id, position=1,
         model=None, reason_code='approved_model_fallback', status='dispatched'):
    kind = ('remediate.ai_escalation_started' if status == 'dispatched'
            else 'remediate.ai_escalation_finished')
    detail = dict(file=file, operation_id=operation_id, run_id=run_id,
                  generation_position=position, tier='fallback_' + str(position),
                  reason_code=reason_code, may_take_longer=True, status=status)
    if model:
        detail['model'] = model
    try:
        with store.transaction():
            with store._db.cursor() as cur:
                if store._db.supports_skip_locked:
                    store._db.execute(cur, 'SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                                      ('ai-activity:' + owner_id + ':' + operation_id,))
                store._db.execute(cur, 'SELECT detail FROM decision_log WHERE scan_id=%s AND file=%s AND action=%s',
                                  (scan_id, file, kind))
                if any(json.loads(row['detail']).get('operation_id') == operation_id
                       and json.loads(row['detail']).get('generation_position') == position
                       for row in store._db.fetchall(cur)):
                    return
            event = store.append_scan_event(scan_id, kind, phase='remediate', document=file,
                                             owner_email=owner_id, detail=detail)
            if event is None:
                return
            store.log_decision('system', kind, scan_id=scan_id, file=file,
                               detail=json.dumps(detail, sort_keys=True))
        from activity import record
        record(scan_id, file=file, action=('Trying the next approved model' if status == 'dispatched'
               else 'Replacement caption checked' if status == 'candidate_caption_validated'
               else 'Next-model attempt: ' + status.replace('_', ' ')),
               detail=('May take longer' if status == 'dispatched' else
                       'Saved-file verification is next' if status == 'candidate_caption_validated' else None),
               phase='remediate', force=True)
    except Exception:
        # Narration must not change model admission, billing, or artifact authority.
        pass
