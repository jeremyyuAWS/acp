import io

import pikepdf
import pytest

from pdf_structural_language import (
    apply_pdf_structure_language, collect_language_targets, deficient_language_targets,
    language_parts_checks, language_marked_spans, valid_language,
)
from remediate_pdf import apply_pdf_approved


TEXT = 'Bonjour, nous sommes heureux de vous accueillir dans notre établissement et nous vous souhaitons une excellente journée.'


def fixture(*, text=TEXT, lang=None, tag='/Span', nested=False):
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page()
    page.obj['/Contents'] = pdf.make_stream(b'/Span << /MCID 0 >> BDC EMC')
    root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
    pdf.Root['/StructTreeRoot'] = root
    pdf.Root['/Lang'] = 'en-US'
    node = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
        S=pikepdf.Name(tag), P=root, Pg=page.obj, K=0, ActualText=text))
    if lang:
        node['/Lang'] = lang
    root['/K'] = pikepdf.Array([node])
    if nested:
        child = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
            S=pikepdf.Name.Span, P=node, K=0))
        node['/K'] = child
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


def targets(data):
    with pikepdf.open(io.BytesIO(data)) as pdf:
        return collect_language_targets(pdf)


def test_approved_write_reopen_and_content_preservation():
    data = fixture()
    target = targets(data)[0]
    candidate, applied, unresolved = apply_pdf_approved(data, {target.locator: 'fr-FR'})
    assert unresolved == []
    assert applied[0]['rule_id'] == 'SC_3_1_2'
    assert applied[0]['before'] == ''
    assert targets(candidate)[0].current_language == 'fr-FR'
    with pikepdf.open(io.BytesIO(candidate)) as pdf:
        node = pdf.Root.StructTreeRoot.K[0]
        assert str(node.S) == '/Span'
        assert node.K == 0
        assert str(node.ActualText) == TEXT
        assert pdf.pages[0].Contents.read_bytes() == b'/Span << /MCID 0 >> BDC EMC'
        assert str(pdf.Root.Lang) == 'en-US'


def test_changed_text_stale_locator_cannot_write():
    original = fixture()
    locator = targets(original)[0].locator
    changed = fixture(text=TEXT + ' Merci.')
    result, applied, unresolved = apply_pdf_structure_language(changed, {locator: 'fr'})
    assert result == changed and not applied and unresolved == [locator]


@pytest.mark.parametrize('value', ['', 'en US', '/fr', '<script>', '123', None])
def test_invalid_languages_fail_closed(value):
    data = fixture()
    locator = targets(data)[0].locator
    result, applied, unresolved = apply_pdf_structure_language(data, {locator: value})
    assert result == data and not applied and unresolved == [locator]


@pytest.mark.parametrize('tag,nested', [('/Figure', False), ('/P', True), ('/Table', False)])
def test_unsupported_or_nested_targets_not_exposed(tag, nested):
    assert targets(fixture(tag=tag, nested=nested)) == []


def test_detection_checks_clear_only_after_matching_language(tmp_path):
    data = fixture()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        deficient = deficient_language_targets(pdf)
    assert len(deficient) == 1 and deficient[0].suggested_language == 'fr'
    path = tmp_path / 'passage.pdf'
    path.write_bytes(data)
    checks = language_parts_checks(path)
    assert len(checks) == 1 and checks[0]['location'] == deficient[0].locator
    corrected, _, _ = apply_pdf_structure_language(data, {deficient[0].locator: 'fr'})
    path.write_bytes(corrected)
    assert language_parts_checks(path) == []
    assert len(targets(corrected)) == 1


def test_cycle_and_unknown_locator_are_unresolved():
    data = fixture()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        node = pdf.Root.StructTreeRoot.K[0]
        node.K = node
        out = io.BytesIO(); pdf.save(out)
    data = out.getvalue()
    assert targets(data) == []
    assert apply_pdf_structure_language(data, {'pdf:lang:no': 'fr'}) == (data, [], ['pdf:lang:no'])


def test_valid_language_shape():
    assert valid_language('zh-Hant-TW') and valid_language('fr')


def test_inherited_language_mark_is_not_reported_deficient(tmp_path):
    with pikepdf.open(io.BytesIO(fixture())) as pdf:
        root = pdf.Root.StructTreeRoot
        node = root.K[0]
        parent = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
            S=pikepdf.Name.Div, P=root, K=pikepdf.Array([node]), Lang='fr-FR'))
        node.P = parent
        root.K = pikepdf.Array([parent])
        out = io.BytesIO(); pdf.save(out)
    path = tmp_path / 'inherited.pdf'
    path.write_bytes(out.getvalue())
    assert targets(out.getvalue())[0].current_language == 'fr-FR'
    assert language_parts_checks(path) == []
    assert language_marked_spans(path) == {'fr': TEXT}


def test_signed_document_rejected_without_changes():
    with pikepdf.open(io.BytesIO(fixture())) as pdf:
        pdf.Root['/AcroForm'] = pikepdf.Dictionary(SigFlags=3)
        out = io.BytesIO(); pdf.save(out)
    data = out.getvalue()
    locator = targets(data)[0].locator
    assert apply_pdf_structure_language(data, {locator: 'fr'}) == (data, [], [locator])


def test_no_actualtext_or_invalid_content_reference_not_exposed():
    with pikepdf.open(io.BytesIO(fixture())) as pdf:
        node = pdf.Root.StructTreeRoot.K[0]
        del node['/ActualText']
        out = io.BytesIO(); pdf.save(out)
    assert targets(out.getvalue()) == []
    with pikepdf.open(io.BytesIO(fixture())) as pdf:
        node = pdf.Root.StructTreeRoot.K[0]
        node['/K'] = -1
        out = io.BytesIO(); pdf.save(out)
    assert targets(out.getvalue()) == []
