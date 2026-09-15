"""A year swap passes token-presence checks; Quality-first must not auto-write it."""
from types import SimpleNamespace
from pathlib import Path
import zipfile
import pytest
import ai
import ocr
import llm_waterfall_provider
from chart_caption_review import quality_first_review

OCR = 'Revenue chart\n2024 2025\nNorth South\nUSD millions\n-10 20 30 40'
SWAPPED = 'Revenue chart: North earned USD 20 million in 2024 and USD -10 million in 2025.'


@pytest.fixture
def quality_run(monkeypatch):
    monkeypatch.setattr(llm_waterfall_provider, 'managed_context', lambda: SimpleNamespace(
        policy={'quality_first': True}, enabled=True))
    monkeypatch.setattr(ocr, 'ocr_text', lambda data: OCR)
    monkeypatch.setattr(ai, '_vision_generate', lambda *a, **kw: SWAPPED)


def test_swapped_year_caption_is_not_verified_by_matching_ocr_tokens(quality_run):
    result = ai.describe_image_structured(b'synthetic-chart', allow_transcription=False)
    assert result['alt'] == SWAPPED
    assert not result['grounded'] and result['automatic_write_blocked']
    assert result['reason_code'] == 'chart_relationships_unverified'
    assert result['chart_review']['checks'] == ['series', 'year', 'sign', 'value', 'units']
    assert result['chart_review']['status'] == 'needs_review'
    assert result['chart_review']['evidence_basis'] == 'image_ocr'
    assert 'do not verify' in result['evidence']


def test_chart_without_ocr_still_requires_review(quality_run, monkeypatch):
    monkeypatch.setattr(ocr, 'ocr_text', lambda data: '')
    result = ai.describe_image_structured(b'chart')
    assert result['chart_review']['evidence_basis'] == 'image_only'
    assert result['approval_required']


def test_uncertainty_is_not_silently_autoapplied(quality_run):
    result = quality_first_review('The label is unreadable in this diagram.')
    assert result['review_status'] == 'needs_review'
    assert result['reason_code'] == 'image_description_uncertain'
    assert result['automatic_write_blocked']


def test_existing_nonquality_flow_is_unchanged(monkeypatch):
    monkeypatch.setattr(llm_waterfall_provider, 'managed_context', lambda: None)
    assert quality_first_review(SWAPPED, ocr_text=OCR) == {}


def test_ordinary_photo_is_not_forced_into_chart_review(quality_run):
    assert quality_first_review('A doctor welcomes a patient at reception.') == {}


def test_real_office_writer_keeps_swapped_caption_as_review_proposal(quality_run, tmp_path, monkeypatch):
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image
    import core
    import remediate_office
    from release_continuation import eligibility, proposal_identity
    image = Path(__file__).parent / 'fixtures/vision/labeled_bar_chart.png'
    source = tmp_path / 'chart.xlsx'
    workbook = Workbook()
    workbook.active['A1'] = 'Do not change'
    workbook.active.add_image(Image(image), 'D4')
    workbook.save(source)
    with zipfile.ZipFile(source) as archive:
        entries = {n: archive.read(n) for n in archive.namelist()}
    before = entries.copy()
    monkeypatch.setattr(core.store, 'get_auto_apply_validated', lambda: True)
    monkeypatch.setattr(ai, 'validate_alt_text', lambda *a, **kw: pytest.fail('No extra model review'))
    proposals, fixes = [], []
    applied, deferred = remediate_office._fix_image_alt(entries, vision_enabled=True,
        context_file='chart.xlsx', proposals=proposals, applied_fixes=fixes, evidence=[])
    assert not applied and deferred == 1 and not fixes
    assert entries == before
    p = proposals[0]
    assert p['proposed_value'] == SWAPPED and p['thumb']
    assert p['review_status'] == 'needs_review' and p['automatic_write_blocked']
    assert p['chart_review']['checks'] == ['series', 'year', 'sign', 'value', 'units']
    row = dict(id='item', rule_id='1.1.1', file='chart.xlsx', status='pending',
               finding_count=1, proposals=proposals, proposal_snapshot_ids=['snapshot'], decision_version=0)
    assert 'individual review' in eligibility(row, 'chart.xlsx')
    assert proposal_identity(row)['proposals'][0]['chart_review'] == p['chart_review']


def test_prompts_warn_against_year_and_legend_swaps():
    for prompt in (ai._structured_vision_prompt('', OCR, ''), ai._vision_prompt('', '')):
        assert 'series' in prompt and 'year' in prompt and 'units' in prompt
        assert 'unclear' in prompt


def test_chart_cannot_bypass_review_through_prose_transcription(quality_run, monkeypatch):
    monkeypatch.setattr(ai, '_looks_like_an_image_of_text', lambda text: True)
    result = ai.describe_image_structured(b'chart', allow_transcription=True)
    assert result['alt'] == SWAPPED and result['automatic_write_blocked']
    assert result.get('source') != 'ocr'


def test_pdf_proposal_retains_review_metadata_even_if_validator_accepts(quality_run, monkeypatch):
    import caption_validation
    import remediate_pdf
    from test_pdf_figure_evidence import raster_pdf
    monkeypatch.setattr(caption_validation, 'validate_caption', lambda *a, **kw: {
        'approved': True, 'status': 'validated', 'canonical_caption': SWAPPED})
    pdf, figure, image = raster_pdf(size=32)
    with pdf:
        drafts = remediate_pdf._pdf_figure_drafts(pdf, ai_enabled=True, scan_id=None, file='chart.pdf')
        proposal = drafts[0][1]
        assert proposal['automatic_write_blocked'] and proposal['requires_semantic_review']
        assert proposal['review_status'] == 'needs_review'
        assert proposal['chart_review']['checks'] == ['series', 'year', 'sign', 'value', 'units']
        assert 'Needs review' in proposal['why_review']
        assert '/Alt' not in figure
