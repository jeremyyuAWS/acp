"""Tier 5: Resource Health and Service Health, read from the Azure activity log.

THE CONSTRAINT THAT SHAPES EVERY TEST HERE. `activity_logs.list` returns health TRANSITION
EVENTS, not a current status. Azure's current resource health lives behind a different provider
(Microsoft.ResourceHealth/availabilityStatuses/current) that this repo does not install. So no
field here may claim "this app is Available" — only "the last transition Azure reported was
Available, at time T". An app that went unavailable ninety seconds ago has not had its event
ingested yet, and reading the older event as a current status would show a broken service as
healthy at exactly the moment that matters most.

The second theme is that the two questions stay apart. Resource Health is about this container
app; Service Health is about Azure, subscription-wide. Attributing a regional Azure incident to
one worker service would read as that service being at fault.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ACP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ACP / "api"))

import pytest

import routes.control as control

NOW = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
APP_ID = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.App/containerApps/acp-worker"


class _Local:
    def __init__(self, value):
        self.value = value
        self.localized_value = value


class _Event:
    def __init__(self, category, properties, at=None, resource_id=APP_ID):
        self.category = _Local(category)
        self.properties = properties
        self.event_timestamp = at or NOW
        self.resource_id = resource_id


class _FakeClient:
    def __init__(self, events, raises=None):
        self._events = events
        self._raises = raises
        self.filters = []
        outer = self

        class _ActivityLogs:
            def list(self, filter):  # noqa: A002 — the SDK's own parameter name
                outer.filters.append(filter)
                if outer._raises:
                    raise outer._raises
                return iter(outer._events)

        self.activity_logs = _ActivityLogs()


@pytest.fixture(autouse=True)
def _quiet():
    import swallowed as _s
    _s.reset()
    yield
    _s.reset()


def _install(monkeypatch, client):
    monkeypatch.setattr(control, "_monitor_client", lambda: client)
    return client


# ── Resource health: a transition is not a current status ───────────────────────────────────────

def test_the_reading_is_dated_so_it_cannot_be_read_as_now():
    """The whole point. Every consumer needs `reported_at` to exist, because a status without one
    is indistinguishable from a live reading — and this API cannot supply a live one."""
    block = control._empty_resource_health()
    assert "reported_at" in block and "status" in block
    assert "window_hours" in block, "the reader has to know how far back this looked"


def test_no_transitions_is_reported_as_no_events_never_as_available(monkeypatch):
    """The failure that would undo this file. A quiet 24 hours is the NORMAL case, and it is also
    what an un-ingested outage looks like. Reporting it as Available invents the one answer the
    data cannot support."""
    _install(monkeypatch, _FakeClient([]))
    block = control._resource_health(APP_ID, NOW)
    assert block["queried"] is True
    assert block["status"] is None
    assert block["transitions"] == []
    assert block["tone"] is None


def test_the_latest_transition_wins_and_carries_its_own_timestamp(monkeypatch):
    older = _Event("ResourceHealth", {"currentHealthStatus": "Available",
                                      "previousHealthStatus": "Unavailable",
                                      "cause": "PlatformInitiated"},
                   at=datetime(2026, 9, 5, 6, 0, tzinfo=timezone.utc))
    newer = _Event("ResourceHealth", {"currentHealthStatus": "Degraded",
                                      "previousHealthStatus": "Available",
                                      "cause": "PlatformInitiated"},
                   at=datetime(2026, 9, 5, 11, 0, tzinfo=timezone.utc))
    _install(monkeypatch, _FakeClient([older, newer]))
    block = control._resource_health(APP_ID, NOW)
    assert block["status"] == "Degraded"
    assert block["previous"] == "Available"
    assert block["reported_at"].startswith("2026-09-05T11:00")
    assert len(block["transitions"]) == 2


def test_events_out_of_order_still_yield_the_newest(monkeypatch):
    """The activity log is documented newest-first, but the ordering is the API's promise rather
    than this code's. Sorting locally means a change there degrades to a slower read, not to the
    wrong status."""
    a = _Event("ResourceHealth", {"currentHealthStatus": "Available"},
               at=datetime(2026, 9, 5, 3, 0, tzinfo=timezone.utc))
    b = _Event("ResourceHealth", {"currentHealthStatus": "Unavailable"},
               at=datetime(2026, 9, 5, 9, 0, tzinfo=timezone.utc))
    _install(monkeypatch, _FakeClient([a, b]))       # deliberately oldest-first
    assert control._resource_health(APP_ID, NOW)["status"] == "Unavailable"


def test_unknown_is_its_own_state_not_folded_into_healthy_or_broken(monkeypatch):
    """Azure says Unknown when it cannot tell. Mapping that to ok would claim health nobody
    measured; mapping it to bad would page someone for an absence of information."""
    _install(monkeypatch, _FakeClient([_Event("ResourceHealth", {"currentHealthStatus": "Unknown"})]))
    block = control._resource_health(APP_ID, NOW)
    assert block["status"] == "Unknown"
    assert block["tone"] == "warn"
    assert control._HEALTH_STATES["available"] == "ok"
    assert control._HEALTH_STATES["unavailable"] == "bad"


def test_the_cause_separates_azure_did_this_from_a_deploy_did_this(monkeypatch):
    """PlatformInitiated and UserInitiated call for opposite responses — wait it out, or roll
    back. Dropping the cause makes an operator guess which."""
    _install(monkeypatch, _FakeClient([_Event("ResourceHealth", {
        "currentHealthStatus": "Unavailable", "cause": "UserInitiated"})]))
    assert control._resource_health(APP_ID, NOW)["cause"] == "UserInitiated"


def test_a_failed_query_is_not_a_healthy_app(monkeypatch):
    err = RuntimeError("forbidden")
    err.status_code = 403
    _install(monkeypatch, _FakeClient([], raises=err))
    block = control._resource_health(APP_ID, NOW)
    assert block["queried"] is False
    assert block["status"] is None
    assert block["unavailable_reason"] == "permission"


def test_no_app_id_asks_azure_nothing(monkeypatch):
    client = _install(monkeypatch, _FakeClient([]))
    assert control._resource_health(None, NOW)["queried"] is False
    assert client.filters == []


def test_the_filter_bounds_time_and_narrows_to_this_resource(monkeypatch):
    """activity_logs.list REJECTS a filter without eventTimestamp bounds, and without a resourceId
    it returns the whole subscription's log — every app's health under one app's name."""
    client = _install(monkeypatch, _FakeClient([]))
    control._resource_health(APP_ID, NOW)
    sent = client.filters[0]
    assert "eventTimestamp ge" in sent and "eventTimestamp le" in sent
    assert "category eq 'ResourceHealth'" in sent
    assert f"resourceId eq '{APP_ID}'" in sent


