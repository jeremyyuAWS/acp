"""Queue drilldowns use exact execution membership and receipt evidence."""
import pytest
import progress_queues


OWNER = 'queue-owner'
SID = 'queue-scan'


def remediation(store, *, fingerprint='fixture'):
    if not store.get_scan(SID, owner=OWNER):
        store.init_scan_run(SID, 'local', 2, '2026-09-12T00:00:00Z', 'rubric', 'hash', owner=OWNER)
        with store._db.cursor() as cur:
            for file, count in [('a.docx', 2), ('b.pdf', 1)]:
                store._db.execute(cur, "INSERT INTO scan_rule_traces(scan_id,file,rule_id,outcome,finding_count) "
                    "VALUES(%s,%s,'1.1.1','FAIL',%s)", (SID, file, count))
    return store.enqueue_stage_batch(SID, 'remediate', 'remediate_file',
        [{'file': file, 'scan_id': SID, 'owner': OWNER} for file in ['a.docx', 'b.pdf']],
        snapshot_id='assessment', request_fingerprint=fingerprint)['batch_id']


def test_unrecorded_rows_and_missing_ledger_use_exact_admission_queued_membership(isolated_store):
    store = isolated_store
    run = remediation(store)
    queue = progress_queues.read(store, run, OWNER, 'queued')
    assert queue['available'] is True
    assert queue['count'] == 3
    assert queue['files'] == [{'file': 'a.docx', 'status': 'queued', 'label': 'Queued', 'findingCount': 2},
                              {'file': 'b.pdf', 'status': 'queued', 'label': 'Queued', 'findingCount': 1}]
    with store._db.cursor() as cur:
        store._db.execute(cur, 'DELETE FROM finding_disposition WHERE scan_id=%s AND batch_id=%s', (SID, run))
    assert progress_queues.read(store, run, OWNER, 'queued')['files'] == queue['files']


def test_verified_findings_are_grouped_by_file_and_other_batch_cannot_leak(isolated_store):
    store = isolated_store
    old = remediation(store)
    rows = store.finding_disposition_drilldown(SID, old)
    for row in rows[:2]:
        store.transition_finding_disposition(SID, old, row['finding_id'], 'resolved_verified',
            expected_revision=0, event_id='verified-' + row['finding_id'],
            fix_evidence_ids=['fixture'], verified_at='2026-09-12T00:00:00Z')
    queue = progress_queues.read(store, old, OWNER, 'verified')
    assert queue['count'] == 2 and len(queue['files']) == 1
    assert queue['files'][0]['findingCount'] == 2
    with store._db.cursor() as cur:
        store._db.execute(cur, "UPDATE jobs SET status='done' WHERE batch_id=%s", (old,))
        store._db.execute(cur, "UPDATE stage_work_items SET state='completed' WHERE execution_id=%s", (old,))
    current = remediation(store, fingerprint='second')
    assert current != old
    assert progress_queues.read(store, current, OWNER, 'verified')['count'] == 0
    assert progress_queues.read(store, current, OWNER, 'queued')['count'] == 3
    with pytest.raises(PermissionError):
        progress_queues.read(store, current, 'stranger', 'queued')


def test_incomplete_or_mismatched_roster_does_not_invent_queue_membership(isolated_store):
    store = isolated_store
    run = remediation(store)
    with store._db.cursor() as cur:
        store._db.execute(cur, 'DELETE FROM finding_disposition WHERE scan_id=%s AND batch_id=%s', (SID, run))
        store._db.execute(cur, 'DELETE FROM remediation_contribution_runs WHERE run_id=%s', (run,))
    assert progress_queues.read(store, run, OWNER, 'queued')['available'] is False


def test_scan_findings_outside_execution_scope_are_not_mixed_into_queue(isolated_store):
    store = isolated_store
    original = remediation(store)
    with store._db.cursor() as cur:
        store._db.execute(cur, "UPDATE jobs SET status='done' WHERE batch_id=%s", (original,))
        store._db.execute(cur, "INSERT INTO scan_rule_traces(scan_id,file,rule_id,outcome,finding_count) "
            "VALUES(%s,'outside.docx','1.1.1','FAIL',4)", (SID,))
    run = remediation(store, fingerprint='scope-check')
    result = progress_queues.read(store, run, OWNER, 'queued')
    assert result['available'] is False
    assert result['files'] == []


def test_publication_completion_labels_preserve_verified_vs_unverified_delivery(isolated_store):
    store = isolated_store
    remediation(store)
    run = store.enqueue_stage_batch(SID, 'release', 'publish_file',
        [{'file': file, 'owner': OWNER} for file in ['published.docx', 'unverified.docx', 'waiting.pdf']],
        snapshot_id='corrected', request_fingerprint='publication')['batch_id']
    with store._db.cursor() as cur:
        store._db.execute(cur, "UPDATE stage_work_items SET state='completed' WHERE execution_id=%s "
            "AND input_id IN ('published.docx','unverified.docx')", (run,))
        store._db.execute(cur, 'SELECT input_id,work_item_id FROM stage_work_items WHERE execution_id=%s', (run,))
        ids = {row['input_id']: row['work_item_id'] for row in store._db.fetchall(cur)}
    for file, verified in [('published.docx', True), ('unverified.docx', False)]:
        store.record_side_effect_receipt(execution_id=run, work_item_id=ids[file],
            effect_type='sharepoint.publish', destination=file, content_digest=file, receipt={'verified': verified})
    published = progress_queues.read(store, run, OWNER, 'published')
    assert published['available'] is True and published['count'] == 2
    files = {row['file']: row for row in published['files']}
    assert files['published.docx']['deliveryVerified'] is True
    assert files['unverified.docx']['deliveryVerified'] is False
    assert 'check pending' in files['unverified.docx']['label'].lower()
    assert progress_queues.read(store, run, OWNER, 'attention')['count'] == 0
    with store._db.cursor() as cur:
        store._db.execute(cur, "UPDATE stage_work_items SET state='unknown' WHERE execution_id=%s AND input_id='waiting.pdf'", (run,))
    assert progress_queues.read(store, run, OWNER, 'queued')['available'] is False
