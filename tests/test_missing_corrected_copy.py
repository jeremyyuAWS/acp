import hashlib
import io
from types import SimpleNamespace

import pikepdf
import pytest

import blob
from missing_corrected_copy import GENERIC, MAX_SOURCE_BYTES, explanation, project_documents


def pdf_bytes(tagged=False):
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page()
    if tagged:
        pdf.Root.StructTreeRoot = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
    stream = io.BytesIO()
    pdf.save(stream)
    return stream.getvalue()


def diagnose(monkeypatch, data, *, file='file.pdf', checksum=None, items=None):
    calls = []
    def read(owner, sid, name, **kwargs):
        calls.append((owner, sid, name, kwargs))
        return data
    monkeypatch.setattr(blob, 'download_report_evidence', read)
    store = SimpleNamespace(list_hitl_queue=lambda **kwargs: items if items is not None else [
        dict(file=file, rule_id='1.3.1', status='pending')])
    record = dict(checksum=checksum if checksum is not None else hashlib.sha256(data or b'').hexdigest())
    return explanation(store, 'scan', 'owner', file, record), calls


def test_existing_untagged_pdf_is_actionable_and_cache_only(monkeypatch):
    message, calls = diagnose(monkeypatch, pdf_bytes())
    assert 'no accessibility tag tree' in message
    assert 'document reconstruction' in message
    assert 'explicitly approve a new' in message
    assert 'original is unchanged' in message
    assert len(calls) == 1 and calls[0][:3] == ('owner', 'scan', 'file.pdf')
    assert calls[0][3]['original'] is True and calls[0][3]['max_bytes'] == MAX_SOURCE_BYTES


@pytest.mark.parametrize('data', [None, b'not a PDF', b'x' * (MAX_SOURCE_BYTES + 1)],
                         ids=['missing', 'unreadable', 'oversized'])
def test_unavailable_corrupt_or_oversized_evidence_is_not_misdiagnosed(monkeypatch, data):
    assert diagnose(monkeypatch, data)[0] == GENERIC


def test_tagged_pdf_cannot_be_classified_as_unsupported_untagged(monkeypatch):
    assert diagnose(monkeypatch, pdf_bytes(tagged=True))[0] == GENERIC


def test_source_checksum_mismatch_cannot_supply_diagnosis(monkeypatch):
    assert diagnose(monkeypatch, pdf_bytes(), checksum='0' * 64)[0] == GENERIC


@pytest.mark.parametrize('items', [[], [dict(file='file.pdf', rule_id='1.3.1', status='resolved')],
    [dict(file='file.pdf', rule_id='1.3.1', status='pending', superseded=True)],
    [dict(file='different.pdf', rule_id='1.3.1', status='pending')]])
def test_no_current_structure_obligation_does_not_read_source(monkeypatch, items):
    message, calls = diagnose(monkeypatch, pdf_bytes(), items=items)
    assert message == GENERIC and calls == []


def test_non_pdf_does_not_read_source(monkeypatch):
    message, calls = diagnose(monkeypatch, b'office', file='file.docx')
    assert message == GENERIC and calls == []


def test_historical_failed_document_projection_is_owner_bound_and_nonmutating(monkeypatch):
    import missing_corrected_copy
    old = dict(file='file.pdf', status='failed', failure_category='no_corrected_copy',
               explanation='Frozen original explanation')
    published = dict(file='published.pdf', status='published', failure_category=None)
    calls = []
    def records(sid, **kwargs):
        calls.append((sid, kwargs))
        return {'file.pdf': {'checksum': 'source'}}
    monkeypatch.setattr(missing_corrected_copy, 'explanation', lambda *args: 'Repair PDF; approve new plan.')
    store = SimpleNamespace(get_file_records=records)
    result = project_documents(store, 'scan', 'owner', [old, published])
    assert calls == [('scan', dict(owner='owner', files=['file.pdf']))]
    assert result[0]['recovery_explanation'] == 'Repair PDF; approve new plan.'
    assert result[0]['explanation'] == 'Frozen original explanation'
    assert 'recovery_explanation' not in old and result[1] == published


def test_historical_unknown_or_cross_owner_record_does_not_guess(monkeypatch):
    old = dict(file='file.pdf', status='failed', failure_category='no_corrected_copy')
    store = SimpleNamespace(get_file_records=lambda *args, **kwargs: {})
    assert project_documents(store, 'scan', 'other-owner', [old]) == [old]


def test_new_corrected_artifact_does_not_inherit_old_unsupported_diagnosis(monkeypatch):
    import missing_corrected_copy
    old = dict(file='file.pdf', status='failed', failure_category='no_corrected_copy')
    store = SimpleNamespace(get_file_records=lambda *args, **kwargs: {'file.pdf':
        dict(remediated_at='new-time', corrected_sha256='a' * 64)})
    monkeypatch.setattr(missing_corrected_copy, 'explanation', lambda *args: pytest.fail('Must not diagnose old source'))
    assert project_documents(store, 'scan', 'owner', [old]) == [old]


def test_release_get_projects_history_without_changing_store_snapshot(monkeypatch):
    import core
    import missing_corrected_copy
    from routes import scans
    docs = [dict(file='file.pdf', status='failed', failure_category='no_corrected_copy', explanation='saved')]
    status = dict(id='release', folder_name='folder', created_at='time', status='attention',
                  documents_total=1, published=0, failed=1, remaining=0, roots=[], documents=docs)
    store = SimpleNamespace(get_scan=lambda sid, owner: {'id': sid} if owner == 'owner' else None,
                            release_for_scan=lambda sid, owner: status,
                            get_file_records=lambda sid, **kwargs: {'file.pdf': {'checksum': 'source'}})
    monkeypatch.setattr(core, 'store', store)
    monkeypatch.setattr(missing_corrected_copy, 'explanation', lambda *args: 'Tagged replacement needed; approve new plan.')
    result = scans.get_release_status('scan', SimpleNamespace(state=SimpleNamespace(user_email='owner')))
    assert result['documents'][0]['recovery_explanation'].startswith('Tagged replacement')
    assert result['documents'][0]['status'] == 'failed'
    assert status['documents'] == docs and 'recovery_explanation' not in docs[0]
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as denied:
        scans.get_release_status('scan', SimpleNamespace(state=SimpleNamespace(user_email='different')))
    assert denied.value.status_code == 404
