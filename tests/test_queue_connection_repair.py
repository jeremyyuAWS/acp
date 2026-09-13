"""Legacy application DSNs must not leak or break KEDA's stricter URI parser."""
import importlib.util
from pathlib import Path
from urllib.parse import unquote, urlsplit
import pytest

spec = importlib.util.spec_from_file_location('queue_connection_repair', Path(__file__).resolve().parents[1] / 'deploy/public/repair_queue_connection.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


@pytest.mark.parametrize('password', ['legacy:p-word', 'already%2Fencoded%40word', 'simple-word'])
def test_reserved_password_roundtrips_without_changing_application_secret(password):
    raw = 'postgresql://user:' + password + '@db.test:5432/acp?sslmode=require'
    expected_password = unquote(password)
    fixed = helper.canonical_connection(raw)
    parsed = urlsplit(fixed)
    assert parsed.hostname == 'db.test'
    assert parsed.port == 5432
    assert unquote(parsed.password) == expected_password
    assert parsed.query == 'sslmode=require'
    assert helper.canonical_connection(fixed) == fixed


def test_bad_host_exception_does_not_include_credential_or_url():
    with pytest.raises(ValueError) as error:
        helper.canonical_connection('postgresql://user:private@db.test:private/acp')
    assert 'private' not in str(error.value)


def test_patch_preserves_application_env_other_secrets_and_scale_bounds():
    app = {'properties': {'configuration': {'secrets': [{'name': 'database-url'}, {'name': 'other', 'keyVaultUrl': 'https://vault.test/secret', 'identity': 'system'}]},
           'template': {'containers': [{'env': [{'name': 'DATABASE_URL', 'secretRef': 'database-url'}]}],
                        'scale': {'minReplicas': 5, 'maxReplicas': 10, 'rules': [{'name': 'queue', 'custom': {'type': 'postgresql', 'metadata': {'query': 'preserve'}, 'auth': [{'triggerParameter': 'connection', 'secretRef': 'database-url'}]}}]}}}}
    patch = helper.repair_patch(app, [{'name': 'database-url', 'value': "host=db.test port=5432 dbname=acp user=u password='p/word'"}])
    assert patch['properties']['template']['containers'] == app['properties']['template']['containers']
    assert patch['properties']['configuration']['secrets'][0] == {'name': 'database-url', 'value': "host=db.test port=5432 dbname=acp user=u password='p/word'"}
    assert patch['properties']['configuration']['secrets'][1] == app['properties']['configuration']['secrets'][1]
    scale = patch['properties']['template']['scale']
    assert (scale['minReplicas'], scale['maxReplicas']) == (5, 10)
    assert scale['rules'][0]['custom']['auth'][0]['secretRef'] == 'database-url-keda'
    assert app['properties']['template']['scale']['rules'][0]['custom']['auth'][0]['secretRef'] == 'database-url'
    second = {'properties': patch['properties']}
    repeated = helper.repair_patch(second, [{'name': 'database-url', 'value': "host=db.test port=5432 dbname=acp user=u password='p/word'"}] + patch['properties']['configuration']['secrets'][1:])
    assert repeated == patch


def test_keyword_dsn_reserved_password_matches_real_libpq():
    from psycopg2.extensions import parse_dsn
    raw = "host=db.test port=5432 dbname=acp user=u password='p/word@tail:colon#hash?query' sslmode=require"
    fixed = helper.canonical_connection(raw)
    assert parse_dsn(raw) == parse_dsn(fixed)
    assert urlsplit(fixed).port == 5432


def test_ambiguous_malformed_uri_fails_without_guessing_credentials():
    with pytest.raises(ValueError):
        helper.canonical_connection('postgresql://u:pass@tail@db.test:5432/acp')


def test_normal_deploy_paths_repair_scaler_after_worker_guard_and_cutover():
    root = Path(__file__).resolve().parents[1]
    redeploy = (root / 'deploy/public/redeploy.sh').read_text()
    assert redeploy.count('repair_queue_connection.py') == 2
    guard = redeploy.index('if [ "$ALLOW_ACTIVE_JOBS" != 1 ]')
    assert redeploy.index('repair_queue_connection.py') > guard
    assert redeploy.index('repair_queue_connection.py') > redeploy.index('_verify_remediation_scaler')
    deploy = (root / 'deploy/public/deploy.sh').read_text()
    assert deploy.index('repair_queue_connection.py') > deploy.index('  _apply_worker_scale_rule\n')


def test_malformed_scaler_secret_is_not_used_instead_of_working_application_dsn():
    app = {'properties': {'configuration': {'secrets': [{'name': 'database-url'}, {'name': 'stale-scaler'}]},
           'template': {'containers': [{'env': [{'name': 'DATABASE_URL', 'secretRef': 'database-url'}]}],
                        'scale': {'rules': [{'custom': {'type': 'postgresql', 'auth': [{'triggerParameter': 'connection', 'secretRef': 'stale-scaler'}]}}]}}}}
    valid = 'postgresql://u:p%40word@db.test:5432/acp?sslmode=require'
    patch = helper.repair_patch(app, [{'name': 'database-url', 'value': valid}, {'name': 'stale-scaler', 'value': 'postgresql://u:p@tail@db.test:bad/acp'}])
    assert helper.canonical_connection(patch['properties']['configuration']['secrets'][-1]['value']) == helper.canonical_connection(valid)
    assert patch['properties']['template']['containers'] == app['properties']['template']['containers']


def test_live_shape_uri_without_explicit_port_roundtrips_default_port():
    from psycopg2.extensions import parse_dsn
    source = 'postgresql://u:p%3Aword@db.test/acp?sslmode=require'
    fixed = helper.canonical_connection(source)
    before = parse_dsn(source)
    before['port'] = '5432'
    assert parse_dsn(fixed) == before


def test_pipeline_provisions_authoritative_libpq_parser_before_deploy():
    pipeline = (Path(__file__).resolve().parents[1] / '.github/workflows/deploy.yml').read_text()
    assert pipeline.index('psycopg2-binary>=2.9,<3') < pipeline.index('run: bash deploy/public/redeploy.sh')


def test_live_cli_template_schema_is_preserved_and_already_repaired_is_noop(monkeypatch, capsys):
    from copy import deepcopy
    connection = 'postgresql://u:p@db.test:5432/acp'
    app = {'id': '/subscriptions/test/resourceGroups/group/providers/Microsoft.App/containerapps/worker', 'properties': {'configuration': {'secrets': [{'name': 'database-url'}]},
           'template': {'customMetricsSettings': {'enable': True}, 'containers': [{'name': 'worker', 'image': 'registry.test/worker:v20',
                                       'imageType': 'ContainerImage',
                                       'resources': {'cpu': 2, 'memory': '4Gi'},
                                       'env': [{'name': 'DATABASE_URL', 'secretRef': 'database-url'}]}],
                        'scale': {'minReplicas': 5, 'maxReplicas': 10, 'rules': [{'custom': {'type': 'postgresql', 'auth': [{'triggerParameter': 'connection', 'secretRef': 'database-url'}]}}]}}}}
    original = deepcopy(app)
    secrets = [{'name': 'database-url', 'value': connection}]
    patch = helper.repair_patch(app, secrets)
    container = patch['properties']['template']['containers'][0]
    assert container == original['properties']['template']['containers'][0]
    assert patch['properties']['template']['customMetricsSettings'] == {'enable': True}
    assert helper.ARM_API_VERSION == '2025-10-02-preview'  # Older 2025-07-01 rejects these actual CLI fields.
    assert app == original

    # A subsequent CLI read adds imageType again; it must still be a no-op.
    repaired = deepcopy(app)
    repaired['properties']['template']['scale'] = patch['properties']['template']['scale']
    live_secrets = secrets + [{'name': 'database-url-keda', 'value': helper.canonical_connection(connection)}]
    calls = []
    def azure(*args):
        calls.append(args)
        if args[:3] == ('containerapp', 'secret', 'list'):
            return live_secrets
        if args[:2] == ('containerapp', 'show'):
            cli = deepcopy(repaired)
            cli['properties']['template']['futureUnsupportedField'] = True
            return cli
        if args[:3] == ('rest', '--method', 'get'):
            assert args[-1].endswith('?api-version=' + helper.ARM_API_VERSION)
            return repaired
        pytest.fail('An already-correct scaler must not issue another ARM PATCH')
    monkeypatch.setattr(helper, 'azure', azure)
    helper.repair('group', 'worker')
    assert 'already verified' in capsys.readouterr().out
    assert len(calls) == 3


def test_full_secret_patch_hydrates_literal_values_and_fails_closed_if_unresolved():
    app = {'properties': {'configuration': {'secrets': [{'name': 'database-url'}, {'name': 'other'}]},
           'template': {'containers': [{'env': [{'name': 'DATABASE_URL', 'secretRef': 'database-url'}]}],
                        'scale': {'rules': [{'custom': {'type': 'postgresql', 'auth': [{'triggerParameter': 'connection', 'secretRef': 'database-url'}]}}]}}}}
    secrets = [{'name': 'database-url', 'value': 'postgresql://u:p@db.test/acp'}, {'name': 'other', 'value': 'unchanged-private-value'}]
    patch = helper.repair_patch(app, secrets)
    entries = {s['name']: s for s in patch['properties']['configuration']['secrets']}
    assert entries['other']['value'] == 'unchanged-private-value'
    assert entries['database-url']['value'] == secrets[0]['value']
    with pytest.raises(ValueError, match='preserved safely') as error:
        helper.repair_patch(app, secrets[:1])
    assert 'unchanged-private-value' not in str(error.value)


@pytest.mark.parametrize('secrets', [
    [{'name': 'database-url', 'value': 'postgresql://u:p@db.test/acp'}],
    [{'name': 'database-url', 'value': 'postgresql://u:p@db.test/acp'}, {'name': 'database-url', 'value': 'duplicate'}],
])
def test_unresolved_or_duplicate_secret_fails_before_provider_patch(monkeypatch, secrets):
    app = {'id': '/subscriptions/test/resourceGroups/group/providers/Microsoft.App/containerapps/worker',
           'properties': {'configuration': {'secrets': [{'name': 'database-url'}, {'name': 'other'}]},
           'template': {'containers': [{'env': [{'name': 'DATABASE_URL', 'secretRef': 'database-url'}]}],
                        'scale': {'rules': [{'custom': {'type': 'postgresql', 'auth': [{'triggerParameter': 'connection', 'secretRef': 'database-url'}]}}]}}}}
    def azure(*args):
        if args[:3] == ('containerapp', 'secret', 'list'): return secrets
        if args[:2] == ('containerapp', 'show') or args[:3] == ('rest', '--method', 'get'): return app
        pytest.fail('Unresolved or duplicate credentials must never issue a PATCH')
    monkeypatch.setattr(helper, 'azure', azure)
    with pytest.raises(ValueError): helper.repair('group', 'worker')


def test_successful_async_patch_waits_for_exact_template_without_reissuing_write(monkeypatch):
    desired = {'containers': [{'imageType': 'ContainerImage', 'env': [{'secretRef': 'original'}]}], 'scale': {'minReplicas': 5, 'maxReplicas': 10}}
    reads = iter([{'properties': {'template': {'scale': {'minReplicas': 5}}}}, {'properties': {'template': desired}}])
    pauses = []
    monkeypatch.setattr(helper, 'read_app', lambda *args: next(reads))
    monkeypatch.setattr(helper.time, 'sleep', pauses.append)
    assert helper.verified_template('group', 'worker', desired)['properties']['template'] == desired
    assert pauses == [5]


def test_template_verification_stops_after_bounded_propagation_window(monkeypatch):
    reads = []
    pauses = []
    def read(*args):
        reads.append(args)
        return {'properties': {'template': {}}}
    monkeypatch.setattr(helper, 'read_app', read)
    monkeypatch.setattr(helper.time, 'sleep', pauses.append)
    with pytest.raises(RuntimeError, match='verification failed'):
        helper.verified_template('group', 'worker', {'scale': {'maxReplicas': 10}})
    assert len(reads) == 12
    assert pauses == [5] * 11


def test_azure_errors_expose_only_operation_and_http_category(monkeypatch):
    import subprocess
    monkeypatch.setattr(helper.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 1, '', 'ERROR Bad Request HTTP 400 private-password postgresql://private'))
    with pytest.raises(helper.AzureOperationError) as error:
        helper.azure('rest', '--method', 'patch', '--url', 'https://management.test/private')
    assert str(error.value) == 'rest_patch:http_400'
    assert 'private' not in str(error.value)


