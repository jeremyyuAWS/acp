"""Tier 6: cost and capacity, and the two things it refuses to do.

THE OWNER'S RULE, stated as a hard constraint and not an inference: Azure billing data is not
real-time. Cost Management refreshes roughly every four hours and Microsoft advises against
querying it more than daily. So nothing here is ever labelled a live cost. A figure is either
"estimated from configured capacity" — derived, never measured — or "billing data, last updated
<t>", and those labels never swap.

NO PRICE IS HARDCODED. Container Apps rates vary by region, by plan and over time; a rate baked
into the module would be wrong somewhere on the day it was written and wrong everywhere within a
year, while still rendering as a confident currency figure. So the quantities are exact and money
appears only when an operator supplies their own rate. Every test below is a way one of those two
rules could be broken.
"""
from __future__ import annotations

import sys
from pathlib import Path

ACP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ACP / "api"))

import pytest

import routes.control as control


def block(**over):
    row = {"worker_app_name": "acp-assess", "cpu_cores_per_replica": 2.0,
           "memory_per_replica": "4Gi", "current_replicas": 3, "min_replicas": 1,
           "max_replicas": 10}
    row.update(over)
    return row


@pytest.fixture(autouse=True)
def _no_rates(monkeypatch):
    for name in (control._COST_VCPU_HOUR_ENV, control._COST_GIB_HOUR_ENV,
                 control._COST_CURRENCY_ENV):
        monkeypatch.delenv(name, raising=False)
    yield


def _rates(monkeypatch, vcpu="0.04", gib="0.004", currency="USD"):
    if vcpu is not None:
        monkeypatch.setenv(control._COST_VCPU_HOUR_ENV, vcpu)
    if gib is not None:
        monkeypatch.setenv(control._COST_GIB_HOUR_ENV, gib)
    if currency is not None:
        monkeypatch.setenv(control._COST_CURRENCY_ENV, currency)


# ── No invented price ───────────────────────────────────────────────────────────────────────────

def test_without_a_rate_there_is_no_money_only_resource_hours():
    """The rule the module is built around. A currency figure with no rate behind it is the most
    confidently wrong thing this panel could show."""
    cost = control._cost_block({"acp-assess": block()})
    assert cost["rate_configured"] is False
    assert cost["estimated_hourly"] is None
    assert cost["estimated_daily"] is None
    # The quantities ARE known and are still useful: 3 replicas x 2 cores, x 4 GiB.
    assert cost["total_vcpu_hours"] == 6.0
    assert cost["total_gib_hours"] == 12.0


def test_the_missing_rate_says_how_to_supply_one_and_why_none_is_assumed():
    note = control._cost_block({"acp-assess": block()})["rate_note"]
    assert control._COST_VCPU_HOUR_ENV in note
    assert control._COST_GIB_HOUR_ENV in note
    assert "wrong for some region" in note


def test_a_rate_for_only_one_resource_buys_no_money_at_all(monkeypatch):
    """Memory is a large share of a Container Apps bill. An hourly figure built from vCPU alone
    would silently omit it and still read as the cost of running the service."""
    _rates(monkeypatch, vcpu="0.04", gib=None)
    cost = control._cost_block({"acp-assess": block()})
    assert cost["rate_configured"] is False
    assert cost["estimated_hourly"] is None


def test_a_rate_produces_money_from_both_halves(monkeypatch):
    _rates(monkeypatch)
    cost = control._cost_block({"acp-assess": block()})
    # 6 vCPU-hours * 0.04 + 12 GiB-hours * 0.004 = 0.24 + 0.048
    assert cost["estimated_hourly"] == pytest.approx(0.288)
    assert cost["estimated_daily"] == pytest.approx(6.912)
    assert cost["currency"] == "USD"


def test_a_nonsense_rate_is_ignored_rather_than_used(monkeypatch):
    """A zero or negative rate is a misconfiguration, not a free deployment."""
    for bad in ("0", "-1", "free", ""):
        monkeypatch.setenv(control._COST_VCPU_HOUR_ENV, bad)
        monkeypatch.setenv(control._COST_GIB_HOUR_ENV, "0.004")
        assert control._cost_block({"acp-assess": block()})["estimated_hourly"] is None


def test_the_basis_label_never_reads_as_a_measurement():
    cost = control._cost_block({"acp-assess": block()})
    assert cost["basis"] == "Estimated from configured capacity"
    assert "live" not in str(cost["basis"]).lower()


