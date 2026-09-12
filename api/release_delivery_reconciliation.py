"""Read-only delivery projections; missing jobs never authorize provider replay.

A legacy queued row is not evidence that a worker is still delivering a file. Keep its
receipt unchanged, and expose interruption only after an admission grace period.
"""
import json
from datetime import datetime, timedelta, timezone

ADMISSION_GRACE = timedelta(minutes=30)
INTERRUPTED_MESSAGE = (
    'Delivery is not confirmed and no active publishing job remains. '
    'Reconnect the destination and check the saved copy and delivery receipt before retrying.'
)


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (TypeError, ValueError):
        return None


def project_delivery(release, documents, jobs, *, now=None):
    now = _timestamp(now) if now is not None else datetime.now(timezone.utc)
    owned_jobs = []
    for job in jobs:
        try:
            payload = json.loads(job['payload']) if isinstance(job.get('payload'), str) else job.get('payload')
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        if (payload.get('release_id') == release['id'] and payload.get('owner') == release['owner_email']
                and job.get('scan_id') == release['scan_id']
                and payload.get('scan_id', release['scan_id']) == release['scan_id']):
            owned_jobs.append((job, payload))
    active = {payload.get('file') for job, payload in owned_jobs if job.get('status') in {'queued', 'running'}}
    projected = []
    interrupted = 0
    for document in documents:
        row = dict(document)
        if row.get('status') in {'queued', 'running', 'publishing'} and row.get('file') not in active:
            times = [_timestamp(release.get('created_at'))]
            times += [_timestamp(job.get('updated_at') or job.get('created_at'))
                      for job, payload in owned_jobs if payload.get('file') == row.get('file')]
            known = [stamp for stamp in times if stamp is not None]
            if now is not None and known and now - max(known) >= ADMISSION_GRACE:
                row.update(status='interrupted', durable_status=document['status'],
                           failure_category='delivery_not_confirmed', explanation=INTERRUPTED_MESSAGE)
                interrupted += 1
        projected.append(row)
    total = int(release.get('documents_total') or 0)
    published = sum(row.get('status') == 'published' for row in projected)
    failed = sum(row.get('status') == 'failed' for row in projected)
    status = 'completed' if total and published == total else 'attention' if failed or interrupted else 'running'
    return {**release, 'status': status, 'documents': projected, 'interrupted': interrupted,
            'published': min(total, published), 'failed': failed,
            'remaining': max(0, total - published - failed)}
