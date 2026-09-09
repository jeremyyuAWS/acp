"""Durable, owner-scoped intent for an explicitly authorized Release continuation."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone


def _decode(row):
    if row:
        row = dict(row)
        row['intent'] = json.loads(row['intent'])
        row['progress'] = json.loads(row['progress'])
        row['artifacts'] = json.loads(row['artifacts'])
    return row


def get(store, intent_id, owner, *, lock=False):
    suffix = ' FOR UPDATE' if lock and store._db.supports_skip_locked else ''
    with store._db.cursor() as cur:
        store._db.execute(cur, 'SELECT * FROM release_continuations WHERE id=%s AND owner_email=%s' + suffix,
                          (intent_id, owner))
        return _decode(store._db.fetchone(cur))


def create(store, owner, scan_id, intent):
    fingerprint = store.canonical_request_fingerprint(intent)
    intent_id = store.canonical_request_fingerprint([owner, scan_id, fingerprint])
    now = store._now()
    with store.transaction():
        if store.get_scan(scan_id, owner=owner) is None:
            raise ValueError('scan not found')
        with store._db.cursor() as cur:
            store._db.execute(cur,
                'INSERT INTO release_continuations(id,owner_email,scan_id,fingerprint,intent,progress,status,revision,created_at,updated_at) '
                "VALUES(%s,%s,%s,%s,%s,%s,'draft',0,%s,%s) ON CONFLICT(id) DO NOTHING",
                (intent_id, owner, scan_id, fingerprint, json.dumps(intent), '{}', now, now))
        return get(store, intent_id, owner)


def save(store, row, *, status, progress, schedule=False, delay=0):
    """Compare-and-swap progress and its next job in one transaction.

    Duplicate workers cannot schedule two successors. A crash before this commit leaves the
    current job retryable; after it, the successor is already durable.
    """
    with store.transaction():
        with store._db.cursor() as cur:
            store._db.execute(cur,
                'UPDATE release_continuations SET progress=%s,status=%s,revision=revision+1,updated_at=%s '
                'WHERE id=%s AND owner_email=%s AND revision=%s',
                (json.dumps(progress), status, store._now(), row['id'], row['owner_email'], row['revision']))
            if cur.rowcount != 1:
                raise ValueError('continuation changed; refresh its status')
        if schedule:
            store.enqueue_job('release_continue', {'intent_id': row['id'], 'owner': row['owner_email'],
                              'revision': row['revision'] + 1}, scan_id=row['scan_id'],
                              run_after=(datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat())
        return get(store, row['id'], row['owner_email'])


def latest(store, scan_id, owner):
    with store._db.cursor() as cur:
        store._db.execute(cur,
            "SELECT * FROM release_continuations WHERE scan_id=%s AND owner_email=%s AND status<>'draft' "
            'ORDER BY updated_at DESC LIMIT 1', (scan_id, owner))
        return _decode(store._db.fetchone(cur))


def artifact(store, intent_id, owner, file, digest):
    with store.transaction():
        row = get(store, intent_id, owner, lock=True)
        if not row or row['status'] not in {'waiting', 'publishing'}:
            raise ValueError('Release authorization is no longer active')
        artifacts = {**row['artifacts'], file: digest}
        with store._db.cursor() as cur:
            store._db.execute(cur, 'UPDATE release_continuations SET artifacts=%s WHERE id=%s AND owner_email=%s',
                              (json.dumps(artifacts), intent_id, owner))
