"""Capture the actual app pods before teardown without shipping raw logs or inputs."""
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import sys
from contextlib import nullcontext

import pytest
from packaging_helpers import ROOT
from test_packaging_reference_kind import render

spec = importlib.util.spec_from_file_location('kind_diagnostics', ROOT / 'scripts/collect_kind_acceptance_diagnostics.py')
diagnostics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostics)


@pytest.mark.skipif(shutil.which('helm') is None, reason='helm is not installed')
def test_selector_matches_every_rendered_application_pod():
    assert diagnostics.APP_SELECTOR == 'app.kubernetes.io/instance=acp,app.kubernetes.io/component in (api,worker)'
    deployments = [d for d in render() if d['kind'] == 'Deployment']
    assert len(deployments) == 4
    for deployment in deployments:
        labels = deployment['spec']['template']['metadata']['labels']
        assert labels['app.kubernetes.io/instance'] == 'acp'
        assert labels['app.kubernetes.io/component'] in ('api', 'worker')


def test_structured_log_allowlist_drops_payloads_errors_credentials_and_document_names():
    row = {'event':'job.failed','job_id':'a'*16,'status':'dead','attempt':2,
           'error':'postgresql://admin:private@db', 'file':'Secret clinical report.pdf', 'reason':'private'}
    output = diagnostics.safe_events('postgresql://admin:private@db\n' + json.dumps(row))
    assert output == [{'event':'job.failed','job_id':'a'*16,'attempt':2,'status':'dead'}]
    assert 'private' not in json.dumps(output)


def test_capture_pods_and_database_uses_allowlisted_output_and_ignores_command_errors():
    def runner(args, **kwargs):
        assert kwargs['capture_output'] and kwargs['timeout'] == 45
        if 'get' in args:
            stdout=json.dumps({'items':[{'metadata':{'name':'api-pod','labels':{'app.kubernetes.io/component':'api'}},
                'status':{'containerStatuses':[{'ready':True,'restartCount':2}]}}]})
        elif 'logs' in args:
            stdout=json.dumps({'event':'job.claim','job_id':'a'*16,'error':'private'})
        else:
            stdout='untrusted private startup\nACP_KIND_DIAGNOSTICS='+json.dumps({'redacted':True,'jobs':[]})
        return SimpleNamespace(returncode=0,stdout=stdout,stderr='private')
    result=diagnostics.collect('kind',runner=runner)
    assert result['pod_count']==1 and result['workloads'][0]['restarts']==2
    assert result['database']=={'redacted':True,'jobs':[]}
    assert 'private' not in json.dumps(result)


@pytest.fixture
def readonly_pg(monkeypatch):
    import psycopg2
    observed=SimpleNamespace(rows=[],waits=[],queries=[],session=None,closed=False)
    class Cursor:
        def execute(self,sql):
            assert sql.startswith('SELECT '), 'diagnostics must never run schema or writes'
            observed.queries.append(sql)
        def fetchall(self):
            return observed.waits if 'pg_stat_activity' in observed.queries[-1] else observed.rows
    class Connection:
        def set_session(self,**kwargs): observed.session=kwargs
        def cursor(self,**kwargs):
            assert kwargs.get('cursor_factory') is not None
            return nullcontext(Cursor())
        def close(self): observed.closed=True
    def connect(dsn,**kwargs):
        assert dsn=='postgresql://private:test@db/test'
        assert kwargs['connect_timeout']==5
        assert 'default_transaction_read_only=on' in kwargs['options']
        assert 'statement_timeout=5000' in kwargs['options']
        return Connection()
    class NoStore:
        def __getattr__(self,name): raise AssertionError('Store must not be initialized by diagnostics')
    monkeypatch.setitem(sys.modules,'core',NoStore())
    monkeypatch.setattr(psycopg2,'connect',connect)
    monkeypatch.setenv('DATABASE_URL','postgresql://private:test@db/test')
    return observed


def test_database_diagnostic_categories_do_not_export_phase_or_last_error(monkeypatch,capsys,readonly_pg):
    readonly_pg.rows=[{
        'id':'a'*16,'type':'remediate_file','status':'queued','attempts':2,'max_attempts':5,
        'phase':'downloading Private.docx','last_error':'connection to postgresql://admin:private@db failed'}]
    monkeypatch.setitem(sys.modules,'routes.system',SimpleNamespace(_bundle_leaks=lambda *a:[],_secret_env_values=lambda:set()))
    exec(diagnostics.DB_READ,{})
    output=capsys.readouterr().out
    row=json.loads(output.split('=',1)[1])['jobs'][0]
    assert row['stage_category']=='download' and row['error_category']=='connection_failure'
    assert 'Private.docx' not in output and 'postgresql' not in output
    assert readonly_pg.session=={'readonly':True,'autocommit':False}
    assert readonly_pg.closed
    assert 'core.store' not in diagnostics.DB_READ


def test_database_refuses_artifact_when_existing_secret_checker_detects_a_match(monkeypatch,capsys,readonly_pg):
    monkeypatch.setitem(sys.modules,'routes.system',SimpleNamespace(
        _bundle_leaks=lambda *a:['jobs'],_secret_env_values=lambda:{'private-secret'}))
    exec(diagnostics.DB_READ,{})
    output=capsys.readouterr().out
    assert json.loads(output.split('=',1)[1])=={'redacted':True,'collection_status':'refused_secret_match'}
    assert 'private-secret' not in output


def test_capture_precedes_artifact_upload_and_restore_reset():
    import yaml
    workflow=yaml.safe_load((ROOT/'.github/workflows/packaging-kind.yml').read_text())
    steps=workflow['jobs']['install']['steps']
    names=[step.get('name') for step in steps]
    capture=names.index('Capture application diagnostics before the restore drill replaces pods')
    assert steps[capture]['if']=='always()'
    assert capture < names.index('Keep the acceptance report') < names.index('Is the backup restorable, or only written?')
