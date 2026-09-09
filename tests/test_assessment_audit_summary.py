"""The sealed assessment is unchanged when remediation replaces live traces."""
from test_workflow_stage_completion import _scan, _execution, _hold


def test_assessment_manifest_preserves_counts_after_remediation(isolated_store):
    store = isolated_store
    _scan(store)
    with store._db.cursor() as cur:
        store._db.execute(cur,
            "INSERT INTO scan_rule_traces(scan_id,file,rule_id,outcome,finding_count) "
            "VALUES(%s,'a.docx','1.1.1','FAIL',920)", ('stage-scan',))
        # Another file outside this execution must not inflate its audit result.
        store._db.execute(cur,
            "INSERT INTO scan_rule_traces(scan_id,file,rule_id,outcome,finding_count) "
            "VALUES(%s,'other.docx','1.1.1','FAIL',5)", ('stage-scan',))
    batch = _execution(store)
    for job in batch['job_ids']:
        claim = _hold(store, job)
        store._start_stage_attempt(store.get_job(job))
        store.publish_worker_stage_event(job, claim['worker_id'], claim['attempt'], 'attempt.started')
        assert store.complete_job(job, **claim)
    before = store.stage_execution_snapshot(batch['batch_id'])
    assert before['assessment_summary']['findings_recorded'] == 920
    with store._db.cursor() as cur:
        store._db.execute(cur, "UPDATE scan_rule_traces SET outcome='PASS',finding_count=0 "
                          "WHERE scan_id=%s", ('stage-scan',))
    assert store.live_findings_count('stage-scan') == 0
    after = store.stage_execution_snapshot(batch['batch_id'])
    assert after['assessment_summary'] == before['assessment_summary']
    assert after['domain_reconciliation'] == before['domain_reconciliation']
    assert store.seal_stage_if_ready(batch['batch_id'])['manifest_id'] == before['output_manifest_id']


def test_remediation_partition_uses_independent_assessment_baseline(isolated_store, monkeypatch):
    store = isolated_store
    _scan(store)
    with store._db.cursor() as cur:
        store._db.execute(cur, "INSERT INTO scan_rule_traces(scan_id,file,rule_id,outcome,finding_count) "
                          "VALUES(%s,'a.docx','1.1.1','FAIL',2)", ('stage-scan',))
    batch = _execution(store)
    for job in batch['job_ids']:
        claim = _hold(store, job)
        store._start_stage_attempt(store.get_job(job))
        store.publish_worker_stage_event(job, claim['worker_id'], claim['attempt'], 'attempt.started')
        assert store.complete_job(job, **claim)
    sealed = store.stage_execution_snapshot(batch['batch_id'])['output_manifest_id']
    remediate = store.enqueue_stage_batch('stage-scan', 'remediate', 'remediate_file',
        [{'file': 'a.docx'}], snapshot_id=sealed, request_fingerprint='rem-request',
        input_manifest_id=sealed)
    rid = remediate['batch_id']
    rows = store.seed_finding_dispositions('stage-scan', rid)
    for i, row in enumerate(rows):
        store.transition_finding_disposition('stage-scan', rid, row['finding_id'],
            'resolved_verified', expected_revision=0, event_id=f'resolved-{i}')
    with store._db.cursor() as cur:
        store._db.execute(cur, "UPDATE scan_rule_traces SET outcome='PASS',finding_count=0 "
                          "WHERE scan_id=%s", ('stage-scan',))
    import remediation_capability
    monkeypatch.setitem(remediation_capability.REMEDIATION['docx'], '1.1.1', 'auto')
    final = store.finding_reconciliation('stage-scan', rid)
    assert final['original_assessment'] == [{'file': 'a.docx', 'rule_id': '1.1.1',
                                              'finding_count': 2, 'fix_mode': 'assisted'}]
    assert final['assessed'] == final['resolved_verified'] == 2
    assert final['exact'] is True
    with store._db.cursor() as cur:
        store._db.execute(cur, "DELETE FROM finding_disposition WHERE scan_id=%s AND batch_id=%s "
                          "AND finding_id=%s", ('stage-scan', rid, rows[0]['finding_id']))
    partial = store.finding_reconciliation('stage-scan', rid)
    assert partial['assessed'] == 2
    assert partial['exact'] is False
