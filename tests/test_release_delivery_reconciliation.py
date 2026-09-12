"""An orphaned legacy queue is an interruption, never a successful/replayed upload."""
import json
from release_delivery_reconciliation import project_delivery

OWNER = 'owner@example.com'
OLD = '2026-09-11T01:15:33Z'
NOW = '2026-09-12T01:15:33Z'
RELEASE = {'id': 'legacy-release', 'owner_email': OWNER, 'scan_id': 'legacy-scan',
           'source': 'drive', 'documents_total': 1, 'created_at': OLD, 'updated_at': NOW}
DOC = {'file': 'report.docx', 'status': 'queued', 'verification': None, 'artifact_digest': None}


def test_orphaned_queue_does_not_claim_processing_or_success_or_change_receipt():
    result = project_delivery(RELEASE, [DOC], [], now=NOW)
    assert result['status'] == 'attention'
    assert result['interrupted'] == 1
    assert (result['published'], result['failed'], result['remaining']) == (0, 0, 1)
    assert result['documents'][0]['status'] == 'interrupted'
    assert result['documents'][0]['durable_status'] == 'queued'
    assert result['documents'][0]['verification'] is None
    assert result['documents'][0]['artifact_digest'] is None
    assert DOC['status'] == 'queued'


def job(**extra):
    return {'scan_id': RELEASE['scan_id'], 'status': 'queued', 'created_at': OLD,
            'payload': json.dumps({'release_id': RELEASE['id'], 'owner': OWNER, 'file': DOC['file']}), **extra}


def test_real_queued_job_remains_queued_even_while_workers_are_offline():
    assert project_delivery(RELEASE, [DOC], [job()], now=NOW)['documents'][0]['status'] == 'queued'


def test_dead_or_completed_job_without_receipt_never_establishes_success():
    for status in ['dead', 'cancelled', 'completed']:
        assert project_delivery(RELEASE, [DOC], [job(status=status)], now=NOW)['interrupted'] == 1


def test_foreign_or_malformed_job_cannot_hide_orphaned_delivery():
    for candidate in [job(scan_id='foreign'), job(payload='{'), job(payload='null'),
                      job(payload=json.dumps({'release_id': RELEASE['id'], 'owner': OWNER, 'file': DOC['file'], 'scan_id': 'foreign'})),
                      job(payload=json.dumps({'release_id': 'foreign', 'owner': OWNER, 'file': DOC['file']})),
                      job(payload=json.dumps({'release_id': RELEASE['id'], 'owner': 'foreign', 'file': DOC['file']}))]:
        assert project_delivery(RELEASE, [DOC], [candidate], now=NOW)['interrupted'] == 1


def test_recent_admission_and_recent_retry_get_grace():
    assert project_delivery({**RELEASE, 'created_at': NOW}, [DOC], [], now=NOW)['interrupted'] == 0
    assert project_delivery(RELEASE, [DOC], [job(status='completed', updated_at=NOW)], now=NOW)['interrupted'] == 0


def test_published_receipts_are_untouched_even_with_dead_jobs():
    receipt = {**DOC, 'status': 'published', 'verification': 'sha256', 'artifact_digest': 'sha256:abc'}
    result = project_delivery(RELEASE, [receipt], [job(status='dead')], now=NOW)
    assert result['status'] == 'completed'
    assert result['documents'] == [receipt]
    assert result['interrupted'] == 0


def test_store_status_and_history_reconcile_without_database_or_provider_mutation(isolated_store):
    from test_release_store import _scan
    _scan(isolated_store, 'legacy-scan', OWNER)
    original_now = isolated_store._now
    isolated_store._now = lambda: OLD
    release = isolated_store.ensure_release_execution('legacy-scan', OWNER, 'drive', 1)
    isolated_store.record_release_document(release['id'], OWNER, DOC)
    isolated_store._now = lambda: NOW
    try:
        status = isolated_store.release_status(release['id'], OWNER)
        assert status['documents'][0]['status'] == 'interrupted'
        assert isolated_store.list_release_history(OWNER)[0]['status'] == 'attention'
        assert isolated_store.get_release_document(release['id'], DOC['file'], OWNER)['status'] == 'queued'
        assert isolated_store.release_status(release['id'], 'foreign') is None
        isolated_store.enqueue_job('publish_file', {'release_id': release['id'], 'owner': OWNER, 'file': DOC['file']}, scan_id='legacy-scan')
        assert isolated_store.release_status(release['id'], OWNER)['documents'][0]['status'] == 'queued'
        with isolated_store._db.cursor() as cur:
            isolated_store._db.execute(cur, 'SELECT updated_at,status FROM release_executions WHERE id=%s', (release['id'],))
            saved = isolated_store._db.fetchone(cur)
        assert saved['updated_at'] == OLD
        assert saved['status'] == 'running'
    finally:
        isolated_store._now = original_now
