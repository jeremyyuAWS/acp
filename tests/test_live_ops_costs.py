from types import SimpleNamespace

import pytest


@pytest.fixture()
def open_client(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient
    from app import app
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", "", raising=False)
    return TestClient(app)


def test_estimate_service_uses_only_explicit_rate_inputs():
    from routes.costs import estimate_service
    line = estimate_service("acp-assess", 2, 2, 4, {"vcpu_hour": 0.10, "gib_hour": 0.01})
    assert line["estimated_hourly_usd"] == 0.48
    assert line["estimated_daily_usd"] == 11.52
    assert line["status"] == "estimated"
    assert estimate_service("acp-assess", 2, 2, 4, None)["estimated_hourly_usd"] is None


def test_cost_endpoint_is_truthful_when_not_configured(open_client, monkeypatch):
    from routes import costs
    monkeypatch.setattr(costs, "_AZ_SUB", None)
    monkeypatch.setattr(costs, "_app_names", lambda: [])
    body = open_client.get("/control/costs").json()
    assert body["configured"] is False
    assert body["estimated_hourly_usd"] is None
    assert body["billing"]["freshness_label"] == "Azure billing feed not configured"


def test_cost_endpoint_is_mapped_to_live_operations_access():
    import workspace_capability_map as capmap
    assert capmap.ROUTE_CAPABILITIES[("GET", "/control/costs")] == frozenset({"operations.view"})


def test_cost_endpoint_reports_each_service_and_total(open_client, monkeypatch):
    from routes import costs
    resources = SimpleNamespace(cpu=2, memory="4Gi")
    app = SimpleNamespace(properties=SimpleNamespace(
        latest_ready_revision_name="r1",
        template=SimpleNamespace(containers=[SimpleNamespace(resources=resources)])))
    replicas = SimpleNamespace(value=[object(), object()])
    client = SimpleNamespace(
        container_apps=SimpleNamespace(get=lambda rg, name: app),
        container_apps_revision_replicas=SimpleNamespace(list_replicas=lambda rg, name, revision: replicas))
    monkeypatch.setattr(costs, "_AZ_SUB", "sub")
    monkeypatch.setattr(costs, "_app_names", lambda: ["acp-discovery", "acp-assess"])
    monkeypatch.setattr(costs, "_rate_card", lambda: ({
        "acp-discovery": {"vcpu_hour": .1, "gib_hour": .01},
        "acp-assess": {"vcpu_hour": .1, "gib_hour": .01},
    }, "Contract rate card 2026-09"))
    monkeypatch.setattr(costs, "_az_client", lambda: client)
    body = open_client.get("/control/costs").json()
    assert [line["app"] for line in body["services"]] == ["acp-discovery", "acp-assess"]
    assert body["estimated_hourly_usd"] == .96
    assert body["estimated_daily_usd"] == 23.04
    assert body["rate_source"] == "Contract rate card 2026-09"


def test_one_unavailable_app_does_not_fabricate_or_hide_other_costs(open_client, monkeypatch):
    from routes import costs
    resources = SimpleNamespace(cpu=1, memory="2Gi")
    good = SimpleNamespace(properties=SimpleNamespace(
        latest_ready_revision_name="r1",
        template=SimpleNamespace(containers=[SimpleNamespace(resources=resources)])))
    def get(_rg, name):
        if name == "acp-remediate":
            raise RuntimeError("unavailable")
        return good
    client = SimpleNamespace(
        container_apps=SimpleNamespace(get=get),
        container_apps_revision_replicas=SimpleNamespace(list_replicas=lambda *_: SimpleNamespace(value=[object()])))
    monkeypatch.setattr(costs, "_AZ_SUB", "sub")
    monkeypatch.setattr(costs, "_app_names", lambda: ["acp-assess", "acp-remediate"])
    monkeypatch.setattr(costs, "_rate_card", lambda: ({
        name: {"vcpu_hour": .1, "gib_hour": .01} for name in ("acp-assess", "acp-remediate")
    }, "rates"))
    monkeypatch.setattr(costs, "_az_client", lambda: client)
    body = open_client.get("/control/costs").json()
    assert body["services"][0]["estimated_hourly_usd"] == .12
    assert body["services"][1]["status"] == "not_reported"
    assert body["estimated_hourly_usd"] is None
