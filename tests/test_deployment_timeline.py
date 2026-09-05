"""Tier 4: the deployment timeline, and the half of a deployment Azure cannot see.

WHAT MAKES THIS FILE NECESSARY. Azure knows what it did to the platform — a revision was created,
it took traffic, an old one drained, a write succeeded or failed. It knows nothing about the half
that happens first: the build, the image publish, the smoke test. A timeline that silently begins
at "revision created" reads as though the deployment began there, and the most common real failure
— a build that never produced an image — would show up as no timeline at all, which is
indistinguishable from no deployment having been attempted.

The second theme is per-revision attribution. Azure Monitor collects CPU, memory, latency and
errors per CONTAINER APP. Splitting them by revision is not attempted, because a dimension filter
Azure ignored rather than rejected would return app-wide data wearing one revision's name — a
regression blamed on a deploy that did not cause it.
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


class _Event:
    def __init__(self, operation, status="Succeeded", at=None, description=None):
        self.operation_name = _Local(operation)
        self.status = _Local(status)
        self.category = _Local("Administrative")
        self.description = _Local(description) if description else None
        self.event_timestamp = at or NOW
        self.caller = "someone@example.org"
        self.properties = {}


class _FakeClient:
    def __init__(self, events, raises=None):
        self._events = events
        self._raises = raises
        self.filters = []
        outer = self

        class _ActivityLogs:
            def list(self, filter):  # noqa: A002
                outer.filters.append(filter)
                if outer._raises:
                    raise outer._raises
                return iter(outer._events)

        self.activity_logs = _ActivityLogs()


def rev(name, **over):
    row = {"name": name, "active": False, "health": "Healthy",
           "provisioning_state": "Provisioned", "provisioning_error": None,
           "running_state": "Running", "replicas": 2, "traffic_percent": 0,
           "created_at": "2026-09-05T09:00:00+00:00", "last_active_at": None, "age_s": 100,
           "image": "acr.io/acp:v1", "cpu": 1.0, "memory": "2Gi"}
    row.update(over)
    return row


@pytest.fixture(autouse=True)
def _quiet():
    import swallowed as _s
    _s.reset()
    yield
    _s.reset()


def _install(monkeypatch, client):
    monkeypatch.setattr(control, "_monitor_client", lambda: client)
    return client


# ── The steps Azure cannot see are named, not omitted ───────────────────────────────────────────

def test_the_steps_azure_cannot_see_are_named_with_where_they_live():
    """The whole reason this file exists. A timeline that begins at "revision created" claims the
    deployment began there."""
    block = control._empty_deployments()
    steps = {row["step"] for row in block["not_reported"]}
    assert steps == {"Build started", "Image published", "Smoke test passed"}
    for row in block["not_reported"]:
        assert row["reason"], row["step"]
        assert len(row["reason"]) > 30, "a gap without a reason is just an absence"


def test_the_named_gaps_survive_a_deployment_with_no_azure_at_all(monkeypatch):
    """They are gaps on a local deployment too — arguably more so. A payload that only names them
    when Azure answers would hide them exactly where nothing else fills them in."""
    monkeypatch.setattr(control, "_AZ_CONFIGURED", False)
    payload = control.get_capacity()
    assert len(payload["deployments"]["not_reported"]) == 3
    assert payload["deployments"]["system_logs"]["available"] is False


def test_the_system_log_gap_says_which_workspace_and_that_it_lags():
    """"Not available" is not enough to act on. The reason names Log Analytics, and the roughly
    three-minute ingestion delay, so nobody expects it to be live once it exists."""
    logs = control._empty_deployments()["system_logs"]
    assert "Log Analytics" in logs["reason"]
    assert "three minutes" in logs["reason"]


# ── The timeline itself ─────────────────────────────────────────────────────────────────────────

def test_deployment_operations_become_timeline_rows(monkeypatch):
    _install(monkeypatch, _FakeClient([
        _Event("Microsoft.App/containerApps/write", "Succeeded",
               at=datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc))]))
    block = control._deployments_for_app(APP_ID, [], NOW)
    assert block["queried"] is True
    assert [e["label"] for e in block["events"]] == ["Container app updated"]
    assert block["events"][0]["status"] == "Succeeded"
    assert block["events"][0]["failed"] is False


def test_a_failed_operation_is_kept_and_flagged(monkeypatch):
    """The row that matters most on a deployment timeline. Filtering non-successes would leave the
    timeline showing only the deploys that worked."""
    _install(monkeypatch, _FakeClient([
        _Event("Microsoft.App/containerApps/write", "Failed")]))
    row = control._deployments_for_app(APP_ID, [], NOW)["events"][0]
    assert row["failed"] is True
    assert row["status"] == "Failed"


def test_unrelated_administrative_writes_are_not_rendered_as_deployments(monkeypatch):
    """A tag write and a diagnostic-setting change are Administrative too. Showing them as deploys
    would put a deployment on the timeline that never happened."""
    _install(monkeypatch, _FakeClient([
        _Event("Microsoft.Resources/tags/write"),
        _Event("Microsoft.Insights/diagnosticSettings/write"),
        _Event("Microsoft.App/containerApps/write")]))
    labels = [e["label"] for e in control._deployments_for_app(APP_ID, [], NOW)["events"]]
    assert labels == ["Container app updated"]


def test_the_caller_never_reaches_the_payload(monkeypatch):
    """An activity-log caller is a person's UPN or a service principal id, and this response lands
    on a screen any signed-in workspace user can open. "What happened and when" is the operational
    question; "who did it" belongs to the audit log, with a different audience."""
    _install(monkeypatch, _FakeClient([_Event("Microsoft.App/containerApps/write")]))
    block = control._deployments_for_app(APP_ID, [], NOW)
    assert "someone@example.org" not in str(block)
    assert all("caller" not in row for row in block["events"])


def test_revision_milestones_survive_an_activity_log_failure(monkeypatch):
    """They came from a call that already succeeded. A partial timeline that says so beats none."""
    _install(monkeypatch, _FakeClient([], raises=RuntimeError("nope")))
    block = control._deployments_for_app(APP_ID, [rev("acp--v2")], NOW)
    assert block["queried"] is False
    assert block["unavailable_reason"] == "error"
    assert [e["label"] for e in block["events"]] == ["Revision acp--v2 created"]


def test_a_failed_revision_carries_azures_own_error_string(monkeypatch):
    """Where a failed rollout actually surfaces: a failed replica is simply absent from the
    replica list, so without this a rollout that never came up reads as fewer replicas."""
    _install(monkeypatch, _FakeClient([]))
    block = control._deployments_for_app(APP_ID, [rev(
        "acp--bad", provisioning_state="Failed",
        provisioning_error="ImagePullBackOff: manifest unknown")], NOW)
    row = block["events"][0]
    assert row["failed"] is True
    assert "ImagePullBackOff" in row["detail"]


def test_when_a_revision_became_ready_is_not_invented(monkeypatch):
    """Azure records that a revision was created and what state it is in now — never when it
    finished provisioning. Approximating "first replica ready" from created_time would report a
    slow rollout as an instant one."""
    _install(monkeypatch, _FakeClient([]))
    labels = [e["label"] for e in
              control._deployments_for_app(APP_ID, [rev("acp--v2")], NOW)["events"]]
    assert not any("ready" in label.lower() for label in labels)


def test_the_live_revision_does_not_get_a_last_served_row(monkeypatch):
    """On the active revision that timestamp is "a moment ago" and would sit on the timeline
    restating the present."""
    _install(monkeypatch, _FakeClient([]))
    rows = control._deployments_for_app(APP_ID, [
        rev("acp--v2", active=True, last_active_at="2026-09-05T11:59:00+00:00"),
        rev("acp--v1", active=False, last_active_at="2026-09-05T09:30:00+00:00")], NOW)["events"]
    served = [e["label"] for e in rows if "last served" in e["label"]]
    assert served == ["Revision acp--v1 last served traffic"]


def test_the_timeline_is_newest_first_across_both_sources(monkeypatch):
    _install(monkeypatch, _FakeClient([
        _Event("Microsoft.App/containerApps/write", at=datetime(2026, 9, 5, 11, 0, tzinfo=timezone.utc))]))
    rows = control._deployments_for_app(APP_ID, [rev("acp--v2", created_at="2026-09-05T08:00:00+00:00")], NOW)["events"]
    assert [r["at"][:16] for r in rows] == ["2026-09-05T11:00", "2026-09-05T08:00"]


def test_the_filter_narrows_to_this_app_and_bounds_time(monkeypatch):
    client = _install(monkeypatch, _FakeClient([]))
    control._deployments_for_app(APP_ID, [], NOW)
    sent = client.filters[0]
    assert "category eq 'Administrative'" in sent
    assert f"resourceId eq '{APP_ID}'" in sent
    assert "eventTimestamp ge" in sent


# ── Revision comparison ─────────────────────────────────────────────────────────────────────────

def test_what_is_not_comparable_is_named_with_the_reason():
    """The honest half. A "CPU went up 12% in this revision" figure would be app-wide data wearing
    a revision's name — a regression blamed on a deploy that did not cause it."""
    cmp = control._revision_comparison([])
    fields = {row["field"] for row in cmp["not_compared"]}
    assert fields == {"error_rate", "latency", "cpu_used", "memory_used"}
    for row in cmp["not_compared"]:
        # Each reason has to say WHERE the number actually lives, not merely that it is absent —
        # it is collected at the APP level and so cannot be attributed to a REVISION. Asserted on
        # both nouns rather than an exact phrase: pinning the wording makes the test a copy of the
        # string, which passes for a reason that has been edited into nonsense.
        reason = row["reason"].lower()
        assert "app" in reason and "revision" in reason, row
        assert len(row["reason"]) > 40, f"{row['field']}: a gap without a reason is an absence"


