"""Real PDF evidence boundaries for the no-copy follow-up explanation.

Only the blob boundary is replaced: documents are parsed by the shipping PDF library.
No cloud model, provider upload, or document repair is invoked.
"""
import base64
import hashlib
import io
from types import SimpleNamespace

import pikepdf
import pytest

import blob
from missing_corrected_copy import GENERIC, explanation
from source_checksum import quickxor_digest


def _pdf(*, encrypted=False):
    with pikepdf.Pdf.new() as pdf:
        for _ in range(3):
            pdf.add_blank_page()
        output = io.BytesIO()
        kwargs = {'encryption': pikepdf.Encryption(owner='fixture-owner', user='', R=6)} if encrypted else {}
        pdf.save(output, **kwargs)
        return output.getvalue()


def _store():
    return SimpleNamespace(list_hitl_queue=lambda **kwargs: [
        {'file': 'document.pdf', 'rule_id': '1.3.1', 'status': 'pending'}])


def test_readable_encrypted_pdf_does_not_claim_untagged_reconstruction(monkeypatch):
    data = _pdf(encrypted=True)
    with pikepdf.open(io.BytesIO(data)) as pdf:
        assert pdf.is_encrypted and len(pdf.pages) == 3
    monkeypatch.setattr(blob, 'download_report_evidence', lambda *args, **kwargs: data)
    result = explanation(_store(), 'scan', 'owner', 'document.pdf',
                         {'checksum': hashlib.sha256(data).hexdigest()})
    assert result == GENERIC


@pytest.mark.parametrize('algorithm', ['sha1', 'quickxor'])
def test_provider_checksum_verified_multipage_pdf_can_explain_no_copy(monkeypatch, algorithm):
    data = _pdf()
    checksum = hashlib.sha1(data).hexdigest() if algorithm == 'sha1' else base64.b64encode(quickxor_digest(data)).decode()
    calls = []
    def cached(owner, scan, file, **kwargs):
        calls.append((owner, scan, file, kwargs))
        return data
    monkeypatch.setattr(blob, 'download_report_evidence', cached)
    record = {'checksum': checksum, 'original_etag': 'source-version'}
    original_record = dict(record)
    result = explanation(_store(), 'scan', 'owner', 'document.pdf', record)
    assert 'no accessibility tag tree' in result and 'document reconstruction' in result
    assert calls[0][:3] == ('owner', 'scan', 'document.pdf')
    assert calls[0][3]['checksum'] == checksum and calls[0][3]['original'] is True
    assert record == original_record


def test_cache_outage_preserves_generic_follow_up_instead_of_guessing_corruption(monkeypatch):
    def unavailable(*args, **kwargs):
        raise TimeoutError('synthetic cache timeout')
    monkeypatch.setattr(blob, 'download_report_evidence', unavailable)
    result = explanation(_store(), 'scan', 'owner', 'document.pdf', {'checksum': 'a' * 64})
    assert result == GENERIC
    assert 'corrupt' not in result and 'tag tree' not in result
