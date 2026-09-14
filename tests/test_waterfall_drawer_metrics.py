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


def test_real_schema_and_http_route_are_owner_scoped(tmp_path, monkeypatch):
    from store import _SQLiteAdapter
    from ai_spending_budget import BudgetLedger
    from ai_attempt_history import AttemptHistory
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes.remediation_waterfall import router
    import core
    db = _SQLiteAdapter(str(tmp_path / 'metrics.db'))
    ledger = BudgetLedger(db)
    ledger.init_schema()
    ledger.create_budget('owner@example.test', 'r', 10000)
    history = AttemptHistory(db)
    history.init_schema()
    from ai_local_activity import SCHEMA as LOCAL_ACTIVITY_SCHEMA
    with db.cursor() as cur:
        for stmt in LOCAL_ACTIVITY_SCHEMA:
            db.execute(cur,stmt)
    with db.cursor() as cur:
        db.execute(cur, 'CREATE TABLE ai_calls (id TEXT PRIMARY KEY, scan_id TEXT, file TEXT, provider TEXT, model TEXT, timing TEXT, zone TEXT, cost_usd REAL, ok INT, ts TEXT, latency_ms INT)')
    history.begin('owner@example.test', 's', 'r', 'op', 'a', file='PRIVATE.pdf', input_sha256='a' * 64,
                  provider='openai', model='model', purpose='draft')
    with db.cursor() as cur:
        db.execute(cur, 'UPDATE ai_attempt_history SET status=%s,result_json=%s,created_at=%s,updated_at=%s',
                   ('drafted', record()['result_json'], record()['created_at'], record()['updated_at']))
        db.execute(cur, 'INSERT INTO ai_calls(id,scan_id,file,provider,model,timing) VALUES(%s,%s,%s,%s,%s,%s)',
                   ('call', 's', 'PRIVATE.pdf', 'openai', 'model', '{"model_load_ms": 12, "inference_ms": 80}'))
        db.execute(cur, 'INSERT INTO ai_attempt_trace_links VALUES(%s,%s,%s,%s)',
                   ('owner@example.test', 'r', 'a', 'call'))
        db.execute(cur, 'INSERT INTO ai_calls(id,scan_id,file,provider,model,timing) VALUES(%s,%s,%s,%s,%s,%s)',
                   ('wrong-scan', 'another-scan', 'PRIVATE.pdf', 'openai', 'model', '{"model_load_ms": 9999}'))
        db.execute(cur, 'INSERT INTO ai_attempt_trace_links VALUES(%s,%s,%s,%s)',
                   ('owner@example.test', 'r', 'a', 'wrong-scan'))
        db.execute(cur, 'INSERT INTO ai_spending_attempts VALUES(%s,%s,%s,%s,%s,%s,%s)',
                   ('owner@example.test', 'r', 'a', 3000, 'fixture', 'settled', 2500))
    class Store:
        _db = db
        def get_stage_execution(self, run_id, owner=None):
            return {'owner_email': 'owner@example.test', 'scan_id': 's', 'stage': 'remediate', 'state': 'completed'} if run_id == 'r' else None
        def get_scan(self, scan_id, owner=None):
            return {'id': 's'} if scan_id == 's' and owner == 'owner@example.test' else None
    monkeypatch.setattr(core, 'store', Store())
    app = FastAPI()
    @app.middleware('http')
    async def owner(request, call_next):
        request.state.user_email = request.headers.get('x-test-owner', 'owner@example.test')
        return await call_next(request)
    app.include_router(router)
    client = TestClient(app)
    response = client.get('/scans/s/remediation/waterfall/r/metrics?stage=primary&provider=openai&model=model')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    payload = response.json()
    assert payload['models']['rows'][0]['provider_timing']['model_load_ms'] == {'average': 12, 'measured_attempts': 1}
    assert payload['spend']['total'] == .0025
    assert payload['contribution']['rows'][0]['value'] == 1
    assert payload['scope'] == {'stage': 'primary', 'provider': 'openai', 'model': 'model'}
    assert 'PRIVATE' not in response.text
    assert client.get('/scans/s/remediation/waterfall/r/metrics', headers={'x-test-owner': 'other'}).status_code == 404
    assert client.get('/scans/other/remediation/waterfall/r/metrics').status_code == 404


