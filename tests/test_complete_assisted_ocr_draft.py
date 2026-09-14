"""Live assisted DOCX drafting must use recovered content, not finding excerpts."""
from io import BytesIO
import zipfile
import pytest
from PIL import Image
from docx import Document
import ai
import ocr
import remediate_office

INSTRUCTIONS = ' '.join(f'{i}. Connect the controller and inspect the hose before operating the device.' for i in range(1, 7))


@pytest.fixture
def source(tmp_path, monkeypatch):
    raster = BytesIO()
    Image.new('RGB', (400, 400), 'white').save(raster, format='PNG')
    doc = Document()
    doc.add_picture(BytesIO(raster.getvalue()))
    path = tmp_path / 'instructions.docx'
    doc.save(path)
    monkeypatch.setattr(ocr, 'is_available', lambda: True)
    monkeypatch.setattr(ocr, 'read_image_text', lambda *a, **kw: INSTRUCTIONS)
    monkeypatch.setattr(ai, 'model_is_available', lambda: True)
    monkeypatch.setattr(ai, 'suggest_fix', lambda *a, **kw: pytest.fail('Source transcription must not call AI'))
    with zipfile.ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    return path, entries


def test_live_draft_keeps_complete_recovered_instructions_and_exact_image_locator(source):
    path, entries = source
    original = path.read_bytes()
    # The actual finding formatter deliberately bounds its display excerpt.
    findings = ocr.images_of_text(path, '.docx')
    assert len(findings) == 1 and INSTRUCTIONS not in findings[0]['detail']
    proposals = []
    count = remediate_office._draft_docx_assisted(entries, path, proposals,
        in_scope=lambda sc: sc == '1.4.5')
    assert count == 1 and len(proposals) == 1
    assert proposals[0]['proposed_value'] == INSTRUCTIONS
    assert proposals[0]['locator'] == 'image 1'
    assert proposals[0]['sc'] == '1.4.5'
    assert '6. Connect' in proposals[0]['proposed_value']
    assert path.read_bytes() == original


def test_chart_essential_exception_is_preserved(source, monkeypatch):
    path, entries = source
    chart = 'Monthly totals revenue trends North South East West Sales 100 80 60 40 20'
    monkeypatch.setattr(ocr, 'read_image_text', lambda *a, **kw: chart)
    assert ocr._looks_like_chart(chart)
    proposals = []
    count = remediate_office._draft_docx_assisted(entries, path, proposals,
        in_scope=lambda sc: sc == '1.4.5')
    assert count == 0 and proposals == []


def test_excluded_criterion_does_not_recover_or_offer_its_content(source):
    path, entries = source
    proposals = []
    assert remediate_office._draft_docx_assisted(entries, path, proposals, in_scope=lambda sc: False) == 0
    assert proposals == []


def test_unused_embedded_media_does_not_create_an_extra_draft(source):
    path, entries = source
    with zipfile.ZipFile(path, 'a') as archive:
        archive.writestr('word/media/image2.png', entries['word/media/image1.png'])
    with zipfile.ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    original = path.read_bytes()
    assert len(ocr.images_of_text(path, '.docx')) == 1
    proposals = []
    count = remediate_office._draft_docx_assisted(entries, path, proposals, in_scope=lambda sc: sc == '1.4.5')
    assert count == 1 and [p['locator'] for p in proposals] == ['image 1']
    assert path.read_bytes() == original
