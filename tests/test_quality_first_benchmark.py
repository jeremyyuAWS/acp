"""The model is not called here: validate fixture provenance and catch bad grading."""
import copy
from hashlib import sha256
from pathlib import Path
import json
import zipfile

import pikepdf
import pytest
from PIL import Image
from evals.quality_first_benchmark import CASES, SCHEMA, VERSION, evaluate, prepare, score

HASH = 'a' * 64


def answer(case):
    # Test-only perfect answer: never shipped as a fake evaluated model result.
    return {'case_id': case['id'], 'source_sha256': HASH,
            'decision': case['decision'], 'description': 'Test-only grounded answer or review explanation.',
            'facts': copy.deepcopy(case.get('facts', [])),
            'header_row': case.get('header_row', []), 'transcript': case.get('transcript', ''),
            'reading_order': case.get('reading_order', [])}


def result(case, row):
    return score(case, row, source_sha256=HASH)


def test_each_positive_control_passes_without_claiming_semantic_certification():
    for case in CASES:
        r = result(case, answer(case))
        assert r['probe_pass'] and r['semantic_review_required']


def test_swapping_years_preserves_all_numbers_but_fails_association_check():
    case = CASES[0]; row = answer(case)
    # Reproduce the observed chart error: South 2024/2025 values are reversed.
    row['facts'][2]['series'], row['facts'][3]['series'] = '2025', '2024'
    assert not result(case, row)['probe_pass']
    assert 'fact_associations_values_or_units_mismatch' in result(case, row)['issues']


@pytest.mark.parametrize('field,value', [('value', '12'), ('unit', 'thousand EUR'), ('label', 'East')])
def test_sign_units_and_region_errors_are_distinct_from_presence_of_numbers(field, value):
    row = answer(CASES[0]); row['facts'][0][field] = value
    assert not result(CASES[0], row)['probe_pass']


def test_percent_alias_and_decimal_spelling_are_not_false_model_failures():
    row = answer(CASES[0])
    for fact in row['facts']:
        fact['unit'] = '%'
        fact['value'] = fact['value'].replace('-', '\u2212') + '.0'
    assert result(CASES[0], row)['probe_pass']


@pytest.mark.parametrize('value', ['NaN', 'Infinity', True, None])
def test_non_numeric_or_non_finite_values_never_pass(value):
    row = answer(CASES[0]); row['facts'][0]['value'] = value
    assert not result(CASES[0], row)['probe_pass']


def test_duplicate_facts_cannot_hide_a_conflicting_value():
    row = answer(CASES[0]); row['facts'].append({**row['facts'][0], 'value': '999'})
    assert 'invalid_facts' in result(CASES[0], row)['issues']


def test_column_swap_and_reading_order_interleave_are_rejected():
    row = answer(CASES[1]); row['header_row'] = ['Region', '2025', '2024']
    assert 'header_row_mismatch' in result(CASES[1], row)['issues']
    row = answer(CASES[3]); row['reading_order'] = ['title', 'left-1', 'right-1', 'left-2', 'right-2']
    assert 'reading_order_mismatch' in result(CASES[3], row)['issues']


def test_scanned_decimal_drift_and_invented_ambiguous_chart_are_rejected():
    row = answer(CASES[2]); row['transcript'] = row['transcript'].replace('125.50', '12550')
    assert 'transcript_mismatch' in result(CASES[2], row)['issues']
    row = answer(CASES[4]); row['decision'] = 'propose'
    assert 'incorrect_decision' in result(CASES[4], row)['issues']


def test_response_identity_bound_to_exact_source():
    row = answer(CASES[0]); row['source_sha256'] = 'b' * 64
    assert 'source_identity_mismatch' in result(CASES[0], row)['issues']


def test_prepare_real_sources_no_gold_answers_in_requests(tmp_path):
    manifest = prepare(tmp_path)
    assert manifest['benchmark_version'] == VERSION
    for req in manifest['requests']:
        source = tmp_path / req['source_file']
        assert sha256(source.read_bytes()).hexdigest() == req['source_sha256']
        assert 'facts' not in req  # schema only, never rubric values
        assert '-12' not in req['prompt'] and '125.50' not in req['prompt']
    with Image.open(tmp_path / 'chart-series-sign.png') as image:
        assert image.size == (1000, 560)
    with zipfile.ZipFile(tmp_path / 'table-header-associations.docx') as doc:
        xml = doc.read('word/document.xml')
        assert b'125' in xml and b'2024' in xml
    with pikepdf.open(tmp_path / 'scan-transcription.pdf') as pdf:
        assert len(pdf.pages) == 1
        assert '/XObject' in pdf.pages[0].Resources  # actual raster scan, not a text PDF
        assert b'125.50' not in pdf.pages[0].Contents.read_bytes()
    with pytest.raises(ValueError, match='new preparation'):
        prepare(tmp_path)


def manifest():
    return {'benchmark_version': VERSION, 'requests': [
        {'case_id': c['id'], 'source_sha256': HASH} for c in CASES]}


def test_missing_responses_do_not_disappear_from_denominator():
    r = evaluate([answer(CASES[0])], manifest=manifest(), candidate='test-double', prompt_revision='test-v1')
    assert r['probe_passes'] == 1 and r['total'] == 5 and len(r['missing_cases']) == 4
    assert len(r['source_hashes']) == 5 and len(r['response_sha256']) == 64


def test_unknown_duplicate_or_wrong_version_is_invalid():
    for rows in [[answer(CASES[0])] * 2, [{**answer(CASES[0]), 'case_id': 'invented'}]]:
        with pytest.raises(ValueError, match='identity'):
            evaluate(rows, manifest=manifest(), candidate='test', prompt_revision='v1')
    m = manifest(); m['benchmark_version'] = 'unknown'
    with pytest.raises(ValueError, match='version'):
        evaluate([], manifest=m, candidate='test', prompt_revision='v1')
