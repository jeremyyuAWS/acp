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
    def read(*args, **kw):
        if not kw.get('original'):
            return candidate
        calls.append((args, kw))
        return source
    monkeypatch.setattr(blob, 'download_report_evidence', read)
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
    assert calls == [(('owner', 'scan', 'file.pdf'), {'checksum': 'source-cache-key', 'original': True, 'max_bytes': evidence.MAX_BYTES})]


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


def test_writer_locators_in_durable_notes_locate_pages_without_guessing_ids():
    assert evidence.page_numbers([{'note': 'approved by a reviewer · pdf:fig:3:0'},
        {'locator': 'pdf:field:2:12'}, {'pages': [4, False, '5']},
        {'locator': 'pdf:field:?:98'}, {'locator': 'xref:66'}]) == [2, 3, 4]
    assert evidence.evidence_location({'note': 'reviewer · pdf:fig:3:0'}) == 'pdf:fig:3:0'
    assert '#pdf-evidence-page-3' in evidence.evidence_links({'note': 'pdf:fig:3:0'})


def field_pdf():
    stream = io.BytesIO()
    doc = canvas.Canvas(stream)
    doc.drawString(72, 720, 'Patient name')
    doc.acroForm.textfield(name='patient', x=72, y=680, width=160, height=24)
    doc.showPage()
    doc.save()
    return stream.getvalue()


def test_exact_field_crop_reads_real_accessible_name_and_geometry():
    import pikepdf
    source = field_pdf()
    with pikepdf.open(io.BytesIO(source)) as document:
        document.Root.AcroForm.Fields[0]['/TU'] = 'Patient name'
        output = io.BytesIO()
        document.save(output)
    candidate = output.getvalue()
    crops = evidence.field_crops(source, candidate, [{'locator': 'pdf:field:1:0'}])
    assert len(crops) == 1
    assert crops[0][2:] == (None, 'Patient name')
    from PIL import Image
    image = Image.open(io.BytesIO(crops[0][1][0]))
    assert image.width < 300 and image.height < 100
    with pikepdf.open(io.BytesIO(candidate)) as document:
        document.Root.AcroForm.Fields[0]['/Rect'] = pikepdf.Array([72, 600, 232, 624])
        output = io.BytesIO()
        document.save(output)
    assert evidence.field_crops(source, output.getvalue(), [{'locator': 'pdf:field:1:0'}]) == []


def test_standalone_pdf_keeps_valid_internal_navigation_only():
    from release_reports import _page
    from release_report_pdf import render_report_pdf
    output = render_report_pdf(_page('Navigation', '<p><a href="#pdf-evidence-page-2">Page 2 evidence</a> <a href="#missing">Missing target</a></p><h2 id="pdf-evidence-page-2">Page 2</h2>'))
    reader = PdfReader(io.BytesIO(output))
    annotations = [a.get_object() for page in reader.pages for a in page.get('/Annots', [])]
    assert any(a.get('/Dest') == 'pdf-evidence-page-2' for a in annotations)
    assert not any(a.get('/Dest') == 'missing' for a in annotations)


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
    assert len(doc.pages) == 1


