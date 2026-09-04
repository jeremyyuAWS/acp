"""GET /control/workers/revisions — the FULL deploy/revision history for the acp-worker
Container App, not just the active revision's handful of fields GET /control/workers/capacity
extracts. Same fakes-not-real-SDK approach as test_worker_capacity.py — see that file's own
docstring for why (no network access to install azure-mgmt-appcontainers in this sandbox) and the
same caveat: these tests prove this endpoint's OWN parsing/degradation logic given an ASSUMED
response shape, not that the shape itself matches a live Azure account.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
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
    assert '@router.get("/control/workers/revisions")' in src


def test_reports_configured_false_when_azure_is_not_set_up(open_client, monkeypatch):
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", False)
    r = open_client.get("/control/workers/revisions")
    assert r.status_code == 200
    body = r.json()
    assert body == {"configured": False, "revisions": []}


def test_open_to_a_non_admin_caller(open_client, monkeypatch):
    import core
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", False)
    monkeypatch.setattr(core, "OWNER_EMAIL", "admin@example.com", raising=False)
    monkeypatch.setattr(core, "is_admin", lambda e: e == "admin@example.com", raising=False)
    r = open_client.get("/control/workers/revisions")
    assert r.status_code == 200


def _fake_app(traffic=None):
    ingress = SimpleNamespace(traffic=traffic) if traffic is not None else None
    configuration = SimpleNamespace(ingress=ingress)
    properties = SimpleNamespace(configuration=configuration)
    return SimpleNamespace(properties=properties, id="/subs/x/app")


def _fake_traffic_weight(revision_name, weight):
    return SimpleNamespace(revision_name=revision_name, weight=weight)


def _fake_revision(name, active, health_state=None, provisioning_state=None, running_state=None,
                    replicas=0, created_time=None, nested=True):
    fields = dict(active=active, health_state=health_state, provisioning_state=provisioning_state,
                  running_state=running_state, replicas=replicas, created_time=created_time)
    if nested:
        return SimpleNamespace(properties=SimpleNamespace(**fields), name=name)
    return SimpleNamespace(properties=SimpleNamespace(), name=name, **fields)


def _revisions_client(fake_app, revisions):
    return SimpleNamespace(
        container_apps=SimpleNamespace(get=lambda rg, name: fake_app),
        container_apps_revisions=SimpleNamespace(
            list_revisions=lambda rg, name: SimpleNamespace(value=revisions)),
    )


def test_returns_every_revision_with_its_own_fields(open_client, monkeypatch):
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", True)

    fake_app = _fake_app()
    revisions = [
        _fake_revision("acp-worker--rev1", active=False, health_state="Healthy",
                        provisioning_state="Provisioned", running_state="Running", replicas=1,
                        created_time="2026-08-20T10:00:00+00:00"),
        _fake_revision("acp-worker--rev2", active=True, health_state="Healthy",
                        provisioning_state="Provisioned", running_state="Running", replicas=3,
                        created_time="2026-08-27T10:00:00+00:00"),
    ]
    monkeypatch.setattr(control_module, "_az_client", lambda: _revisions_client(fake_app, revisions))

    r = open_client.get("/control/workers/revisions")
    body = r.json()
    assert body["configured"] is True
    assert len(body["revisions"]) == 2
    active = next(x for x in body["revisions"] if x["active"])
    assert active["name"] == "acp-worker--rev2"
    assert active["replicas"] == 3
    assert active["running_state"] == "Running"


def test_sorts_newest_first_by_created_time(open_client, monkeypatch):
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", True)

    fake_app = _fake_app()
    revisions = [
        _fake_revision("rev-old", active=False, created_time="2026-08-10T00:00:00+00:00"),
        _fake_revision("rev-newest", active=True, created_time="2026-08-28T00:00:00+00:00"),
        _fake_revision("rev-mid", active=False, created_time="2026-08-20T00:00:00+00:00"),
    ]
    monkeypatch.setattr(control_module, "_az_client", lambda: _revisions_client(fake_app, revisions))

    body = open_client.get("/control/workers/revisions").json()
    names = [r["name"] for r in body["revisions"]]
    assert names == ["rev-newest", "rev-mid", "rev-old"]


def test_revisions_with_no_created_time_sort_last(open_client, monkeypatch):
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", True)

    fake_app = _fake_app()
    revisions = [
        _fake_revision("rev-known", active=True, created_time="2026-08-20T00:00:00+00:00"),
        _fake_revision("rev-unknown", active=False, created_time=None),
    ]
    monkeypatch.setattr(control_module, "_az_client", lambda: _revisions_client(fake_app, revisions))

    body = open_client.get("/control/workers/revisions").json()
    names = [r["name"] for r in body["revisions"]]
    assert names == ["rev-known", "rev-unknown"]
    assert body["revisions"][1]["created_time"] is None


def test_matches_traffic_percent_per_revision_not_just_the_active_one(open_client, monkeypatch):
    """A canary/blue-green rollout can split traffic across two revisions simultaneously — the
    exact case GET /control/workers/capacity can't show, since it only checks the active
    revision's own weight. This is the case this whole endpoint exists to make visible."""
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", True)

    fake_app = _fake_app(traffic=[
        _fake_traffic_weight("rev-old", 20), _fake_traffic_weight("rev-new", 80)])
    revisions = [
        _fake_revision("rev-old", active=False, replicas=1, created_time="2026-08-20T00:00:00Z"),
        _fake_revision("rev-new", active=True, replicas=3, created_time="2026-08-28T00:00:00Z"),
    ]
    monkeypatch.setattr(control_module, "_az_client", lambda: _revisions_client(fake_app, revisions))

    body = open_client.get("/control/workers/revisions").json()
    by_name = {r["name"]: r for r in body["revisions"]}
    assert by_name["rev-old"]["traffic_percent"] == 20
    assert by_name["rev-new"]["traffic_percent"] == 80


