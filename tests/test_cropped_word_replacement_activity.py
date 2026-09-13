"""An approved full-image OCR draft cannot silently remove a cropped Word picture."""
import sys

from lxml import etree as ET

from apply_office_image_replacement import (
    NS, apply_office_image_replacement, office_image_replacement_refusal,
)
from test_remediation_verified_office_image_replacement import document, mutate, TEXT, store


def cropped_document():
    def crop(root):
        fill = root.xpath('.//a:blip/..', namespaces=NS)[0]
        ET.SubElement(fill, '{' + NS['a'] + '}srcRect', t='19861')
    return mutate(document('docx'), 'word/document.xml', crop)


def test_actual_crop_refusal_distinguishes_existing_picture_from_missing_locator():
    original = cropped_document()
    assert office_image_replacement_refusal(original, 'docx', 'image 1') == (
        'cropped_image_requires_visible_transcription')
    assert office_image_replacement_refusal(original, 'docx', 'image 9') is None
    assert office_image_replacement_refusal(document('docx'), 'docx', 'image 1') is None
    assert apply_office_image_replacement(original, 'docx', {'image 1': TEXT}) == (
        original, [], ['image 1'])


def test_crop_block_explained_in_actual_approved_apply_activity(monkeypatch, store):
    import test_remediation_verified_pptx_image_of_text as lane
    import core, handlers
    monkeypatch.setattr(lane, 'FILE', 'visible-crop.docx')
    original = cropped_document()
    blob = lane._Blob(original)
    lane._seed(store, {'image 1': TEXT})
    monkeypatch.setattr(core, 'store', store)
    monkeypatch.setitem(sys.modules, 'blob', blob)
    handlers._apply_approved_values({'scan_id': lane.SID, 'file': lane.FILE}, {})
    notes = [d['detail'] for d in store.list_decisions(scan_id=lane.SID)
             if d['action'] == 'apply.unverified']
    assert len(notes) == 1
    assert "image is cropped in Word" in notes[0]
    assert "transcription of the visible crop" in notes[0]
    assert "no useful diagram content would be lost" in notes[0]
    assert "original image is kept unchanged" in notes[0]
    assert 'reach no image' not in notes[0]
    assert not blob.uploads
    assert blob.data == original
    assert store.count_unapplied_approved_values(lane.SID, lane.FILE) > 0
