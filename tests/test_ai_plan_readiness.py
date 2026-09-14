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
