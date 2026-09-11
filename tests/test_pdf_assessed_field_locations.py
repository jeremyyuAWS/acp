"""Real detector identities must resolve unchanged in the production PDF writer."""
from io import BytesIO
import pikepdf
from test_pdf_form_field_names import _form_pdf
from formats.pdf.detectors.name_role_value import detect
from remediate_pdf import _collect_form_fields, _form_field_locators, apply_pdf_field_name


def test_two_assessed_fields_have_exact_writer_locators(tmp_path):
    source = tmp_path / 'fields.pdf'
    _form_pdf(source, ['Text1', 'Text2'])
    findings = detect(source)
    assert [f['location'] for f in findings] == ['pdf:field:1:0', 'pdf:field:1:1']
    data, applied, unresolved = apply_pdf_field_name(source.read_bytes(),
        {findings[0]['location']: 'First name', findings[1]['location']: 'Last name'})
    assert len(applied) == 2 and not unresolved
    target = tmp_path / 'fixed.pdf'; target.write_bytes(data)
    assert detect(target) == []
    with pikepdf.open(BytesIO(data)) as pdf:
        assert [str(f['/TU']) for f in _collect_form_fields(pdf)] == ['First name', 'Last name']


def test_already_named_sibling_does_not_shift_failing_locator(tmp_path):
    source = tmp_path / 'fields.pdf'
    _form_pdf(source, ['Text1', 'Text2'])
    data, _, _ = apply_pdf_field_name(source.read_bytes(), {'pdf:field:1:0': 'First name'})
    target = tmp_path / 'partial.pdf'; target.write_bytes(data)
    assert [f['location'] for f in detect(target)] == ['pdf:field:1:1']
