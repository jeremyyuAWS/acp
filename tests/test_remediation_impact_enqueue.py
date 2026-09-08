"""HTTP execution seals server-derived routing, independent of browser eligibility claims."""
from copy import deepcopy
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import core
import handlers
import remediation_impact
import remediation_impact_settings as settings
from routes import scans


OWNER = "planner@example.com"


@pytest.fixture
def route(monkeypatch, isolated_store):
    captured = []
    isolated_store.init_scan_run("scan", "local", 0, "t0", "r", "h", owner=OWNER)
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(isolated_store, "get_ai_enabled", lambda: True)
    monkeypatch.setattr(scans, "_owner", lambda _: OWNER)
    monkeypatch.setattr(isolated_store, "get_scan", lambda *args, **kwargs: {
        "run": {"source": "local", "owner_email": OWNER, "assessed_at": "2026-09-08T12:00:00Z"},
        "files": [{"file": "a.html", "issues": [{}]}]})
    monkeypatch.setattr(isolated_store, "seed_finding_dispositions", lambda *args, **kwargs: None)
    monkeypatch.setattr(scans, "_sealed_stage_input", lambda *_: ("assessment-v1", "manifest-v1"))
    monkeypatch.setattr(handlers, "scan_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(remediation_impact, "load_run_findings", lambda *_: ([
        {"id": "a-language", "file": "a.html", "rule_id": "3.1.1", "finding_count": 2,
         "origin": "rule_based", "remediation_supported": True},
        {"id": "a-judgment", "file": "a.html", "rule_id": "1.1.1", "finding_count": 1,
         "origin": "ai", "human_only": True},
    ], [{"file": "a.html", "complete": True, "blocked": False}]))

    def enqueue(*args, **kwargs):
        captured.append({"payloads": deepcopy(args[3]), **deepcopy(kwargs)})
        return {"job_ids": [f"job-{len(captured)}"], "batch_id": f"batch-{len(captured)}",
                "reused": False}

    monkeypatch.setattr(scans, "_enqueue_stage_batch", enqueue)
    app = FastAPI()
    app.include_router(scans.router)
    return TestClient(app), captured, isolated_store


def test_explicit_policy_seals_only_server_eligible_rules(route):
    client, captured, store = route
    response = client.post("/scans/scan/remediate", json={
        "remediation_policy": {"rule_based": 2, "ai": 1},
        "remediation_impact_allowed_rules": ["1.1.1", "3.1.1", "2.4.2"]})
    assert response.status_code == 200, response.text
    job = captured[0]["payloads"][0]
    assert job["remediation_impact_allowed_rules"] == ["3.1.1"]
    sealed = deepcopy(job["remediation_impact_policy"])
    assert sealed["rule_based"] == 2 and sealed["ai"] == 1
    assert sealed["snapshot_id"].startswith("rip-")
    settings.save_impact_policy(store, OWNER, OWNER, {"rule_based": 0, "ai": 0}, 0)
    assert job["remediation_impact_policy"] == sealed


@pytest.mark.parametrize("ai", [2, 3])
def test_unsupported_ai_application_rejected_before_queue(route, ai):
    client, captured, _ = route
    response = client.post("/scans/scan/remediate", json={
        "remediation_policy": {"rule_based": 2, "ai": ai}})
    assert response.status_code == 422
    assert "Automatic AI application" in response.text
    assert captured == []


def test_different_policy_has_different_execution_identity(route):
    client, captured, _ = route
    for rule_based in [2, 0]:
        response = client.post("/scans/scan/remediate", json={
            "remediation_policy": {"rule_based": rule_based, "ai": 1}})
        assert response.status_code == 200, response.text
    assert captured[0]["request_fingerprint"] != captured[1]["request_fingerprint"]
    assert captured[1]["payloads"][0]["remediation_impact_allowed_rules"] == []
    fingerprint = json.loads(captured[1]["request_fingerprint"])
    assert fingerprint["remediation_impact_policy"]["rule_based"] == 0


def test_saved_defaults_govern_request_without_explicit_policy(route):
    client, captured, store = route
    settings.save_impact_policy(store, OWNER, OWNER, {"rule_based": 0, "ai": 0}, 0)
    response = client.post("/scans/scan/remediate", json={})
    assert response.status_code == 200, response.text
    job = captured[0]["payloads"][0]
    assert job["remediation_impact_policy"]["rule_based"] == 0
    assert job["remediation_impact_policy"]["ai"] == 0
    assert job["remediation_impact_allowed_rules"] == []


@pytest.mark.parametrize("scope", ["a.html", [{"file": "a.html"}], [["a.html"]], [None], [""]])
def test_invalid_selected_scope_never_expands_to_whole_assessment(route, scope):
    client, captured, _ = route
    response = client.post("/scans/scan/remediate", json={
        "scope": scope, "remediation_policy": {"rule_based": 2, "ai": 0}})
    assert response.status_code == 422
    assert captured == []


def test_application_ai_off_requires_off_policy_but_allows_rule_fixes(route, monkeypatch):
    client, captured, store = route
    monkeypatch.setattr(store, "get_ai_enabled", lambda: False)
    response = client.post("/scans/scan/remediate", json={
        "remediation_policy": {"rule_based": 2, "ai": 1}})
    assert response.status_code == 409
    assert captured == []
    response = client.post("/scans/scan/remediate", json={
        "remediation_policy": {"rule_based": 2, "ai": 0}})
    assert response.status_code == 200, response.text
    assert captured[0]["payloads"][0]["remediation_impact_allowed_rules"] == ["3.1.1"]


def test_incomplete_assessment_cannot_execute_partial_forecast(route, monkeypatch):
    client, captured, store = route
    original = store.get_scan

    def incomplete(*args, **kwargs):
        result = original(*args, **kwargs)
        result["run"]["assessed_at"] = None
        return result

    monkeypatch.setattr(store, "get_scan", incomplete)
    response = client.post("/scans/scan/remediate", json={
        "remediation_policy": {"rule_based": 2, "ai": 0}})
    assert response.status_code == 409
    assert captured == []
