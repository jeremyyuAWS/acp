"""Exact reviewed descriptions become selectable without deleting the cropped graphic."""
import io
import zipfile
from docx import Document
from office_visible_image import visible_word_image
from word_crop_description import write_descriptions
from test_office_visible_crop import _document


def plan(data):
    visible = visible_word_image(data, 'image 1')
    visible.pop('image_bytes')
    return {'image 1': {'description':'Reviewed diagram description\nVisible instructions',
        'visible_crop':{**visible,'selectable_description_supported':True}}}


def test_reviewed_description_is_selectable_next_to_unchanged_graphic_and_idempotent():
    original = _document()
    candidate = write_descriptions(original, plan(original))
    doc = Document(io.BytesIO(candidate))
    assert len(doc.inline_shapes) == 1
    assert doc.paragraphs[1].text == 'Reviewed diagram description\nVisible instructions'
    assert visible_word_image(candidate,'image 1') == visible_word_image(original,'image 1')
    with zipfile.ZipFile(io.BytesIO(original)) as before, zipfile.ZipFile(io.BytesIO(candidate)) as after:
        assert before.namelist() == after.namelist()
        for name in before.namelist():
            if name != 'word/document.xml':
                assert before.read(name) == after.read(name)
    assert write_descriptions(candidate, plan(original)) == candidate


def test_changed_crop_or_missing_disclosed_option_keeps_file_unchanged():
    original = _document()
    approved = plan(original)
    changed = _document('30000')
    assert write_descriptions(changed, approved) == changed
    approved['image 1']['visible_crop'].pop('selectable_description_supported')
    assert write_descriptions(original,approved) == original


def test_ambiguous_shared_graphic_is_not_changed():
    original = _document()
    shared = _document(shared=True)
    assert write_descriptions(shared, plan(original)) == shared


def test_real_ocr_still_reports_raster_text_after_reviewed_description():
    import pytest, ocr
    from lxml import etree as ET
    from test_remediation_verified_office_image_replacement import document, mutate
    from office_visible_image import NS
    if not ocr.is_available():
        pytest.skip('Tesseract required for independent verification')
    def crop(root):
        fill = root.xpath('//*[local-name()="blipFill"]')[0]
        ET.SubElement(fill, '{' + NS['a'] + '}srcRect', t='19861')
    original = mutate(document('docx'), 'word/document.xml', crop)
    before = ocr.images_of_text(original,'.docx')
    assert before
    candidate = write_descriptions(original, plan(original))
    assert candidate != original
    assert ocr.images_of_text(candidate,'.docx') == before
