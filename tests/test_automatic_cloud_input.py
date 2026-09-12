"""Synthetic admission and durable workflow fixtures; no external model calls."""
from dataclasses import replace
from io import BytesIO
from types import MappingProxyType

import pikepdf
import pytest

from ai_run_policy import RunContext, normalize_run_policy, optional_current_run_context
from ai_spending_budget import BudgetError
from remediation_impact_settings import normalize_policy, snapshot_impact_policy
from automatic_cloud_input import select_document_input, selected_document_context
from test_document_wide_pdf_transport import make_generator
from test_llm_waterfall_provider import specs


def policy(**changes):
    return normalize_policy({'rule_based': 2, 'ai': 1, 'ai_zone': 'any',
                             'cloud_input_strategy': 'automatic', **changes})


def context(filename='a.pdf', **changes):
    return RunContext(None, 'owner', 'scan', 'run', MappingProxyType(normalize_run_policy(policy(**changes))), file=filename)


def pdf_data(pages=1):
    pdf = pikepdf.Pdf.new()
    for _ in range(pages):
        pdf.add_blank_page()
    out = BytesIO()
    pdf.save(out)
    return out.getvalue()


def test_new_contract_freezes_server_default_but_honors_explicit_caps(isolated_store):
    assert policy()['ai_budget_usd'] == '25.00'
    assert policy(ai_budget_usd='0.00')['ai_budget_usd'] == '0.00'
    first = snapshot_impact_policy(isolated_store, 'owner', policy())
    assert first['cloud_input_strategy'] == 'automatic'
    assert first['snapshot_id'] == snapshot_impact_policy(isolated_store, 'owner', policy())['snapshot_id']
    assert normalize_run_policy(first)['cloud_input_strategy'] == 'automatic'
    assert normalize_run_policy({'ai': 1}) is None
    assert normalize_policy({'rule_based': 2, 'ai': 1, 'ai_zone': 'local', 'ai_budget_usd': '0.00'}) == {
        'rule_based': 2, 'ai': 1, 'ai_zone': 'local', 'ai_budget_usd': '0.00'}


@pytest.mark.parametrize('changes', [{'ai_zone': 'local'}, {'ai': 0}, {'cloud_input_strategy': 'guess'},
                                     {'document_wide_input_mode': 'native_pdf'}])
def test_invalid_new_selections_fail_closed(changes):
    with pytest.raises(ValueError):
        policy(**changes)


def test_worker_never_invents_cap_for_unfrozen_automatic_snapshot():
    with pytest.raises(BudgetError, match='frozen'):
        normalize_run_policy({'ai': 1, 'ai_zone': 'any', 'cloud_input_strategy': 'automatic'})


def test_local_and_zero_caps_never_inspect_cloud_models(monkeypatch):
    import native_pdf_quality
    monkeypatch.setattr(native_pdf_quality, 'configured_native_pdf_generator', lambda *a: pytest.fail('no cloud admission'))
    zero = context(ai_budget_usd='0.00')
    local = replace(zero, policy=MappingProxyType({'ai': 1, 'ai_zone': 'local', 'cap_units': 0}))
    for ctx in (zero, local):
        assert select_document_input(ctx, pdf_data())[0] is ctx


def test_admitted_native_pdf_preserves_source_context_and_ledger(monkeypatch, specs):
    import native_pdf_quality
    generator, _ = make_generator(specs, lambda *a, **kw: pytest.fail('admission must not dispatch'), context=1000000)
    monkeypatch.setattr(native_pdf_quality, 'configured_native_pdf_generator', lambda ctx: generator)
    ctx = context()
    with selected_document_context(ctx, pdf_data()) as (selected, decision):
        assert selected.policy['document_wide_input_mode'] == decision['input_mode'] == 'native_pdf'
        assert optional_current_run_context() is selected
        assert selected.ledger is ctx.ledger and selected.deferred is ctx.deferred
        assert (selected.owner_id, selected.scan_id, selected.run_id, selected.file) == ('owner', 'scan', 'run', 'a.pdf')
    assert optional_current_run_context() is None
    assert 'document_wide_input_mode' not in ctx.policy


def test_single_vendor_native_configuration_uses_existing_authorized_generator(monkeypatch, specs):
    import native_pdf_quality, llm_waterfall_provider
    generator, _ = make_generator(specs, lambda *a, **kw: pytest.fail('no dispatch'), context=1000000)
    monkeypatch.setattr(native_pdf_quality, 'configured_native_pdf_generator', lambda ctx: (_ for _ in ()).throw(ValueError('fallback vendor unavailable')))
    monkeypatch.setattr(llm_waterfall_provider, 'configured_generator', lambda: generator)
    selected, decision = select_document_input(context(), pdf_data())
    assert decision['input_mode'] == 'native_pdf'
    assert 'document_wide_model_profile' not in selected.policy


