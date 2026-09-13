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
    assert patch['properties']['configuration']['secrets'][0] == {'name': 'database-url'}
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
