"""Tier 5: which alert rules watch a worker app, and which are firing.

THE ONE THING THIS FILE IS FOR. An empty firing list means "nothing is firing" only when
something is actually watching. With no alert rules configured — which is this deployment's state
today — an empty list means "nobody is watching", and a panel that renders the two alike answers
the operator's real question ("is this component healthy?") with evidence that does not exist.
Every test below is a way that distinction could be lost.
"""
from __future__ import annotations

import sys
from pathlib import Path

ACP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ACP / "api"))

import pytest

import routes.control as control


class _Props:
    def __init__(self, status, timestamp=None):
        self.status = status
        self.timestamp = timestamp


class _StatusRow:
    def __init__(self, status, timestamp=None):
        self.properties = _Props(status, timestamp)


class _StatusCollection:
    def __init__(self, rows):
        self.value = rows


class _Criterion:
    def __init__(self, metric_name, operator, threshold, time_aggregation=None):
        self.metric_name = metric_name
        self.operator = operator
        self.threshold = threshold
        self.time_aggregation = time_aggregation


class _Criteria:
    def __init__(self, all_of):
        self.all_of = all_of


class _Rule:
    def __init__(self, name, scopes, severity=2, enabled=True, description=None,
                 criteria=None, window_size=None, evaluation_frequency=None):
        self.name = name
        self.scopes = scopes
        self.severity = severity
        self.enabled = enabled
        self.description = description
        self.criteria = criteria
        self.window_size = window_size
        self.evaluation_frequency = evaluation_frequency


class _FakeClient:
    """Enough of MonitorManagementClient for the two operation groups this reads."""

    def __init__(self, rules, statuses, rules_raise=None, status_raise=None):
        self._rules = rules
        self._statuses = statuses
        self._rules_raise = rules_raise
        self._status_raise = status_raise
        self.status_calls = []
        outer = self

        class _MetricAlerts:
            def list_by_resource_group(self, rg):
                if outer._rules_raise:
                    raise outer._rules_raise
                return list(outer._rules)

        class _MetricAlertsStatus:
            def list(self, rg, rule_name):
                outer.status_calls.append(rule_name)
                if outer._status_raise:
                    raise outer._status_raise
                return _StatusCollection(outer._statuses.get(rule_name, []))

        self.metric_alerts = _MetricAlerts()
        self.metric_alerts_status = _MetricAlertsStatus()


APP_ID = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.App/containerApps/acp-worker"


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    import swallowed as _s
    _s.reset()
    yield
    _s.reset()


def _install(monkeypatch, client):
    monkeypatch.setattr(control, "_monitor_client", lambda: client)
    return client


# ── The distinction the whole file exists for ───────────────────────────────────────────────────

def test_no_rules_configured_is_not_the_same_answer_as_nothing_firing(monkeypatch):
    """Zero rules and one resolved rule both produce an empty `firing` list. `rules_total` is the
    only thing that separates "nobody is watching" from "everything is fine", so it must be
    present and it must differ between the two."""
    _install(monkeypatch, _FakeClient(rules=[], statuses={}))
    nothing_watching = control._alerts_for_app(APP_ID)

    rule = _Rule("cpu-high", [APP_ID])
    _install(monkeypatch, _FakeClient([rule], {"cpu-high": [_StatusRow("Resolved")]}))
    watched_and_healthy = control._alerts_for_app(APP_ID)

    assert nothing_watching["firing"] == watched_and_healthy["firing"] == []
    assert nothing_watching["rules_total"] == 0
    assert watched_and_healthy["rules_total"] == 1
    # And both were actually asked — an unqueried block is a third state, not either of these.
    assert nothing_watching["queried"] is True and watched_and_healthy["queried"] is True


def test_a_failed_query_is_not_reported_as_zero_rules(monkeypatch):
    """The failure mode that would undo the test above: if a 403 came back as `rules_total: 0`,
    an unreadable subscription would render identically to an unmonitored one — and then a panel
    that correctly warns "nobody is watching" would start crying wolf at every permissions blip."""
    err = RuntimeError("forbidden")
    err.status_code = 403
    _install(monkeypatch, _FakeClient([], {}, rules_raise=err))
    block = control._alerts_for_app(APP_ID)
    assert block["queried"] is False
    assert block["rules_total"] is None
    assert block["unavailable_reason"] == "permission"


