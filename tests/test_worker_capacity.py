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


def _fake_app(min_replicas=1, max_replicas=5, latest_revision="acp-worker--rev1", app_id="/subs/x/app",
              traffic=None):
    scale = SimpleNamespace(min_replicas=min_replicas, max_replicas=max_replicas)
    template = SimpleNamespace(scale=scale)
    ingress = SimpleNamespace(traffic=traffic) if traffic is not None else None
    configuration = SimpleNamespace(ingress=ingress)
    properties = SimpleNamespace(template=template, latest_ready_revision_name=latest_revision,
                                 configuration=configuration)
    return SimpleNamespace(properties=properties, id=app_id)


def _fake_traffic_weight(revision_name, weight):
    return SimpleNamespace(revision_name=revision_name, weight=weight)


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


# --- Revision health / draining-replicas (2026-08-29) ------------------------------------------
# `container_apps_revisions.list_revisions()` is a THIRD Azure call, alongside the container-app
# lookup and the replica-count call above — its own try/except so a failure here never loses the
# min/max/current_replicas/metrics data the other two calls already gathered.

def _fake_revision(name, active, health_state=None, provisioning_state=None, replicas=0,
                    nested=True):
    """`nested=True` puts health_state/provisioning_state/replicas/active under `.properties`
    (the shape _rev_field() tries first, matching this file's `app.properties.template.scale`
    convention); `nested=False` puts them at the top level, proving the fallback path works too —
    the exact uncertainty _rev_field()'s docstring in control.py explains.

    `name` is ALWAYS top-level, never nested — it's a standard Azure Resource field (like id/
    type), not part of RevisionProperties, regardless of which shape the rest of this fake uses."""
    fields = dict(active=active, health_state=health_state,
                  provisioning_state=provisioning_state, replicas=replicas)
    if nested:
        return SimpleNamespace(properties=SimpleNamespace(**fields), name=name)
    return SimpleNamespace(properties=SimpleNamespace(), name=name, **fields)


def _capacity_client(fake_app, revisions):
    return SimpleNamespace(
        container_apps=SimpleNamespace(get=lambda rg, name: fake_app),
        container_apps_revision_replicas=SimpleNamespace(
            list_replicas=lambda rg, name, rev: SimpleNamespace(value=[])),
        container_apps_revisions=SimpleNamespace(
            list_revisions=lambda rg, name: SimpleNamespace(value=revisions)),
    )


def _no_metrics_monitor():
    return SimpleNamespace(metrics=SimpleNamespace(list=lambda *a, **kw: SimpleNamespace(value=[])))


def test_reports_active_revision_health_and_sums_draining_replicas_on_old_revisions(
        open_client, monkeypatch):
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", True)
    fake_app = _fake_app(latest_revision="acp-worker--rev2")
    revisions = [
        _fake_revision("acp-worker--rev1", active=False, replicas=2),   # still draining
        _fake_revision("acp-worker--rev2", active=True, health_state="Healthy",
                        provisioning_state="Provisioned", replicas=3),
    ]
    monkeypatch.setattr(control_module, "_az_client", lambda: _capacity_client(fake_app, revisions))
    monkeypatch.setattr(control_module, "_monitor_client", _no_metrics_monitor)

    r = open_client.get("/control/workers/capacity")
    body = r.json()
    assert body["revision_health"] == "Healthy"
    assert body["revision_provisioning_state"] == "Provisioned"
    assert body["draining_replicas"] == 2


# --- Revision traffic-split (2026-08-29) ---------------------------------------------------
# A revision can be perfectly Healthy/Provisioned while receiving 0% of ingress traffic — a
# real incident on this app (a stuck blue-green rollout left the new revision healthy but
# unreachable, and nothing surfaced it until customer-facing requests kept hitting the old
# revision). revision_health answers "is the active revision itself okay"; this answers the
# independent question "is it actually receiving traffic".

