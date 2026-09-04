"""Replica lifecycle — what Azure Container Apps actually reports about a worker's replicas, and
the two states in the wish list it does not report at all.

The claim under test is the boundary. `Replica.properties.runningState` is a three-value enum —
Running, NotRunning, Unknown — so "allocating", "starting" and "ready" cannot be read off it and
are DERIVED from the container-level `started` and `ready` booleans, named for what they are. And
two states are not derivable at any level:

  · REQUESTED — Azure exposes no pending-replica list.
  · FAILED — a replica that failed and was removed is simply absent from list_replicas; the
    failure surfaces on the REVISION's provisioningState and provisioningError.

Both are reported as unavailable with the reason, because a reader who counts six states and sees
four should be told why rather than left to assume the missing ones are zero.

Same caveat as test_worker_capacity.py: the fake SDK shapes come from Microsoft's published REST
reference (Revision and Replica definitions), not from a live account.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import pytest


def _container(ready=True, started=True, restart_count=0, image="acr.io/acp-assess:v25"):
    return SimpleNamespace(properties=SimpleNamespace(
        ready=ready, started=started, restart_count=restart_count, image=image,
        running_state="Running", running_state_details=None))


def _replica(name="replica-1", running_state="Running", containers=None, created_minutes_ago=5,
             details=None):
    created = datetime.now(timezone.utc) - timedelta(minutes=created_minutes_ago)
    return SimpleNamespace(name=name, properties=SimpleNamespace(
        running_state=running_state, running_state_details=details, created_time=created,
        containers=containers if containers is not None else [_container()]))


def _revision(name, active=True, replicas=1, traffic=100, health="Healthy",
              provisioning="Provisioned", error=None, running="Running", created_minutes_ago=30):
    created = datetime.now(timezone.utc) - timedelta(minutes=created_minutes_ago)
    return SimpleNamespace(name=name, properties=SimpleNamespace(
        active=active, replicas=replicas, traffic_weight=traffic, health_state=health,
        provisioning_state=provisioning, provisioning_error=error, running_state=running,
        created_time=created))


@pytest.fixture()
def control(monkeypatch):
    import routes.control as control_module
    monkeypatch.setattr(control_module, "_AZ_CONFIGURED", True)
    monkeypatch.setattr(control_module, "_AZ_APP", "acp-assess")
    control_module._capacity_cache.update(at=0.0, value=None)
    return control_module


# ── The derived states ──────────────────────────────────────────────────────────────────────

def test_a_replica_whose_containers_are_all_ready_is_ready(control):
    assert control._replica_state(_replica(), draining=False)[0] == "ready"


def test_started_but_not_ready_is_starting_not_ready(control):
    """This is the startup window a reader is looking for when they ask why capacity has not
    arrived yet. Azure's own runningState says "Running" for both."""
    replica = _replica(containers=[_container(ready=False, started=True)])
    assert control._replica_state(replica, draining=False)[0] == "starting"


def test_a_container_that_has_not_started_is_allocating(control):
    replica = _replica(containers=[_container(ready=False, started=False)])
    assert control._replica_state(replica, draining=False)[0] == "allocating"


def test_one_container_not_ready_holds_the_whole_replica_out_of_ready(control):
    replica = _replica(containers=[_container(ready=True), _container(ready=False, started=True)])
    assert control._replica_state(replica, draining=False)[0] == "starting"


def test_azure_own_not_running_and_unknown_are_passed_through(control):
    assert control._replica_state(_replica(running_state="NotRunning"), draining=False)[0] == "not_running"
    assert control._replica_state(_replica(running_state="Unknown"), draining=False)[0] == "unknown"
    assert control._replica_state(_replica(running_state=""), draining=False)[0] == "unknown"


def test_draining_wins_over_the_replica_own_state(control):
    """A replica still up on a superseded revision is draining whatever it reports about itself.
    That is the practical signal a rollout is mid-drain rather than done."""
    assert control._replica_state(_replica(), draining=True)[0] == "draining"
    assert control._replica_state(_replica(running_state="NotRunning"), draining=True)[0] == "draining"


def test_the_platform_detail_string_is_carried_rather_than_discarded(control):
    replica = _replica(running_state="NotRunning", details="ImagePullBackOff")
    state, detail = control._replica_state(replica, draining=False)
    assert (state, detail) == ("not_running", "ImagePullBackOff")


# ── Rows ────────────────────────────────────────────────────────────────────────────────────

