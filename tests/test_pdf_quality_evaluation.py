from dataclasses import asdict
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('pdf_eval', Path(__file__).resolve().parents[1] / 'scripts/run_pdf_quality_evaluation.py')
eval = importlib.util.module_from_spec(spec); spec.loader.exec_module(eval)


def request(case):
    from experiments.document_wide_ai.packaging.manifest_builder import build_pdf_manifest
    from experiments.document_wide_ai.request.builder import build_request
    return build_request(build_pdf_manifest(case['pdf'], document_id='synthetic.pdf', assessment_revision='v', selected_criteria=('4.1.2',)), request_id='test')


def response(req, case, override=None):
    edits, unresolved = [], []
    for f, expected in zip(req.manifest.findings, case['expected']):
        if expected is None and override is None:
            unresolved.append({'finding_id': f.finding_id, 'reason': 'No external label'})
        else:
            edits.append({'edit_id': f.finding_id, 'finding_ids': [f.finding_id],
                          'locator': asdict(f.locator), 'operation': 'set_pdf_field_accessible_name',
                          'proposed_value': override or expected[0], 'expected_original_value': None,
                          'rationale': 'Visible external label'})
    return json.dumps({'contract_version': req.manifest.contract_version, 'request_id': req.request_id,
                      'source_sha256': req.manifest.source_sha256, 'edits': edits, 'unresolved': unresolved})


def test_six_real_fixtures_validate_apply_readback_and_preserve_content_fields():
    cases = eval.synthetic_cases()
    assert len(cases) == 6 and len({c['name'] for c in cases}) == 6
    for case in cases:
        req = request(case)
        score, saved = eval.evaluate_response(req, response(req, case), case)
        assert score['valid_contract'] and score['saved_integrity']
        assert score['semantic_errors'] == score['unsupported_requests'] == 0
        assert score['useful_applied_fixes'] == sum(e is not None for e in case['expected'])
        assert saved is not None


def test_widget_value_guess_and_unsupported_operations_are_not_useful():
    case = eval.synthetic_cases()[2]; req = request(case)
    score, _ = eval.evaluate_response(req, response(req, case, 'SAMPLE PERSON'), case)
    assert score['semantic_errors'] == 1 and score['useful_applied_fixes'] == 0
    raw = json.loads(response(req, case)); raw['edits'][0]['operation'] = 'delete_pages'
    score, saved = eval.evaluate_response(req, json.dumps(raw), case)
    assert score['unsupported_requests'] == 1 and not score['valid_contract'] and saved is None


def test_offline_prepares_requests_reserves_whole_ceiling_and_never_fake_scores(tmp_path):
    result = eval.run(tmp_path)
    assert result['status'] == 'offline_prepared' and len(result['attempts']) == 18
    assert eval.Decimal(result['reserved_maximum_usd']) < eval.CAP_USD
    assert all(r['status'] == 'prepared' and r['cost_usd'] is None for r in result['attempts'])
    assert 'summary' not in result
    with pytest.raises(ValueError, match='never replayed'):
        eval.run(tmp_path)


def test_uncertain_transport_keeps_full_reservation_and_stops_before_second_call(tmp_path):
    calls = []
    def post(*args, **kwargs):
        # Whole-experiment reservation must already exist before dispatch.
        ledger = json.loads((tmp_path / 'evaluation.json').read_text())
        assert ledger['reserved_maximum_usd'] == '1.290240'
        assert len(ledger['reservation_plan']) == 18
        assert len(ledger['verified_model_specs']) == 2
        calls.append(1); raise TimeoutError('Unknown transport outcome')
    config = ('anthropic', {'anthropic': 'test-only'}, {'anthropic'},
              {'anthropic': 'https://api.anthropic.com/v1/messages', 'openai': 'https://api.openai.com/v1/chat/completions'})
    result = eval.run(tmp_path, live=True, provider_config=config, post=post)
    assert len(calls) == 1 and result['status'] == 'blocked'
    assert result['attempts'][0]['status'] == 'uncertain_spend'
    assert result['attempts'][0]['cost_usd'] is None