def test_reports_the_active_revisions_own_traffic_weight(open_client, monkeypatch):
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", True)
    fake_app = _fake_app(latest_revision="acp-worker--rev2", traffic=[
        _fake_traffic_weight("acp-worker--rev1", 20),
        _fake_traffic_weight("acp-worker--rev2", 80),
    ])
    revisions = [
        _fake_revision("acp-worker--rev1", active=False, replicas=1),
        _fake_revision("acp-worker--rev2", active=True, health_state="Healthy",
                        provisioning_state="Provisioned", replicas=3),
    ]
    monkeypatch.setattr(control_module, "_az_client", lambda: _capacity_client(fake_app, revisions))
    monkeypatch.setattr(control_module, "_monitor_client", _no_metrics_monitor)

    r = open_client.get("/control/workers/capacity")
    body = r.json()
    assert body["revision_health"] == "Healthy"
    assert body["revision_traffic_percent"] == 80


def test_reports_zero_traffic_on_a_healthy_but_stranded_revision(open_client, monkeypatch):
    """The exact stuck-rollout shape: the new revision is Healthy and Provisioned, but ingress
    was never repointed at it — 0%, not None, so a diagnosis rule can tell "stranded" apart from
    "traffic data unavailable"."""
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", True)
    fake_app = _fake_app(latest_revision="acp-worker--rev2", traffic=[
        _fake_traffic_weight("acp-worker--rev1", 100),
        _fake_traffic_weight("acp-worker--rev2", 0),
    ])
    revisions = [
        _fake_revision("acp-worker--rev1", active=False, replicas=2),
        _fake_revision("acp-worker--rev2", active=True, health_state="Healthy",
                        provisioning_state="Provisioned", replicas=1),
    ]
    monkeypatch.setattr(control_module, "_az_client", lambda: _capacity_client(fake_app, revisions))
    monkeypatch.setattr(control_module, "_monitor_client", _no_metrics_monitor)

    r = open_client.get("/control/workers/capacity")
    body = r.json()
    assert body["revision_health"] == "Healthy"
    assert body["revision_traffic_percent"] == 0


def test_traffic_percent_stays_none_when_ingress_is_not_configured(open_client, monkeypatch):
    """Single-revision-mode apps or ones with no external ingress at all have ingress=None —
    must degrade to None, not crash the whole capacity response."""
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", True)
    fake_app = _fake_app(latest_revision="acp-worker--rev1")   # no traffic= passed -> ingress=None
    revisions = [_fake_revision("acp-worker--rev1", active=True, health_state="Healthy",
                                provisioning_state="Provisioned", replicas=2)]
    monkeypatch.setattr(control_module, "_az_client", lambda: _capacity_client(fake_app, revisions))
    monkeypatch.setattr(control_module, "_monitor_client", _no_metrics_monitor)

    r = open_client.get("/control/workers/capacity")
    body = r.json()
    assert body["revision_health"] == "Healthy"
    assert body["revision_traffic_percent"] is None


def test_traffic_percent_stays_none_when_active_revision_name_never_resolved(open_client, monkeypatch):
    """No revision in the list reports active=True (a transient Azure state) — there is no
    revision to look up in the traffic list, so this must degrade quietly rather than raise."""
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", True)
    fake_app = _fake_app(traffic=[_fake_traffic_weight("acp-worker--rev1", 100)])
    revisions = [_fake_revision("acp-worker--rev1", active=False, replicas=1)]
    monkeypatch.setattr(control_module, "_az_client", lambda: _capacity_client(fake_app, revisions))
    monkeypatch.setattr(control_module, "_monitor_client", _no_metrics_monitor)

    r = open_client.get("/control/workers/capacity")
    body = r.json()
    assert body["revision_traffic_percent"] is None


