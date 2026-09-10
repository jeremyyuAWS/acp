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


def test_deferred_assessment_seals_after_fanout_results_not_coordinator(isolated_store):
    store = isolated_store
    _scan(store)
    batch = store.enqueue_stage_batch('stage-scan', 'assess', 'scan_assess',
        [{'scan_id': 'stage-scan'}], snapshot_id='deferred', request_fingerprint='deferred')
    # The coordinator has dispatched two files but has not assessed either one.
    store.enqueue_job('scan_file', {'scan_id': 'stage-scan', 'file': 'a.docx'}, scan_id='stage-scan')
    store.enqueue_job('scan_file', {'scan_id': 'stage-scan', 'file': 'b.docx'}, scan_id='stage-scan')
    job = batch['job_ids'][0]
    claim = _hold(store, job)
    store._start_stage_attempt(store.get_job(job))
    store.publish_worker_stage_event(job, claim['worker_id'], claim['attempt'], 'attempt.started')
    assert store.complete_job(job, **claim)
    assert store.get_stage_execution(batch['batch_id'])['output_manifest_id'] is None
    with store._db.cursor() as cur:
        store._db.execute(cur, "INSERT INTO scan_rule_traces(scan_id,file,rule_id,outcome,finding_count) "
                          "VALUES(%s,'a.docx','1.1.1','FAIL',11)", ('stage-scan',))
        for file in ['a.docx', 'b.docx']:
            store._db.execute(cur, "INSERT INTO file_records(scan_id,file,status) VALUES(%s,%s,'uncertain')",
                              ('stage-scan', file))
    store.mark_assessed('stage-scan', store._now())
    summary = store.stage_execution_snapshot(batch['batch_id'])['assessment_summary']
    assert summary['findings_recorded'] == 11
    assert summary['domain_reconciliation']['buckets']['assessed'] == 2
    with store._db.cursor() as cur:
        store._db.execute(cur, "UPDATE scan_rule_traces SET outcome='PASS',finding_count=0 WHERE scan_id=%s",
                          ('stage-scan',))
    store.mark_assessed('stage-scan', store._now())
    assert store.stage_execution_snapshot(batch['batch_id'])['assessment_summary'] == summary


def test_premature_historical_audit_is_flagged_without_rewriting_manifest(isolated_store):
    import json
    store = isolated_store
    _scan(store)
    batch = _execution(store)
    for job in batch['job_ids']:
        claim = _hold(store, job)
        store._start_stage_attempt(store.get_job(job))
        store.publish_worker_stage_event(job, claim['worker_id'], claim['attempt'], 'attempt.started')
        assert store.complete_job(job, **claim)
    execution = store.get_stage_execution(batch['batch_id'])
    manifest_id = execution['output_manifest_id']
    manifest = store.get_stage_output_manifest(manifest_id)
    # Fixture reproduces the already deployed premature coordinator snapshot.
    entries = manifest['entries']
    entries[0]['assessment_summary'] = {
        'findings_recorded': 0, 'finding_groups': [],
        'domain_reconciliation': {'scope': 'current Assess scan population', 'exact': True,
                                  'buckets': {'waiting': 2, 'processing': 0}}}
    with store._db.cursor() as cur:
        store._db.execute(cur, "UPDATE stage_output_manifests SET entries=%s WHERE manifest_id=%s",
                          (json.dumps(entries), manifest_id))
    before = store.get_stage_output_manifest(manifest_id)
    summary = store.assessment_audit_summary(execution)
    assert summary['valid'] is False
    assert summary['invalid_reason'] == 'assessment_incomplete_at_capture'
    assert summary['findings_recorded'] == 0  # raw recorded evidence is preserved
    remediate = store.enqueue_stage_batch('stage-scan', 'remediate', 'remediate_file',
        [{'file': 'a.docx'}], snapshot_id=manifest_id, request_fingerprint='rem-request',
        input_manifest_id=manifest_id)
    reconciliation = store.finding_reconciliation('stage-scan', remediate['batch_id'])
    assert reconciliation['baseline_valid'] is False
    assert reconciliation['exact'] is False  # even an empty ledger cannot validate bad evidence
    assert reconciliation['original_assessment'] is None
    assert {'code': 'assessment_incomplete_at_capture'} in reconciliation['violations']
    assert store.get_stage_output_manifest(manifest_id) == before


def test_new_remediation_batch_seeds_the_same_finding_population_as_sealed_assess(isolated_store):
    """A rerun must not seed fewer identities from mutable post-fix traces."""
    store = isolated_store
    _scan(store)
    with store._db.cursor() as cur:
        store._db.execute(cur, "INSERT INTO scan_rule_traces(scan_id,file,rule_id,outcome,finding_count) "
                          "VALUES(%s,'a.docx','1.1.1','FAIL',8)", ('stage-scan',))
    assess = _execution(store)
    for job in assess['job_ids']:
        claim = _hold(store, job)
        store._start_stage_attempt(store.get_job(job))
        store.publish_worker_stage_event(job, claim['worker_id'], claim['attempt'], 'attempt.started')
        assert store.complete_job(job, **claim)
    saved = store.stage_execution_snapshot(assess['batch_id'])
    assert saved['assessment_summary']['valid'], saved['assessment_summary']
    sealed = saved['output_manifest_id']
    with store._db.cursor() as cur:
        store._db.execute(cur, "UPDATE scan_rule_traces SET finding_count=7 WHERE scan_id=%s", ('stage-scan',))
    batch = store.enqueue_stage_batch('stage-scan', 'remediate', 'remediate_file',
        [{'file': 'a.docx'}], snapshot_id=sealed, request_fingerprint='rerun-after-fix', input_manifest_id=sealed)
    rows = store.seed_finding_dispositions('stage-scan', batch['batch_id'], snapshot_id=sealed)
    assert len(rows) == 8
    for index, row in enumerate(rows):
        store.transition_finding_disposition('stage-scan', batch['batch_id'], row['finding_id'],
            'unchanged_no_fix', expected_revision=0, event_id=f'unchanged-{index}')
    reconciliation = store.finding_reconciliation('stage-scan', batch['batch_id'])
    assert reconciliation['assessed'] == 8
    assert reconciliation['accounted'] == 8
    assert reconciliation['exact'] is True
