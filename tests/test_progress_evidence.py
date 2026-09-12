"""Progress uses admission scope and real attempts, not successful remediation counts."""
import pytest
import progress_evidence


@pytest.fixture
def store(monkeypatch, tmp_path):
    import store as module
    monkeypatch.setattr(module, '_SQLITE_PATH', tmp_path / 'progress.db')
    return module.Store()


def admit(store, document_baseline=None):
    store.init_scan_run('scan', 'local', 1, '2026-09-12T00:00:00Z',
                        'rubric', 'hash', owner='owner')
    with store._db.cursor() as cur:
        for name, count in [('a.docx', 4), ('b.pdf', 2)]:
            store._db.execute(cur, "INSERT INTO scan_rule_traces(scan_id,file,rule_id,outcome,finding_count) "
                "VALUES(%s,%s,%s,'FAIL',%s)", ('scan', name, '1.1.1', count))
    return store.enqueue_stage_batch('scan', 'remediate', 'remediate_file',
        [{'file': name, 'owner': 'owner', 'scan_id': 'scan',
          'document_progress_baseline': document_baseline} for name in ['a.docx', 'b.pdf']],
        snapshot_id='assessment', request_fingerprint='progress-fixture')['batch_id']


def test_baseline_is_frozen_and_failed_attempt_counts_as_processed(store):
    run = admit(store)
    before = progress_evidence.read(store, run, owner='owner')
    assert before['progress_baseline']['findings']['queued'] == 6
    assert before['file_processing']['counts'] == {'withFindings': 2, 'processed': 0, 'remaining': 2}
    with store._db.cursor() as cur:
        store._db.execute(cur, "UPDATE scan_rule_traces SET finding_count=100 WHERE scan_id='scan'")
        store._db.execute(cur, "UPDATE stage_work_items SET state='failed',attempt=1 "
            "WHERE execution_id=%s AND input_id='a.docx'", (run,))
    after = progress_evidence.read(store, run, owner='owner')
    assert after['progress_baseline'] == before['progress_baseline']
    assert after['file_processing']['counts'] == {'withFindings': 2, 'processed': 1, 'remaining': 1}


def test_unstarted_terminal_does_not_count_and_scheduled_retry_returns_outstanding(store):
    run = admit(store)
    with store._db.cursor() as cur:
        store._db.execute(cur, "UPDATE stage_work_items SET state='skipped' WHERE execution_id=%s", (run,))
    assert progress_evidence.read(store, run)['file_processing']['counts']['processed'] == 0
    with store._db.cursor() as cur:
        store._db.execute(cur, "UPDATE stage_work_items SET state='queued',attempt=2 "
            "WHERE execution_id=%s AND input_id='a.docx'", (run,))
    evidence = progress_evidence.read(store, run)['file_processing']
    assert evidence['counts']['remaining'] == 2
    assert evidence['attempts'][0]['retryScheduled'] is True


def test_missing_or_inferred_baseline_stays_unavailable(store):
    run = admit(store)
    assert progress_evidence.read(store, run, owner='other')['progress_baseline']['available'] is False
    with store._db.cursor() as cur:
        store._db.execute(cur, "DELETE FROM remediation_contribution_runs WHERE run_id=%s", (run,))
    assert progress_evidence.read(store, run)['file_processing']['available'] is False


def test_malformed_optional_baseline_does_not_break_authoritative_snapshot(store):
    run = admit(store)
    with store._db.cursor() as cur:
        store._db.execute(cur, "UPDATE remediation_contribution_runs SET baseline_json='{' WHERE run_id=%s", (run,))
    assert progress_evidence.read(store, run)['progress_baseline']['available'] is False


def test_release_baseline_comes_from_observed_admission(store):
    admit(store)
    run = store.enqueue_stage_batch('scan', 'release', 'publish_file',
        [{'file': 'a.docx', 'owner': 'owner', 'scan_id': 'scan'}],
        snapshot_id='corrected', request_fingerprint='release-fixture')['batch_id']
    evidence = progress_evidence.read(store, run, owner='owner')['progress_baseline']
    assert evidence['publication'] == {'queued': 1, 'processing': 0, 'published': 0, 'attention': 0, 'skipped': 0}
    with store._db.cursor() as cur:
        store._db.execute(cur, "UPDATE stage_executions SET provenance='inferred' WHERE execution_id=%s", (run,))
    assert progress_evidence.read(store, run)['progress_baseline']['available'] is False


def test_fresh_document_baseline_is_saved_before_jobs_and_replay_preserves_it(store):
    scan = {'run': {'id': 'scan'}, 'files': [
        {'file': 'a.docx', 'issues': [{'rule': '1.1.1'}], 'compliant': False},
        {'file': 'b.pdf', 'issues': [{'rule': '1.1.1'}], 'compliant': False}]}
    before = progress_evidence.capture_documents(store, scan, ['a.docx', 'b.pdf'], owner='owner',
        snapshot_id='assessment', request_fingerprint='progress-fixture')
    assert before['counts'] == {'processing': 0, 'verified': 0, 'attention': 2, 'ready': 0, 'published': 0}
    run = admit(store, before)
    assert progress_evidence.read(store, run)['progress_baseline']['documents'] == before['counts']
    # The new submission sees active jobs; an exact replay nevertheless returns
    # its original start values rather than capturing the new processing state.
    assert progress_evidence.capture_documents(store, scan, ['a.docx', 'b.pdf'], owner='owner',
        snapshot_id='assessment', request_fingerprint='progress-fixture') == before


def test_previously_verified_file_without_saved_freshness_keeps_baseline_unavailable(store):
    scan = {'run': {'id': 'scan'}, 'files': [{'file': 'a.docx', 'issues': [],
        'compliant': True, 'remediated_at': '2026-09-12T00:00:00Z', 'corrected_sha256': 'f' * 64}]}
    assert progress_evidence.capture_documents(store, scan, ['a.docx'], owner='owner',
        snapshot_id='assessment', request_fingerprint='fixture') is None
