"""Exact JSON fences must not trigger another paid model; bindings remain mandatory."""
import json
import pytest
from document_wide_provider import _decode
from test_document_wide_provider import request_package, response


@pytest.mark.parametrize('language', ['json', ''])
def test_single_json_fence_preserves_validated_envelope(request_package, language):
    raw = response(request_package)
    wrapped = '\n```' + language + '\n' + json.dumps(raw) + '\n```\n'
    envelope, validation = _decode(request_package, wrapped)
    assert envelope.request_id == request_package.request_id
    assert not validation.rejected_edits


@pytest.mark.parametrize('wrapper', ['Here is the result:\n```json\n%s\n```', '```json\n%s\n```\nextra', '```python\n%s\n```', '```json\n%s\n```\n```json\n{}\n```'])
def test_fence_is_not_a_general_text_extractor(request_package, wrapper):
    with pytest.raises(ValueError):
        _decode(request_package, wrapper % json.dumps(response(request_package)))


@pytest.mark.parametrize('change', [{'request_id': 'wrong'}, {'source_sha256': 'b'*64}, {'unresolved': []}, {'extra': 'untrusted'}])
def test_fenced_response_still_checks_exact_source_scope_and_coverage(request_package, change):
    with pytest.raises(ValueError):
        _decode(request_package, '```json\n' + json.dumps(response(request_package, **change)) + '\n```')


def test_fenced_edit_uses_the_same_operation_allowlist(request_package):
    from dataclasses import asdict, replace
    raw = response(request_package, unresolved=[], edits=[dict(edit_id='e1', finding_ids=['finding1'],
        locator=asdict(request_package.manifest.findings[0].locator),
        operation='set_pdf_field_accessible_name', proposed_value='Full name', expected_original_value=None)])
    wrapped = '```json\n' + json.dumps(raw) + '\n```'
    envelope, validation = _decode(request_package, wrapped)
    assert len(validation.valid_edits) == 1 and len(envelope.edits) == 1
    altered = replace(request_package, manifest=replace(request_package.manifest, allowed_operations=()))
    with pytest.raises(ValueError):
        _decode(altered, wrapped)