def test_real_store_change_report_wires_exact_release_evidence(isolated_store, monkeypatch):
    from release_reports import build_release_report_sources
    import blob
    store = isolated_store
    source, candidate = pdf(), pdf(title='Accessible title')
    store.init_scan_run('scan', 'sharepoint', 1, '2026-09-11T10:00:00Z', 'rubric', 'hash', owner='owner', status='completed')
    release = store.ensure_release_execution('scan', 'owner', 'sharepoint', 1)
    store.record_release_document(release['id'], 'owner', {'file': 'file.pdf', 'status': 'published', 'published_url': 'https://example.com/corrected.pdf', 'artifact_digest': 'sha256:' + sha256(candidate).hexdigest(), 'corrected_checksum': 'provider-specific-not-sha256'})
    store.record_remediation_diffs('scan', 'file.pdf', [{'rule_id': 'SC_2_4_2', 'before': '', 'after': 'Accessible title', 'note': 'reviewer · pdf:fig:1:0'}])
    monkeypatch.setattr(blob, 'download_report_evidence', lambda *args, **kw: source if kw.get('original') else candidate)
    assets = build_release_report_sources(store, 'scan', 'owner', release['id'])
    changes = next(a['content'].decode() for a in assets if a['name'].startswith('changes-'))
    checklist = next(a['content'].decode() for a in assets if a['name'].startswith('checklist-'))
    assert 'Released corrected copy' in changes and 'Visual appearance unchanged' in changes
    assert 'Released file receipt' in changes and 'https://example.com/corrected.pdf' in changes
    assert 'pdf:fig:1:0' in changes and 'href="#pdf-evidence-page-1"' in changes
    assert 'shortened by evidence storage limits' in changes
    assert '1 verified-process change records' in changes
    assert 'Released corrected copy' not in checklist


@pytest.mark.parametrize('available', [True, False])
def test_change_navigation_only_targets_rendered_page_sections(isolated_store, monkeypatch, available):
    from release_reports import build_release_report_sources
    store = isolated_store
    store.init_scan_run('nav', 'sharepoint', 1, '2026-09-11T10:00:00Z', 'rubric', 'hash', owner='owner', status='completed')
    release = store.ensure_release_execution('nav', 'owner', 'sharepoint', 1)
    store.record_release_document(release['id'], 'owner', {'file': 'file.pdf', 'status': 'published'})
    store.record_remediation_diffs('nav', 'file.pdf', [
        {'rule_id': 'SC_1_1_1', 'before': '', 'after': 'Description', 'note': f'pdf:fig:{page}:0'}
        for page in range(1, 5)])
    calls = []
    def visual(*args):
        calls.append(args)
        return ''.join(f'<section id="pdf-evidence-page-{page}">Page {page}</section>' for page in range(1, 4)) if available else '<p>Page images unavailable</p>'
    monkeypatch.setattr(evidence, 'build_visual_evidence', visual)
    assets = build_release_report_sources(store, 'nav', 'owner', release['id'])
    report = next(a['content'].decode() for a in assets if a['name'].startswith('changes-'))
    assert len(calls) == 1
    assert ('href="#pdf-evidence-page-1"' in report) is available
    assert 'href="#pdf-evidence-page-4"' not in report
    if not available:
        assert 'href="#pdf-evidence-page-' not in report
    assert 'pdf:fig:4:0' in report  # Location remains useful without an image link.


def test_oversized_download_rejected_before_hash_or_render(monkeypatch):
    build, _ = setup(monkeypatch, pdf(), b'oversized', 'sha256:' + '0' * 64)
    monkeypatch.setattr(evidence, 'MAX_BYTES', 4)
    monkeypatch.setattr(evidence, 'sha256', lambda *a: pytest.fail('oversized candidate must not be hashed'))
    assert 'corrected PDF exceeds' in build()


def test_blob_evidence_requests_bounded_owner_scoped_range(monkeypatch):
    import blob
    calls = []
    def client(**identity):
        def download(**kwargs):
            calls.append((identity, kwargs))
            return SimpleNamespace(readall=lambda: b'x' * kwargs['length'])
        return SimpleNamespace(download_blob=download)
    monkeypatch.setattr(blob, '_service_client', lambda: SimpleNamespace(get_blob_client=client))
    assert len(blob.download_report_evidence('owner', 'scan', 'file.pdf', max_bytes=4)) == 5
    assert calls[0][0] == {'container': blob._CONTAINER, 'blob': blob._blob_path('owner', 'scan', 'file.pdf')}
    assert calls[0][1]['offset'] == 0 and calls[0][1]['length'] == 5
    blob.download_report_evidence('owner', 'scan', 'file.pdf', original=True, checksum='cached', max_bytes=4)
    assert calls[1][0] == {'container': blob._SOURCES_CONTAINER, 'blob': blob._source_key('owner', 'scan', 'file.pdf', 'cached')}
