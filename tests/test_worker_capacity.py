"""GET /control/workers/capacity — Azure-side capacity EVIDENCE (current replica count,
CPU/memory utilization), distinct from GET /control/workers/replicas' CONFIGURED min/max.

Real azure-mgmt-appcontainers / azure-mgmt-monitor are not importable in this sandbox (no
network access to install them), matching how test_worker_replica_control.py already handles
this — so every test here either (a) exercises the AZURE_SUBSCRIPTION_ID-unset path, which never
imports the SDK at all, or (b) monkeypatches routes.control._az_client / _monitor_client
directly with plain Python fakes, which needs no real azure package installed since Python is
duck-typed and the route code only calls attributes/methods, never isinstance-checks a real SDK
type.

IMPORTANT CAVEAT this file cannot close: the fake response shapes below (a `.value` list of
replicas; a `.value` list of metrics, each with `.name.value` and `.timeseries[].data[].average`)
are built from current published Azure SDK documentation, not exercised against a real Azure
account. These tests prove the endpoint's OWN parsing/degradation logic is correct given that
assumed shape — they cannot prove the assumed shape itself is correct. The first real deployment
with a live Monitoring Reader grant is this endpoint's actual proof.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

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


def test_route_exists():
    src = (ACP / "api" / "routes" / "control.py").read_text()
    assert '@router.get("/control/workers/capacity")' in src


def test_reports_configured_false_when_azure_is_not_set_up(open_client, monkeypatch):
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", False)
    r = open_client.get("/control/workers/capacity")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is False
    assert body["current_replicas"] is None
    assert body["min_replicas"] is None
    assert body["cpu_percent"] is None
    assert body["metrics_available"] is False


def test_open_to_a_non_admin_caller(open_client, monkeypatch):
    """GET is read-only visibility, same reasoning as GET /control/workers/replicas (#950) —
    must never require admin. Confirmed unconfigured so it doesn't need a fake SDK client."""
    import core
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", False)
    monkeypatch.setattr(core, "OWNER_EMAIL", "admin@example.com", raising=False)
    monkeypatch.setattr(core, "is_admin", lambda e: e == "admin@example.com", raising=False)
    r = open_client.get("/control/workers/capacity")
    assert r.status_code == 200


def _fake_app(min_replicas=1, max_replicas=5, latest_revision="acp-worker--rev1", app_id="/subs/x/app"):
    scale = SimpleNamespace(min_replicas=min_replicas, max_replicas=max_replicas)
    template = SimpleNamespace(scale=scale)
    properties = SimpleNamespace(template=template, latest_ready_revision_name=latest_revision)
    return SimpleNamespace(properties=properties, id=app_id)


def test_returns_min_max_and_current_replicas_when_everything_succeeds(open_client, monkeypatch):
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", True)

    fake_app = _fake_app(min_replicas=1, max_replicas=5)
    az_client = SimpleNamespace(
        container_apps=SimpleNamespace(get=lambda rg, name: fake_app),
        container_apps_revision_replicas=SimpleNamespace(
            list_replicas=lambda rg, name, rev: SimpleNamespace(value=[object(), object()])),
    )
    monkeypatch.setattr(control_module, "_az_client", lambda: az_client)

    cpu_metric = SimpleNamespace(
        name=SimpleNamespace(value="CpuPercentage"),
        timeseries=[SimpleNamespace(data=[SimpleNamespace(average=12.0), SimpleNamespace(average=14.0)])])
    mem_metric = SimpleNamespace(
        name=SimpleNamespace(value="MemoryPercentage"),
        timeseries=[SimpleNamespace(data=[SimpleNamespace(average=40.0)])])
    monitor_client = SimpleNamespace(
        metrics=SimpleNamespace(list=lambda *a, **kw: SimpleNamespace(value=[cpu_metric, mem_metric])))
    monkeypatch.setattr(control_module, "_monitor_client", lambda: monitor_client)

    r = open_client.get("/control/workers/capacity")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is True
    assert body["min_replicas"] == 1
    assert body["max_replicas"] == 5
    assert body["current_replicas"] == 2
    assert body["cpu_percent"] == 13.0   # (12.0 + 14.0) / 2
    assert body["memory_percent"] == 40.0
    assert body["metrics_available"] is True
    assert body["measured_at"] is not None


def test_min_max_still_returned_when_the_replica_list_call_fails(open_client, monkeypatch):
    """A partial failure must not lose the data that DID come back."""
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", True)

    fake_app = _fake_app()
    az_client = SimpleNamespace(
        container_apps=SimpleNamespace(get=lambda rg, name: fake_app),
        container_apps_revision_replicas=SimpleNamespace(
            list_replicas=lambda rg, name, rev: (_ for _ in ()).throw(RuntimeError("no permission"))),
    )
    monkeypatch.setattr(control_module, "_az_client", lambda: az_client)
    monkeypatch.setattr(control_module, "_monitor_client",
                         lambda: SimpleNamespace(metrics=SimpleNamespace(
                             list=lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no permission")))))

    r = open_client.get("/control/workers/capacity")
    body = r.json()
    assert r.status_code == 200
    assert body["min_replicas"] == 1
    assert body["max_replicas"] == 5
    assert body["current_replicas"] is None    # honest "couldn't measure", not a fabricated 0
    assert body["metrics_available"] is False


def test_falls_back_to_configured_true_with_nothing_when_the_container_app_itself_is_unreachable(
        open_client, monkeypatch):
    """The most total failure short of Azure being unconfigured — the Container App lookup
    itself fails (bad credentials, resource renamed). Must degrade to all-None, not 500."""
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", True)
    az_client = SimpleNamespace(container_apps=SimpleNamespace(
        get=lambda rg, name: (_ for _ in ()).throw(RuntimeError("not found"))))
    monkeypatch.setattr(control_module, "_az_client", lambda: az_client)

    r = open_client.get("/control/workers/capacity")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is True
    assert body["min_replicas"] is None
    assert body["current_replicas"] is None
    assert body["metrics_available"] is False


def test_metrics_unavailable_does_not_block_replica_data(open_client, monkeypatch):
    """CpuPercentage/MemoryPercentage are Microsoft Preview metrics and may simply return no
    data points (not an error) — must degrade to metrics_available: false, not crash."""
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", True)
    fake_app = _fake_app()
    az_client = SimpleNamespace(
        container_apps=SimpleNamespace(get=lambda rg, name: fake_app),
        container_apps_revision_replicas=SimpleNamespace(
            list_replicas=lambda rg, name, rev: SimpleNamespace(value=[object()])),
    )
    monkeypatch.setattr(control_module, "_az_client", lambda: az_client)
    monkeypatch.setattr(control_module, "_monitor_client",
                         lambda: SimpleNamespace(metrics=SimpleNamespace(list=lambda *a, **kw: SimpleNamespace(value=[]))))

    r = open_client.get("/control/workers/capacity")
    body = r.json()
    assert body["current_replicas"] == 1
    assert body["cpu_percent"] is None
    assert body["memory_percent"] is None
    assert body["metrics_available"] is False


def test_replica_list_falls_back_to_direct_iteration_when_no_value_attribute(open_client, monkeypatch):
    """Defensive shape handling: if list_replicas ever returns a bare iterable instead of an
    OData-style `.value` wrapper, current_replicas must still be counted, not silently lost."""
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", True)
    fake_app = _fake_app()
    az_client = SimpleNamespace(
        container_apps=SimpleNamespace(get=lambda rg, name: fake_app),
        container_apps_revision_replicas=SimpleNamespace(
            list_replicas=lambda rg, name, rev: iter([object(), object(), object()])),
    )
    monkeypatch.setattr(control_module, "_az_client", lambda: az_client)
    monkeypatch.setattr(control_module, "_monitor_client",
                         lambda: SimpleNamespace(metrics=SimpleNamespace(list=lambda *a, **kw: SimpleNamespace(value=[]))))

    r = open_client.get("/control/workers/capacity")
    assert r.json()["current_replicas"] == 3
