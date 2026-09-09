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
