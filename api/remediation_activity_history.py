"""Bounded recent narration from saved events, using the stream's privacy projection."""
import json

KINDS = (
    'remediate.accepted', 'remediate.fix_applied', 'remediate.verified',
    'remediate.verification_failed', 'remediate.delivered', 'remediate.delivery_failed',
    'remediate.review_requested', 'remediate.document_completed', 'scan.interrupted',
    'scan.retrying', 'remediate.delivery_retry_requested', 'remediate.delivery_retry_refused',
    'remediate.cancel_requested', 'remediate.paused', 'remediate.resumed',
    'remediate.vision_retry_pending', 'remediate.vision_retry_recovered', 'remediate.vision_retry_blocked',
)


def read_recent_activity(store, sid, owner, *, after_seq=None, limit=50):
    from routes.scans import _project_event
    if store.get_scan(sid, owner=owner) is None:
        return {'available': False, 'reason': 'scan_not_found'}
    try:
        privacy = store.remediation_filename_privacy(sid)
        paged = after_seq is not None
        cursor_clause = ' AND seq>%s' if paged else ''
        order = 'ASC' if paged else 'DESC'
        parameters = (sid, *KINDS, after_seq, limit) if paged else (sid, *KINDS, limit)
        with store._db.cursor() as cur:
            store._db.execute(cur,
                'SELECT * FROM scan_events WHERE scan_id=%s AND kind IN (' +
                ','.join(['%s'] * len(KINDS)) + ')' + cursor_clause + ' ORDER BY seq ' + order + ' LIMIT %s',
                parameters)
            rows = store._db.fetchall(cur)
        for row in rows:
            raw = row.get('detail')
            row['detail'] = json.loads(raw) if isinstance(raw, str) and raw else raw
        events = [_project_event(row, sid, privacy) for row in (rows if paged else reversed(rows))]
        result = {'available': True, 'scan_id': sid, 'events': events}
        if paged:
            result.update(count=len(events), latest_seq=events[-1]['seq'] if events else None)
        return result
    except Exception:
        return {'available': False, 'reason': 'history_unavailable'}