# ── Service health: Azure's problem, not this service's ─────────────────────────────────────────

def test_service_health_is_not_scoped_to_one_app(monkeypatch):
    """Subscription-wide by construction. A resourceId filter here would silently drop every
    regional incident that did not happen to name this container app."""
    client = _install(monkeypatch, _FakeClient([]))
    control._service_health(NOW)
    assert "category eq 'ServiceHealth'" in client.filters[0]
    assert "resourceId eq" not in client.filters[0]


def test_one_incident_is_one_row_at_its_latest_stage(monkeypatch):
    """An incident emits an event per stage. Three rows would read as three incidents."""
    events = [
        _Event("ServiceHealth", {"trackingId": "ABC-123", "stage": "Resolved",
                                 "title": "Networking degradation"},
               at=datetime(2026, 9, 5, 11, 0, tzinfo=timezone.utc)),
        _Event("ServiceHealth", {"trackingId": "ABC-123", "stage": "Active",
                                 "title": "Networking degradation"},
               at=datetime(2026, 9, 5, 9, 0, tzinfo=timezone.utc)),
    ]
    _install(monkeypatch, _FakeClient(events))
    block = control._service_health(NOW)
    assert len(block["active"]) == 1
    assert block["active"][0]["stage"] == "Resolved"
    assert block["active"][0]["resolved"] is True


def test_a_resolved_incident_is_kept_not_filtered_out(monkeypatch):
    """An incident that resolved twenty minutes ago is the explanation for the restarts still on
    the timeline. Dropping it leaves an operator hunting a cause Azure already published."""
    _install(monkeypatch, _FakeClient([_Event("ServiceHealth", {
        "trackingId": "X", "stage": "Resolved", "title": "Storage latency"})]))
    block = control._service_health(NOW)
    assert len(block["active"]) == 1
    assert block["active"][0]["resolved"] is True


def test_an_incident_without_a_tracking_id_is_not_deduplicated_away(monkeypatch):
    """Keying on trackingId must not collapse the events that have none into a single row."""
    _install(monkeypatch, _FakeClient([
        _Event("ServiceHealth", {"stage": "Active", "title": "One"}),
        _Event("ServiceHealth", {"stage": "Active", "title": "Two"}),
    ]))
    assert len(control._service_health(NOW)["active"]) == 2


