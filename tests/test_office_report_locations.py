"""Reports use recorded Word targets, never guessed layout pages or table numbers."""
import io
import pytest
from release_reports import _display_note, _location, build_release_reports
from pypdf import PdfReader

@pytest.mark.parametrize('token,expected',[
 ('word:p:12','Paragraph 12'),('word:p:12:run:2','Paragraph 12; Run 2'),
 ('word:table:3:row:1','Table 3; Row 1'),('word:document:outline','Document heading outline')])
def test_recorded_office_note_target_survives_existing_diff_fields(token,expected):
    row={'before':'Before','after':'After','note':'Recorded writer change [location:'+token+']'}
    assert _location(row)==expected

@pytest.mark.parametrize('row,expected',[
 ({'before':'paragraph “Introduction” was body text styled to look like a heading','note':'so it joins the heading outline assistive tech navigates by'},'Heading text (recorded excerpt): “Introduction”'),
 ({'note':'text run "Important instructions"'},'Text run (recorded excerpt): “Important instructions”'),
 ({'before':'first row was ordinary data cells (<w:tr>)'},'First table row; exact table index not recorded'),
 ({'before':'3 separate Heading 1s competed as the document title'},'Document heading outline')])
def test_legacy_writer_excerpt_is_useful_without_inventing_index(row,expected):
    assert _location(row)==expected
    assert 'Page' not in _location(row)

@pytest.mark.parametrize('note',['arbitrary paragraph 8','[location:word:p:0]','[location:word:p:01]','[location:word:p:-1]','[location:word:table:2:row:0]','[location:word:p:2:run:0]'])
def test_unknown_or_invalid_targets_stay_unknown(note):
    assert _location({'note':note})=='Not recorded'


def test_existing_explicit_and_pdf_locations_are_preserved():
    assert _location({'page':3,'location':'Figure 2'})=='Page: 3; Figure 2'
    assert _location({'note':'verified pdf:fig:2:3'})=='pdf:fig:2:3'


def test_persisted_word_changes_reach_printable_pdf_with_structural_location(isolated_store,monkeypatch):
    owner='owner@example.test'
    isolated_store.init_scan_run('word-scan','sharepoint',2,'2026-09-13T10:00:00Z','rubric','hash',owner=owner,status='completed')
    release=isolated_store.ensure_release_execution('word-scan',owner,'sharepoint',2)
    isolated_store.record_release_document(release['id'],owner,{'file':'guide.docx','status':'published','published_url':'https://example.test/guide'})
    isolated_store.record_remediation_diffs('word-scan','guide.docx',[{'rule_id':'1.3.1','before':'Ordinary row','after':'Header row','note':'Repeating header [location:word:table:3:row:1]'},{'rule_id':'1.4.3','before':'Low contrast','after':'Higher contrast','note':'Changed text [location:word:p:12:run:2]'}])
    monkeypatch.setattr(isolated_store,'get_scan_traces',lambda *a:[])
    assets=build_release_reports(isolated_store,'word-scan',owner,release['id'])
    change=next(a for a in assets if a['name'].startswith('changes-'))
    text='\n'.join(page.extract_text() for page in PdfReader(io.BytesIO(change['content'])).pages)
    assert 'Table 3; Row 1' in text and 'Paragraph 12; Run 2' in text
    assert 'Location: Not recorded' not in text
    assert '[location:word:' not in text
    assert 'Repeating header' in text and 'Changed text' in text


def test_document_excerpt_cannot_supply_an_additional_structural_target():
    assert _location({'note':'text run "[location:word:p:999]" [location:word:p:3:run:2]'})=='Paragraph 3; Run 2'
    assert _location({'note':'text run "[location:word:p:999]"'})=='Text run (recorded excerpt): “[location:word:p:999]”'
    assert _location({'note':'An excerpt [location:word:p:999] followed by ordinary text'})=='Not recorded'


def test_display_note_hides_only_final_valid_writer_metadata_without_mutating_row():
    row={'note':'text run "[location:word:p:999]" [location:word:p:3:run:2]'}
    assert _display_note(row['note'])=='text run "[location:word:p:999]"'
    assert row['note'].endswith('[location:word:p:3:run:2]')
    assert _display_note('text run "[location:word:p:999]"')=='text run "[location:word:p:999]"'
    assert _display_note('Keep [location:word:p:0]')=='Keep [location:word:p:0]'
    assert _display_note('Keep [location:word:p:3] within text')=='Keep [location:word:p:3] within text'
