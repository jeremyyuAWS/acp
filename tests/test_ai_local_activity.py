"""Exact local request binding never creates a paid attempt or grants consent."""
import json
from dataclasses import replace
from types import SimpleNamespace
import pytest
from ai_run_policy import run_context
from test_ai_run_policy import seed


def local_job(store, owner='owner', scan='scan'):
    seed(store, owner=owner, scan=scan)
    batch = store.enqueue_stage_batch(scan, 'remediate', 'remediate_file', [
        {'owner': owner, 'scan_id': scan, 'file': 'a.docx',
         'remediation_impact_policy': {'ai': 1, 'ai_zone': 'local', 'ai_budget_usd': '0.00'}}],
        snapshot_id='snapshot', request_fingerprint='local')
    return store.get_job(batch['job_ids'][0])


def call(store, **changes):
    return store.record_ai_call(**(dict(surface='vision',provider='ollama',model='vision',zone='local',
        latency_ms=350,ok=True,scan_id='scan',file='a.docx',cost_usd=0,timing={'queue_wait_ms':250}) | changes))


def links(store):
    with store._db.cursor() as cur:
        store._db.execute(cur,'SELECT owner_id,run_id,trace_call_id FROM ai_local_call_execution_links')
        return store._db.fetchall(cur)


def test_real_authenticated_local_call_is_exactly_bound_and_replay_is_metadata_only(isolated_store):
    from ai_local_activity import bind_local_call
    store=isolated_store; job=local_job(store); identity=call(store)
    with run_context(store,job['payload'],job) as ctx:
        assert bind_local_call(store,ctx,identity) is True
        assert bind_local_call(store,ctx,identity) is True
    assert links(store)==[{'owner_id':'owner','run_id':job['batch_id'],'trace_call_id':identity}]
    with store._db.cursor() as cur:
        for table in ('ai_attempt_history','ai_spending_attempts'):
            store._db.execute(cur,f'SELECT COUNT(*) AS n FROM {table}')
            assert store._db.fetchone(cur)['n']==0


@pytest.mark.parametrize('changes',[{'scan_id':'foreign'}, {'file':'foreign.docx'}, {'provider':'anthropic'}, {'zone':'cloud'}, {'cost_usd':1}])
def test_foreign_or_nonlocal_evidence_is_never_bound(isolated_store,changes):
    from ai_local_activity import bind_local_call
    store=isolated_store;job=local_job(store); identity=call(store,**changes)
    with run_context(store,job['payload'],job) as ctx:
        assert bind_local_call(store,ctx,identity) is False
    assert links(store)==[]


def test_absent_forged_or_foreign_owner_context_cannot_bind(isolated_store):
    from ai_local_activity import bind_local_call
    store=isolated_store;job=local_job(store); identity=call(store)
    assert bind_local_call(store,None,identity) is False
    assert bind_local_call(store,SimpleNamespace(local_drafting=True),identity) is False
    with run_context(store,job['payload'],job) as ctx:
        assert bind_local_call(store,replace(ctx,owner_id='foreign'),identity) is False
    assert bind_local_call(store,ctx,identity) is False
    assert links(store)==[]


def test_real_trace_links_local_failures_without_inventing_usable_validation(isolated_store,monkeypatch):
    import ai,core
    store=isolated_store;job=local_job(store)
    monkeypatch.setattr(core,'store',store)
    with run_context(store,job['payload'],job):
        identity=ai._trace_ai('vision','PRIVATE_PROMPT',None,ai.time.monotonic(),ok=False,
            model='vision',scan_id='scan',file='a.docx',provider='ollama',zone='local',reason='timeout',timing={'queue_wait_ms':3})
    assert links(store)==[{'owner_id':'owner','run_id':job['batch_id'],'trace_call_id':identity}]
    assert 'PRIVATE' not in json.dumps(links(store))


def test_bound_local_metrics_include_measured_timings_and_exclude_foreign_run(isolated_store):
    from ai_local_activity import bind_local_call, read_local_activity
    store=isolated_store;job=local_job(store);success=call(store);failed=call(store,ok=False,latency_ms=100,reason='timeout')
    call(store,latency_ms=9999)  # Unbound historical call is not guessed into this run.
    with run_context(store,job['payload'],job) as ctx:
        bind_local_call(store,ctx,success);bind_local_call(store,ctx,failed)
    result=read_local_activity(store._db,'owner','scan',job['batch_id'])
    row=result['rows'][0]
    assert row['requests']==2
    assert row['successful_responses']==row['unsuccessful_requests']==1
    assert row['average_request_ms']==225
    assert row['timings']['queue_wait_ms']=={'average':250,'measured_requests':2}
    assert read_local_activity(store._db,'foreign','scan',job['batch_id'])['rows']==[]
    assert read_local_activity(store._db,'owner','foreign',job['batch_id'])['rows']==[]
    assert read_local_activity(store._db,'owner','scan','foreign')['rows']==[]
    assert 'verified repair' in result['basis']
    assert 'a.docx' not in json.dumps(result)


