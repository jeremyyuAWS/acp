from unittest.mock import Mock

from ai_plan_readiness import plan_ai_readiness


def test_public_endpoint_is_blocked_before_connection_or_generation(monkeypatch):
    import ai
    import httpx
    monkeypatch.setattr(ai, '_maybe_refresh_endpoint', lambda: None)
    monkeypatch.setattr(ai, 'OLLAMA_BASE_URL', 'https://public.example.com')
    probe = Mock(side_effect=AssertionError('must not probe public endpoint'))
    monkeypatch.setattr(httpx, 'get', probe)
    assert plan_ai_readiness({'ai': 1, 'ai_zone': 'local', 'ai_budget_usd': '0.00'}) == {'state': 'local_endpoint_required', 'blocked': True}
    probe.assert_not_called()


def test_private_endpoint_readiness_and_zero_budget(monkeypatch):
    import ai
    import httpx
    monkeypatch.setattr(ai, '_maybe_refresh_endpoint', lambda: None)
    monkeypatch.setattr(ai, 'OLLAMA_BASE_URL', 'http://10.0.1.2:11434')
    response = Mock()
    response.json.return_value = {'models': [{'name': ai.OLLAMA_MODEL}, {'name': ai.OLLAMA_VISION_MODEL}]}
    probe = Mock(return_value=response)
    monkeypatch.setattr(httpx, 'get', probe)
    assert plan_ai_readiness({'ai': 1, 'ai_zone': 'local', 'ai_budget_usd': '0.00'}) == {'state': 'local_endpoint_reachable', 'blocked': False, 'text_model_available': True, 'vision_model_available': True}
    assert probe.call_args.kwargs['timeout'] == 3.0
    response.json.return_value = {'models': []}
    assert plan_ai_readiness({'ai': 1, 'ai_zone': 'local'}) == {'state': 'local_models_missing', 'blocked': True, 'text_model_available': False, 'vision_model_available': False}
    response.json.return_value = {'models': [{'name': 'unrelated-model:latest'}]}
    assert plan_ai_readiness({'ai': 1, 'ai_zone': 'local'})['blocked'] is True
    response.json.return_value = {'models': [{'name': ai.OLLAMA_MODEL}]}
    readiness = plan_ai_readiness({'ai': 1, 'ai_zone': 'local'})
    assert readiness['text_model_available'] is True
    assert readiness['vision_model_available'] is False
    assert readiness['blocked'] is True
    monkeypatch.setattr(httpx, 'get', Mock(side_effect=httpx.ConnectError('unreachable')))
    assert plan_ai_readiness({'ai': 1, 'ai_zone': 'local'})['blocked'] is True


def test_rules_and_cloud_do_not_probe_local_endpoint(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, 'get', Mock(side_effect=AssertionError('no local probe')))
    assert plan_ai_readiness({'ai': 0})['state'] == 'not_required'
    assert plan_ai_readiness({'ai': 1, 'ai_zone': 'any'})['state'] == 'governed_cloud'
    assert plan_ai_readiness({'ai': 1}, False)['state'] == 'ai_disabled'


def test_local_access_denied_is_not_endpoint_failure_or_cloud_budget(monkeypatch):
    import ai
    import httpx
    monkeypatch.setattr(ai, '_maybe_refresh_endpoint', lambda: None)
    monkeypatch.setattr(ai, 'OLLAMA_BASE_URL', 'http://10.0.1.2:11434')
    for status in (401, 403, 503):
        response = httpx.Response(status, request=httpx.Request('GET', 'http://10.0.1.2:11434/api/tags'))
        monkeypatch.setattr(httpx, 'get', Mock(return_value=response))
        readiness = plan_ai_readiness({'ai': 1, 'ai_zone': 'local', 'ai_budget_usd': '0.00'})
        assert readiness == {'state': 'local_endpoint_access_denied' if status in (401, 403) else 'local_endpoint_unreachable', 'blocked': True}


def test_local_readiness_retries_transient_timeout_without_generation(monkeypatch):
    import ai
    import httpx
    monkeypatch.setattr(ai, '_maybe_refresh_endpoint', lambda: None)
    monkeypatch.setattr(ai, 'OLLAMA_BASE_URL', 'https://ollama.internal.example.com')
    response = Mock()
    response.json.return_value = {'models': [{'name': ai.OLLAMA_MODEL}, {'name': ai.OLLAMA_VISION_MODEL}]}
    probe = Mock(side_effect=[httpx.ReadTimeout('starting'), response])
    monkeypatch.setattr(httpx, 'get', probe)
    assert plan_ai_readiness({'ai': 1, 'ai_zone': 'local'})['blocked'] is False
    assert probe.call_count == 2
    assert all(call.kwargs['timeout'] == 3.0 for call in probe.call_args_list)


def test_local_readiness_retry_is_bounded(monkeypatch):
    import ai
    import httpx
    monkeypatch.setattr(ai, '_maybe_refresh_endpoint', lambda: None)
    monkeypatch.setattr(ai, 'OLLAMA_BASE_URL', 'https://ollama.internal.example.com')
    probe = Mock(side_effect=httpx.ReadTimeout('unavailable'))
    monkeypatch.setattr(httpx, 'get', probe)
    assert plan_ai_readiness({'ai': 1, 'ai_zone': 'local'})['blocked'] is True
    assert probe.call_count == 2


def test_local_readiness_retries_startup_gateway_failure_but_not_access_denial(monkeypatch):
    import ai
    import httpx
    monkeypatch.setattr(ai, '_maybe_refresh_endpoint', lambda: None)
    monkeypatch.setattr(ai, 'OLLAMA_BASE_URL', 'https://ollama.internal.example.com')
    request = httpx.Request('GET', ai.OLLAMA_BASE_URL + '/api/tags')
    healthy = httpx.Response(200, request=request, json={'models': [{'name': ai.OLLAMA_MODEL}, {'name': ai.OLLAMA_VISION_MODEL}]})
    for status in (502, 503, 504):
        probe = Mock(side_effect=[httpx.Response(status, request=request), healthy])
        monkeypatch.setattr(httpx, 'get', probe)
        assert plan_ai_readiness({'ai': 1, 'ai_zone': 'local'})['blocked'] is False
        assert probe.call_count == 2
    for status in (401, 403):
        probe = Mock(return_value=httpx.Response(status, request=request))
        monkeypatch.setattr(httpx, 'get', probe)
        assert plan_ai_readiness({'ai': 1, 'ai_zone': 'local'})['state'] == 'local_endpoint_access_denied'
        assert probe.call_count == 1
