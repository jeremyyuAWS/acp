"""No network, credentials, real documents, or paid model calls."""
from dataclasses import replace
from copy import deepcopy
import json

import pytest

from llm_remediation_waterfall import (
    Evidence, Generation, Model, Request, apply_html_language,
    run_waterfall, verify_html_language,
)


SOURCE = '<!DOCTYPE html>\n<html><body><p>Hello &amp; welcome</p></body></html>\n'
REQUEST = Request('fix-1', SOURCE, 'html-root-language', 'auto', True, 'en', 'metadata:42')
MODELS = (Model('small', '0.02'), Model('large', '0.05'))


class Harness:
    def __init__(self):
        self.calls = []
        self.snapshots = []
        self.languages = ['en', 'en']

    def reserve(self, key, model, maximum):
        self.calls.append(('reserve', key, model, maximum))
        return key

    def generate(self, model, request):
        self.calls.append(('generate', model))
        return Generation({'language': self.languages.pop(0)}, '0.01', 'call-42')

    def claim_dispatch(self, token):
        self.calls.append(('dispatch', token))
        return True

    def mark_uncertain(self, token, reason):
        self.calls.append(('uncertain', token, reason))

    def settle(self, token, cost):
        self.calls.append(('settle', token, cost))

    def persist(self, state):
        self.snapshots.append(json.loads(json.dumps(state)))

    def run(self, request=REQUEST, **overrides):
        callbacks = dict(generate=self.generate, reserve=self.reserve, claim_dispatch=self.claim_dispatch, settle=self.settle,
                         mark_uncertain=self.mark_uncertain,
                         apply_to_copy=apply_html_language, verify=verify_html_language,
                         persist=self.persist)
        callbacks.update(overrides)
        return run_waterfall(request, MODELS, **callbacks)


def fail(*args):
    raise RuntimeError('fixture failure')


def test_auto_verified_first_model_and_durable_trace():
    h = Harness()
    result = h.run()
    assert result['status'] == 'approved'
    assert result['candidate'] == SOURCE.replace('<html>', '<html lang="en">')
    assert len(result['attempts']) == 1
    attempt = result['attempts'][0]
    assert attempt['cost_usd'] == '0.01'
    assert attempt['model'] == 'small'
    assert attempt['evidence']['no_content_loss'] is True
    assert [call[0] for call in h.calls] == ['reserve', 'dispatch', 'generate', 'settle']
    assert [s['attempts'][-1]['status'] for s in h.snapshots if s['attempts']] == [
        'reserving', 'dispatching', 'generating', 'settling', 'verifying', 'verified']
    assert REQUEST.source == SOURCE


def test_two_models_bounded_with_rejected_evidence_recorded():
    h = Harness()
    h.languages = ['fr', 'en']
    result = h.run()
    assert result['status'] == 'approved'
    assert [a['model'] for a in result['attempts']] == ['small', 'large']
    assert result['attempts'][0]['evidence']['issue_resolved'] is False
    assert result['attempts'][0]['reasons']


def test_both_models_exhausted():
    h = Harness()
    h.languages = ['fr', 'de']
    result = h.run()
    assert result['status'] == 'exception'
    assert result['candidate'] is None
    assert result['reasons'][0].startswith('attempts_exhausted:')
    assert len(result['attempts']) == 2


@pytest.mark.parametrize('req', [replace(REQUEST, mode='hitl'), replace(REQUEST, auto_eligible=False)])
def test_verified_does_not_bypass_human_policy(req):
    result = Harness().run(req)
    assert result['status'] == 'awaiting_approval'
    assert result['candidate']


def test_family_allowlist_cannot_be_overridden_by_eligible_flag():
    result = Harness().run(replace(REQUEST, family='alt-text'),
        verify=lambda *a: Evidence('fixture', True, True, True, True, True))
    assert result['status'] == 'awaiting_approval'


@pytest.mark.parametrize('field', ['objective', 'issue_resolved', 'no_content_loss', 'no_regression', 'scope_preserved'])
@pytest.mark.parametrize('value', [None, 'true', 1])
def test_unknown_or_non_boolean_evidence_never_approves(field, value):
    h = Harness()
    evidence = replace(Evidence('fixture', True, True, True, True, True), **{field: value})
    result = h.run(verify=lambda *args: evidence)
    assert result['status'] == 'exception'
    assert result['reasons'][0].startswith('unknown_evidence:')
    assert len(result['attempts']) == 1


def test_subjective_evidence_stops_even_with_model_agreement():
    result = Harness().run(verify=lambda *a: Evidence('second-model-agrees', False, True, True, True, True))
    assert result['status'] == 'exception'
    assert result['reasons'][0].startswith('subjective_decision:')


@pytest.mark.parametrize('callback,reason', [('reserve', 'cost_failure:'),
    ('claim_dispatch', 'cost_failure:'), ('generate', 'unknown_usage:'), ('settle', 'cost_failure:'),
    ('apply_to_copy', 'unknown_evidence:'), ('verify', 'unknown_evidence:')])
