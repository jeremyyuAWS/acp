"""The exact production discrepancy: a titled 50-page PDF reported Page Titled
because the bookmark rule was assigned to that unrelated criterion.
"""
from pypdf import PdfWriter
from pypdf.generic import BooleanObject, DictionaryObject, NameObject

from assessment_selection import selection
from scanner import _analyse_pdf


def document(tmp_path, *, title=True, display=True, bookmarks=False, pages=50):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    if title:
        writer.add_metadata({'/Title': 'Simulated Clinical Record 47'})
    if display:
        writer._root_object[NameObject('/ViewerPreferences')] = DictionaryObject({
            NameObject('/DisplayDocTitle'): BooleanObject(True)})
    if bookmarks:
        writer.add_outline_item('Clinical record', 0)
    path = tmp_path / 'clinical-record.pdf'
    writer.write(path)
    return path


def issues(path, scope):
    with selection(scope):
        result = _analyse_pdf(path)
    assert result['succeeded'] and not result['errors']
    return result['issues']


def test_titled_fifty_page_pdf_without_bookmarks_passes_title_checks(tmp_path):
    assert issues(document(tmp_path), {'2.4.2'}) == []


def test_bookmarks_are_a_separate_multiple_ways_advisory(tmp_path):
    findings = issues(document(tmp_path), {'2.4.5'})
    assert len(findings) == 1
    assert findings[0]['ruleId'] == 'pdf.missing-bookmarks'
    assert findings[0]['wcag'] == 'SC_2_4_5'
    assert findings[0]['severity'] == 'REVIEW'


def test_real_bookmarks_clear_navigation_advisory(tmp_path):
    assert issues(document(tmp_path, bookmarks=True), {'2.4.5'}) == []


def test_missing_title_still_fails_actual_title_check(tmp_path):
    findings = issues(document(tmp_path, title=False), {'2.4.2'})
    assert {finding['ruleId'] for finding in findings} == {'pdf.document-title'}


def test_missing_title_display_still_fails_actual_title_check(tmp_path):
    findings = issues(document(tmp_path, display=False), {'2.4.2'})
    assert {finding['ruleId'] for finding in findings} == {'pdf.display-doc-title'}


def test_short_pdf_has_no_navigation_advisory(tmp_path):
    assert issues(document(tmp_path, pages=9), {'2.4.5'}) == []
