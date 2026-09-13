"""Validated inline captions must survive proposal-only recovery with exact identity."""
from pathlib import Path
import ai
import core
import remediate_office


def test_validated_caption_is_recovered_with_locator_and_call_identity(tmp_path, monkeypatch):
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image
    source = tmp_path / 'picture.xlsx'
    workbook = Workbook()
    workbook.active.add_image(Image(Path(__file__).parent / 'fixtures/vision/labeled_bar_chart.png'), 'D4')
    workbook.save(source)
    original = source.read_bytes()
    monkeypatch.setattr(ai, 'vision_is_available', lambda: True)
    monkeypatch.setattr(ai, 'describe_image_structured', lambda *a, **kw: {
        'alt': 'A chart with three categories.', 'grounded': False,
        'model': 'fixture-model', 'ai_call_id': 'fixture-call', 'source': 'vision'})
    monkeypatch.setattr(core.store, 'get_auto_apply_validated', lambda: True)
    monkeypatch.setattr(ai, 'validate_alt_text', lambda *a, **kw: {'verdict': 'consistent'})
    proposals, _ = remediate_office.alt_proposals_for_office(original, 'xlsx',
        context_file='picture.xlsx', scan_id='fixture-scan', include_grounded=True)
    assert len(proposals) == 1
    assert proposals[0]['locator'].startswith('xl/drawings/drawing1.xml#')
    assert proposals[0]['model'] == 'fixture-model'
    assert proposals[0]['model_call_id'] == 'fixture-call'
    assert proposals[0]['proposed_value'] == 'A chart with three categories.'
    assert source.read_bytes() == original
