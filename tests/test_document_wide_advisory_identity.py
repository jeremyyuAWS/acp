import json
import pytest
from document_wide_manifest import build_manifest
from document_wide_provider import build_document_prompt, _decode
from experiments.document_wide_ai.request.builder import build_request
from test_document_wide_pdf_context import pdf_context, setup_manifest


def test_advisory_selected_findings_do_not_offer_response_ids(isolated_store, monkeypatch):
    data = pdf_context()
    rows = setup_manifest(isolated_store, monkeypatch, data, 'a.pdf', '1.1.1', ['pdf:fig:1:0', 'unsupported-location'])
    manifest = build_manifest(isolated_store, 'scan', 'a.pdf', data)
    assert rows[0]['finding_id'] in manifest.finding_ids()
    assert rows[1]['finding_id'] not in manifest.text_context
    assert 'no write authorization' in manifest.text_context
    # Semantic advisory context is retained; only its response identity is withheld.
    advisory = json.loads(manifest.text_context.split('\n')[-1])
    assert advisory[0]['rule_id'] == '1.1.1'
    assert 'finding_id' not in advisory[0]
    request = build_request(manifest, request_id='allowlist-test')
    prompt = build_document_prompt(request)
    line = next(line for line in prompt.splitlines() if line.startswith('Response finding ID allowlist: '))
    assert json.loads(line.split(': ', 1)[1]) == [rows[0]['finding_id']]
    assert prompt.index(line) < prompt.index('Untrusted document manifest:')
    assert rows[1]['finding_id'] not in prompt
    assert rows[0]['finding_id'] in prompt
    assert any(rows[1]['finding_id'] in issue.related_finding_ids for issue in manifest.extraction_issues)
    assert request.stable_prefix == manifest.to_json()


def test_advisory_ids_remain_invalid_in_unresolved_envelope(isolated_store, monkeypatch):
    data = pdf_context()
    rows = setup_manifest(isolated_store, monkeypatch, data, 'a.pdf', '1.1.1', ['pdf:fig:1:0', 'unsupported-location'])
    manifest = build_manifest(isolated_store, 'scan', 'a.pdf', data)
    request = build_request(manifest, request_id='strict-membership-test')
    response = {'contract_version': manifest.contract_version, 'request_id': request.request_id,
                'source_sha256': manifest.source_sha256, 'edits': [],
                'unresolved': [{'finding_id': row['finding_id'], 'reason': 'Source editing required'} for row in rows]}
    with pytest.raises(ValueError, match='invalid_required_structure'):
        _decode(request, json.dumps(response))