def test_the_cpu_that_is_compared_is_labelled_as_requested_not_used():
    """Two different numbers with the same name. The comparison shows allocation; the metrics
    panel shows use; conflating them is how a resize reads as a regression."""
    cmp = control._revision_comparison([
        rev("v2", active=True, cpu=2.0), rev("v1", cpu=1.0, created_at="2026-09-04T09:00:00+00:00")])
    labels = {c["label"] for c in cmp["changes"]}
    assert "CPU requested" in labels
    assert not any(c["label"] == "CPU" for c in cmp["changes"])


def test_only_real_differences_become_changes():
    same = control._revision_comparison([
        rev("v2", active=True), rev("v1", created_at="2026-09-04T09:00:00+00:00")])
    assert same["changes"] == []


def test_an_image_change_is_reported_from_and_to():
    cmp = control._revision_comparison([
        rev("v2", active=True, image="acr.io/acp:v2"),
        rev("v1", image="acr.io/acp:v1", created_at="2026-09-04T09:00:00+00:00")])
    change = next(c for c in cmp["changes"] if c["field"] == "image")
    assert change["from"] == "acr.io/acp:v1" and change["to"] == "acr.io/acp:v2"


def test_the_previous_revision_is_the_newest_one_that_is_not_current():
    cmp = control._revision_comparison([
        rev("v3", active=True, created_at="2026-09-05T10:00:00+00:00"),
        rev("v1", created_at="2026-09-03T10:00:00+00:00"),
        rev("v2", created_at="2026-09-04T10:00:00+00:00")])
    assert cmp["previous"]["name"] == "v2"