def test_individual_cloud_usage_retains_tokens_without_private_payload():
    result = chart([record(result_json=json.dumps({'prompt_tokens': 120, 'completion_tokens': 40, 'text': 'PRIVATE OUTPUT'})),
                    record(attempt_id='b', provider='anthropic', model='sonnet', result_json=json.dumps({'prompt_tokens': 90, 'completion_tokens': 20})),
                    record(attempt_id='c', spending_state='released')])
    rows = {r['label']: r for r in result['models']['rows']}
    assert rows['openai · model']['input_tokens'] == 120
    assert rows['openai · model']['output_tokens'] == 40
    assert rows['openai · model']['average_seconds'] == 585
    assert rows['anthropic · sonnet']['value'] == 1
    assert sum(r['value'] for r in rows.values()) == 2
    assert 'PRIVATE OUTPUT' not in json.dumps(result)


def test_unknown_tokens_and_invalid_timing_are_not_zero_or_negative():
    result = chart([record(), record(attempt_id='b', updated_at='2026-09-09T11:00:00Z')])
    row = result['models']['rows'][0]
    assert row['input_tokens'] is None and row['output_tokens'] is None
    assert row['timed_attempts'] == 1
    assert row['average_seconds'] == 585
    assert chart([record(status='started', spending_state='dispatched')])['models']['rows'][0]['active'] == 1


def test_model_quality_coverage_and_duration_distribution_are_observed():
    rows = [record(attempt_id='usable', created_at='2026-09-09T12:09:44+00:00'),
            record(attempt_id='refused', status='refused', created_at='2026-09-09T12:09:35+00:00', result_json='{}'),
            record(attempt_id='unknown', created_at='2026-09-09T12:09:42+00:00', result_json='{}'),
            record(attempt_id='active', status='started', spending_state='dispatched')]
    model = chart(rows)['models']['rows'][0]
    assert model['usable_outputs'] == 1
    assert model['no_usable_output'] == 1
    assert model['validation_unavailable'] == 1
    assert model['validated_attempts'] == 2
    assert model['usable_percent'] == 50
    assert model['median_seconds'] == 3
    assert model['p95_seconds'] == 10


def test_unknown_quality_is_unavailable_and_partial_window_is_labelled():
    row = chart([record(result_json='{}')], complete=False)['models']['rows'][0]
    assert row['usable_percent'] is None
    assert row['validated_attempts'] == 0
    assert row['validation_unavailable'] == 1
    assert row['quality_complete'] is False


def test_measured_provider_timings_have_field_specific_coverage_and_numeric_allowlist():
    model = chart([record(measured_timing=json.dumps({'model_load_ms': 100, 'inference_ms': 200, 'secret': 'SECRET'})),
                   record(attempt_id='b', measured_timing=json.dumps({'inference_ms': 400, 'model_load_ms': -1})),
                   record(attempt_id='c', measured_timing='not JSON')])['models']['rows'][0]
    assert model['provider_timing']['model_load_ms'] == {'average': 100, 'measured_attempts': 1}
    assert model['provider_timing']['inference_ms'] == {'average': 300, 'measured_attempts': 2}
    assert 'SECRET' not in json.dumps(model)


def test_queue_wait_projection_preserves_observed_measurement_coverage():
    row = chart([record(measured_timing=json.dumps({'queue_wait_ms': 100})),
                 record(attempt_id='b', measured_timing=json.dumps({'queue_wait_ms': 300})),
                 record(attempt_id='legacy')])['models']['rows'][0]
    assert row['provider_timing']['queue_wait_ms'] == {'average': 200, 'measured_attempts': 2}
    assert chart([record()])['models']['rows'][0]['provider_timing'] == {}
