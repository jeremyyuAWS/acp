"""Offline audit recommendations never imply that approval saved a repair."""
from copy import deepcopy
import pytest
from api.remediation_audit_guide import build_remediation_audit_guide, _GUIDANCE


def test_duplicate_criteria_and_lossless_tasks_keep_distinct_targets():
    files = [{'file': 'a.docx', 'issues': [
        {'wcag': 'SC_1_1_1', 'locator': 'pic:1', 'severity': 'MINOR'},
        {'ruleId': 'SC_1_1_1', 'locator': 'pic:2', 'severity': 'CRITICAL'}]}]
    tasks = [{'file': 'a.docx', 'rule_id': 'SC_1_1_1', 'status': 'approved', 'approved_value': 'not proof of a saved file',
              'proposals': [{'locator': 'pic:1', 'proposed_value': 'First', 'rationale': 'Recorded reason'},
                            {'locator': 'pic:2', 'proposed_value': 'Second'}]}]
    original = deepcopy((files, tasks))
    doc = build_remediation_audit_guide(files, facts={'audit_review_tasks': tasks})[0]
    assert doc['assessment_findings_remaining'] == 2
    assert [row['proposed_value'] for row in doc['remaining']] == ['Second', 'First']
    assert all('not recorded as saved' in row['status'] for row in doc['remaining'])
    assert (files, tasks) == original


def test_criterion_only_changes_cannot_retire_baseline_or_approve_meaning():
    files = [{'file': 'a.pdf', 'issues': [{'wcag': '1.1.1'}, {'wcag': '1.1.1'}]}]
    evidence = [{'file': 'a.pdf', 'applied': [{'sc': '1.1.1', 'validated': True, 'decision': 'approved', 'after': 'A description'}]}]
    doc = build_remediation_audit_guide(files, evidence=evidence)[0]
    assert doc['assessment_findings_remaining'] == 2
    assert 'not recorded' in doc['applied'][0]['human_status']
    assert 'not recorded' in doc['artifact']['display']
    assert 'Location not recorded' in doc['remaining'][0]['location']


@pytest.mark.parametrize('evidence_identity,stale,expected', [('new', False, 0), ('old', False, 1), ('new', True, 1), (None, False, 1)])
def test_resolution_requires_durable_finding_and_current_artifact(evidence_identity, stale, expected):
    files = [{'file': 'a.pdf', 'artifact_digest': 'new', 'issues': [{'finding_id': 'f1', 'wcag': '3.1.2'}]}]
    item = {'finding_id': 'f1', 'sc': '3.1.2', 'validated': True, 'artifact_digest': evidence_identity, 'stale': stale}
    doc = build_remediation_audit_guide(files, evidence=[{'file': 'a.pdf', 'applied': [item]}])[0]
    assert doc['assessment_findings_remaining'] == expected


def test_source_hash_is_not_saved_artifact_attestation():
    file = {'file': 'a.pdf', 'source_sha256': 'old', 'issues': [{'finding_id': 'f', 'wcag': '3.1.2'}]}
    evidence = [{'file': 'a.pdf', 'source_sha256': 'old', 'applied': [{'finding_id': 'f', 'sc': '3.1.2', 'validated': True}]}]
    assert build_remediation_audit_guide([file], evidence=evidence)[0]['assessment_findings_remaining'] == 1


def test_stale_ai_text_withheld_and_unlinked_proposal_not_a_finding():
    files = [{'file': 'a.pptx', 'artifact_digest': 'new', 'issues': [{'wcag': '1.1.1', 'slide': 2}]}]
    tasks = [{'file': 'a.pptx', 'sc': '1.1.1', 'artifact_digest': 'old', 'proposals': [{'slide': 2, 'proposed_value': 'Stale picture', 'reason': 'Stale reason'}]},
             {'file': 'other.pptx', 'sc': '1.1.1', 'proposals': [{'proposed_value': 'Private other file'}]}]
    doc = build_remediation_audit_guide(files, facts={'audit_review_tasks': tasks})[0]
    assert doc['assessment_findings_remaining'] == 1
    assert len(doc['remaining']) == 2
    assert doc['remaining'][1]['proposed_value'] is None
    assert doc['remaining'][1]['reason'] is None
    assert 'Private other' not in str(doc)