def test_exact_source_hash_mismatch_invalidates_contract():
    case = eval.synthetic_cases()[0]; req = request(case)
    raw = json.loads(response(req, case)); raw['source_sha256'] = '0' * 64
    score, saved = eval.evaluate_response(req, json.dumps(raw), case)
    assert not score['valid_contract'] and saved is None


def test_governance_snapshot_requires_fresh_exact_enabled_provider_binding(monkeypatch):
    from datetime import datetime, timezone, timedelta
    from types import SimpleNamespace
    env = {'properties': {'template': {'containers': [{'env': [{'name': 'ANTHROPIC_API_KEY', 'secretRef': 'anthropic'}]}]}}}
    def command(args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps(
            [{'name': 'anthropic', 'value': 'test-only'}] if 'secret' in args else env))
    monkeypatch.setattr(eval.subprocess, 'run', command)
    snapshot = {'observed_at': datetime.now(timezone.utc).isoformat(), 'primary': 'anthropic',
                'permitted': ['anthropic'], 'provider': {'enabled': True,
                'key_secret_ref': 'ANTHROPIC_API_KEY', 'model': 'claude-haiku-4-5-20251001',
                'endpoint': 'https://api.anthropic.com/v1'}}
    assert eval.azure_provider_config(governance_snapshot=snapshot)[0] == 'anthropic'
    for mutation in ({'enabled': False}, {'model': 'unknown'}, {'key_secret_ref': 'OTHER_SECRET'}):
        bad = dict(snapshot, provider=dict(snapshot['provider'], **mutation))
        with pytest.raises(RuntimeError, match='governance'):
            eval.azure_provider_config(governance_snapshot=bad)
    snapshot['observed_at'] = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
    with pytest.raises(RuntimeError, match='governance'):
        eval.azure_provider_config(governance_snapshot=snapshot)


def test_excess_fixture_count_is_rejected_before_dispatch(tmp_path, monkeypatch):
    cases = eval.synthetic_cases()
    monkeypatch.setattr(eval, 'synthetic_cases', lambda: cases + cases[:1])
    with pytest.raises(ValueError, match='ceiling'):
        eval.run(tmp_path)
    assert not (tmp_path / 'evaluation.json').exists()


def test_shared_production_prompt_requires_unfenced_full_locator_and_manifest_identity():
    from dataclasses import replace
    from document_wide_provider import build_document_prompt
    req = request(eval.synthetic_cases()[0])
    prompt = build_document_prompt(req, native_pdf=True, native_profile='native-pdf-quality.v1')
    assert prompt.startswith('Return JSON only:')
    assert 'locator string is invalid' in prompt and 'no Markdown, code fences' in prompt
    assert '"fingerprint":<exact fingerprint>' in prompt
    assert 'Request ID: "test"' in prompt
    assert 'Input mode: native_pdf' in prompt
    assert 'Native PDF model profile: native-pdf-quality.v1' in prompt
    assert '\nUntrusted document manifest:\n' + req.manifest.to_json() in prompt
    with pytest.raises(ValueError, match='manifest_mismatch'):
        build_document_prompt(replace(req, stable_prefix='altered'))


def test_post_transport_rejection_retains_sanitized_accounting_not_headers(tmp_path):
    class Response:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {'model': 'unexpected-model', 'id': 'synthetic-response',
                    'usage': {'input_tokens': 100, 'output_tokens': 20, 'secret': 'must-not-retain'},
                    'content': [{'type': 'text', 'text': '{}'}], 'stop_reason': 'end_turn',
                    'headers': {'x-api-key': 'must-not-retain'}}
    config = ('anthropic', {'anthropic': 'test-only'}, {'anthropic'},
              {'anthropic': 'https://api.anthropic.com/v1/messages', 'openai': 'https://api.openai.com/v1/chat/completions'})
    result = eval.run(tmp_path, live=True, provider_config=config, post=lambda *a, **kw: Response())
    assert result['status'] == 'blocked'
    row = result['attempts'][0]
    assert row['status'] == 'uncertain_spend' and row['cost_usd'] is None
    assert row['response_diagnostics']['usage'] == {'input_tokens': 100, 'output_tokens': 20}
    assert 'must-not-retain' not in (tmp_path / 'evaluation.json').read_text()