@pytest.mark.parametrize('mode', ['office', 'pages', 'bytes', 'context', 'models'])
def test_safe_extracted_fallback_records_reason_without_cloud_dispatch(monkeypatch, specs, mode):
    import native_pdf_quality, llm_waterfall_provider
    generator, _ = make_generator(specs, lambda *a, **kw: pytest.fail('no dispatch'), context=32768)
    if mode == 'models':
        monkeypatch.setattr(native_pdf_quality, 'configured_native_pdf_generator', lambda ctx: (_ for _ in ()).throw(ValueError('unavailable')))
        monkeypatch.setattr(llm_waterfall_provider, 'configured_generator', lambda: (_ for _ in ()).throw(ValueError('unavailable')))
    else:
        monkeypatch.setattr(native_pdf_quality, 'configured_native_pdf_generator', lambda ctx: generator)
    data = pdf_data(101 if mode == 'pages' else 1)
    if mode == 'bytes':
        data = b'%PDF-' + b'0' * (20 * 1024 * 1024)
    selected, decision = select_document_input(context('a.docx' if mode == 'office' else 'a.pdf'), data)
    assert selected.policy['document_wide_input_mode'] == decision['input_mode'] == 'extracted'
    assert decision['reason']


def test_workflow_records_automatic_choice_and_preserves_proposal_lineage(monkeypatch):
    from test_document_wide_workflow import setup
    import document_wide_workflow
    store, ctx, calls, logs, queued = setup(monkeypatch)
    monkeypatch.setattr(document_wide_workflow, '_saved_input', lambda *a: None)
    managed = RunContext(None, ctx.owner_id, ctx.scan_id, ctx.run_id,
                         MappingProxyType(normalize_run_policy(policy())), file=ctx.file)
    document_wide_workflow.process_file(store, managed)
    assert len(calls) == len(queued) == 1
    assert queued[0][0][3][0]['cloud_input_strategy'] == 'automatic'
    assert queued[0][0][3][0]['document_wide_input_mode'] == 'extracted'
    assert queued[0][1]['validated'] is False
    assert 'document_wide.input_selected' in [args[1] for args, kwargs in logs]

@pytest.mark.parametrize('state', ['missing', 'stale', 'public'])
def test_automatic_local_first_skips_unavailable_capability_without_probe_or_dispatch(monkeypatch, state):
    import ai, time
    from automatic_cloud_input import try_local_text_draft
    monkeypatch.setattr(ai, 'OLLAMA_BASE_URL', 'https://vendor.example' if state == 'public' else 'http://localhost:11434')
    monkeypatch.setattr(ai, 'OLLAMA_MODEL', 'fixture-local')
    monkeypatch.setattr(ai, '_TAGS_CACHE', {'at': time.monotonic() - (999 if state == 'stale' else 0),
        'tags': [] if state == 'missing' else [{'name': 'fixture-local'}]})
    monkeypatch.setattr('httpx.post', lambda *a, **kw: pytest.fail('no unavailable local dispatch'))
    monkeypatch.setattr(ai, '_fetch_tags', lambda: pytest.fail('must not block on a cold-start probe'))
    assert try_local_text_draft('grounded input', context()) is None


@pytest.mark.parametrize('local_ok', [True, False])
def test_available_local_draft_is_bounded_and_cloud_fallback_is_honest(monkeypatch, local_ok):
    import ai, time, providers
    from types import SimpleNamespace
    import llm_waterfall_provider
    ctx = context('a.docx')
    monkeypatch.setattr(llm_waterfall_provider, 'managed_context', lambda: ctx)
    monkeypatch.setattr(ai, 'OLLAMA_BASE_URL', 'http://localhost:11434')
    monkeypatch.setattr(ai, 'OLLAMA_MODEL', 'fixture-local')
    monkeypatch.setattr(ai, '_TAGS_CACHE', {'at': time.monotonic(), 'tags': [{'name': 'fixture-local'}]})
    monkeypatch.setenv('OLLAMA_FALLBACK_MODEL', 'must-not-run')
    monkeypatch.setattr(ai, '_trace_ai', lambda *a, **kw: 'actual-local-call' if kw['provider'] == 'ollama' else 'actual-cloud-call')
    requests = []
    def post(url, **kwargs):
        requests.append((url, kwargs))
        return SimpleNamespace(raise_for_status=lambda: None,
            json=lambda: {'response': 'Grounded page title' if local_ok else '', 'done': True})
    monkeypatch.setattr('httpx.post', post)
    clouds = []
    def cloud(*a, **kw):
        clouds.append(a)
        return {'text': 'Cloud page title', 'provider': 'openai', 'zone': 'customer_cloud', 'model': 'configured-cloud',
                'prompt_tokens': 5, 'completion_tokens': 3, 'cost_usd': 0.0001}
    monkeypatch.setattr(providers, 'text_generate', cloud)
    result = ai.suggest_fix('2.4.2', 'Page title', 'A', 'a.docx', detail='Relevant title evidence')
    assert len(requests) == 1 and requests[0][1]['timeout'] == 5
    assert requests[0][1]['json']['model'] == 'fixture-local'
    assert len(clouds) == (0 if local_ok else 1)
    assert result['provider'] == ('ollama' if local_ok else 'openai')
    assert result['cost_usd'] == (0.0 if local_ok else 0.0001)