@pytest.mark.parametrize('fmt', ['docx', 'xlsx', 'pptx', 'pdf'])
def test_all_core17_criteria_have_offline_format_guidance(fmt):
    files = [{'file': 'a.' + fmt, 'issues': [{'wcag': sc, 'page': 0} for sc in _GUIDANCE]}]
    doc = build_remediation_audit_guide(files)[0]
    assert len(doc['remaining']) == 17
    assert all(row['recommendation'] and len(row['editor_steps']) == 3 for row in doc['remaining'])
    assert all('page 0' in row['location'] for row in doc['remaining'])
    assert all(row.get('proposed_value') is None for row in doc['remaining'])


def test_ambiguous_same_locator_proposals_remain_unlinked_and_json_tasks_supported():
    tasks = [{'file': 'a.xlsx', 'sc': '1.1.1', 'proposals': '[{"locator":"x", "value":"a"},{"locator":"x", "value":"b"}]'}]
    doc = build_remediation_audit_guide([{'file': 'a.xlsx', 'issues': [{'wcag': '1.1.1', 'locator': 'x'}]}], facts={'audit_review_tasks': tasks})[0]
    assert 'proposed_value' not in doc['remaining'][0]
    assert len(doc['remaining']) == 3
    assert doc['assessment_findings_remaining'] == 1


def test_legacy_stale_document_without_source_hash_withholds_text():
    evidence = [{'file': 'a.pdf', 'stale': True, 'proposed': [{'sc': '1.1.1', 'proposals': [{'locator': 'x', 'proposed_value': 'stale'}]}]}]
    doc = build_remediation_audit_guide([{'file': 'a.pdf', 'issues': [{'wcag': '1.1.1', 'locator': 'x'}]}], evidence=evidence)[0]
    assert doc['remaining'][1]['proposed_value'] is None
    assert 'Stale recommendation' in doc['remaining'][1]['status']


@pytest.mark.parametrize('value', [0, ''])
def test_queue_falsey_values_and_processing_state_preserved(value):
    tasks = [{'file': 'a.docx', 'sc': '1.1.1', 'status': 'processing', 'proposals': [{'locator': 'x', 'value': value, 'text': 'wrong fallback'}]}]
    doc = build_remediation_audit_guide([{'file': 'a.docx', 'issues': [{'wcag': '1.1.1', 'locator': 'x'}]}], facts={'audit_review_tasks': tasks})[0]
    assert doc['remaining'][0]['proposed_value'] == value
    assert doc['remaining'][0]['status'].startswith('Processing')


def test_digest_prefix_and_case_normalized_both_sides():
    digest = 'a' * 64
    file = {'file': 'a.pdf', 'artifact_digest': 'SHA256:' + digest.upper(), 'issues': [{'finding_id': 'f', 'wcag': '3.1.2'}]}
    evidence = [{'file': 'a.pdf', 'artifact_digest': digest, 'applied': [{'finding_id': 'f', 'sc': '3.1.2', 'validated': True}]}]
    assert build_remediation_audit_guide([file], evidence=evidence)[0]['assessment_findings_remaining'] == 0


def test_integer_applied_queue_excluded_and_source_locator_explicit():
    task = {'file': 'a.pdf', 'sc': '1.1.1', 'applied': 1, 'proposals': [{'source_locator': 'Figure:1', 'proposed_value': 'already saved'}]}
    doc = build_remediation_audit_guide([{'file': 'a.pdf', 'issues': []}], facts={'audit_review_tasks': [task]})[0]
    assert not doc['remaining']
    task['applied'] = False
    doc = build_remediation_audit_guide([{'file': 'a.pdf', 'issues': []}], facts={'audit_review_tasks': [task]})[0]
    assert doc['remaining'][0]['location'] == 'Figure:1'