def test_a_non_permission_failure_says_error_not_permission(monkeypatch):
    _install(monkeypatch, _FakeClient([], {}, rules_raise=RuntimeError("network")))
    assert control._alerts_for_app(APP_ID)["unavailable_reason"] == "error"


# ── Scoping ─────────────────────────────────────────────────────────────────────────────────────

def test_a_rule_is_matched_by_resource_id_not_by_its_name(monkeypatch):
    """A rule named after this app can be scoped at a different one, and a rule with an unrelated
    name can cover it. Matching on the name would attach the wrong alerts to a service — the same
    class of error as charting one container app's CPU on another."""
    mine = _Rule("watch-something", [APP_ID])
    theirs = _Rule("acp-worker-cpu", ["/subscriptions/s/resourceGroups/rg/providers/"
                                      "Microsoft.App/containerApps/other-app"])
    _install(monkeypatch, _FakeClient([mine, theirs], {"watch-something": [_StatusRow("Resolved")]}))
    block = control._alerts_for_app(APP_ID)
    assert [r["name"] for r in block["rules"]] == ["watch-something"]


def test_scope_matching_ignores_case(monkeypatch):
    """Azure resource ids round-trip through several casings (the portal, the CLI and ARM
    templates disagree on `resourceGroups` vs `resourcegroups`), and a case-sensitive compare
    would silently drop every rule."""
    shouty = _Rule("cpu", [APP_ID.upper()])
    _install(monkeypatch, _FakeClient([shouty], {"cpu": [_StatusRow("Resolved")]}))
    assert control._alerts_for_app(APP_ID)["rules_total"] == 1


def test_no_app_id_asks_azure_nothing(monkeypatch):
    """The container-app lookup can fail before an id exists. Listing every rule in the resource
    group and attaching all of them would be worse than showing none."""
    client = _FakeClient([_Rule("cpu", [APP_ID])], {})
    _install(monkeypatch, client)
    block = control._alerts_for_app(None)
    assert block["queried"] is False and block["rules"] == []
    assert client.status_calls == []


# ── State ───────────────────────────────────────────────────────────────────────────────────────

def test_a_fired_rule_is_reported_firing_with_the_time_it_fired(monkeypatch):
    rule = _Rule("queue-stalled", [APP_ID], severity=1, description="Queue has not drained")
    _install(monkeypatch, _FakeClient(
        [rule], {"queue-stalled": [_StatusRow("Fired", "2026-09-05T01:00:00+00:00")]}))
    block = control._alerts_for_app(APP_ID)
    assert [r["name"] for r in block["firing"]] == ["queue-stalled"]
    assert block["firing"][0]["state"] == "fired"
    assert block["firing"][0]["since"] == "2026-09-05T01:00:00+00:00"
    assert block["firing"][0]["severity_label"] == "Error"


def test_one_fired_dimension_makes_the_rule_fired(monkeypatch):
    """A rule split by dimensions returns one status row per combination. Taking the first row
    would report a live incident as resolved whenever the resolved combination sorted first."""
    rule = _Rule("cpu", [APP_ID])
    _install(monkeypatch, _FakeClient([rule], {"cpu": [
        _StatusRow("Resolved", "2026-09-05T00:00:00+00:00"),
        _StatusRow("Fired", "2026-09-05T01:00:00+00:00"),
        _StatusRow("Resolved", "2026-09-05T00:30:00+00:00"),
    ]}))
    block = control._alerts_for_app(APP_ID)
    assert block["firing"] and block["firing"][0]["since"] == "2026-09-05T01:00:00+00:00"


def test_an_unreadable_status_is_unknown_never_resolved(monkeypatch):
    """The direction this must be wrong in. A status call that fails means the rule's state is
    not known; rendering that as resolved turns an unreadable alert into a green tick."""
    rule = _Rule("cpu", [APP_ID])
    _install(monkeypatch, _FakeClient([rule], {}, status_raise=RuntimeError("boom")))
    row = control._alerts_for_app(APP_ID)["rules"][0]
    assert row["state"] == "unknown"
    assert row["since"] is None


def test_an_empty_status_collection_is_unknown_not_resolved(monkeypatch):
    """Azure answers with no rows for a rule it has not evaluated yet. That is not "resolved"."""
    rule = _Rule("cpu", [APP_ID])
    _install(monkeypatch, _FakeClient([rule], {"cpu": []}))
    assert control._alerts_for_app(APP_ID)["rules"][0]["state"] == "unknown"


