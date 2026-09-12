"""The delivered follow-up PDF is usable without returning to ACP's review queue."""
from release_reports import build_release_report_sources
from test_release_reports import OWNER, setup


def _asset(assets, prefix):
    return next(a['content'].decode() for a in assets if a['name'].startswith(prefix))


def test_follow_up_and_summary_include_the_released_version_receipt(isolated_store):
    release = setup(isolated_store)
    isolated_store.record_release_document(release, OWNER, {
        'file': 'one.pdf', 'status': 'published',
        'published_url': 'https://example.com/corrected',
        'artifact_digest': 'sha256:released-fixture',
    })
    assets = build_release_report_sources(isolated_store, 'scan', OWNER, release)
    for markup in [_asset(assets, 'checklist-one'), assets[0]['content'].decode()]:
        assert 'Document version for follow-up' in markup
        assert 'sha256:released-fixture' in markup
        assert 'not additional edits saved to that copy' in markup
        assert 'reassess' in markup
    # The existing applied-change evidence remains a distinct delivered artifact.
    assert 'Released file receipt' in _asset(assets, 'changes-one')


def test_missing_receipt_does_not_invent_a_released_identity(isolated_store):
    release = setup(isolated_store)
    assets = build_release_report_sources(isolated_store, 'scan', OWNER, release)
    assert 'Recorded released artifact identity: Not recorded' in _asset(assets, 'checklist-one')


def test_released_checklist_prints_each_target_recommendation_without_approval(isolated_store, monkeypatch):
    release = setup(isolated_store)
    isolated_store.save_file_result('scan', {
        'file': 'one.pdf', 'engine': 'pdf', 'status': 'fail', 'score': 0,
        'compliant': False, 'skipped_rules': 0, 'issues': [
            {'wcag': '1.1.1', 'ruleId': 'SC_1_1_1', 'detail': 'Missing figure description',
             'locator': 'pdf:figure:first', 'severity': 'critical'},
            {'wcag': '1.1.1', 'ruleId': 'SC_1_1_1', 'detail': 'Second image description missing',
             'locator': 'pdf:figure:second', 'severity': 'moderate'},
        ]}, '2026-09-09T10:00:00Z')
    tasks = [
        {'id': 'first', 'file': 'one.pdf', 'rule_id': '1.1.1', 'status': 'pending',
         'locator': 'pdf:figure:first', 'proposals': [
             {'locator': 'pdf:figure:first', 'value': 'Parking entrance <north>',
              'reason': 'Recorded image shows the parking entrance'}]},
        {'id': 'second', 'file': 'one.pdf', 'rule_id': '1.1.1', 'status': 'pending',
         'locator': 'pdf:figure:second', 'proposals': [
             {'locator': 'pdf:figure:second', 'value': 'Map of accessible route'}]},
        {'id': 'foreign', 'file': 'unreleased.pdf', 'rule_id': '1.1.1', 'status': 'pending',
         'proposals': [{'value': 'Foreign recommendation must stay absent'}]},
    ]
    monkeypatch.setattr(isolated_store, 'list_hitl_queue', lambda **kw: tasks)
    assets = build_release_report_sources(isolated_store, 'scan', OWNER, release)
    for markup in [_asset(assets, 'checklist-one'), assets[0]['content'].decode()]:
        assert 'Offline remediation guide' in markup
        assert 'In-app review is optional' in markup
        assert 'Parking entrance &lt;north&gt;' in markup
        assert 'Map of accessible route' in markup
        assert 'Recorded image shows the parking entrance' in markup
        assert 'Acrobat Pro' in markup
        assert 'not recorded as saved' in markup
        assert 'Human confirmation of meaning not recorded' in markup
        assert 'Foreign recommendation must stay absent' not in markup
        assert markup.count('Offline remediation guide') == 1


def test_applied_proposals_are_not_reprinted_as_unsaved_guidance(isolated_store, monkeypatch):
    release = setup(isolated_store)
    monkeypatch.setattr(isolated_store, 'list_hitl_queue', lambda **kw: [
        {'id': 'saved', 'file': 'one.pdf', 'rule_id': '1.1.1', 'status': 'approved',
         'applied': True, 'proposals': [{'value': 'Already saved AI description'}]},
    ])
    assets = build_release_report_sources(isolated_store, 'scan', OWNER, release)
    assert 'Already saved AI description' not in _asset(assets, 'checklist-one')


def test_actual_delivered_pdfs_keep_the_offline_recommendation(isolated_store, monkeypatch):
    from io import BytesIO
    from pypdf import PdfReader
    from release_reports import build_release_reports
    release = setup(isolated_store)
    monkeypatch.setattr(isolated_store, 'list_hitl_queue', lambda **kw: [
        {'id': 'offline', 'file': 'one.pdf', 'rule_id': '4.1.2', 'status': 'pending',
         'locator': 'pdf:field:patient', 'proposals': [
             {'value': 'Patient full name', 'reason': 'Describes the form field purpose'}]},
    ])
    assets = build_release_reports(isolated_store, 'scan', OWNER, release)
    for asset in [assets[0], next(a for a in assets if a['name'].startswith('checklist-one'))]:
        assert asset['content_type'] == 'application/pdf'
        text = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(asset['content'])).pages)
        assert 'Offline remediation guide' in text
        assert 'Patient full name' in text
        assert 'pdf:field:patient' in text
        assert 'Describes the form field purpose' in text
        assert 'not recorded as saved' in text
        assert 'How to fix:' in text


def test_processing_target_does_not_hide_other_same_criterion_guidance(isolated_store, monkeypatch):
    release = setup(isolated_store)
    isolated_store.save_file_result('scan', {
        'file': 'one.pdf', 'engine': 'pdf', 'status': 'fail', 'score': 0,
        'compliant': False, 'skipped_rules': 0, 'issues': [
            {'wcag': '1.1.1', 'ruleId': 'SC_1_1_1', 'severity': 'critical', 'detail': 'Pending figure needs description', 'locator': 'pdf:figure:pending'},
            {'wcag': '1.1.1', 'ruleId': 'SC_1_1_1', 'severity': 'moderate', 'detail': 'Processing figure needs description', 'locator': 'pdf:figure:processing'},
        ]}, '2026-09-09T10:00:00Z')
    monkeypatch.setattr(isolated_store, 'list_hitl_queue', lambda **kw: [
        {'id': status, 'file': 'one.pdf', 'rule_id': '1.1.1', 'status': status,
         'locator': locator, 'proposals': [{'locator': locator, 'value': value}]}
        for status, locator, value in [
            ('pending', 'pdf:figure:pending', 'Entrance sign beside the door'),
            ('processing', 'pdf:figure:processing', 'Directions to the parking garage'),
        ]])
    assets = build_release_report_sources(isolated_store, 'scan', OWNER, release)
    for markup in [_asset(assets, 'checklist-one'), assets[0]['content'].decode()]:
        assert 'Entrance sign beside the door' in markup
        assert 'Directions to the parking garage' in markup
        assert 'Pending figure needs description' in markup
        assert 'Processing figure needs description' in markup
        assert ('Processing — recommendation not recorded as saved' in markup or
                'Processing — unlinked recommendation not recorded as saved' in markup)
        assert 'not recorded as saved' in markup
        assert 'Recorded saved change' not in markup