def test_saved_automatic_admission_never_switches_input_on_replay(monkeypatch):
    import native_pdf_quality
    monkeypatch.setattr(native_pdf_quality, 'configured_native_pdf_generator', lambda *a: pytest.fail('do not reselect paid operation'))
    frozen = {'strategy': 'automatic', 'input_mode': 'native_pdf', 'model_profile': 'native-pdf-quality.v1', 'reason': 'supported_current_pdf'}
    with selected_document_context(context(), pdf_data(), frozen_decision=frozen) as (selected, decision):
        assert decision is frozen
        assert selected.policy['document_wide_model_profile'] == 'native-pdf-quality.v1'


def test_saved_input_is_scoped_to_owner_run_and_exact_artifact(isolated_store):
    import document_wide_workflow as workflow, json
    from test_ai_run_policy import seed
    seed(isolated_store)
    ctx = context()
    for owner, run, digest in [('other', 'run', 'same'), ('owner', 'other', 'same'), ('owner', 'run', 'old')]:
        isolated_store.log_decision('system', 'document_wide.input_selected', scan_id='scan', file='a.pdf',
            detail=json.dumps({'owner_id': owner, 'run_id': run, 'source_sha256': digest, 'strategy': 'automatic', 'input_mode': 'extracted'}))
    assert workflow._saved_input(isolated_store, ctx, 'same') is None
    isolated_store.log_decision('system', 'document_wide.input_selected', scan_id='scan', file='a.pdf',
        detail=json.dumps({'owner_id': 'owner', 'run_id': 'run', 'source_sha256': 'same', 'strategy': 'automatic', 'input_mode': 'extracted'}))
    assert workflow._saved_input(isolated_store, ctx, 'same')['input_mode'] == 'extracted'


def test_durable_job_and_accepted_summary_keep_automatic_authority(isolated_store):
    from test_ai_run_policy import seed
    from ai_run_policy import run_context
    from accepted_remediation_plan import read_accepted_plan
    seed(isolated_store)
    frozen = snapshot_impact_policy(isolated_store, 'owner', policy())
    batch = isolated_store.enqueue_stage_batch('scan', 'remediate', 'remediate_file', [{
        'owner': 'owner', 'scan_id': 'scan', 'file': 'a.pdf', 'remediation_impact_policy': frozen,
    }], snapshot_id='snapshot', request_fingerprint='automatic-cloud-input')
    job = isolated_store.get_job(batch['job_ids'][0])
    with run_context(isolated_store, job['payload'], job) as ctx:
        assert ctx.enabled is True
        assert ctx.policy['cloud_input_strategy'] == 'automatic'
        assert ctx.policy['cap_units'] == 25_000_000
    saved = read_accepted_plan(isolated_store, 'owner', 'scan', batch['batch_id'])
    assert saved['policy']['cloud_input_strategy'] == 'automatic'
    assert saved['policy']['ai_budget_usd'] == '25.00'
    assert read_accepted_plan(isolated_store, 'other', 'scan', batch['batch_id']) is None


def test_pikepdf_valid_but_text_reader_failure_is_safe_extracted_admission(monkeypatch, specs):
    import native_pdf_quality, pypdf
    from types import SimpleNamespace
    from document_wide_native_pdf import validate_native_pdf
    data = pdf_data()
    assert validate_native_pdf(data) == data
    generator, _ = make_generator(specs, lambda *a, **kw: pytest.fail('no paid admission dispatch'), context=1000000)
    monkeypatch.setattr(native_pdf_quality, 'configured_native_pdf_generator', lambda ctx: generator)
    def unreadable():
        raise ValueError('unsupported text encoding')
    monkeypatch.setattr(pypdf, 'PdfReader', lambda *a, **kw: SimpleNamespace(pages=[SimpleNamespace(extract_text=unreadable)]))
    selected, decision = select_document_input(context(), data)
    assert selected.policy['document_wide_input_mode'] == 'extracted'
    assert decision['reason'] == 'native_pdf_text_read_failed'


def test_automatic_failures_do_not_refer_to_removed_manual_controls():
    from document_wide_workflow import _reason
    for reason in ('document_wide_native_pdf_context_limit', 'document_wide_native_pdf_model_unavailable', 'request_rejected_before_dispatch'):
        text = _reason(reason, 'native_pdf', automatic=True)
        assert 'Choose Document context' not in text and 'Try Document context' not in text
        assert 'Remaining findings stay in review' in text
    assert 'Choose Document context' in _reason('document_wide_native_pdf_model_unavailable', 'native_pdf')