def _client(revisions, replicas_by_revision):
    return SimpleNamespace(
        container_apps_revisions=SimpleNamespace(
            list_revisions=lambda rg, app: SimpleNamespace(value=revisions)),
        container_apps_revision_replicas=SimpleNamespace(
            list_replicas=lambda rg, app, rev: SimpleNamespace(value=replicas_by_revision.get(rev, []))),
    )


def test_a_row_carries_age_restarts_and_the_image_it_is_running(control):
    client = _client([], {"acp-assess--v25": [
        _replica(containers=[_container(restart_count=2), _container(restart_count=1)])]})
    rows = control._replica_rows(client, "acp-assess--v25")
    assert len(rows) == 1
    row = rows[0]
    assert row["state"] == "ready"
    assert row["restarts"] == 3          # summed across containers: a pod's restarts, not one process's
    assert row["image"] == "acr.io/acp-assess:v25"
    assert row["containers_ready"] == 2 and row["containers"] == 2
    assert 250 <= row["age_s"] <= 350    # created five minutes ago
    assert row["created_at"]


def test_a_revision_whose_replicas_cannot_be_listed_contributes_nothing(control):
    """Never raises: one unreadable revision must not lose the reading for the others."""
    client = SimpleNamespace(container_apps_revision_replicas=SimpleNamespace(
        list_replicas=lambda rg, app, rev: (_ for _ in ()).throw(RuntimeError("forbidden"))))
    assert control._replica_rows(client, "acp-assess--v25") == []


def test_age_never_fabricates_a_zero_for_a_timestamp_it_cannot_read(control):
    assert control._age_seconds(None) is None
    assert control._age_seconds("not a timestamp") is None
    assert control._age_seconds(datetime.now(timezone.utc) - timedelta(seconds=90)) in range(88, 93)
    # A naive timestamp is treated as UTC rather than crashing on the comparison.
    assert control._age_seconds((datetime.now(timezone.utc) - timedelta(seconds=60)).replace(tzinfo=None)) in range(58, 63)


# ── What Azure does not report ──────────────────────────────────────────────────────────────

def test_the_summary_names_the_states_azure_does_not_report(control):
    summary = control._lifecycle_summary([
        {"state": "ready"}, {"state": "ready"}, {"state": "starting"}, {"state": "draining"}])
    assert summary["counts"]["ready"] == 2
    assert summary["counts"]["starting"] == 1
    assert summary["counts"]["draining"] == 1
    assert summary["counts"]["allocating"] == 0
    assert summary["total"] == 4
    # The point of the test: these are absent measurements, not zeroes.
    assert summary["unreported_states"] == ["requested", "failed"]
    assert "does not list pending or removed replicas" in summary["unreported_reason"]


# ── End to end through the route ────────────────────────────────────────────────────────────

def test_capacity_reports_every_revision_and_the_replicas_on_each(control, monkeypatch):
    active = _revision("acp-assess--v25", active=True, replicas=2, traffic=100)
    old = _revision("acp-assess--v24", active=False, replicas=1, traffic=0, created_minutes_ago=300)
    client = _client([active, old], {
        "acp-assess--v25": [_replica("r1"), _replica("r2", containers=[_container(ready=False, started=True)])],
        "acp-assess--v24": [_replica("r0")],
    })
    client.container_apps = SimpleNamespace(get=lambda rg, name: SimpleNamespace(
        id="/subs/x/app", properties=SimpleNamespace(
            template=SimpleNamespace(scale=SimpleNamespace(min_replicas=1, max_replicas=5), containers=[]),
            latest_ready_revision_name="acp-assess--v25", workload_profile_name="Consumption",
            configuration=SimpleNamespace(ingress=None))))
    monkeypatch.setattr(control, "_az_client", lambda: client)
    monkeypatch.setattr(control, "_monitor_client",
                        lambda: SimpleNamespace(metrics=SimpleNamespace(
                            list=lambda *a, **kw: SimpleNamespace(value=[]))))

    body = control.get_capacity()
    assert [r["name"] for r in body["revisions"]] == ["acp-assess--v25", "acp-assess--v24"]
    assert body["revisions"][0]["traffic_percent"] == 100
    assert body["revisions"][0]["active"] is True
    assert body["draining_replicas"] == 1
    # The old revision's replica is draining; the active revision's two are ready and starting.
    assert sorted(r["state"] for r in body["replicas"]) == ["draining", "ready", "starting"]
    assert body["replica_lifecycle"]["counts"] == {
        "ready": 1, "starting": 1, "allocating": 0, "not_running": 0, "draining": 1, "unknown": 0}