def test_a_failed_query_is_not_an_absence_of_incidents(monkeypatch):
    _install(monkeypatch, _FakeClient([], raises=RuntimeError("network")))
    block = control._service_health(NOW)
    assert block["queried"] is False
    assert block["active"] == []
    assert block["unavailable_reason"] == "error"


# ── Microsoft's prose reaches our page ──────────────────────────────────────────────────────────

def test_microsofts_html_is_stripped_before_it_reaches_the_page():
    """`communication` is HTML written by an external system, and it lands on a screen any
    signed-in workspace user can open. Tags are removed rather than escaped-and-rendered: handing
    external markup to a renderer is safe only until somebody swaps the renderer."""
    assert control._strip_html("<p>Storage is <b>degraded</b></p>") == "Storage is degraded"
    assert "<script>" not in (control._strip_html("<script>alert(1)</script>hi") or "")
    assert control._strip_html("<img src=x onerror=alert(1)>text") == "text"


def test_entities_are_decoded_so_they_do_not_read_as_themselves():
    assert control._strip_html("Cloud &amp; Storage") == "Cloud & Storage"


def test_stripping_collapses_the_whitespace_tags_leave_behind():
    """A tag becomes a space, not nothing — otherwise `<div>a</div><div>b</div>` reads as "ab"."""
    assert control._strip_html("<div>a</div><div>b</div>") == "a b"


def test_the_space_a_tag_leaves_does_not_land_before_punctuation():
    """The cost of the rule above, taken back out rather than paid on screen: prose ending in an
    inline tag would otherwise read "We are investigating ."."""
    assert control._strip_html("<p>We are <i>investigating</i>.</p>") == "We are investigating."
    assert control._strip_html("up <b>85</b>%") == "up 85%"
    assert control._strip_html("see <a href='#'>this</a>, then wait") == "see this, then wait"


def test_empty_and_missing_prose_stay_none_rather_than_becoming_blank_strings():
    assert control._strip_html(None) is None
    assert control._strip_html("") is None
    assert control._strip_html("<p></p>") is None


def test_the_prose_actually_gets_stripped_on_the_way_through(monkeypatch):
    """The unit above proves the helper works; this proves it is wired in. A stripper nothing
    calls is the shape of a security control that is not there."""
    _install(monkeypatch, _FakeClient([_Event("ServiceHealth", {
        "trackingId": "X", "stage": "Active", "title": "<b>Outage</b>",
        "communication": "<p>We are <i>investigating</i>.</p>"})]))
    row = control._service_health(NOW)["active"][0]
    assert row["title"] == "Outage"
    assert row["summary"] == "We are investigating."
    assert "<" not in f"{row['title']}{row['summary']}"


def test_impacted_services_are_parsed_from_the_json_string_azure_nests(monkeypatch):
    _install(monkeypatch, _FakeClient([_Event("ServiceHealth", {
        "trackingId": "X", "stage": "Active",
        "impactedServices": '[{"ServiceName":"Container Apps",'
                            '"ImpactedRegions":[{"RegionName":"East US"}]}]'})]))
    assert control._service_health(NOW)["active"][0]["services"] == [
        {"service": "Container Apps", "regions": ["East US"]}]


def test_a_shape_azure_changes_degrades_to_empty_rather_than_raising():
    """This is nested JSON inside a string inside a property map — three chances for the encoding
    to move. None of them should take the incident row down with them."""
    for raw in ("not json", "{}", '["a string"]', '[{"no":"names"}]', None, 42):
        assert isinstance(control._impacted_services(raw), list)


# ── Present in every shape, and separate from each other ────────────────────────────────────────

def test_resource_health_is_per_app_and_service_health_is_not(monkeypatch):
    """The structural half of keeping the two questions apart: if service health were nested in an
    app block, a regional Azure incident would render as that service's fault."""
    block = control._empty_capacity(True, "acp-assess")
    assert "resource_health" in block
    assert "service_health" not in block, \
        "service health is subscription-scoped and must not sit inside one app's block"


def test_an_unconfigured_deployment_still_carries_both_keys(monkeypatch):
    monkeypatch.setattr(control, "_AZ_CONFIGURED", False)
    payload = control.get_capacity()
    assert payload["resource_health"]["queried"] is False
    assert payload["service_health"]["queried"] is False