def test_frozen_policy_mismatch_rejects_metadata_binding(isolated_store):
    from ai_local_activity import bind_local_call
    store=isolated_store;job=local_job(store);identity=call(store)
    with run_context(store,job['payload'],job) as ctx:
        with store._db.cursor() as cur:
            store._db.execute(cur,"UPDATE ai_spending_run_policies SET policy_json='{}'")
        assert bind_local_call(store,ctx,identity) is False
    assert links(store)==[]


def test_postgres_additive_upgrade_idempotence_and_exact_local_projection(monkeypatch):
    import os,store,psycopg2
    from conftest import require_disposable_postgres
    from ai_local_activity import bind_local_call,read_local_activity
    url=os.environ.get('ACP_LOCAL_ACTIVITY_PG_TEST_URL') or os.environ.get('DATABASE_URL')
    if not url:
        pytest.skip('requires guarded disposable PostgreSQL')
    require_disposable_postgres(url)
    with psycopg2.connect(url) as connection:
        require_disposable_postgres(url,conn=connection)
        with connection.cursor() as cur:
            cur.execute('DROP SCHEMA public CASCADE')
            cur.execute('CREATE SCHEMA public')
    monkeypatch.setattr(store,'_DATABASE_URL',url)
    stores=[]
    try:
        original=store.Store();stores.append(original)
        job=local_job(original);identity=call(original)
        # Reproduce the previous deployment: ai_calls survives, binding table absent.
        with original._db.cursor() as cur:
            original._db.execute(cur,'DROP TABLE ai_local_call_execution_links')
            original._db.execute(cur,'DELETE FROM acp_schema_version')
            original._db.execute(cur,'INSERT INTO acp_schema_version(version,checksum) VALUES(%s,%s)',
                (53,'10672a4d7523cb18b78c2add1da271d8'))
        upgraded=store.Store();stores.append(upgraded)
        assert upgraded.list_ai_calls('scan')[0]['id']==identity
        assert links(upgraded)==[]  # No historical ownership inferred by migration.
        with run_context(upgraded,job['payload'],job) as ctx:
            assert bind_local_call(upgraded,ctx,identity)
            assert bind_local_call(upgraded,ctx,identity)
        assert len(links(upgraded))==1
        result=read_local_activity(upgraded._db,'owner','scan',job['batch_id'])
        assert result['rows'][0]['timings']['queue_wait_ms']=={'average':250,'measured_requests':1}
        assert read_local_activity(upgraded._db,'foreign','scan',job['batch_id'])['rows']==[]
        again=store.Store();stores.append(again)
        assert len(links(again))==1
        assert store._PgAdapter._SCHEMA_VERSION>=54
        assert store._PgAdapter._schema_checksum()==store._PgAdapter._SCHEMA_CHECKSUM_AT_VERSION
    finally:
        for instance in stores:
            if instance._db._pool is not None:
                instance._db._pool.closeall()


def test_owner_scoped_metrics_route_includes_bound_local_requests(isolated_store):
    from ai_local_activity import bind_local_call
    from waterfall_drawer_metrics import read_metrics
    store=isolated_store;job=local_job(store);identity=call(store)
    with run_context(store,job['payload'],job) as ctx:
        bind_local_call(store,ctx,identity)
    result=read_metrics(store,'owner','scan',job['batch_id'])
    assert result['local_activity']['rows'][0]['requests']==1
    assert result['models']['rows']==[]  # Do not invent a governed spending attempt.
    assert 'a.docx' not in json.dumps(result)
    with pytest.raises(LookupError):
        read_metrics(store,'foreign','scan',job['batch_id'])


def test_installed_but_noncanonical_owner_context_is_rejected(isolated_store):
    import ai_run_policy
    from ai_local_activity import bind_local_call
    store=isolated_store;job=local_job(store);identity=call(store)
    with run_context(store,job['payload'],job) as ctx:
        foreign=replace(ctx,owner_id='foreign')
        token=ai_run_policy._CURRENT.set(foreign)
        try:
            assert bind_local_call(store,foreign,identity) is False
        finally:
            ai_run_policy._CURRENT.reset(token)
    assert links(store)==[]


def test_owner_reset_removes_only_its_local_telemetry_links(isolated_store):
    from ai_local_activity import bind_local_call
    store=isolated_store
    job=local_job(store);identity=call(store)
    with run_context(store,job['payload'],job) as ctx:
        bind_local_call(store,ctx,identity)
    other=local_job(store,owner='other',scan='other-scan');other_identity=call(store,scan_id='other-scan')
    with run_context(store,other['payload'],other) as ctx:
        bind_local_call(store,ctx,other_identity)
    store.reset_user_data('owner')
    assert links(store)==[{'owner_id':'other','run_id':other['batch_id'],'trace_call_id':other_identity}]
