"""Scan-wide Assess jobs must report documents, including after queue cleanup."""
import pytest

from test_stage_integrity_equations import _scan, _execution, OWNER


@pytest.mark.parametrize("count", [1, 177])
@pytest.mark.parametrize("kind", ["scan_assess", "assess_trace"])
def test_assess_coordinator_counts_documents_not_one_job(isolated_store, count, kind):
    store = isolated_store
    sid, _ = _scan(store, 'assess-177-documents')
    store.set_scan_files(sid, count)
    execution = store.enqueue_stage_batch(
        sid, 'assess', kind, [{'scan_id': sid}], snapshot_id='assess-snapshot',
        request_fingerprint='document-count')
    with store._db.cursor() as cur:
        for index in range(count):
            store._db.execute(cur,
                "INSERT INTO file_records(scan_id,file,status) VALUES(%s,%s,'pass')",
                (sid, f'{index}.docx'))
        store._db.execute(cur,
            "UPDATE stage_work_items SET state='completed' WHERE execution_id=%s",
            (execution['batch_id'],))
    snapshot = store.stage_execution_snapshot(execution['batch_id'], owner=OWNER)
    assert snapshot['counts']['work_items']['total'] == 1
    domain = snapshot['domain_reconciliation']
    assert domain['total'] == count
    assert domain['buckets']['assessed'] == count
    assert domain['exact'] is True

    # The durable outbox retains coordinator identity after old jobs are purged.
    with store._db.cursor() as cur:
        store._db.execute(cur, "DELETE FROM jobs WHERE batch_id=%s", (execution['batch_id'],))
    assert store.stage_execution_snapshot(execution['batch_id'], owner=OWNER)[
        'domain_reconciliation'] == domain


def test_assess_partial_batch_uses_admitted_population_and_result_outcomes(isolated_store):
    store = isolated_store
    sid, _ = _scan(store, 'assess-partial-documents')
    store.add_inventory(sid, [{'file': f'{i}.docx'} for i in range(20)])
    store.set_scan_files(sid, 6)
    execution = _execution(store, sid, 'assess', [{'scan_id': sid}])
    for status in ('pass', 'error', 'skipped'):
        with store._db.cursor() as cur:
            store._db.execute(cur,
                "INSERT INTO file_records(scan_id,file,status) VALUES(%s,%s,%s)",
                (sid, f'{status}.docx', status))
    job_id = store.enqueue_job('scan_batch', {'items': [
        {'file': 'running1.docx'}, {'file': 'running2.docx'}]}, scan_id=sid)
    with store._db.cursor() as cur:
        store._db.execute(cur, "UPDATE jobs SET status='running' WHERE id=%s", (job_id,))
    domain = store.stage_execution_snapshot(execution['batch_id'], owner=OWNER)[
        'domain_reconciliation']
    assert domain['total'] == 6  # not 20 inventory files or one coordinator
    assert domain['buckets'] == dict(assessed=1, failed=1, skipped=1,
                                     processing=2, waiting=1, cancelled=0)
    assert domain['exact'] is True


def test_assess_before_admission_does_not_use_discovered_total(isolated_store):
    store = isolated_store
    sid, _ = _scan(store, 'assess-before-admission')
    store.set_scan_files(sid, 177)
    execution = _execution(store, sid, 'assess', [{'scan_id': sid}])
    domain = store.stage_execution_snapshot(execution['batch_id'], owner=OWNER)[
        'domain_reconciliation']
    assert domain['total'] is None
    assert domain['buckets']['assessed'] == 0
    store.set_scan_files(sid, 0)
    store.merge_scan_scope(sid, {'lifecycle_eligible_excluded': 177})
    domain = store.stage_execution_snapshot(execution['batch_id'], owner=OWNER)[
        'domain_reconciliation']
    assert domain['total'] == 0
    assert domain['exact'] is True
