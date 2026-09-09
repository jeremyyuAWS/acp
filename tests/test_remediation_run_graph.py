"""Graph projection uses explicit scope and lineage, never paid calls or chronology."""
import json
import pytest
from remediation_run_graph import project_run_graph, read_run_graph
from remediation_waterfall_view import read_waterfall
from test_remediation_waterfall_view import seed


def policy():
    return {'generation_chain': {'version': 1, 'steps': [
        {'step_id': key, 'position': n, 'provider': 'anthropic', 'model': model, 'enabled': True}
        for n, (key, model) in enumerate(zip(('primary', 'fallback_1', 'fallback_2'), ('z-primary', 'a-first', 'm-second')))]}}


def attempt(aid, step=None, **extra):
    position = {'primary': 0, 'fallback_1': 1, 'fallback_2': 2}.get(step)
    execution = {'chain_version': 1, 'step_id': step, 'generation_position': position,
                 'parent_attempt_id': extra.pop('parent', None), 'source_sha256': 'a'*64,
                 'assessment_revision': 'assessment-1', 'finding_ids': ['finding-1']}
    return dict(attempt_id=aid, operation_id='op', file='a.html', purpose='draft' if position == 0 else 'fallback',
                provider='anthropic', model={0: 'z-primary', 1: 'a-first', 2: 'm-second'}.get(position, 'legacy'),
                result_json=json.dumps({'execution': execution}), status='empty_response', spending_state='settled', **extra)


def test_configured_order_separate_purpose_and_explicit_causal_edges():
    records = [attempt('second', 'fallback_2', parent='first'), attempt('primary', 'primary'), attempt('first', 'fallback_1', parent='primary')]
    reviewer = attempt('reviewer', 'fallback_2') | {'purpose': 'review', 'model': 'review-model'}
    records.append(reviewer)
    receipt = {'operation_id': 'op', 'review_json': json.dumps({'steps': [
        {'attempt_id': 'final', 'purpose': 'final_review', 'model': 'z'},
        {'attempt_id': 'reviewer', 'purpose': 'review', 'model': 'a'}]})}
    graph = project_run_graph(policy(), records, [receipt])
    assert [s['model'] for s in graph['steps']] == ['z-primary', 'a-first', 'm-second']
    assert [s['attempt_ids'] for s in graph['steps']] == [['primary'], ['first'], ['second']]
    assert graph['attempts'][-1]['generation_position'] is None
    assert graph['attempts'][-1]['purpose'] == 'review'
    assert graph['edges'] == [{'source': 'first', 'target': 'second', 'kind': 'parent_attempt'}, {'source': 'primary', 'target': 'first', 'kind': 'parent_attempt'}]
    assert [s['purpose'] for s in graph['review_receipts'][0]['steps']] == ['final_review', 'review']


def test_legacy_does_not_fabricate_unused_models_or_causality():
    graph = project_run_graph({}, [attempt('legacy:2:0') | {'result_json': '{}'}], [])
    assert graph['coverage'] == 'partial'
    assert graph['steps'] == graph['edges'] == []
    assert graph['attempts'][0]['step_id'] is None
    assert project_run_graph({}, [], [])['coverage'] == 'unavailable'


def test_no_success_claim_from_settlement_or_draft_and_no_false_skips():
    graph = project_run_graph(policy(), [attempt('draft', 'primary') | {'status': 'drafted'}], [])
    assert all(s['state'] == 'outcome_unknown' for s in graph['steps'])
    usable = attempt('usable', 'primary')
    usable['result_json'] = json.dumps({**json.loads(usable['result_json']), 'validation_outcome': 'usable'})
    assert project_run_graph(policy(), [usable], [])['steps'][0]['state'] == 'suggestions_ready'
    graph = project_run_graph(policy(), [attempt('active', 'primary') | {'status': 'started', 'spending_state': 'dispatched'}], [])
    assert graph['steps'][0]['state'] == 'outcome_unknown'
    assert graph['steps'][0]['in_flight'] is False
    graph = project_run_graph(policy(), [attempt('lost', 'primary') | {'status': 'started', 'spending_state': 'uncertain'}], [])
    assert graph['steps'][0]['state'] == 'outcome_unknown'


def test_wrong_actual_model_or_parent_scope_stays_unattributed():
    records = [attempt('primary', 'primary') | {'file': 'different.html'}, attempt('second', 'fallback_2', parent='primary'), attempt('bad', 'fallback_1') | {'model': 'wrong'}]
    graph = project_run_graph(policy(), records, [])
    assert graph['coverage'] == 'partial'
    assert graph['edges'] == []
    assert graph['attempts'][-1]['step_id'] is None
    assert graph['attempts'][1]['parent_attempt_id'] is None