def test_traffic_percent_is_none_for_every_revision_when_ingress_is_absent(open_client, monkeypatch):
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", True)

    fake_app = _fake_app()   # no traffic= passed -> ingress=None
    revisions = [_fake_revision("rev1", active=True, created_time="2026-08-20T00:00:00Z")]
    monkeypatch.setattr(control_module, "_az_client", lambda: _revisions_client(fake_app, revisions))

    body = open_client.get("/control/workers/revisions").json()
    assert body["revisions"][0]["traffic_percent"] is None


def test_returns_empty_list_when_the_container_app_is_unreachable(open_client, monkeypatch):
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", True)

    class _Boom:
        container_apps = SimpleNamespace(get=lambda rg, name: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(control_module, "_az_client", lambda: _Boom())

    body = open_client.get("/control/workers/revisions").json()
    assert body == {"configured": True, "revisions": []}


def test_returns_empty_list_when_list_revisions_itself_fails(open_client, monkeypatch):
    """The Container App itself is reachable (app.properties resolves fine) but the revisions
    call specifically fails — a narrower failure than the app being unreachable entirely, and
    the response must still be an honest configured:true/revisions:[] rather than a 500."""
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", True)

    fake_app = _fake_app()
    az_client = SimpleNamespace(
        container_apps=SimpleNamespace(get=lambda rg, name: fake_app),
        container_apps_revisions=SimpleNamespace(
            list_revisions=lambda rg, name: (_ for _ in ()).throw(RuntimeError("nope"))),
    )
    monkeypatch.setattr(control_module, "_az_client", lambda: az_client)

    body = open_client.get("/control/workers/revisions").json()
    assert body == {"configured": True, "revisions": []}


def test_created_time_accepts_a_datetime_object_via_isoformat(open_client, monkeypatch):
    """created_time's exact SDK shape is unverified (see this file's and control.py's own
    caveats) — a real datetime is one plausible shape, a pre-formatted string is another; both
    must survive without an AttributeError swallowing the whole revision list."""
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", True)

    dt = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)
    fake_app = _fake_app()
    revisions = [_fake_revision("rev1", active=True, created_time=dt)]
    monkeypatch.setattr(control_module, "_az_client", lambda: _revisions_client(fake_app, revisions))

    body = open_client.get("/control/workers/revisions").json()
    assert body["revisions"][0]["created_time"] == dt.isoformat()


def test_fields_fall_through_to_the_flat_shape_when_not_nested_under_properties(open_client, monkeypatch):
    """Same dual-path safety _rev_field already has for GET /control/workers/capacity — proven
    here too since get_revisions() reuses the same helper for every field it reads."""
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", True)

    fake_app = _fake_app()
    revisions = [_fake_revision("rev1", active=True, health_state="Healthy", replicas=2,
                                 created_time="2026-08-20T00:00:00Z", nested=False)]
    monkeypatch.setattr(control_module, "_az_client", lambda: _revisions_client(fake_app, revisions))

    body = open_client.get("/control/workers/revisions").json()
    rev = body["revisions"][0]
    assert rev["active"] is True
    assert rev["health_state"] == "Healthy"
    assert rev["replicas"] == 2


def test_the_revision_list_reads_the_named_app_and_a_scope_slip_cannot_hide_in_the_except(
        open_client, monkeypatch):
    """Regression, and a guard on the shape of the bug rather than the typo.

    A global rename for the multi-app capacity read reached this function, where no `app_name`
    exists — and the resulting NameError landed in the bare `except` below as `revisions: []`. The
    endpoint answered 200 with an empty list, which is exactly what it answers when Azure is
    reachable but has no revisions, so nothing looked wrong.

    So this asserts the app the list was asked FOR, not just that a list came back: a call made
    against the wrong name, or against a name that does not resolve, fails here instead of
    degrading into a plausible empty answer.
    """
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", True)
    monkeypatch.setattr(control_module, "_AZ_APP", "acp-assess")
    asked = []

    fake_app = _fake_app()
    client = SimpleNamespace(
        container_apps=SimpleNamespace(get=lambda rg, name: fake_app),
        container_apps_revisions=SimpleNamespace(
            list_revisions=lambda rg, name: (asked.append(name), SimpleNamespace(value=[
                _fake_revision("acp-assess--rev1", active=True, health_state="Healthy",
                               provisioning_state="Provisioned", running_state="Running",
                               replicas=2, created_time="2026-09-01T10:00:00+00:00")]))[1]),
    )
    monkeypatch.setattr(control_module, "_az_client", lambda: client)

    body = open_client.get("/control/workers/revisions").json()
    assert asked == ["acp-assess"]
    assert [r["name"] for r in body["revisions"]] == ["acp-assess--rev1"]
    assert body["revisions"][0]["replicas"] == 2