def test_callback_errors_fail_closed(callback, reason):
    h = Harness()
    result = h.run(**{callback: fail})
    assert result['status'] == 'exception'
    assert result['reasons'][0].startswith(reason)
    assert len(result['attempts']) == 1
    assert result['candidate'] is None
    if callback == 'reserve':
        assert h.calls == []


@pytest.mark.parametrize('cost', ['NaN', 'Infinity', '-0.01', 'nonsense', None, 0.01])
def test_invalid_usage_keeps_reservation_for_reconciliation(cost):
    h = Harness()
    result = h.run(generate=lambda *a: Generation({'language': 'en'}, cost))
    assert result['status'] == 'exception'
    assert result['reasons'][0].startswith('unknown_usage:')
    assert not any(c[0] == 'settle' for c in h.calls)


def test_overrun_is_accounted_but_blocks_approval():
    h = Harness()
    result = h.run(generate=lambda *a: Generation({'language': 'en'}, '0.03'))
    assert ('settle', 'fix-1:1', '0.03') in h.calls
    assert result['status'] == 'exception'
    assert 'exceeded' in result['reasons'][0]


def test_persistence_failure_prevents_provider_call():
    h = Harness()
    def persist(state):
        if state['attempts'] and state['attempts'][-1]['status'] == 'generating':
            raise OSError('disk full')
        h.persist(state)
    with pytest.raises(OSError):
        h.run(persist=persist)
    assert not any(c[0] == 'generate' for c in h.calls)


def test_every_interrupted_stage_stops_without_duplicate_effects():
    h = Harness()
    h.run()
    for snapshot in h.snapshots:
        if snapshot['status'] != 'running':
            continue
        fresh = Harness()
        result = fresh.run(previous=snapshot)
        assert result['status'] == 'exception'
        assert result['reasons'][-1].startswith('interrupted_attempt:')
        assert fresh.calls == []


def test_terminal_replay_has_no_effects_and_config_changes_rejected():
    h = Harness()
    result = h.run()
    assert Harness().run(previous=result, persist=fail, generate=fail) == result
    with pytest.raises(ValueError, match='does not match'):
        Harness().run(replace(REQUEST, mode='hitl'), previous=result)


def test_initial_durable_state_can_resume():
    h = Harness()
    h.run()
    assert Harness().run(previous=h.snapshots[0])['status'] == 'approved'


@pytest.mark.parametrize('changed', [
    lambda s: s.replace('Hello', ''),
    lambda s: s.replace('<p>', '<p style="color:white">'),
    lambda s: s.replace('lang="en"', 'lang="fr"'),
    lambda s: s.replace('&amp;', '&'),
    lambda s: s + '<script>alert(1)</script>',
])
def test_independent_verifier_rejects_content_loss_scope_and_regression(changed):
    candidate = apply_html_language(SOURCE, {'language': 'en'})
    evidence = verify_html_language(REQUEST, changed(candidate))
    assert not evidence.accepted()
    assert evidence.scope_preserved is False


@pytest.mark.parametrize('source', [
    '<html lang="en" lang="fr"><body>Hi</body></html>',
    '<html xml:lang="fr"><body>Hi</body></html>',
    '<html><html>Hi</html></html>',
    '<html><body>Hi</body>',
    '<html><!-- </html> -->Hi</html>',
])
def test_ambiguous_markup_fails_closed(source):
    request = replace(REQUEST, source=source)
    evidence = verify_html_language(request, source)
    assert not evidence.accepted()


def test_missing_authority_is_unknown():
    result = Harness().run(replace(REQUEST, authority_ref=''))
    assert result['status'] == 'exception'
    assert result['reasons'][0].startswith('unknown_evidence:')


@pytest.mark.parametrize('patch', [{'language': 'en', 'confidence': 1},
    {'language': 'en" onload="evil'}, {'language': 'english'}, {'content': 'new document'}])
def test_structured_patch_rejects_extra_fields_or_injection(patch):
    with pytest.raises(ValueError):
        apply_html_language(SOURCE, patch)


def test_invalid_configuration_rejected_before_reservation():
    h = Harness()
    with pytest.raises(ValueError):
        h.run(replace(REQUEST, mode='maybe'))
    with pytest.raises(ValueError):
        run_waterfall(REQUEST, (MODELS[0], MODELS[0]), generate=fail,
            reserve=fail, claim_dispatch=fail, settle=fail, mark_uncertain=fail,
            apply_to_copy=fail, verify=fail, persist=fail)
    assert h.calls == []


@pytest.mark.parametrize('claim', [False, None, 1, 'true'])
def test_dispatch_must_be_explicitly_granted(claim):
    h = Harness()
    result = h.run(claim_dispatch=lambda *a: claim)
    assert result['status'] == 'exception'
    assert not any(c[0] == 'generate' for c in h.calls)


