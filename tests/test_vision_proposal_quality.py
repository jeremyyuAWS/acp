"""Observable draft failures must not receive automatic writing credit."""
import ai
import ocr
import pytest

INSTRUCTIONS = ' '.join(f'{i}. Connect the controller and check the hose before operating the cold therapy device.' for i in range(1, 7))


def test_complete_recovered_instructions_are_not_truncated(monkeypatch):
    monkeypatch.setattr(ocr, 'ocr_text', lambda _: INSTRUCTIONS)
    monkeypatch.setattr(ai, '_vision_generate', lambda *a, **kw: pytest.fail('OCR transcription requires no model'))
    result = ai.describe_image_structured(b'image', allow_transcription=True)
    assert result['alt'] == INSTRUCTIONS
    assert '6. Connect' in result['alt']
    assert result['grounded'] is True


@pytest.mark.parametrize('caption,reason', [
    ('I cannot provide instructions for medical equipment.', 'provider_refusal'),
    ('I’m sorry, but I can’t describe this image.', 'provider_refusal'),
    ("I'm sorry, but I cannot provide a description.", 'provider_refusal'),
    ('Sorry, I cannot describe this image.', 'provider_refusal'),
    ("Sorry, I can't describe this image.", 'provider_refusal'),
    ('As an AI language model, I cannot view images.', 'provider_refusal'),
    ('Connect the controller and then…', 'incomplete_description'),
    ('Connect the controller and then...', 'incomplete_description'),
])
def test_unusable_drafts_are_blocked_even_with_ocr_grounding(monkeypatch, caption, reason):
    monkeypatch.setattr(ocr, 'ocr_text', lambda _: 'Controller Hose')
    monkeypatch.setattr(ai, '_vision_generate', lambda *a, **kw: caption)
    result = ai.describe_image_structured(b'image')
    assert result['alt'] == caption
    assert result['grounded'] is False
    assert result['automatic_write_blocked'] is True
    assert result['reason_code'] == reason


@pytest.mark.parametrize('caption', ['Medication schedule table.', 'Mova.io logo.', 'A warning label reading “Do not disconnect”.'])
def test_short_or_negated_content_is_not_a_refusal(monkeypatch, caption):
    monkeypatch.setattr(ocr, 'ocr_text', lambda _: 'Controller Hose')
    monkeypatch.setattr(ai, '_vision_generate', lambda *a, **kw: caption)
    result = ai.describe_image_structured(b'image')
    assert result['grounded'] is True
    assert not result.get('automatic_write_blocked')


@pytest.mark.parametrize('caption', ['I cannot describe this image.', 'Connect the hose and then…'])
@pytest.mark.parametrize('validate_policy', [False, True])
def test_office_writer_preserves_bytes_and_routes_only_bad_draft_to_review(tmp_path, monkeypatch, caption, validate_policy):
    import zipfile
    from pathlib import Path
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image
    import core
    import remediate_office
    from ai_standing_approval import eligible_item
    from types import SimpleNamespace
    monkeypatch.setattr(ocr, 'ocr_text', lambda _: 'Controller Hose')
    monkeypatch.setattr(ai, '_vision_generate', lambda *a, **kw: caption)
    monkeypatch.setattr(core.store, 'get_auto_apply_validated', lambda: validate_policy)
    monkeypatch.setattr(ai, '_ALT_VALIDATOR_MODEL', 'independent-validator')
    monkeypatch.setattr(ai, 'validate_alt_text', lambda *a, **kw: pytest.fail('Bad draft must not gain consensus credit'))
    source = tmp_path / 'fixture.xlsx'
    workbook = Workbook()
    image = Path(__file__).parent / 'fixtures/vision/labeled_bar_chart.png'
    workbook.active.add_image(Image(image), 'D4')
    workbook.save(source)
    original = source.read_bytes()
    with zipfile.ZipFile(source) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    before = entries.copy()
    fixes, proposals = [], []
    applied, deferred = remediate_office._fix_image_alt(entries, vision_enabled=True,
        context_file='fixture.xlsx', applied_fixes=fixes, proposals=proposals, evidence=[])
    assert applied == [] and fixes == [] and deferred == 1
    assert entries == before and source.read_bytes() == original
    assert len(proposals) == 1 and proposals[0]['proposed_value'] == caption
    assert proposals[0]['automatic_write_blocked'] is True
    assert 'provider' in proposals[0]['why_review'].lower() or 'omission' in proposals[0]['why_review']
    item = dict(id='fixture', rule_id='1.1.1', file='fixture.xlsx', status='pending',
                finding_count=1, proposals=proposals, proposal_snapshot_ids=['snapshot'], decision_version=0)
    with pytest.raises(ValueError, match='individual review'):
        eligible_item(SimpleNamespace(_selected_sc=lambda *args: True), 'owner', 'scan', 'run', item)


def test_cleaned_length_bound_cannot_receive_grounded_write_credit(monkeypatch):
    monkeypatch.setattr(ocr, 'ocr_text', lambda _: 'Controller Hose')
    cleaned = ai._clean_alt(INSTRUCTIONS)
    assert cleaned.endswith('…') and '6. Connect' not in cleaned
    monkeypatch.setattr(ai, '_vision_generate', lambda *a, **kw: cleaned)
    result = ai.describe_image_structured(b'image')
    assert result['automatic_write_blocked'] is True
    assert result['reason_code'] == 'incomplete_description'


def test_refusal_words_in_recovered_image_text_are_content(monkeypatch):
    quote = "I'm sorry, but I cannot provide a description. This is the quoted message shown on screen."
    monkeypatch.setattr(ocr, 'ocr_text', lambda _: quote)
    result = ai.describe_image_structured(b'image', allow_transcription=True)
    assert result['alt'] == quote and result['grounded'] is True
    assert not result.get('automatic_write_blocked')
