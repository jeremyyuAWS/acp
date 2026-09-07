import json
import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

from remediation_automation_policy import REASON_ORDER, build_policy_preview
from fastapi import FastAPI


FIXTURE = Path(__file__).parent / "fixtures/remediation_automation_policy_preview.json"


def _router():
    path = Path(__file__).parents[1] / "api/routes/remediation_policy.py"
    spec = importlib.util.spec_from_file_location("remediation_policy_route", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.router


def _fixture():
    return json.loads(FIXTURE.read_text())


def test_contract_has_exact_counts_exclusive_reasons_and_honest_unknown():
    result = build_policy_preview(_fixture()["findings"], level=3)
    assert result["open"] == {"findings": 8, "files": 7}
    assert result["lanes"] == {
        "automatic": {"findings": 1, "files": 1},
        "review": {"findings": 3, "files": 3},
        "protected": {"findings": 4, "files": 4},
    }
    assert [item["reason"] for item in result["reasons"]] == list(REASON_ORDER)
    assert sum(item["findings"] for item in result["reasons"]) == 6
    assert result["findings"][-1]["primary_reason"] is None
    assert result["integrity"] == {
        "open_equals_lane_sum": True,
        "reason_is_mutually_exclusive": True,
        "unknown_primary_reason": {"findings": 1, "files": 1},
        "complete": False,
    }


def test_reason_drilldown_counts_distinct_files_by_criterion_and_format():
    rows = [
        {"file": "one.docx", "criterion": "1.1.1", "lane": "review", "primary_reason": "missing_evidence"},
        {"file": "one.docx", "criterion": "1.1.1", "lane": "review", "primary_reason": "missing_evidence"},
        {"file": "two.pdf", "criterion": "1.1.1", "lane": "review", "primary_reason": "missing_evidence"},
    ]
    reason = build_policy_preview(rows)["reasons"][0]
    assert reason["findings"] == 3 and reason["files"] == 2
    assert reason["criteria"] == [{"criterion": "1.1.1", "findings": 3, "files": 2}]
    assert reason["formats"] == [
        {"format": "docx", "findings": 2, "files": 1},
        {"format": "pdf", "findings": 1, "files": 1},
    ]


def test_preview_route_returns_the_versioned_contract():
    app = FastAPI()
    app.include_router(_router())
    response = TestClient(app).post("/remediation/automation-policy/preview", json=_fixture())
    assert response.status_code == 200
    assert response.json()["contract_version"] == "remediation-automation-policy-preview.v1"
