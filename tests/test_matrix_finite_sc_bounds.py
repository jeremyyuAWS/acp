"""Static lane bounds preserve runtime subsets without expanding capabilities."""
import ast
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('matrix_bounds', Path(__file__).resolve().parents[1] / 'scripts/gen_matrix_coverage.py')
gen = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(gen)
SCS = {'_PDF_STRUCTURE_SCS': {'1.3.1', '1.3.2', '2.4.6'}}


@pytest.mark.parametrize('expression,expected', [
    ('set(criteria) & set(_PDF_STRUCTURE_SCS)', SCS['_PDF_STRUCTURE_SCS']),
    ('tuple(sorted(set(criteria) & set(_PDF_STRUCTURE_SCS)))', SCS['_PDF_STRUCTURE_SCS']),
    ('set(_PDF_STRUCTURE_SCS) & set(criteria)', SCS['_PDF_STRUCTURE_SCS']),
    ('set(_PDF_STRUCTURE_SCS) & {"1.3.1"}', {'1.3.1'}),
    ('set(criteria)', None),
    ('set(criteria) | set(_PDF_STRUCTURE_SCS)', None),
    ('set(criteria) - set(_PDF_STRUCTURE_SCS)', None),
    ('set(_PDF_STRUCTURE_SCS, unexpected)', None),
    ('set(_PDF_STRUCTURE_SCS, key=unknown)', None),
    ('{"1.3.1", dynamic}', None),
])
def test_finite_intersections_only(expression, expected):
    assert gen.finite_sc_upper_bound(ast.parse(expression, mode='eval').body, SCS) == expected


def test_named_pdf_lane_derives_only_pdf_and_runtime_subset_is_preserved(tmp_path, monkeypatch):
    src = '''
_APPLY_VALUE_EXTS = ('docx', 'pdf')
_PDF_STRUCTURE_EXTS = ('pdf',)
_PDF_STRUCTURE_SCS = ('1.3.1', '1.3.2', '2.4.6')
def _apply_approved_values(ext, criteria):
    if ext not in _APPLY_VALUE_EXTS:
        return
    values = {}
    if ext in _PDF_STRUCTURE_EXTS:
        _apply_one_value_kind(values=values,
            scs_to_clear=set(criteria) & set(_PDF_STRUCTURE_SCS),
            credit_rule_ids=tuple(sorted(set(criteria) & set(_PDF_STRUCTURE_SCS))))
'''
    (tmp_path / 'handlers.py').write_text(src)
    monkeypatch.setattr(gen, 'API', tmp_path)
    possible = gen.load_appliers()
    assert possible['pdf'] == SCS['_PDF_STRUCTURE_SCS'] and possible['docx'] == set()
    assert gen.load_appliers(keyword='credit_rule_ids') == possible
    namespace = {'_apply_one_value_kind': lambda **kwargs: namespace.update(captured=kwargs)}
    exec(src, namespace)
    namespace['_apply_approved_values']('pdf', ('1.3.2',))
    assert namespace['captured']['scs_to_clear'] == {'1.3.2'}
    assert namespace['captured']['credit_rule_ids'] == ('1.3.2',)


@pytest.mark.parametrize('predicate,narrows', [
    ('ext in _PDF_STRUCTURE_EXTS', True),
    ('ext in _PDF_STRUCTURE_EXTS and ready', True),
    ('ready and ext in _PDF_STRUCTURE_EXTS', True),
    ('ext in _PDF_STRUCTURE_EXTS or ready', False),
    ('ext not in _PDF_STRUCTURE_EXTS', False),
])
def test_only_positive_conjunctive_membership_narrows_scope(tmp_path, monkeypatch, predicate, narrows):
    src = f'''
_APPLY_VALUE_EXTS = ('docx', 'pdf')
_PDF_STRUCTURE_EXTS = ('pdf',)
_PDF_STRUCTURE_SCS = ('1.3.1',)
def _apply_approved_values(ext, ready):
    if ext not in _APPLY_VALUE_EXTS:
        return
    values = {{}}
    if {predicate}:
        _apply_one_value_kind(values=values, scs_to_clear=_PDF_STRUCTURE_SCS)
'''
    (tmp_path / 'handlers.py').write_text(src)
    monkeypatch.setattr(gen, 'API', tmp_path)
    assert gen.load_appliers()['docx'] == (set() if narrows else {'1.3.1'})