def test_generation_failure_marks_budget_uncertain():
    h = Harness()
    result = h.run(generate=fail)
    assert ('uncertain', 'fix-1:1', 'generation_or_usage_unknown') in h.calls
    assert result['status'] == 'exception'


def test_uncertainty_record_failure_still_stops():
    result = Harness().run(generate=fail, mark_uncertain=fail)
    assert result['status'] == 'exception'
    assert any('uncertainty_record_failed' in reason for reason in result['attempts'][0]['reasons'])


def test_budget_adapter_bindings_rounding_and_breach():
    from llm_remediation_waterfall import BudgetAdapter
    class Ledger:
        calls = []
        def reserve(self, *args, **kwargs):
            self.calls.append(('reserve', args, kwargs))
            return {'state': 'reserved'}
        def claim_dispatch(self, *args):
            self.calls.append(('claim', args))
            return True
        def settle(self, *args, **kwargs):
            self.calls.append(('settle', args, kwargs))
            return {'state': 'breached'}
        def mark_uncertain(self, *args):
            self.calls.append(('uncertain', args))
    ledger = Ledger()
    adapter = BudgetAdapter(ledger, 'owner', 'run', {'small': 'verified-price-v1'})
    token = adapter.reserve('fix:1', 'small', '0.0000001')
    assert token == 'fix:1'
    assert ledger.calls[0] == ('reserve', ('owner', 'run', 'fix:1'),
        {'max_cost_units': 1, 'pricing_ref': 'verified-price-v1'})
    assert adapter.claim_dispatch(token) is True
    with pytest.raises(ValueError, match='settlement'):
        adapter.settle(token, '0.0000011')
    assert ledger.calls[-1][2]['actual_cost_units'] == 2
    adapter.mark_uncertain(token, 'fixture')
    assert ledger.calls[-1] == ('uncertain', ('owner', 'run', 'fix:1'))


def test_all_persistence_failures_block_later_effects():
    baseline = Harness()
    baseline.run()
    for failure_at in range(len(baseline.snapshots)):
        h = Harness()
        count = 0
        effects_at_failure = None
        def persist(state):
            nonlocal count, effects_at_failure
            if count == failure_at:
                effects_at_failure = deepcopy(h.calls)
                raise OSError('fixture interruption')
            count += 1
            h.persist(state)
        with pytest.raises(OSError):
            h.run(persist=persist)
        assert h.calls == effects_at_failure
        if h.snapshots:
            recovered = Harness()
            result = recovered.run(previous=h.snapshots[-1])
            if h.snapshots[-1]['status'] == 'running':
                assert recovered.calls == []
                assert result['status'] == 'exception'


@pytest.mark.parametrize('scenario', ['success', 'fallback', 'denied', 'timeout', 'overrun'])
def test_spending_ledger_integration(tmp_path, scenario):
    # Activated when the independently owned spending module is integrated or on PYTHONPATH.
    spending = pytest.importorskip('ai_spending_budget')
    from store import _SQLiteAdapter
    from llm_remediation_waterfall import BudgetAdapter
    ledger = spending.BudgetLedger(_SQLiteAdapter(str(tmp_path / 'budget.db')))
    ledger.init_schema()
    ledger.create_budget('owner', 'run', 1 if scenario == 'denied' else 100_000)
    budget = BudgetAdapter(ledger, 'owner', 'run', {'small': 'fixture-v1', 'large': 'fixture-v1'})
    h = Harness()
    if scenario == 'fallback':
        h.languages = ['fr', 'en']
    generate = h.generate
    if scenario == 'timeout':
        generate = fail
    elif scenario == 'overrun':
        generate = lambda *a: Generation({'language': 'en'}, '0.03')
    result = h.run(reserve=budget.reserve, claim_dispatch=budget.claim_dispatch,
        settle=budget.settle, mark_uncertain=budget.mark_uncertain, generate=generate)
    snapshot = ledger.snapshot('owner', 'run')
    if scenario in {'success', 'fallback'}:
        assert result['status'] == 'approved'
        assert snapshot['held_units'] == 0
        assert snapshot['spent_units'] == (20_000 if scenario == 'fallback' else 10_000)
        # Even if a caller loses the waterfall snapshot, the ledger denies redispatch.
        duplicate = h.run(reserve=budget.reserve, claim_dispatch=budget.claim_dispatch,
            settle=budget.settle, mark_uncertain=budget.mark_uncertain, generate=fail)
        assert duplicate['status'] == 'exception'
    else:
        assert result['status'] == 'exception'
        if scenario == 'timeout':
            assert snapshot['held_units'] == 20_000
            assert snapshot['blocked']
        elif scenario == 'overrun':
            assert snapshot['spent_units'] == 30_000
            assert snapshot['blocked']
        else:
            assert not h.calls
