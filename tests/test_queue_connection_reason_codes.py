"""Staging scaler validation keeps actionable categories without credential text."""
import builtins
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('queue_reason_codes', ROOT / 'deploy/public/repair_queue_connection.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def test_missing_runner_parser_is_distinct_from_invalid_connection(monkeypatch, capsys):
    original = builtins.__import__
    def imports(name, *args, **kwargs):
        if name.startswith('psycopg2'):
            raise ModuleNotFoundError('PRIVATE_DSN_SENTINEL')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', imports)
    with pytest.raises(ValueError) as error:
        helper.canonical_connection('postgresql://synthetic:PRIVATE_PASSWORD@localhost/test_db')
    helper.report_failure(error.value)
    output = capsys.readouterr().err
    assert 'dsn_parser_unavailable' in output
    assert 'PRIVATE' not in output


@pytest.mark.parametrize('message,code', list(helper.VALIDATION_REASON_CODES.items()))
def test_exact_static_validation_categories_are_retained(message, code, capsys):
    helper.report_failure(ValueError(message))
    assert capsys.readouterr().err == f'PostgreSQL scaler repair failed (ValueError:{code})\n'


@pytest.mark.parametrize('error', [ValueError('PRIVATE_DSN'), RuntimeError('PRIVATE_PASSWORD'),
    helper.AzureOperationError('PRIVATE_PROVIDER_RESPONSE')])
def test_unknown_failure_text_never_leaks(error, capsys):
    helper.report_failure(error)
    assert 'PRIVATE' not in capsys.readouterr().err


def test_invalid_connection_gets_safe_normalization_code(capsys):
    with pytest.raises(ValueError) as error:
        helper.canonical_connection('postgresql://user:PRIVATE_PASSWORD@db.test:badport/acp')
    helper.report_failure(error.value)
    assert capsys.readouterr().err == 'PostgreSQL scaler repair failed (ValueError:dsn_normalization_invalid)\n'


def test_staging_installs_same_parser_as_production_before_repair_dispatch():
    import yaml
    staging = yaml.safe_load((ROOT / '.github/workflows/deploy-staging.yml').read_text())
    production = yaml.safe_load((ROOT / '.github/workflows/deploy.yml').read_text())
    steps = staging['jobs']['deploy']['steps']
    setup = next(i for i, s in enumerate(steps) if s.get('uses') == 'actions/setup-python@v5')
    install = next(i for i, s in enumerate(steps) if 'pip install' in s.get('run', ''))
    deploy = next(i for i, s in enumerate(steps) if s.get('name') == 'Deploy to staging')
    assert setup < install < deploy
    assert steps[install]['timeout-minutes'] == 3
    assert steps[setup]['with']['python-version'] == '3.12'
    production_install = next(s['run'] for s in production['jobs']['deploy']['steps'] if 'pip install' in s.get('run', ''))
    assert steps[install]['run'] == production_install
