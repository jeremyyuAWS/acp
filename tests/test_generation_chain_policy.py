"""Chain policy fixtures use isolated storage and a synthetic local catalog only."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
import time
import pytest

from ai_generation_chain import normalize_chain, normalize_execution, chain_options
from ai_run_policy import normalize_run_policy, run_context, read_run_budget
from ai_spending_budget import AttemptConflict, BudgetError
from llm_waterfall_provider import StrictTextGenerator, TextModelSpec
from test_llm_waterfall_provider import FakeProviders


def chain(size=3):
    return {'version': 1, 'steps': [dict(step_id=key, position=n, provider='openai', model=f'fixture-model-{n}', enabled=True, capabilities=['text'])
        for n, key in enumerate(('primary', 'fallback_1', 'fallback_2')[:size])]}


def execution():
    return dict(chain_version=1, step_id='primary', generation_position=0,
        parent_attempt_id=None, escalation_reason=None, source_sha256='a'*64,
        assessment_revision='assessment', finding_ids=['finding'], request_id='attempt',
        adapter_id='pptx-slide-title.v1', locator='slide:1')


@pytest.mark.parametrize('mutate', [
    lambda c: c.update(version=True), lambda c: c.update(version=2),
    lambda c: c.update(steps=c['steps'][:1]), lambda c: c['steps'].reverse(),
    lambda c: c['steps'][2].update(position=True),
    lambda c: c['steps'][2].update(enabled=False),
    lambda c: c['steps'][2].update(capabilities=['image']),
    lambda c: c['steps'][2].update(provider='anthropic'),
    lambda c: c['steps'][2].update(model='fixture-model-0'),
    lambda c: c['steps'][2].update(model='bad model'),
])
def test_malformed_or_broadened_chain_is_rejected(mutate):
    value = chain()
    mutate(value)
    with pytest.raises(ValueError):
        normalize_chain(value)


def test_legacy_absence_and_explicit_chain_need_distinct_managed_policy():
    assert normalize_run_policy({'ai': 1}) is None
    assert 'generation_chain' not in normalize_run_policy({'ai': 1, 'ai_budget_usd': '1.00'})
    with pytest.raises(BudgetError):
        normalize_run_policy({'ai': 1, 'generation_chain': chain()})
    assert normalize_chain(chain(2)) == chain(2)


def test_execution_version_must_be_integer_and_lineage_bounded():
    for changes in ({'chain_version': True}, {'source_sha256': 'old'}, {'finding_ids': ['f', 'f']},
                    {'generation_position': 2}, {'parent_attempt_id': 'unexpected'}):
        with pytest.raises(ValueError):
            normalize_execution(execution() | changes)


def test_accepted_run_cannot_gain_third_position_or_change_selected_model(isolated_store):
    store = isolated_store
    with store._db.cursor() as cur:
        store._db.execute(cur, "INSERT INTO scan_runs(id,owner_email,status) VALUES('scan','owner','done')")
    selected = dict(ai=1, ai_budget_usd='1.00', generation_chain=chain(2))
    payload = dict(owner='owner', scan_id='scan', file='file.pptx', remediation_impact_policy=selected)
    run = store.enqueue_stage_batch('scan', 'remediate', 'remediate_file', [payload], snapshot_id='s', request_fingerprint='same')
    job = store.get_job(run['job_ids'][0])
    with run_context(store, job['payload'], job) as ctx:
        assert len(ctx.policy['generation_chain']['steps']) == 2
    changed = deepcopy(job['payload'])
    changed['remediation_impact_policy']['generation_chain'] = chain(3)
    with pytest.raises(BudgetError):
        with run_context(store, changed, job):
            pytest.fail('caller broadened a saved chain')
    with pytest.raises(AttemptConflict):
        store.enqueue_stage_batch('scan', 'remediate', 'remediate_file', [payload | {'remediation_impact_policy': selected | {'generation_chain': chain(3)}}], snapshot_id='s', request_fingerprint='same')
    assert read_run_budget(store, 'owner', 'scan', run['batch_id'])['policy']['generation_chain'] == chain(2)


def specs(size=3):
    return tuple(TextModelSpec('openai', f'fixture-model-{n}', 'synthetic-price', '1', '2', 8192, 128, int(time.time()) + 3600) for n in range(size))


def test_catalog_is_read_only_defaults_to_two_and_requires_supported_finding(monkeypatch):
    generator = StrictTextGenerator(specs(), provider_module=FakeProviders,
        post=lambda *a, **kw: pytest.fail('capability read dispatched a paid request'))
    monkeypatch.setattr('llm_waterfall_provider.configured_generator', lambda: generator)
    result = chain_options([{'file': 'a.pptx', 'criterion': '2.4.6', 'finding_count': 1}])
    assert result['supported'] is True
    assert result['default_steps'] == chain(2)['steps']
    assert len(result['models']) == 3
    assert 'synthetic-price' not in json.dumps(result)
    assert chain_options([])['supported'] is False
    generator = StrictTextGenerator(specs(2), provider_module=FakeProviders,
        post=lambda *a, **kw: pytest.fail('capability read dispatched a paid request'))
    result = chain_options([{'file': 'a.pptx', 'criterion': '2.4.6', 'finding_count': 1}])
    assert result['supported'] is False
    assert len(result['models']) == len(result['default_steps']) == 2
    assert 'fixture-model-2' not in json.dumps(result)


@pytest.mark.parametrize('changes', [{'verified_until': 1}, {'provider': 'anthropic'}, {'model': 'fixture-model-0'}])
def test_stale_disallowed_or_duplicate_catalog_is_unavailable_without_calls(monkeypatch, changes):
    values = specs()
    def configured():
        return StrictTextGenerator((*values[:2], replace(values[2], **changes)), provider_module=FakeProviders,
            post=lambda *a, **kw: pytest.fail('invalid catalog dispatched a request'))
    monkeypatch.setattr('llm_waterfall_provider.configured_generator', configured)
    result = chain_options([{'file': 'a.pptx', 'rule_id': '2.4.6', 'finding_count': 1}])
    assert result['supported'] is False
    assert result['models'] == result['default_steps'] == []


def test_exact_catalog_ids_are_returned_without_aliases(monkeypatch):
    monkeypatch.setenv('ACP_BOUNDED_TEXT_MODELS_JSON', json.dumps([asdict(s) for s in specs()]))
    monkeypatch.setattr('providers.active_text_provider', lambda: 'openai')
    monkeypatch.setattr('providers._text_key_for', lambda _: 'fixture-key')
    result = chain_options([{'file': 'a.pptx', 'rule_id': '2.4.6', 'finding_count': 1}])
    assert [m['model'] for m in result['models']] == ['fixture-model-0', 'fixture-model-1', 'fixture-model-2']


@pytest.mark.parametrize('status', ['usage_unknown', 'rejected_before_dispatch', 'drafted'])
def test_predispatch_lineage_survives_finish_and_cannot_be_replaced(isolated_store, status):
    from ai_attempt_history import AttemptHistory
    from ai_spending_budget import BudgetLedger
    ledger = BudgetLedger(isolated_store._db)
    ledger.create_budget('owner', 'run', 100)
    ledger.reserve('owner', 'run', 'attempt', 10, 'synthetic')
    history = AttemptHistory(isolated_store._db)
    values = dict(file='a.pptx', input_sha256='b'*64, model='fixture-model-0', provider='openai', execution=execution())
    started = history.begin('owner', 'scan', 'run', 'operation', 'attempt', **values)
    assert started['result']['execution'] == execution()
    assert ledger.snapshot('owner', 'run')['held_units'] == 10
    result = {'text': 'Title', 'model': 'fixture-model-0', 'provider': 'openai', 'validation_outcome': 'usable'} if status == 'drafted' else None
    finished = history.finish('owner', 'scan', 'run', 'attempt', status=status, result=result)
    assert finished['result']['execution'] == execution()
    history.finish('owner', 'scan', 'run', 'attempt', status=status, result=result)
    history.begin('owner', 'scan', 'run', 'operation', 'attempt', **values)
    with pytest.raises(AttemptConflict):
        history.begin('owner', 'scan', 'run', 'operation', 'attempt', **(values | {'execution': execution() | {'finding_ids': ['other']}}))
    with pytest.raises(AttemptConflict):
        history.finish('owner', 'scan', 'run', 'attempt', status=status,
                       result={'model': 'fixture-model-0', 'provider': 'openai', 'execution': execution() | {'finding_ids': ['other']}})


def configured_providers(url='https://api.openai.com/v1', *, endpoint=True, derive=True):
    """A provider module reporting exactly the endpoint configuration under test.

    `zone_for_url` is the REAL one from api/providers.py, so these tests assert what the
    server would actually derive rather than a fixture's opinion of it. `endpoint=False`
    is a module that reports no configured endpoint for the provider; `derive=False` one
    that cannot derive a zone at all.
    """
    import providers
    namespace = {'_ANTHROPIC_MESSAGES_URL': 'https://api.anthropic.com/v1/messages',
                 'active_text_provider': staticmethod(lambda: 'openai'),
                 # These fixtures are about ZONE derivation, not vendor authorisation: every
                 # spec here is the selected provider, so the permitted set is just that one.
                 'permitted_text_providers': staticmethod(lambda: frozenset({'openai'})),
                 '_text_key_for': staticmethod(lambda provider: 'fixture-not-a-secret')}
    if endpoint:
        namespace['_OPENAI_TEXT_BASE_URL'] = url
    if derive:
        namespace['zone_for_url'] = staticmethod(providers.zone_for_url)
    return type('ConfiguredProviders', (), namespace)


def catalog(monkeypatch, module, size=3):
    generator = StrictTextGenerator(specs(size), provider_module=module,
        post=lambda *a, **kw: pytest.fail('capability read dispatched a paid request'))
    monkeypatch.setattr('llm_waterfall_provider.configured_generator', lambda: generator)
    return generator


@pytest.mark.parametrize('url,zone', [
    ('http://127.0.0.1:11434/v1', 'local'),
    ('http://localhost:11434/v1', 'local'),
    ('http://ollama.svc.internal/v1', 'local'),
    ('http://10.1.2.3:8000/v1', 'local'),
    ('https://api.openai.com/v1', 'cloud'),
    ('https://gateway.example.com/v1', 'cloud'),
])
def test_catalog_zone_comes_from_the_configured_endpoint_not_the_provider_name(monkeypatch, url, zone):
    """Same provider NAME on every row; the zone follows the configured endpoint only."""
    catalog(monkeypatch, configured_providers(url))
    result = chain_options([])
    assert {model['provider'] for model in result['models']} == {'openai'}
    assert [model['zone'] for model in result['models']] == [zone] * 3


@pytest.mark.parametrize('module', [configured_providers(endpoint=False),
                                    configured_providers(derive=False)])
def test_unconfigured_zone_is_reported_absent_rather_than_guessed(monkeypatch, module):
    import providers
    catalog(monkeypatch, module)
    result = chain_options([])
    # The key is present and explicitly null: the UI renders "not reported". Falling
    # through to zone_for_url on a missing endpoint would answer 'local' instead —
    # claiming no document leaves the network, the one wrong answer that matters.
    assert providers.zone_for_url('') == 'local'
    assert all('zone' in model and model['zone'] is None for model in result['models'])


def test_existing_specs_without_a_zone_field_still_configure_and_report_one(monkeypatch):
    """Positional construction and the JSON config carry no zone; the catalog still has one."""
    values = specs()
    assert TextModelSpec('openai', 'positional', 'ref', '1', '2', 8192, 128, int(time.time()) + 3600)
    payload = [asdict(spec) for spec in values]
    assert all('zone' not in item and 'base_url' not in item for item in payload)
    monkeypatch.setenv('ACP_BOUNDED_TEXT_MODELS_JSON', json.dumps(payload))
    monkeypatch.setattr('providers.active_text_provider', lambda: 'openai')
    monkeypatch.setattr('providers._text_key_for', lambda _: 'fixture-key')
    monkeypatch.setattr('providers._OPENAI_TEXT_BASE_URL', 'http://10.1.2.3:8000/v1')
    assert [model['zone'] for model in chain_options([])['models']] == ['local'] * 3
    monkeypatch.setattr('providers._OPENAI_TEXT_BASE_URL', 'https://api.openai.com/v1')
    assert [model['zone'] for model in chain_options([])['models']] == ['cloud'] * 3


@pytest.mark.parametrize('rows', [
    [],
    [{'file': 'a.docx', 'criterion': '1.1.1', 'finding_count': 4}],
    [{'file': 'a.pptx', 'criterion': '2.4.6', 'finding_count': 2}],
    [{'file': 'a.pptx', 'criterion': '1.1.1', 'finding_count': 1}],
])
def test_the_default_never_offers_a_step_execution_would_not_admit(monkeypatch, rows):
    """`default_steps` and `supported` tell ONE story, on every scope.

    Defaulting the third step regardless of scope was implemented and reverted. It executed
    nothing wrongly — a chain only reaches the run policy through the explicit toggle, so
    remediation_impact.py:228's `len(steps) == 3 and not supported` refusal never fires — and
    that is precisely what would have let it ship. What it produced was a contradiction on
    screen: the frontend derives the toggle's STATE from default_steps
    (remediationGenerationChain.js:9 falls back to it when the policy carries no chain, and
    RemediationGenerationChain.jsx reads `steps.length === 3`) and its AVAILABILITY REASON
    from `supported`, so the panel rendered "Second fallback enabled" beside "a second
    fallback is not available for this scope on this server", while the run used two models.

    So the invariant is the pairing, not either field: a scope that cannot admit the third
    step is not offered it. "Set the fallbacks automatically" reaches as far as admission
    does, and widening it means widening `supported` — which guards the fail-closed adapter
    and exact source-binding checks before any third-model dispatch.
    """
    catalog(monkeypatch, FakeProviders)
    result = chain_options(rows)
    assert result['supported'] is False
    assert result['reason'] == 'Second fallback requires a supported PPTX slide-title finding with an exact source binding.'
    assert result['default_steps'] == chain(2)['steps'], rows
    assert (len(result['default_steps']) == 3) is result['supported']


def test_the_third_step_remains_optional_where_execution_admits_it(monkeypatch):
    """An available third model does not automatically add another generation step."""
    catalog(monkeypatch, FakeProviders)
    result = chain_options([{'file': 'a.pptx', 'criterion': '2.4.6', 'finding_count': 1}])
    assert result['supported'] is True
    assert result['default_steps'] == chain(2)['steps']
    assert len(result['models']) == 3


def test_two_model_configuration_still_defaults_to_two_positions(monkeypatch):
    catalog(monkeypatch, FakeProviders, size=2)
    result = chain_options([{'file': 'a.pptx', 'criterion': '2.4.6', 'finding_count': 1}])
    assert len(result['default_steps']) == len(result['models']) == 2
    assert result['supported'] is False
    assert 'fixture-model-2' not in json.dumps(result)