def test_a_state_azure_invents_later_is_carried_through_not_coerced(monkeypatch):
    """An unrecognised state must not fall through to resolved. Carried as-is, it renders as
    itself and someone notices; coerced, it becomes a silent green."""
    rule = _Rule("cpu", [APP_ID])
    _install(monkeypatch, _FakeClient([rule], {"cpu": [_StatusRow("Suppressed")]}))
    assert control._alerts_for_app(APP_ID)["rules"][0]["state"] == "suppressed"
    assert control._alerts_for_app(APP_ID)["firing"] == []


def test_a_disabled_rule_is_not_asked_for_its_status(monkeypatch):
    """Azure keeps returning the last status a disabled rule had. A rule switched off while fired
    would otherwise report "fired" forever — an alert nobody can clear, on a condition nobody is
    evaluating."""
    rule = _Rule("cpu", [APP_ID], enabled=False)
    client = _install(monkeypatch, _FakeClient([rule], {"cpu": [_StatusRow("Fired")]}))
    block = control._alerts_for_app(APP_ID)
    assert client.status_calls == []
    assert block["firing"] == []
    assert block["rules"][0]["state"] == "unknown" and block["rules"][0]["enabled"] is False
    # It still COUNTS as a rule that exists, and is excluded from the enabled tally — "one rule,
    # none of them enabled" is a different finding from "no rules at all".
    assert block["rules_total"] == 1 and block["rules_enabled"] == 0


# ── Presentation contracts the UI depends on ────────────────────────────────────────────────────

def test_severity_never_leaves_this_module_as_a_bare_number(monkeypatch):
    """Azure severity is 0-4 and 0 is the WORST, which reads backwards to most people. The word
    travels with the number so a panel cannot render it as a priority where higher means worse."""
    rules = [_Rule(f"r{sev}", [APP_ID], severity=sev) for sev in range(5)]
    _install(monkeypatch, _FakeClient(rules, {f"r{s}": [_StatusRow("Fired")] for s in range(5)}))
    labels = [r["severity_label"] for r in control._alerts_for_app(APP_ID)["rules"]]
    assert labels == ["Critical", "Error", "Warning", "Informational", "Verbose"]


def test_firing_is_ordered_worst_first_and_an_unknown_severity_does_not_lead(monkeypatch):
    rules = [_Rule("warn", [APP_ID], severity=2), _Rule("none", [APP_ID], severity=None),
             _Rule("crit", [APP_ID], severity=0)]
    _install(monkeypatch, _FakeClient(
        rules, {n: [_StatusRow("Fired")] for n in ("warn", "none", "crit")}))
    assert [r["name"] for r in control._alerts_for_app(APP_ID)["firing"]] == ["crit", "warn", "none"]


def test_the_condition_is_read_from_the_rule_never_invented(monkeypatch):
    rule = _Rule("cpu", [APP_ID], criteria=_Criteria(
        [_Criterion("CpuPercentage", "GreaterThan", 85, "Average")]))
    _install(monkeypatch, _FakeClient([rule], {"cpu": [_StatusRow("Fired")]}))
    assert control._alerts_for_app(APP_ID)["rules"][0]["condition"] == \
        "Average CpuPercentage GreaterThan 85"


def test_an_unrecognised_criteria_shape_yields_no_condition_rather_than_a_guess(monkeypatch):
    """Metric alerts have several criteria shapes (static, dynamic, webtest). Describing a
    threshold this code did not actually read would put a number on screen that nobody can
    confirm against the rule."""
    class _Weird:
        all_of = [object()]
    rule = _Rule("cpu", [APP_ID], criteria=_Weird())
    _install(monkeypatch, _FakeClient([rule], {"cpu": [_StatusRow("Fired")]}))
    assert control._alerts_for_app(APP_ID)["rules"][0]["condition"] is None


# ── The block is present in every capacity shape ────────────────────────────────────────────────

def test_every_capacity_shape_carries_the_alerts_key(monkeypatch):
    """A caller must never have to test for the key before reading the values — and an absent key
    cannot express "we did not ask", which is a third state distinct from both firing and quiet."""
    for configured in (False, True):
        block = control._empty_capacity(configured)
        assert "alerts" in block, configured
        assert block["alerts"]["queried"] is False
        assert block["alerts"]["rules_total"] is None
        assert block["alerts"]["firing"] == []
