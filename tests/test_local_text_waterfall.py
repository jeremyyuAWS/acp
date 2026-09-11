from types import SimpleNamespace
import pytest
from local_text_waterfall import generate


@pytest.mark.parametrize('first', [{'response': ''}, {'response': 'Cut off', 'done_reason': 'length'}, RuntimeError('offline')])
def test_one_configured_fallback_same_local_endpoint(monkeypatch, first):
    monkeypatch.setenv('OLLAMA_FALLBACK_MODEL', 'configured-second')
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs['json']['model']))
        value = first if len(calls) == 1 else {'response': 'Complete suggestion', 'done': True}
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: value)
    monkeypatch.setattr('httpx.post', post)
    out = generate('prompt', 'http://localhost:11434', 'configured-first', local_only=True)
    assert out['text'] == 'Complete suggestion'
    assert out['model'] == 'configured-second'
    assert [c[1] for c in calls] == ['configured-first', 'configured-second']
    assert len({c[0] for c in calls}) == 1
    assert out['attempts'][0]['ok'] is False


def test_no_fallback_config_never_invents_model(monkeypatch):
    monkeypatch.delenv('OLLAMA_FALLBACK_MODEL', raising=False)
    calls=[]
    monkeypatch.setattr('httpx.post', lambda url, **kw: (calls.append(kw['json']['model']) or SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'response':''})))
    assert generate('p', 'http://localhost:11434', 'configured-first') is None
    assert calls == ['configured-first']


def test_primary_success_never_calls_fallback(monkeypatch):
    monkeypatch.setenv('OLLAMA_FALLBACK_MODEL', 'configured-second')
    calls=[]
    monkeypatch.setattr('httpx.post', lambda url, **kw: (calls.append(kw['json']['model']) or SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'response':'Ready'})))
    assert generate('p', 'http://localhost:11434', 'configured-first')['text'] == 'Ready'
    assert calls == ['configured-first']


def test_local_consent_cannot_send_to_cloud_endpoint(monkeypatch):
    monkeypatch.setenv('OLLAMA_FALLBACK_MODEL', 'configured-second')
    monkeypatch.setattr('httpx.post', lambda *a, **kw: pytest.fail('No cloud dispatch authorized'))
    assert generate('p', 'https://vendor.example', 'configured-first', local_only=True) is None