def test_traffic_percent_stays_none_when_list_revisions_itself_fails(open_client, monkeypatch):
    """The revision-enumeration try block can fail before active_revision_name is ever set —
    must not leak a NameError into the traffic-lookup block."""
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", True)
    fake_app = _fake_app(traffic=[_fake_traffic_weight("acp-worker--rev1", 100)])
    az_client = SimpleNamespace(
        container_apps=SimpleNamespace(get=lambda rg, name: fake_app),
        container_apps_revision_replicas=SimpleNamespace(
            list_replicas=lambda rg, name, rev: SimpleNamespace(value=[])),
        container_apps_revisions=SimpleNamespace(
            list_revisions=lambda rg, name: (_ for _ in ()).throw(RuntimeError("no permission"))),
    )
    monkeypatch.setattr(control_module, "_az_client", lambda: az_client)
    monkeypatch.setattr(control_module, "_monitor_client", _no_metrics_monitor)

    r = open_client.get("/control/workers/capacity")
    assert r.status_code == 200
    body = r.json()
    assert body["revision_health"] is None
    assert body["revision_traffic_percent"] is None


def test_draining_replicas_is_zero_not_none_when_only_the_active_revision_holds_replicas(
        open_client, monkeypatch):
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", True)
    fake_app = _fake_app()
    revisions = [_fake_revision("acp-worker--rev1", active=True, health_state="Healthy",
                                 provisioning_state="Provisioned", replicas=1)]
    monkeypatch.setattr(control_module, "_az_client", lambda: _capacity_client(fake_app, revisions))
    monkeypatch.setattr(control_module, "_monitor_client", _no_metrics_monitor)

    r = open_client.get("/control/workers/capacity")
    body = r.json()
    assert body["draining_replicas"] == 0
    assert body["revision_health"] == "Healthy"


def test_falls_back_to_flattened_top_level_revision_fields_when_not_nested_under_properties(
        open_client, monkeypatch):
    """Proves _rev_field()'s fallback: if the real SDK ever returns these fields at the top
    level instead of nested under `.properties`, health/draining must still be read correctly."""
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", True)
    fake_app = _fake_app()
    revisions = [
        _fake_revision("acp-worker--rev1", active=False, replicas=1, nested=False),
        _fake_revision("acp-worker--rev2", active=True, health_state="Unhealthy",
                        provisioning_state="Failed", replicas=1, nested=False),
    ]
    monkeypatch.setattr(control_module, "_az_client", lambda: _capacity_client(fake_app, revisions))
    monkeypatch.setattr(control_module, "_monitor_client", _no_metrics_monitor)

    r = open_client.get("/control/workers/capacity")
    body = r.json()
    assert body["revision_health"] == "Unhealthy"
    assert body["revision_provisioning_state"] == "Failed"
    assert body["draining_replicas"] == 1


def test_revision_health_stays_none_when_list_revisions_fails_without_losing_other_data(
        open_client, monkeypatch):
    """A partial failure in the THIRD Azure call must not lose what the first two DID return."""
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", True)
    fake_app = _fake_app(min_replicas=2, max_replicas=6)
    az_client = SimpleNamespace(
        container_apps=SimpleNamespace(get=lambda rg, name: fake_app),
        container_apps_revision_replicas=SimpleNamespace(
            list_replicas=lambda rg, name, rev: SimpleNamespace(value=[object()])),
        container_apps_revisions=SimpleNamespace(
            list_revisions=lambda rg, name: (_ for _ in ()).throw(RuntimeError("no permission"))),
    )
    monkeypatch.setattr(control_module, "_az_client", lambda: az_client)
    monkeypatch.setattr(control_module, "_monitor_client", _no_metrics_monitor)

    r = open_client.get("/control/workers/capacity")
    body = r.json()
    assert body["min_replicas"] == 2
    assert body["current_replicas"] == 1
    assert body["revision_health"] is None
    assert body["draining_replicas"] is None


def test_capacity_unconfigured_response_includes_revision_health_keys_as_none(open_client, monkeypatch):
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", False)
    r = open_client.get("/control/workers/capacity")
    body = r.json()
    assert body["revision_health"] is None
    assert body["revision_provisioning_state"] is None
    assert body["draining_replicas"] is None