def test_a_failed_rollout_surfaces_on_the_revision_not_as_a_missing_replica(control, monkeypatch):
    """A failed replica is simply absent from list_replicas, so without the revision's own
    provisioningError a rollout that never came up reads as an app with fewer replicas."""
    failed = _revision("acp-assess--v26", active=True, replicas=0, traffic=100,
                       health="Unhealthy", provisioning="Failed",
                       error="ImagePullFailure: manifest unknown", running="Failed")
    client = _client([failed], {})
    client.container_apps = SimpleNamespace(get=lambda rg, name: SimpleNamespace(
        id="/subs/x/app", properties=SimpleNamespace(
            template=SimpleNamespace(scale=SimpleNamespace(min_replicas=1, max_replicas=5), containers=[]),
            latest_ready_revision_name="acp-assess--v26", workload_profile_name="Consumption",
            configuration=SimpleNamespace(ingress=None))))
    monkeypatch.setattr(control, "_az_client", lambda: client)
    monkeypatch.setattr(control, "_monitor_client",
                        lambda: SimpleNamespace(metrics=SimpleNamespace(
                            list=lambda *a, **kw: SimpleNamespace(value=[]))))

    body = control.get_capacity()
    revision = body["revisions"][0]
    assert revision["provisioning_state"] == "Failed"
    assert revision["provisioning_error"] == "ImagePullFailure: manifest unknown"
    assert body["replicas"] == []
    assert body["replica_lifecycle"]["total"] == 0


def test_the_unconfigured_shape_carries_the_keys_empty_rather_than_absent(control, monkeypatch):
    monkeypatch.setattr(control, "_AZ_CONFIGURED", False)
    body = control.get_capacity()
    assert body["replicas"] == []
    assert body["revisions"] == []
    assert body["replica_lifecycle"] is None


# ── Scale rules ─────────────────────────────────────────────────────────────────────────────

def _scale(rules=None, min_replicas=1, max_replicas=4, polling=30, cooldown=300):
    return SimpleNamespace(min_replicas=min_replicas, max_replicas=max_replicas,
                           polling_interval=polling, cooldown_period=cooldown, rules=rules or [])


def _app_with_scale(scale):
    return SimpleNamespace(id="/subs/x/app", properties=SimpleNamespace(
        template=SimpleNamespace(scale=scale, containers=[]),
        latest_ready_revision_name="acp-assess--v25", workload_profile_name="Consumption",
        configuration=SimpleNamespace(ingress=None)))


def test_the_configured_scale_rules_are_reported_with_their_thresholds(control):
    rule = SimpleNamespace(name="queue-depth", azure_queue=None, http=None, tcp=None,
                           custom=SimpleNamespace(type="azure-servicebus",
                                                  metadata={"queueLength": "5", "namespace": "acp"}))
    block = control._scale_block(_app_with_scale(_scale([rule])))
    assert block["min_replicas"] == 1 and block["max_replicas"] == 4
    assert block["polling_interval_s"] == 30 and block["cooldown_period_s"] == 300
    assert block["rules"] == [{"name": "queue-depth", "type": "azure-servicebus",
                               "metadata": {"queueLength": "5", "namespace": "acp"},
                               "queue_length": None, "queue_name": None}]


def test_anything_that_reads_like_a_credential_is_dropped_from_rule_metadata(control):
    """KEDA metadata is a free-form map an operator fills in, and this panel is open to any
    signed-in workspace user. Thresholds and queue names are useful next to the live metric;
    a connection string is not published."""
    rule = SimpleNamespace(name="q", azure_queue=None, http=None, tcp=None,
                           custom=SimpleNamespace(type="azure-queue", metadata={
                               "queueLength": "5", "connectionFromEnv": "QUEUE_CONN",
                               "accountKey": "abc", "apiToken": "xyz", "topicName": "t"}))
    block = control._scale_block(_app_with_scale(_scale([rule])))
    assert block["rules"][0]["metadata"] == {"queueLength": "5", "topicName": "t"}


def test_an_app_with_no_scale_rule_reports_an_empty_list_not_a_missing_one(control):
    """No rule is a real configuration — the app stays between min and max — and a different
    answer from "the rules could not be read"."""
    block = control._scale_block(_app_with_scale(_scale([])))
    assert block["rules"] == []
    assert block["rules_reported"] is True


def test_the_block_never_claims_azure_said_which_rule_fired(control):
    block = control._scale_block(_app_with_scale(_scale([])))
    assert "does not report which scale rule caused" in block["attribution"]


def test_an_unreadable_scale_section_is_none_rather_than_an_empty_configuration(control):
    assert control._scale_block(SimpleNamespace(properties=SimpleNamespace(template=None))) is None