def test_secret_propagation_waits_without_rewriting_keys(monkeypatch):
    desired = [{'name': 'database-url', 'value': 'original'}, {'name': 'vault', 'keyVaultUrl': 'https://vault.test/secret', 'identity': 'system'}]
    actual = {'properties': {'template': {'scale': {'maxReplicas': 10}}, 'configuration': {'secrets': [{'name': 'database-url'}, desired[1]]}}}
    reads = iter([[{'name': 'database-url', 'value': 'stale'}], [{'name': 'database-url', 'value': 'original'}]])
    pauses = []
    monkeypatch.setattr(helper, 'read_app', lambda *args: actual)
    monkeypatch.setattr(helper, 'azure', lambda *args: next(reads))
    monkeypatch.setattr(helper.time, 'sleep', pauses.append)
    assert helper.verified_template('group', 'worker', actual['properties']['template'], desired) == actual
    assert pauses == [5]


def test_failed_provisioning_stops_readback_immediately(monkeypatch):
    monkeypatch.setattr(helper, 'read_app', lambda *args: {'properties': {'provisioningState': 'Failed', 'template': {}}})
    monkeypatch.setattr(helper.time, 'sleep', lambda *args: pytest.fail('Failed provisioning must not wait'))
    with pytest.raises(RuntimeError, match='provisioning failed'):
        helper.verified_template('group', 'worker', {})


def test_matching_template_waits_for_successful_provisioning(monkeypatch):
    template = {'scale': {'maxReplicas': 10}}
    reads = iter([{'properties': {'template': template, 'provisioningState': 'Updating'}},
                  {'properties': {'template': template, 'provisioningState': 'Succeeded'}}])
    pauses = []
    monkeypatch.setattr(helper, 'read_app', lambda *args: next(reads))
    monkeypatch.setattr(helper.time, 'sleep', pauses.append)
    assert helper.verified_template('group', 'worker', template)['properties']['provisioningState'] == 'Succeeded'
    assert pauses == [5]
