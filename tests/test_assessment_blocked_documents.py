"""Real malformed Office content and recorded timeouts remain distinct blocked evidence."""
import asyncio
import io
import zipfile
from types import SimpleNamespace
import pytest
import assessment_blocked as blocked


@pytest.fixture
def store(isolated_store):
    isolated_store.init_scan_run('blocked-scan', 'local', 2, '2026-09-12T00:00:00Z',
        'rubric', 'hash', owner='owner')
    return isolated_store


def save(store, name, status, issues=None, errors=None):
    store.save_file_result('blocked-scan', {'file': name, 'engine': 'office', 'status': status,
        'score': None if status == 'error' else 50, 'compliant': 0, 'skipped_rules': 1,
        'issues': issues or [], 'errors': errors or []}, '2026-09-12T00:00:00Z')


def test_real_missing_body_remains_visible_and_has_explicit_unreadable_reason(store, tmp_path):
    import scanner
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('docProps/core.xml', '<properties/>')
    (tmp_path / 'broken.docx').write_bytes(output.getvalue())
    results = {'broken.docx': {'succeeded': True, 'issues': [], 'errors': []}}
    scanner._flag_unreadable_docx(tmp_path, results)
    assert results['broken.docx']['errors']
    save(store, 'broken.docx', 'uncertain', errors=results['broken.docx']['errors'])
    blocked.record(store, 'blocked-scan', {'file': 'broken.docx', 'status': 'uncertain',
        'errors': results['broken.docx']['errors']})
    scan = store.get_scan('blocked-scan', owner='owner')
    evidence = blocked.read(store, 'blocked-scan', owner='owner', scan=scan)
    assert evidence[0]['category'] == 'unreadable'
    assert 'password-protected' in evidence[0]['reason']
    assert blocked.annotate(scan, evidence)['files'][0]['assessment_blocked'] is True
    assert blocked.read(store, 'blocked-scan', owner='stranger') == []


def test_actual_office_assessment_of_missing_main_part_blocks_remediation(store, tmp_path):
    import scanner
    from test_docx_unreadable_body import _rezip
    if not scanner.CLI_DLL.exists():
        pytest.skip('Office analyser is not built in this environment')
    (tmp_path / 'missing.docx').write_bytes(_rezip(lambda name, data:
        None if name == 'word/document.xml' else data))
    result, _ = scanner.analyse_and_assess(tmp_path, 'missing.docx')
    assert result['status'] in {'error', 'uncertain'}
    assert any('word/document.xml' in str(error) for error in result['errors'])
    store.save_file_result('blocked-scan', {'file': 'missing.docx', **result}, '2026-09-12T00:00:00Z')
    blocked.record(store, 'blocked-scan', {'file': 'missing.docx', **result})
    assert blocked.read(store, 'blocked-scan', owner='owner')[0]['category'] == 'unreadable'


def test_timeout_is_not_claimed_as_corruption_and_successful_retry_clears_it(store):
    save(store, 'slow.pdf', 'error')
    store.log_decision('system', 'scan.file_timeout', scan_id='blocked-scan', file='slow.pdf',
        detail='exceeded per-file limit 600s')
    evidence = blocked.read(store, 'blocked-scan', owner='owner')
    assert evidence[0]['category'] == 'assessment_timeout'
    save(store, 'slow.pdf', 'pass')
    assert blocked.read(store, 'blocked-scan', owner='owner') == []


def test_unknown_or_partial_assessment_is_not_inferred_corrupt(store):
    save(store, 'partial.docx', 'uncertain')
    assert blocked.read(store, 'blocked-scan', owner='owner') == []
    assert blocked.classify('discovered', ['BadZipFile: old diagnostic']) is None
    assert blocked.classify('uncertain', [{'message': 'office analyser timed out; findings incomplete'}]) is None


def test_stale_failure_evidence_cannot_label_new_attempt_corrupt(store):
    save(store, 'retry.docx', 'uncertain')
    blocked.record(store, 'blocked-scan', {'file': 'retry.docx', 'status': 'uncertain',
        'errors': [{'message': 'word/document.xml could not be read'}]},
        job={'id': 'old-job', 'attempts': 1})
    with store._db.cursor() as cur:
        store._db.execute(cur, "UPDATE file_records SET written_job='new-job',written_attempt=2 "
            "WHERE scan_id='blocked-scan' AND file='retry.docx'")
    assert blocked.read(store, 'blocked-scan', owner='owner') == []


def test_admission_retains_but_does_not_enqueue_known_assessment_failure(store, monkeypatch):
    import core
    from routes import scans
    issue = {'ruleId': 'DOCX-TITLE-001', 'wcag': '2.4.2', 'severity': 'MAJOR'}
    save(store, 'broken.docx', 'error', issues=[issue])
    save(store, 'good.docx', 'fail', issues=[issue])
    monkeypatch.setattr(core, 'store', store)
    captured = []
    monkeypatch.setattr(scans, '_sealed_stage_input', lambda *a: ('assessment', None))
    def enqueue(*args, **kwargs):
        captured.extend(args[3])
        return {'job_ids': ['job'], 'batch_id': 'fixture-batch', 'reused': True, 'requeued': 0}
    monkeypatch.setattr(scans, '_enqueue_stage_batch', enqueue)
    monkeypatch.setattr(store, 'seed_finding_dispositions', lambda *a, **k: [])
    import remediation_automation_policy
    monkeypatch.setattr(remediation_automation_policy, 'bind_run_snapshot', lambda *a, **k: None)
    async def body():
        return {}
    request = SimpleNamespace(state=SimpleNamespace(user_email='owner'), headers={}, json=body)
    result = asyncio.run(scans.remediate_scan('blocked-scan', request))
    assert [payload['file'] for payload in captured] == ['good.docx']
    assert result['assessment_blocked_files'][0]['file'] == 'broken.docx'
    assert {row['file'] for row in store.get_scan('blocked-scan', owner='owner')['files']} == {'broken.docx', 'good.docx'}