def test_complete_owner_scoped_read_has_no_history_page_limit(isolated_store):
    store = isolated_store
    run = seed(store)
    with store._db.cursor() as cur:
        store._db.execute(cur, 'UPDATE ai_spending_run_policies SET policy_json=%s WHERE owner_id=%s AND run_id=%s', (json.dumps({'ai': 1, **policy()}), 'owner', run))
        for n in range(205):
            row = attempt(f'attempt-{n}', 'primary')
            store._db.execute(cur, '''INSERT INTO ai_attempt_history(owner_id,scan_id,run_id,operation_id,attempt_id,file,input_sha256,model,provider,purpose,status,result_json,output_retention,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                ('owner', 'scan', run, 'op', row['attempt_id'], 'a.html', 'a'*64, row['model'], 'anthropic', 'draft', 'empty_response', row['result_json'], 'unavailable', str(n), str(n)))
    graph = read_run_graph(store, 'owner', 'scan', run)
    assert len(graph['attempts']) == len(graph['steps'][0]['attempt_ids']) == 205
    assert read_waterfall(store, 'owner', 'scan', run)['run_graph']['revision'] == graph['revision']
    for owner, scan, batch in [('intruder', 'scan', run), ('owner', 'different', run), ('owner', 'scan', 'other')]:
        with pytest.raises(LookupError):
            read_run_graph(store, owner, scan, batch)


def usable(aid='primary', *, skips=('fallback_1', 'fallback_2'), operation='op'):
    row = attempt(aid, 'primary') | {'status': 'drafted', 'operation_id': operation}
    row['result_json'] = json.dumps(json.loads(row['result_json']) | {
        'validation_outcome': 'usable', 'skipped_step_ids': list(skips)})
    return row


def test_unused_steps_require_terminal_run_and_explicit_skip_from_every_operation():
    records = [usable(), usable('other', operation='other-op')]
    graph = project_run_graph(policy(), records, [], terminal=True)
    assert [s['state'] for s in graph['steps']] == ['suggestions_ready', 'not_needed', 'not_needed']
    assert all(s['in_flight'] is False for s in graph['steps'])
    assert all(s['state'] != 'not_needed' for s in project_run_graph(policy(), records, [])['steps'])
    records[1] = usable('other', operation='other-op', skips=('fallback_2',))
    states = [s['state'] for s in project_run_graph(policy(), records, [], terminal=True)['steps']]
    assert states[1:] == ['outcome_unknown', 'not_needed']


@pytest.mark.parametrize('blocking', [
    attempt('unknown', 'primary') | {'operation_id': 'other-op', 'status': 'usage_unknown', 'spending_state': 'uncertain'},
    attempt('refused', 'primary') | {'operation_id': 'other-op', 'status': 'refused'},
    attempt('budget-failed', 'primary') | {'operation_id': 'other-op', 'status': 'rejected_before_dispatch', 'spending_state': 'released'},
    attempt('legacy', 'primary') | {'result_json': '{}'},
    attempt('pending', 'primary') | {'status': 'started', 'spending_state': 'dispatched'},
    attempt('fallback-attempted', 'fallback_2'),
])
def test_blockers_or_actual_dispatch_do_not_become_not_needed(blocking):
    graph = project_run_graph(policy(), [usable(), blocking], [], terminal=True)
    assert graph['steps'][2]['state'] != 'not_needed'
    assert all(s['state'] != 'not_needed' for s in project_run_graph(policy(), [], [], terminal=True)['steps'])
    assert project_run_graph({}, [usable()], [], terminal=True)['steps'] == []


@pytest.mark.parametrize('changes', [
    {'source_sha256': None}, {'assessment_revision': ''}, {'finding_ids': []},
    {'source_sha256': 'b'*64}, {'assessment_revision': 'assessment-2'}, {'finding_ids': ['other']},
])
def test_parent_edges_require_matching_nonempty_source_assessment_and_findings(changes):
    parent = attempt('primary', 'primary')
    child = attempt('first', 'fallback_1', parent='primary')
    result = json.loads(child['result_json'])
    result['execution'].update(changes)
    child['result_json'] = json.dumps(result)
    graph = project_run_graph(policy(), [parent, child], [])
    assert graph['edges'] == []
    assert graph['attempts'][1]['parent_attempt_id'] is None
    assert graph['coverage'] == 'partial'


def test_parent_edges_never_skip_positions_or_attach_reviewers():
    for child in (attempt('second', 'fallback_2', parent='primary'),
                  attempt('review', 'fallback_1', parent='primary') | {'purpose': 'review'}):
        assert project_run_graph(policy(), [attempt('primary', 'primary'), child], [])['edges'] == []


def test_read_graph_derives_terminal_flag_from_owner_scoped_execution(isolated_store):
    from ai_spending_budget import BudgetLedger
    store = isolated_store
    run = seed(store)
    row = usable()
    ledger = BudgetLedger(store._db)
    ledger.reserve('owner', run, 'primary', 10, 'test')
    ledger.claim_dispatch('owner', run, 'primary')
    ledger.settle('owner', run, 'primary', 5)
    with store._db.cursor() as cur:
        store._db.execute(cur, 'UPDATE ai_spending_run_policies SET policy_json=%s WHERE owner_id=%s AND run_id=%s',
                          (json.dumps({'ai': 1, **policy()}), 'owner', run))
        store._db.execute(cur, '''INSERT INTO ai_attempt_history(owner_id,scan_id,run_id,operation_id,attempt_id,file,input_sha256,model,provider,purpose,status,result_json,output_retention,created_at,updated_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            ('owner', 'scan', run, 'op', 'primary', 'a.html', 'a'*64, row['model'], 'anthropic', 'draft', 'drafted', row['result_json'], 'full', 'time', 'time'))
    for state in ('running', 'failed', 'cancelled', 'succeeded', 'completed'):
        with store._db.cursor() as cur:
            store._db.execute(cur, 'UPDATE stage_executions SET state=%s WHERE execution_id=%s', (state, run))
        graph = read_run_graph(store, 'owner', 'scan', run)
        assert (graph['steps'][2]['state'] == 'not_needed') is (state in ('succeeded', 'completed'))
