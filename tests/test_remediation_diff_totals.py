"""The bounded detail page must never masquerade as the scan-wide total."""
from types import SimpleNamespace
import pytest
from fastapi import HTTPException


def seed(store):
    store.init_scan_run('s', 'local', 0, '2026-09-09T00:00:00Z', 'r', 'h', owner='owner', status='done')
    store.record_remediation_diffs('s', 'a.pptx', [{'rule_id': '2.4.6', 'before': '', 'after': str(i)} for i in range(2001)])
    store.record_remediation_diffs('s', 'b.pptx', [{'rule_id': '2.4.6', 'before': '', 'after': 'second file'}])
    store.record_remediation_diffs('other', 'not-in-scope.pptx', [{'rule_id': '2.4.6', 'after': 'other'}])


def test_page_reports_full_total_distinct_files_and_truncation(isolated_store):
    seed(isolated_store)
    page = isolated_store.remediation_diff_page('s')
    assert page['total'] == 2002 and page['documents'] == 2
    assert page['loaded'] == len(page['items']) == 2000
    assert page['complete'] is False
    assert all(row['file'] == 'a.pptx' for row in page['items'])
    assert len(isolated_store.list_remediation_diffs('s')) == 2000


def test_empty_page_is_known_complete_zero(isolated_store):
    assert isolated_store.remediation_diff_page('empty') == {'items': [], 'total': 0, 'documents': 0, 'loaded': 0, 'complete': True}


def test_route_keeps_legacy_array_and_enforces_owner_before_totals(monkeypatch, isolated_store):
    import core
    from routes.scans import scan_remediation_diffs
    seed(isolated_store)
    monkeypatch.setattr(core, 'store', isolated_store)
    request = SimpleNamespace(state=SimpleNamespace(user_email='owner'))
    assert isinstance(scan_remediation_diffs('s', request), list)
    assert scan_remediation_diffs('s', request, True)['total'] == 2002
    foreign = SimpleNamespace(state=SimpleNamespace(user_email='someone-else'))
    with pytest.raises(HTTPException) as exc:
        scan_remediation_diffs('s', foreign, True)
    assert exc.value.status_code == 404


def test_sql_route_serializes_verified_changes_without_certifying_the_file(monkeypatch, isolated_store):
    """The exact SQL-backed payload must not turn saved verified repairs into Pending."""
    import core
    from routes.scans import scan_remediation_diffs, file_remediation_diffs
    seed(isolated_store)
    monkeypatch.setattr(core, 'store', isolated_store)
    request = SimpleNamespace(state=SimpleNamespace(user_email='owner'))
    page = scan_remediation_diffs('s', request, True)
    assert page['total'] == 2002 and page['loaded'] == 2000 and not page['complete']
    assert all(row['verified'] is True for row in page['items'])
    assert all(row['verified'] is True for row in scan_remediation_diffs('s', request))
    assert all(row['verified'] is True for row in file_remediation_diffs('s', 'a.pptx', request))
    assert all('compliant' not in row and 'published' not in row for row in page['items'])
    # Current evidence is replaced on rerun and disappears on undo, not carried forever.
    isolated_store.record_remediation_diffs('s', 'a.pptx', [])
    assert file_remediation_diffs('s', 'a.pptx', request) == []
    assert scan_remediation_diffs('s', request, True)['total'] == 1
