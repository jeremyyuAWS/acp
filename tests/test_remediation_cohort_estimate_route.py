from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException, Response
import pytest
from routes.remediation_policy import remediation_plan_estimate, ImpactPreviewRequest


def test_estimate_reuses_owner_and_scope_preview_without_writes():
    request = SimpleNamespace(state=SimpleNamespace(user_email='alice'))
    response = Response()
    body = ImpactPreviewRequest(scope=['selected.html'], ai=1, rule_based=0)
    with patch('routes.remediation_policy.remediation_impact_preview', return_value={}) as preview:
        result = remediation_plan_estimate('scan', body, request, response)
    preview.assert_called_once_with('scan', body, request, response)
    assert result['available'] is False
    assert 'selected.html' not in str(result)


def test_owner_denial_is_not_replaced_with_cross_owner_aggregate():
    with patch('routes.remediation_policy.remediation_impact_preview', side_effect=HTTPException(404, 'scan not found')):
        with pytest.raises(HTTPException) as error:
            remediation_plan_estimate('foreign', ImpactPreviewRequest(), SimpleNamespace(state=SimpleNamespace(user_email='bob')), Response())
    assert error.value.status_code == 404


def test_http_estimate_is_no_store_ignores_caller_evidence_and_denies_other_owner(monkeypatch):
    import core
    import remediation_impact_settings
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes.remediation_policy import router
    from test_remediation_impact import Facts
    monkeypatch.setattr(core, 'store', Facts())
    monkeypatch.setattr(remediation_impact_settings, 'read_impact_policy', lambda *args: {'rule_based': 2, 'ai': 1})
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post('/scans/s/remediation/impact-estimate', json={
            'scope': ['a.docx'], 'estimate_population': {'complete': True},
            'impact_evidence': {'representative': True}, 'eligible_findings': 100,
        })
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        assert response.json()['available'] is False
        assert 'a.docx' not in response.text
    foreign = FastAPI()
    foreign.include_router(router)
    @foreign.middleware('http')
    async def owner(request, call_next):
        request.state.user_email = 'bob'
        return await call_next(request)
    with TestClient(foreign) as client:
        assert client.post('/scans/s/remediation/impact-estimate', json={}).status_code == 404
