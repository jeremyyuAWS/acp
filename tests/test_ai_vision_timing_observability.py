"""Measured GPU timing survives the real vision→trace→durable path, without content."""
import json
from types import SimpleNamespace
import pytest
from ollama_runtime import safe_timings

MEASURED = {'total_ms': 28677.359, 'model_load_ms': 4888.087,
            'prompt_eval_ms': 20948.857, 'inference_ms': 2803.053,
            'output_tokens_per_second': 3.211}

@pytest.mark.parametrize('invalid', [None, 'PRIVATE', [], {
    'model_load_ms': True, 'prompt_eval_ms': float('nan'), 'total_ms': float('inf'),
    'inference_ms': -1, 'output_tokens_per_second': 10**10000, 'payload': 'PRIVATE'}])
def test_numeric_allowlist_rejects_non_measurements(invalid):
    assert safe_timings(invalid) == {}


def test_actual_vision_trace_and_durable_row_keep_only_numeric_measurements(isolated_store, monkeypatch):
    import ai, core, providers, lf
    generations = []
    class Trace:
        def generation(self, **kwargs):
            generations.append(kwargs)
            return SimpleNamespace(end=lambda: None)
    monkeypatch.setattr(core, 'store', isolated_store)
    monkeypatch.setattr(lf, '_lf', lambda: SimpleNamespace(trace=lambda **kwargs: Trace()))
    monkeypatch.setattr(ai, 'provenance', lambda: {'zone': 'local'})
    response = {'ok': True, 'text': 'A solid blue square.', 'model': 'llava:13b',
                'provider': 'ollama', 'zone': 'local', 'reason': 'ok',
                'timing': {**MEASURED, 'payload': 'PRIVATE_PAYLOAD', 'endpoint': 'PRIVATE_URL'}}
    provider = SimpleNamespace(name='ollama', model='llava:13b', base_url='', zone='local',
                               generate=lambda *args, **kwargs: response)
    monkeypatch.setattr(providers, 'active_vision_provider', lambda: provider)
    value = ai._vision_generate('PRIVATE_PROMPT', b'PRIVATE_IMAGE', scan_id='scan', file='document.docx')
    assert value == 'A solid blue square.'
    row = isolated_store.list_ai_calls('scan')[0]
    timing = json.loads(row['timing'])
    assert timing.pop('queue_wait_ms') >= 0
    assert timing == MEASURED
    trace_timing = dict(generations[0]['metadata']['timing'])
    assert trace_timing.pop('queue_wait_ms') >= 0
    assert trace_timing == MEASURED
    assert 'PRIVATE' not in json.dumps(row) + json.dumps(generations)
    assert row['latency_ms'] >= 0


def test_direct_durable_writer_sanitizes_and_legacy_calls_stay_nullable(isolated_store):
    common = dict(surface='vision', provider='ollama', model='llava:13b', zone='local',
                  latency_ms=120, ok=True)
    isolated_store.record_ai_call(**common, timing={**MEASURED, 'content': 'PRIVATE'})
    isolated_store.record_ai_call(**common)
    rows = isolated_store.list_ai_calls()
    assert sorted(bool(row['timing']) for row in rows) == [False, True]
    assert 'PRIVATE' not in json.dumps(rows)
    assert json.loads(next(row['timing'] for row in rows if row['timing'])) == MEASURED


def test_sqlite_upgrade_preserves_legacy_rows_and_adds_nullable_timing(isolated_store):
    import store
    isolated_store.record_ai_call(surface='legacy', provider='ollama', model='m', zone='local',
                                 latency_ms=1, ok=True)
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur, 'ALTER TABLE ai_calls DROP COLUMN timing')
    upgraded = store.Store()
    rows = upgraded.list_ai_calls()
    assert len(rows) == 1 and rows[0]['surface'] == 'legacy' and rows[0]['timing'] is None
    upgraded.record_ai_call(surface='vision', provider='ollama', model='m', zone='local',
                            latency_ms=1, ok=True, timing=MEASURED)
    assert any(row['timing'] for row in upgraded.list_ai_calls())


def test_postgres_upgrade_and_real_parameterized_timing_write(monkeypatch):
    import os, store
    url = os.environ.get('ACP_GPU_TIMING_PG_TEST_URL') or os.environ.get('DATABASE_URL')
    if not url:
        pytest.skip('set ACP_GPU_TIMING_PG_TEST_URL to a guarded disposable PostgreSQL')
    import psycopg2
    from conftest import require_disposable_postgres
    require_disposable_postgres(url)
    with psycopg2.connect(url) as conn:
        require_disposable_postgres(url, conn=conn)
        with conn.cursor() as cur:
            # Own disposable database only; reproduce a pre-timing table plus retained row.
            cur.execute('DROP TABLE IF EXISTS ai_calls CASCADE')
            cur.execute('DROP TABLE IF EXISTS acp_schema_version')
            cur.execute('CREATE TABLE acp_schema_version(version INTEGER PRIMARY KEY, checksum TEXT)')
            cur.execute('INSERT INTO acp_schema_version(version,checksum) VALUES(%s,%s)',
                        (52, '16c3b2ce6b5b581d9f86dcfe680078d2'))
            cur.execute(next(stmt for stmt in store._SCHEMA if stmt.startswith('CREATE TABLE IF NOT EXISTS ai_calls')))
            cur.execute("INSERT INTO ai_calls(id,surface,provider,model,zone,latency_ms,ok) VALUES('legacy','legacy','ollama','m','local',1,1)")
    monkeypatch.setattr(store, '_DATABASE_URL', url)
    upgraded = store.Store()
    try:
        upgraded.record_ai_call(surface='vision', provider='ollama', model='m', zone='local',
                                latency_ms=1, ok=True, timing={**MEASURED, 'payload': 'PRIVATE'})
        rows = upgraded.list_ai_calls()
        assert next(row for row in rows if row['id'] == 'legacy')['timing'] is None
        assert json.loads(next(row['timing'] for row in rows if row['surface'] == 'vision')) == MEASURED
        assert 'PRIVATE' not in json.dumps(rows)
    finally:
        if upgraded._db._pool is not None:
            upgraded._db._pool.closeall()
