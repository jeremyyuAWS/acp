from hashlib import sha256
from types import SimpleNamespace
import io
from pypdf import PdfReader
from reportlab.pdfgen import canvas
import pytest
import pdf_release_evidence as evidence


def pdf(text='Original content', title=''):
    stream = io.BytesIO()
    doc = canvas.Canvas(stream)
    doc.drawString(72, 720, text)
    doc.setTitle(title)
    doc.save()
    return stream.getvalue()


def setup(monkeypatch, source, candidate, digest=None):
    import blob
    calls = []
    monkeypatch.setattr(blob, 'download_remediated', lambda *args: candidate)
    def read(*args, **kw):
        calls.append((args, kw))
        return source
    monkeypatch.setattr(blob, 'download_source', read)
    store = SimpleNamespace(get_file_record=lambda *args: {'checksum': 'source-cache-key'})
    outcome = {'status': 'published', 'artifact_digest': digest or 'sha256:' + sha256(candidate).hexdigest()}
    return lambda records=[{'page': 1}]: evidence.build_visual_evidence(store, 'scan', 'owner', 'file.pdf', outcome, records), calls


def test_visible_and_metadata_changes_render_real_pairs():
    source = pdf()
    metadata = pdf(title='Accessible title')
    assert evidence.render_pairs(source, metadata, [1])[0][2] is True
    visible = pdf('Corrected content')
    assert evidence.render_pairs(source, visible, [1])[0][2] is False
    assert sha256(source).digest() != sha256(metadata).digest()


def test_release_sha_not_provider_checksum_governs_images(monkeypatch):
    source, candidate = pdf(), pdf(title='New title')
    build, calls = setup(monkeypatch, source, candidate)
    html = build()
    assert 'Visual appearance unchanged' in html
    assert html.count('<img ') == 2
    assert sha256(candidate).hexdigest() in html
    assert calls == [(('owner', 'scan', 'file.pdf'), {'checksum': 'source-cache-key'})]


def test_later_candidate_never_shown_as_released(monkeypatch):
    build, calls = setup(monkeypatch, pdf(), pdf('Later version'), 'sha256:' + '0' * 64)
    html = build()
    assert 'differs from this release' in html and '<img ' not in html
    assert calls == []


def test_no_source_and_renderer_failures_keep_textual_fallback(monkeypatch):
    build, _ = setup(monkeypatch, None, pdf())
    assert 'cached original PDF is unavailable' in build()
    build, _ = setup(monkeypatch, pdf(), pdf())
    monkeypatch.setattr(evidence, 'render_pairs', lambda *args: (_ for _ in ()).throw(RuntimeError('secret')))
    html = build()
    assert 'Textual before and after evidence remains above' in html
    assert 'secret' not in html and '<img ' not in html


def test_unknown_location_is_orientation_not_fabricated_target(monkeypatch):
    build, _ = setup(monkeypatch, pdf(), pdf())
    html = build([{'locator': 'pdf:field:12'}])
    assert 'orientation preview, not a located finding' in html
    assert evidence.page_numbers([{'location': 'Page: 3'}, {'page_number': 2}, {'page': False}]) == [2, 3]


def test_oversize_or_missing_page_rejected(monkeypatch):
    monkeypatch.setattr(evidence, 'MAX_BYTES', 10)
    with pytest.raises(ValueError, match='size limit'):
        evidence.render_pairs(pdf(), pdf(), [1])
    monkeypatch.setattr(evidence, 'MAX_BYTES', 200000)
    with pytest.raises(ValueError, match='page is unavailable'):
        evidence.render_pairs(pdf(), pdf(), [2])


def test_report_pdf_embeds_pair_with_labels(monkeypatch, tmp_path):
    from release_reports import _page
    from release_report_pdf import render_report_pdf
    build, _ = setup(monkeypatch, pdf(), pdf(title='Accessible title'))
    output = render_report_pdf(_page('PDF change evidence', build()))
    (tmp_path / 'evidence.pdf').write_bytes(output)
    doc = PdfReader(io.BytesIO(output))
    text = ''.join(page.extract_text() for page in doc.pages)
    assert 'Original' in text and 'Released corrected copy' in text
    assert 'Visual appearance unchanged' in text
    assert sum(len(page.images) for page in doc.pages) >= 2


def test_real_store_change_report_wires_exact_release_evidence(isolated_store, monkeypatch):
    from release_reports import build_release_report_sources
    import blob
    store = isolated_store
    source, candidate = pdf(), pdf(title='Accessible title')
    store.init_scan_run('scan', 'sharepoint', 1, '2026-09-11T10:00:00Z', 'rubric', 'hash', owner='owner', status='completed')
    release = store.ensure_release_execution('scan', 'owner', 'sharepoint', 1)
    store.record_release_document(release['id'], 'owner', {'file': 'file.pdf', 'status': 'published', 'artifact_digest': 'sha256:' + sha256(candidate).hexdigest(), 'corrected_checksum': 'provider-specific-not-sha256'})
    store.record_remediation_diffs('scan', 'file.pdf', [{'rule_id': 'SC_2_4_2', 'before': '', 'after': 'Accessible title'}])
    monkeypatch.setattr(blob, 'download_remediated', lambda *args: candidate)
    monkeypatch.setattr(blob, 'download_source', lambda *args, **kw: source)
    assets = build_release_report_sources(store, 'scan', 'owner', release['id'])
    changes = next(a['content'].decode() for a in assets if a['name'].startswith('changes-'))
    checklist = next(a['content'].decode() for a in assets if a['name'].startswith('checklist-'))
    assert 'Released corrected copy' in changes and 'Visual appearance unchanged' in changes
    assert 'Released corrected copy' not in checklist
