"""Real store reports retain unresolved work without inventing publication or audit."""
import pytest
from release_reports import build_release_reports

OWNER = 'owner@example.com'


def setup(store):
    store.init_scan_run('scan', 'sharepoint', 2, '2026-09-09T10:00:00Z', 'rubric', 'hash', owner=OWNER, status='completed')
    release = store.ensure_release_execution('scan', OWNER, 'sharepoint', 2)
    for name, status in [('one.pdf', 'published'), ('two.pdf', 'failed')]:
        store.record_release_document(release['id'], OWNER, {'file': name, 'status': status, 'published_url': 'https://example.com/one' if status == 'published' else 'javascript:alert(1)', 'explanation': '<script>bad</script>'})
    return release['id']


def test_real_release_honest_outcomes_and_unknown_audit(isolated_store):
    release = setup(isolated_store)
    assets = build_release_reports(isolated_store, 'scan', OWNER, release)
    assert len(assets) == 4
    summary = assets[0]['content'].decode()
    assert 'Files published in this release</td><td>1' in summary
    assert 'Publication failures</td><td>1' in summary
    assert 'Original assessment findings (immutable, whole scan)</td><td>Not recorded' in summary
    assert 'Original findings fixed and verified</td><td>Not recorded' in summary
    assert 'https://example.com/one' in summary
    assert 'javascript:' not in summary
    assert 'not certify full accessibility compliance' in summary
    failed = next(a['content'].decode() for a in assets if a['name'].startswith('checklist-two'))
    assert 'Not published' in failed
    assert '&lt;script&gt;bad&lt;/script&gt;' in failed
    assert '<script>' not in failed


def test_owner_and_scan_scope(isolated_store):
    release = setup(isolated_store)
    with pytest.raises(KeyError):
        build_release_reports(isolated_store, 'scan', 'other@example.com', release)
    with pytest.raises(KeyError):
        build_release_reports(isolated_store, 'other-scan', OWNER, release)


def test_evidence_identity_required_and_remaining_checklist(isolated_store, monkeypatch):
    release = setup(isolated_store)
    # Use actual persisted scan/issues/diffs, with a minimal sealed execution fixture.
    isolated_store.save_file_result('scan', {'file': 'one.pdf', 'engine': 'pdf', 'status': 'fail', 'score': 0, 'compliant': False, 'skipped_rules': 0, 'issues': [{'ruleId': 'SC_1_1_1', 'wcag': '1.1.1', 'severity': 'critical', 'detail': '=Missing <alt>', 'page': 3}]}, '2026-09-09T10:00:00Z')
    isolated_store.record_remediation_diffs('scan', 'one.pdf', [{'rule_id': 'SC_2_4_2', 'before': '', 'after': 'Title'}])
    monkeypatch.setattr(isolated_store, 'canonical_stage_lineage', lambda *a, **kw: {'stages': [{'stage': 'remediate', 'execution_id': 'batch', 'input_manifest_id': 'manifest'}]})
    monkeypatch.setattr(isolated_store, 'get_stage_output_manifest', lambda *a, **kw: {'entries': [{'assessment_summary': {'findings_recorded': 2, 'finding_groups': [{'file': 'one.pdf', 'rule_id': 'SC_2_4_2', 'finding_count': 1}, {'file': 'one.pdf', 'rule_id': 'SC_1_1_1', 'finding_count': 1}]}}]})
    monkeypatch.setattr(isolated_store, 'list_finding_dispositions', lambda *a: [
        {'finding_id': 'a', 'file': 'one.pdf', 'rule_id': 'SC_2_4_2', 'disposition': 'resolved_verified', 'verified_at': '2026-09-09', 'fix_evidence_ids': ['remediation_diff:one.pdf:SC_2_4_2:0']},
        {'finding_id': 'b', 'file': 'one.pdf', 'rule_id': 'SC_1_1_1', 'disposition': 'resolved_verified', 'verified_at': '2026-09-09', 'fix_evidence_ids': ['nonexistent']},
    ])
    assets = build_release_reports(isolated_store, 'scan', OWNER, release)
    summary = assets[0]['content'].decode()
    assert 'Original findings fixed and verified</td><td>1' in summary
    assert 'Original findings not yet verified fixed</td><td>1' in summary
    checklist = next(a['content'].decode() for a in assets if a['name'].startswith('checklist-one'))
    assert '=Missing &lt;alt&gt;' in checklist
    assert '<td>3</td>' in checklist
    csv = assets[-1]['content'].decode('utf-8-sig')
    assert "'=Missing <alt>" in csv


def test_only_release_documents_and_selected_unfinished_checks(isolated_store, monkeypatch):
    release = setup(isolated_store)
    isolated_store.save_file_result('scan', {'file': 'unselected.pdf', 'engine': 'pdf', 'status': 'pass', 'score': 100, 'compliant': True, 'skipped_rules': 0}, '2026-09-09T10:00:00Z')
    monkeypatch.setattr(isolated_store, 'get_scan_traces', lambda *a: [
        {'file': 'one.pdf', 'rule_id': 'SC_1_1_1', 'outcome': 'REVIEW'},
        {'file': 'one.pdf', 'rule_id': 'SC_1_4_3', 'outcome': 'NOT_EVALUATED'},
        {'file': 'one.pdf', 'rule_id': 'SC_2_4_4', 'outcome': 'ERROR'},
    ])
    monkeypatch.setattr(isolated_store, 'get_scan_scope', lambda *a: {'1.1.1': {'pdf'}, '2.4.4': {'pdf'}})
    assets = build_release_reports(isolated_store, 'scan', OWNER, release)
    assert len(assets) == 4
    summary = assets[0]['content'].decode()
    assert 'unselected.pdf' not in summary
    assert 'Checks not completed (current recorded traces)</td><td>1' in summary
    checklist = next(a['content'].decode() for a in assets if a['name'].startswith('checklist-one'))
    assert 'Check not completed: ERROR' in checklist
    assert 'Check not completed: REVIEW' not in checklist
    assert '1.4.3' not in checklist