# ── Memory parsing, where a wrong answer is absurd rather than subtle ────────────────────────────

def test_memory_units_are_parsed_not_assumed():
    """Reading "512Mi" as 512 would overstate a replica's memory a thousandfold, and the cost
    estimate built on it would be confidently absurd."""
    assert control._memory_gib("4Gi") == 4.0
    assert control._memory_gib("512Mi") == pytest.approx(0.5)
    assert control._memory_gib("2G") == 2.0
    assert control._memory_gib("1.5Gi") == pytest.approx(1.5)
    assert control._memory_gib("3") == 3.0


def test_unparseable_memory_is_none_rather_than_a_number():
    for value in (None, "", "lots", "Gi", object()):
        assert control._memory_gib(value) is None


def test_memory_that_cannot_be_parsed_costs_nothing_rather_than_guessing(monkeypatch):
    _rates(monkeypatch)
    cost = control._cost_block({"acp-assess": block(memory_per_replica="unknown")})
    assert cost["total_gib_hours"] is None
    assert cost["estimated_hourly"] is None


# ── Idle capacity: the figure that needs no billing access ──────────────────────────────────────

def test_the_floor_is_reported_separately_from_what_is_running():
    """What the deployment pays for while nothing is happening. Derivable from configuration with
    no billing access at all, and the one cost figure an operator can act on tonight."""
    cost = control._cost_for_app(block(current_replicas=6, min_replicas=2))
    assert cost["running"]["vcpu_hours"] == 12.0
    assert cost["floor"]["vcpu_hours"] == 4.0
    assert cost["idle_vcpu_hours"] == 4.0


def test_a_missing_replica_count_does_not_become_zero():
    """Zero replicas and an unreported replica count are different, and one of them is free."""
    cost = control._cost_for_app(block(current_replicas=None))
    assert cost["running"]["vcpu_hours"] is None
    assert cost["estimated_hourly"] is None


# ── Totals ──────────────────────────────────────────────────────────────────────────────────────

def test_a_total_is_withheld_when_one_app_could_not_be_measured():
    """A sum over the apps that answered would understate the bill while looking complete."""
    cost = control._cost_block({
        "a": block(worker_app_name="a", current_replicas=1),
        "b": block(worker_app_name="b", current_replicas=None)})
    assert cost["total_vcpu_hours"] is None
    assert len(cost["apps"]) == 2


def test_totals_add_up_across_apps():
    cost = control._cost_block({
        "a": block(worker_app_name="a", current_replicas=1, cpu_cores_per_replica=1.0),
        "b": block(worker_app_name="b", current_replicas=2, cpu_cores_per_replica=0.5)})
    assert cost["total_vcpu_hours"] == 2.0


# ── The actuals it cannot supply ────────────────────────────────────────────────────────────────

def test_actual_spend_is_named_unavailable_with_the_four_hour_caveat():
    """The caveat travels in the payload rather than living in the UI, so a frontend change cannot
    drop it and nobody expects the figure to be current once access exists."""
    actuals = control._cost_block({})["actuals"]
    assert actuals["available"] is False
    assert actuals["month_to_date"] is None
    assert actuals["forecast"] is None
    assert actuals["budget_percent"] is None
    assert "Cost Management" in actuals["reason"]
    assert "four hours" in actuals["billing_note"]
    assert "never live" in actuals["billing_note"].lower()


def test_the_acp_side_spend_nobody_meters_is_named_not_omitted():
    items = {row["item"] for row in control._cost_block({})["not_instrumented"]}
    assert any("AI cost" in i for i in items)
    assert any("Storage" in i for i in items)
    for row in control._cost_block({})["not_instrumented"]:
        assert len(row["reason"]) > 40, row


def test_nothing_in_the_payload_calls_any_of_this_live():
    """The one word the owner ruled out. Asserted over the whole block rather than field by field,
    so a label added later cannot slip it back in."""
    import json
    text = json.dumps(control._cost_block({"acp-assess": block()})).lower()
    assert "live cost" not in text
    assert "cost now" not in text


def test_every_capacity_shape_carries_the_cost_block(monkeypatch):
    monkeypatch.setattr(control, "_AZ_CONFIGURED", False)
    payload = control.get_capacity()
    assert payload["cost"]["basis"] == "Estimated from configured capacity"
    assert payload["cost"]["actuals"]["available"] is False
    assert payload["cost"]["rate_note"]
