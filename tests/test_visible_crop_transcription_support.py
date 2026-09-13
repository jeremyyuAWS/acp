"""Visible transcripts preserve diagram-review context without claiming raster clearance."""
from hashlib import sha256
import proposals
import ocr
from office_visible_image import visible_word_image
from test_office_visible_crop import _document


def test_crop_transcription_is_bound_to_visible_pixels_and_names_preservation(tmp_path, monkeypatch):
    data = _document()
    path = tmp_path / 'crop.docx'
    path.write_bytes(data)
    visible = visible_word_image(data, 'image 1')
    seen = []
    monkeypatch.setattr(ocr, 'is_available', lambda: True)
    monkeypatch.setattr(ocr, '_ocr_words', lambda *args, **kwargs: 30)
    def read(image, **kwargs):
        seen.append(image)
        return 'Visible diagram instructions only'
    monkeypatch.setattr(ocr, 'ocr_text', read)
    draft = proposals.propose_images_of_text(path, '.docx', ai_enabled=False)[0]
    assert seen == [visible['image_bytes']]
    evidence = draft['visible_crop']
    assert evidence['transcription_sha256'] == sha256(draft['proposed_value'].encode()).hexdigest()
    assert evidence['transcription_source'] == 'visible-crop-ocr-v1'
    assert evidence['visible_image_sha256'] == visible['visible_image_sha256']
    assert evidence['requires_visual_confirmation'] is True
    assert 'Keep image and describe' in draft['rationale']
    assert 'does not verify' in draft['rationale']
    assert path.read_bytes() == data
