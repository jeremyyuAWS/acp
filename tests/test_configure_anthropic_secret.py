import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('configure_anthropic', Path(__file__).parents[1] / 'scripts/configure_anthropic_secret.py')
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)


def test_missing_secret_never_calls_azure(monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.setattr(config, 'az', lambda *a: pytest.fail('must not call Azure'))
    with pytest.raises(RuntimeError, match='absent'):
        config.main()


def test_secret_only_flows_to_secret_store(monkeypatch, capsys):
    calls = []
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-private-value')
    monkeypatch.setattr(config, 'require_idle', lambda: None)
    monkeypatch.setattr(config, 'az', lambda *args: calls.append(args))
    config.main()
    assert len(calls) == 8
    assert all('test-private-value' in args[-1] for args in calls[:4])
    assert all(args[-1] == 'ANTHROPIC_API_KEY=secretref:anthropic-api-key' for args in calls[4:])
    assert 'test-private-value' not in capsys.readouterr().out


def test_azure_errors_do_not_echo_credentials(monkeypatch):
    monkeypatch.setattr(config.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=1, stderr=b'test-private-value'))
    with pytest.raises(RuntimeError) as exc:
        config.az('containerapp', 'secret', 'set')
    assert 'test-private-value' not in str(exc.value)


def test_busy_queue_stops_before_secret_write(monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-private-value')
    def busy():
        raise RuntimeError('busy')
    monkeypatch.setattr(config, 'require_idle', busy)
    monkeypatch.setattr(config, 'az', lambda *a: pytest.fail('must not call Azure'))
    with pytest.raises(RuntimeError, match='busy'):
        config.main()