def test_a_revision_with_no_timestamp_does_not_become_the_previous_one():
    """Sorting undated rows first would make an unknown revision the comparison baseline."""
    cmp = control._revision_comparison([
        rev("v2", active=True), rev("undated", created_at=None),
        rev("v1", created_at="2026-09-04T10:00:00+00:00")])
    assert cmp["previous"]["name"] == "v1"


def test_a_failed_revision_is_never_offered_as_a_rollback_target():
    """It is not a way back. Offering it sends an operator to a revision that never ran."""
    cmp = control._revision_comparison([
        rev("v3", active=True, created_at="2026-09-05T10:00:00+00:00"),
        rev("v2", provisioning_state="Failed", created_at="2026-09-04T10:00:00+00:00"),
        rev("v1", provisioning_state="Provisioned", created_at="2026-09-03T10:00:00+00:00")])
    assert cmp["rollback"]["name"] == "v1"


def test_no_rollback_target_says_so_rather_than_going_quiet():
    cmp = control._revision_comparison([rev("v1", active=True)])
    assert cmp["rollback"] is None
    assert "nothing to roll back to" in cmp["rollback_reason"]


def test_an_empty_revision_list_does_not_raise():
    for revisions in ([], None, [{"no": "name"}]):
        cmp = control._revision_comparison(revisions)
        assert cmp["current"] is None and cmp["changes"] == []


# ── A container's environment must not travel ───────────────────────────────────────────────────

def test_the_revision_template_reader_takes_the_image_and_never_the_environment():
    """A container's env carries connection strings, keys and tokens, and this response reaches a
    screen any signed-in workspace user can open."""
    class _Res:
        cpu, memory = 1.5, "3Gi"

    class _Container:
        image = "acr.io/acp:v9"
        resources = _Res()
        env = [type("E", (), {"name": "DATABASE_URL", "value": "postgres://u:pw@host/db"})()]

    class _Template:
        containers = [_Container()]

    class _Props:
        template = _Template()

    class _Rev:
        properties = _Props()

    out = control._revision_template(_Rev())
    assert out == {"image": "acr.io/acp:v9", "cpu": 1.5, "memory": "3Gi"}
    assert "postgres" not in str(out)
    assert "env" not in out


def test_a_revision_with_no_template_degrades_to_nulls():
    class _Rev:
        properties = None
    assert control._revision_template(_Rev()) == {"image": None, "cpu": None, "memory": None}
