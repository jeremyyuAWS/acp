import json
from datetime import datetime, timezone
import pytest
from waterfall_drawer_metrics import aggregate_metrics, read_metrics

NOW = datetime(2026, 9, 9, 12, 10, tzinfo=timezone.utc)

def record(**kwargs):
    return dict(attempt_id='a', provider='openai', model='model', purpose='draft', status='drafted',
        spending_state='settled', actual_cost_units=2500, created_at='2026-09-09T12:00:00+00:00',
        updated_at='2026-09-09T12:09:45+00:00', result_json=json.dumps({'execution': {'step_id':'primary','generation_position':0}, 'validation_outcome':'usable'})) | kwargs

def chart(rows, **kwargs):
    return aggregate_metrics(rows, now=NOW, currency='USD', **kwargs)

def test_rate_and_disjoint_outcomes_have_honest_units():
    result = chart([record(), record(attempt_id='b', status='started', spending_state='dispatched')])
    assert result['pace']['value'] == 1
    assert result['pace']['unit'] == 'recorded completions/min'
    assert result['contribution']['unit'] == 'attempts'
    assert sum(r['value'] for r in result['contribution']['rows']) == 1
    assert result['spend']['total'] == .0025
    assert 'scaleMax' not in result['pace']

def test_unknown_partial_and_missing_identity_never_become_zero():
    assert chart([record(actual_cost_units=None)])['spend']['total'] is None
    assert chart([record(provider=None)])['spend']['complete'] is False
    assert chart([record()], complete=False)['pace']['value'] is None
    assert chart([record()], ledger_complete=False)['spend']['total'] is None
    assert all(p['value'] is None for p in chart([record()], complete=False)['trend']['points'])

def test_stage_and_exact_model_filters_and_missing_lineage():
    rows = [record(), record(attempt_id='b', model='other', result_json=json.dumps({'execution':{'step_id':'fallback_2','generation_position':2}}))]
    assert chart(rows, stage='fallback_2', model='other')['spend']['total'] == .0025
    assert chart(rows, stage='primary', model='other')['contribution']['rows'][0]['value'] == 0
    assert chart([record(result_json='{}')], stage='primary')['complete'] is False

def test_history_final_window_and_short_observation():
    saved = chart([record()], terminal=True)
    assert saved['pace']['windowLabel'] == 'Final recorded 60 seconds'
    assert saved['pace']['value'] == 1
    short = chart([record(created_at='2026-09-09T12:09:50+00:00')])
    assert short['pace']['value'] is None
    assert short['trend']['points'][0]['value'] is None

def test_reserved_breached_and_uncertain_are_not_settled_spend():
    rows = [record(spending_state=state) for state in ('reserved','breached','uncertain')]
    assert chart(rows)['spend']['total'] == 0
    assert chart(rows)['pace']['value'] == 0

def test_projection_contains_no_private_payload():
    result = chart([record(result_json=json.dumps({'text':'SECRET', 'execution':{'step_id':'primary','generation_position':0}}), file='PRIVATE')])
    assert 'SECRET' not in json.dumps(result)
    assert 'PRIVATE' not in json.dumps(result)

@pytest.mark.parametrize('owner,execution', [(None,None), ('other',{'owner_email':'real','scan_id':'s','stage':'remediate'}), ('real',{'owner_email':'real','scan_id':'other','stage':'remediate'})])
def test_owner_scope_before_any_query(owner, execution):
    class Store:
        def get_stage_execution(self, run_id, owner=None): return execution
    with pytest.raises(LookupError): read_metrics(Store(), owner, 's', 'r')

def test_invalid_filter_rejected_before_query():
    with pytest.raises(ValueError): read_metrics(None, 'o', 's', 'r', stage='invented')


def test_database_read_is_bounded_and_identity_preserved():
    from contextlib import contextmanager
    class DB:
        queries = []
        @contextmanager
        def cursor(self): yield self
        def execute(self, cur, query, args): self.queries.append((query, args))
        def fetchall(self, cur): return [record(attempt_id=str(i)) for i in range(1001)]
        def fetchone(self, cur): return {'currency':'USD'} if 'currency' in self.queries[-1][0] else {'n':1001}
    class Store:
        _db = DB()
        def get_stage_execution(self, run_id, owner=None): return {'owner_email':'o','scan_id':'s','stage':'remediate','state':'completed'}
        def get_scan(self, sid, owner=None): return {'id':sid}
    store = Store()
    result = read_metrics(store, 'o', 's', 'r', stage='primary')
    assert result['scan_id'] == 's' and result['run_id'] == 'r'
    assert store._db.queries[0][1] == ('o','s','r',1001)
    assert result['record_limit'] == 1000 and result['complete'] is False
    assert result['spend']['complete'] is False and result['pace']['value'] is None
    assert result['mode'] == 'recorded'
    assert 'attempt_id' not in json.dumps(result)
