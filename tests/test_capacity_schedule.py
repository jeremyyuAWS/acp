"""What a capacity schedule means — the half of the Scheduling feature that needs no Azure.

AC 4 of docs/prd-capacity-scheduling.md ("Pacific-time schedules remain correct across daylight
saving") is a pure function of a schedule and an instant, so it is tested here rather than left
to a staging exercise in Phase 3. Review finding R8 moved it forward for that reason.

The DST cases below are the ones a schedule can actually be caught by, and each has a DECIDED
answer rather than whatever zoneinfo happens to return:

  * the same wall-clock start maps to a different UTC instant either side of a transition, with
    nobody editing the schedule — that is the whole point of storing an IANA zone and a local
    time rather than a UTC offset;
  * a nonexistent local time (the hour that does not happen in March) still produces a
    transition, instead of silently dropping a business-hours window once a year;
  * an ambiguous local time (the hour that repeats in November) starts on the first occurrence
    and ends on the last, so both errors land on MORE warm capacity, never less.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import capacity_schedule as cs  # noqa: E402
from capacity_budget import Tier  # noqa: E402

PACIFIC_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri")


def sched(**overrides) -> cs.Schedule:
    """The PRD's proposal, enabled, with whatever this test needs changed."""
    return replace(cs.PROPOSED, enabled=True, **overrides)


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


# ── AC 4: the same schedule, both sides of a DST transition ──────────────────────────────────

@pytest.mark.parametrize("now, expected_start_utc, label", [
    # Mid-January: Pacific is PST, UTC-8, so 06:00 local is 14:00 UTC.
    (utc(2026, 1, 12, 0, 0), utc(2026, 1, 12, 14, 0), "PST"),
    # Mid-July: Pacific is PDT, UTC-7, so the SAME 06:00 local is 13:00 UTC.
    (utc(2026, 7, 13, 0, 0), utc(2026, 7, 13, 13, 0), "PDT"),
])
def test_the_same_local_start_is_a_different_instant_either_side_of_dst(now, expected_start_utc, label):
    """One schedule, unedited, correct in both halves of the year.

    This is the assertion that would fail if the schedule stored a UTC offset instead of an IANA
    zone — the failure mode is an hour of missing warm capacity every morning for half the year,
    which looks exactly like a slow cold start rather than like a bug.
    """
    instant, mode = cs.next_transition(sched(), now)
    assert mode == "business_hours"
    assert instant == expected_start_utc, label


def test_the_local_wall_clock_reading_of_the_start_never_moves():
    """The other half of the same fact, stated the way an administrator would check it."""
    from zoneinfo import ZoneInfo
    pacific = ZoneInfo("America/Los_Angeles")
    for now in (utc(2026, 1, 12, 0, 0), utc(2026, 7, 13, 0, 0)):
        instant, _ = cs.next_transition(sched(), now)
        assert instant.astimezone(pacific).strftime("%H:%M") == "06:00"


def test_effective_mode_reads_the_local_clock_not_a_fixed_offset():
    # 14:00 UTC on a January Monday is 06:00 Pacific — the first minute of business hours.
    assert cs.effective_mode(sched(), utc(2026, 1, 12, 14, 0)) == "business_hours"
    assert cs.effective_mode(sched(), utc(2026, 1, 12, 13, 59)) == "off_hours"
    # The same wall-clock minute in July is an hour earlier in UTC.
    assert cs.effective_mode(sched(), utc(2026, 7, 13, 13, 0)) == "business_hours"
    assert cs.effective_mode(sched(), utc(2026, 7, 13, 12, 59)) == "off_hours"


# ── the two DST edge cases, decided ──────────────────────────────────────────────────────────

def test_a_start_in_the_hour_that_does_not_exist_still_fires():
    """2026-03-08: Pacific clocks jump 02:00 to 03:00, so 02:30 never happens that morning.

    Skipping it would drop a whole business-hours window once a year, on a Sunday schedule that
    would look correct every other week of the year. The transition fires as the clock crosses
    the missing time — 03:30 local, which is 10:30 UTC.
    """
    schedule = sched(days=("sun",), start="02:30", end="20:00")
    instant, mode = cs.next_transition(schedule, utc(2026, 3, 8, 0, 0))
    assert mode == "business_hours"
    assert instant == utc(2026, 3, 8, 10, 30)


def test_an_ambiguous_start_takes_the_first_occurrence_and_an_ambiguous_end_the_last():
    """2026-11-01: Pacific clocks repeat 01:00 to 02:00, so 01:30 happens twice.

    Both choices give MORE warm capacity: start at the earlier 01:30 (08:30 UTC, still PDT), end
    at the later one (09:30 UTC, now PST). Ending on the first occurrence would shed capacity an
    hour early while people were still working — the exact failure this feature exists to stop.
    """
    start_instant, start_mode = cs.next_transition(
        sched(days=("sun",), start="01:30", end="20:00"), utc(2026, 11, 1, 0, 0))
    assert start_mode == "business_hours"
    assert start_instant == utc(2026, 11, 1, 8, 30)

    end_instant, end_mode = cs.next_transition(
        sched(days=("sun",), start="00:30", end="01:30"), utc(2026, 11, 1, 8, 0))
    assert end_mode == "off_hours"
    assert end_instant == utc(2026, 11, 1, 9, 30)
    assert end_instant - start_instant == (utc(2026, 11, 1, 9, 30) - utc(2026, 11, 1, 8, 30))


def test_an_ordinary_day_is_unaffected_by_the_fold_handling():
    """Bite check: if the DST branches applied on every day, this would move too."""
    instant, _ = cs.next_transition(sched(days=("sun",), start="01:30", end="20:00"),
                                   utc(2026, 6, 7, 0, 0))
    assert instant == utc(2026, 6, 7, 8, 30)


# ── the rest of the time logic ───────────────────────────────────────────────────────────────

def test_a_day_the_schedule_does_not_name_is_off_hours_all_day():
    # 2026-09-06 is a Sunday; the proposal runs Monday to Friday.
    assert cs.effective_mode(sched(), utc(2026, 9, 6, 20, 0)) == "off_hours"


def test_a_disabled_schedule_is_off_hours_and_has_no_next_transition():
    disabled = replace(cs.PROPOSED, enabled=False)
    assert cs.effective_mode(disabled, utc(2026, 1, 12, 14, 0)) == "off_hours"
    assert cs.next_transition(disabled, utc(2026, 1, 12, 14, 0)) is None


def test_a_once_weekly_schedule_still_finds_next_week_from_late_on_its_own_day():
    """Why the search runs past a week: a seven-day walk starting after the last transition on
    the only active day finds nothing and returns None, which the tab renders as 'no scheduled
    transition' on the one day it is most obviously scheduled."""
    weekly = sched(days=("mon",))
    # 05:00 UTC on the 13th is 21:00 PST on Monday the 12th — after that Monday's 20:00 end, so
    # the only remaining transition is the following Monday, seven local days on. A range(0, 7)
    # walk from the 12th covers the 12th to the 18th and misses it by one day.
    instant, mode = cs.next_transition(weekly, utc(2026, 1, 13, 5, 0))
    assert mode == "business_hours"
    assert instant == utc(2026, 1, 19, 14, 0)


def test_the_end_of_business_hours_is_the_next_transition_from_the_middle_of_the_day():
    instant, mode = cs.next_transition(sched(), utc(2026, 1, 12, 18, 0))  # 10:00 Pacific
    assert mode == "off_hours"
    assert instant == utc(2026, 1, 13, 4, 0)  # 20:00 PST


# ── shape validation ─────────────────────────────────────────────────────────────────────────

def baseline() -> list[Tier]:
    """A deployment shape to price schedules against. Deliberately small and explicit — these
    tests are about the SCHEDULE, and parsing the production script here would couple them to a
    baseline that moves for unrelated reasons."""
    return [
        Tier("acp-app", 1, 3, 0, None, 1.0),
        Tier("acp-discovery", 1, 2, 2, 2, 1.0),
        Tier("acp-assess", 1, 5, 2, 2, 2.0),
        Tier("acp-remediate", 1, 10, 2, 2, 2.0),
    ]


def codes(result) -> set[str]:
    return {f["code"] for f in result["findings"]}


def validate(schedule, **kwargs):
    return cs.validate(schedule, baseline(), server_max_connections=150, reserve=15, **kwargs)


def test_an_unknown_timezone_blocks_and_reports_no_capacity_figure():
    """A schedule whose zone cannot be resolved has no next transition, so a connection count
    derived from half of it would be a number with nothing behind it."""
    result = validate(sched(timezone="Mars/Olympus_Mons"))
    assert result["blocked"] and not result["schedule_valid"]
    assert "unknown_timezone" in codes(result)
    assert result["capacity"] is None


def test_an_empty_window_blocks():
    assert "empty_window" in codes(validate(sched(start="06:00", end="06:00")))


def test_an_overnight_window_is_refused_rather_than_silently_meaning_nothing():
    """`start <= t < end` is false all day when start > end, so an accepted 20:00-06:00 schedule
    would pin ACP to off-hours capacity forever while the tab read 'enabled'."""
    result = validate(sched(start="20:00", end="06:00"))
    assert "overnight_window_unsupported" in codes(result)
    assert result["blocked"]


def test_a_floor_above_its_own_ceiling_blocks():
    result = validate(sched(business_hours={**cs.PROPOSED.business_hours, "assess": 99}))
    assert "min_exceeds_max" in codes(result)


def test_a_worker_role_at_zero_off_hours_blocks():
    """AC 7, and PRD §7's 'a scheduled role could reach zero with no verified mechanism to wake
    it'. ACP has no such mechanism: the queue scaler reads the jobs table, and nothing polls it
    on behalf of a tier that is not running."""
    result = validate(sched(off_hours={**cs.PROPOSED.off_hours, "remediate": 0}))
    assert "role_could_reach_zero" in codes(result)
    assert result["blocked"]
    # gpu at zero is explicitly fine — the PRD proposes it, and a cold start is the stated cost.
    assert "role_could_reach_zero" not in codes(validate(sched()))


def test_enabled_with_no_days_blocks():
    assert "no_active_days" in codes(validate(sched(days=())))


# ── capacity validation uses the worst mode, which is R2 ─────────────────────────────────────

def test_validation_prices_the_worst_mode_not_the_current_one():
    """THE FINDING, as a test. The overlap term is driven by the floors, so a schedule that is
    affordable overnight can be over budget during business hours — and `validate` takes no
    `now`, precisely so it cannot answer for whichever mode happens to be in force."""
    business_heavy = sched(business_hours={"web": 3, "discovery": 2, "assess": 5, "remediate": 5},
                           off_hours={"web": 1, "discovery": 1, "assess": 1, "remediate": 1},
                           maximums={"web": 3, "discovery": 4, "assess": 10, "remediate": 10})
    off_only = replace(business_heavy, business_hours=business_heavy.off_hours)

    priced = validate(business_heavy)["capacity"]["deploy_connections"]
    cheaper = validate(off_only)["capacity"]["deploy_connections"]
    assert priced > cheaper, (
        "raising only the business-hours floors did not raise the priced worst case — validation "
        "is reading one mode instead of the worst of them")


def test_a_schedule_over_the_connection_budget_is_blocked():
    greedy = sched(maximums={"web": 3, "discovery": 40, "assess": 40, "remediate": 40})
    result = validate(greedy)
    assert result["blocked"]
    assert "over_connection_budget" in codes(result)


def test_a_service_the_schedule_does_not_name_keeps_the_baselines_own_range():
    """A partial schedule must be expressible without restating the whole fleet."""
    partial = sched(business_hours={"assess": 2}, off_hours={"assess": 1},
                    maximums={"assess": 5})
    tiers = {t.name: t for t in cs.tiers_for(partial, baseline())}
    assert (tiers["acp-remediate"].min_replicas, tiers["acp-remediate"].max_replicas) == (1, 10)
    assert (tiers["acp-assess"].min_replicas, tiers["acp-assess"].max_replicas) == (2, 5)


# ── desired versus observed ──────────────────────────────────────────────────────────────────

def test_drift_reports_only_what_azure_actually_answered():
    observed = {
        "acp-assess": {"min_replicas": 5, "max_replicas": 5},
        "acp-remediate": {"min_replicas": None, "max_replicas": None},
    }
    found = cs.drift(sched(), "business_hours", observed)
    assert {(d["app"], d["field"]) for d in found} == {("acp-assess", "max_replicas")}
    # acp-assess's floor of 5 matches the proposal's business-hours 5, so only the ceiling
    # differs; acp-remediate answered nothing and must not be reported as drift.


def test_an_unreadable_app_is_not_drift():
    """Otherwise every slow Azure read fills the tab with differences, and a drift indicator
    that is always on is one nobody reads."""
    assert cs.drift(sched(), "business_hours", {"acp-assess": {}}) == []
    assert cs.drift(sched(), "business_hours", {}) == []


def test_drift_is_measured_against_the_mode_asked_for():
    observed = {"acp-assess": {"min_replicas": 1, "max_replicas": 10}}
    assert cs.drift(sched(), "off_hours", observed) == []
    business = cs.drift(sched(), "business_hours", observed)
    assert [d["field"] for d in business] == ["min_replicas"]
    assert business[0]["desired"] == 5 and business[0]["observed"] == 1


# ── scaler health, including the state AC 10 was missing ─────────────────────────────────────

def test_a_rule_on_a_pinned_tier_is_inert_not_healthy():
    """AC 10 says a broken scaler must not read as healthy. A rule on a tier whose floor equals
    its ceiling is neither broken nor healthy — it is inert, and reporting it as healthy is how
    acp-assess came to look autoscaled when it has never had a rule that could fire."""
    health = cs.scaler_health({
        "acp-assess": {"min_replicas": 5, "max_replicas": 5,
                       "scale": {"rules": [{"name": "assess-queue"}]}},
    })
    assert health["assess"]["state"] == "pinned"
    assert "cannot add a replica" in health["assess"]["detail"]


def test_a_tier_with_room_and_no_rule_is_missing_not_healthy():
    health = cs.scaler_health({"acp-remediate": {"min_replicas": 5, "max_replicas": 10,
                                                 "scale": {"rules": []}}})
    assert health["remediate"]["state"] == "missing"
    assert "nothing asks it to" in health["remediate"]["detail"]


def test_a_tier_with_room_and_a_rule_is_healthy():
    health = cs.scaler_health({"acp-remediate": {
        "min_replicas": 5, "max_replicas": 10,
        "scale": {"rules": [{"name": "remediation-queue"}]}}})
    assert health["remediate"]["state"] == "healthy"
    assert health["remediate"]["rules"] == ["remediation-queue"]


def test_an_unreadable_or_unconfigured_scaler_is_never_reported_as_healthy():
    """The honesty rule this codebase applies everywhere: a reading that failed is its own state,
    never a fabricated good one."""
    assert cs.scaler_health({}, configured=False)["assess"]["state"] == "not_configured"
    assert cs.scaler_health({})["assess"]["state"] == "unreadable"
    assert cs.scaler_health({"acp-assess": {"app_unavailable": True}})["assess"]["state"] == "unreadable"
    assert cs.scaler_health({"acp-assess": {"min_replicas": None, "max_replicas": None}}
                            )["assess"]["state"] == "unreadable"


def test_scaler_health_covers_the_queue_services_and_only_those():
    """web scales on HTTP and gpu on demand; neither reads the jobs table, so 'no queue rule' is
    a finding for three apps and a fact about the other two."""
    assert set(cs.scaler_health({})) == set(cs.QUEUE_SERVICES) == {"discovery", "assess", "remediate"}


# ── the deployment facts a schedule does not set ─────────────────────────────────────────────

def test_the_deployed_shape_matches_the_reviewed_capacity_baseline():
    """DEPLOYED_SHAPE carries what one replica of each app costs — CPU and the ACP_DB_MAX_CONN
    pin. Those are properties of the deployment, not of any schedule, and the authority on them
    is deploy/public/rightsize-production.sh.

    PARSED, not restated. The script moves — acp-discovery's range changed on 2026-09-06 — and a
    copy nobody checks is how the last three capacity models in this repository went stale.
    """
    import re
    script = (ROOT / "deploy/public/rightsize-production.sh").read_text()
    parsed = {
        m.group(1): {"cpu_cores": float(m.group(2)),
                     "db_pool_override": int(m.group(3)) if m.group(3) else None}
        for m in re.finditer(
            r"^update_app\s+(\S+)\s+([\d.]+)\s+\S+\s+\d+\s+\d+(?:\s+(\d+))?",
            script, re.M)
    }
    for app, shape in cs.DEPLOYED_SHAPE.items():
        assert app in parsed, f"{app} is no longer sized by rightsize-production.sh"
        assert shape["cpu_cores"] == parsed[app]["cpu_cores"], app
        assert shape["db_pool_override"] == parsed[app]["db_pool_override"], app


def test_the_gpu_service_is_costed_in_vcpu_and_not_in_connections():
    """acp-ollama holds no ACP job and opens no Postgres connection. Including it in the
    connection budget would spend connections nothing uses; excluding it from vCPU would
    understate the quota check by four cores per replica."""
    assert "acp-ollama" not in cs.DEPLOYED_SHAPE
    assert "gpu" in cs.SERVICE_APPS
    tiers = {t.name for t in cs.baseline_tiers(sched())}
    assert "acp-ollama" not in tiers


def test_the_prd_proposal_is_refused_by_its_own_validator():
    """Finding R2, end to end through the code the Scheduling tab will call.

    A failing assertion here means the proposal became affordable, which is a good thing that
    must move docs/prd-capacity-scheduling.md with it rather than pass quietly.
    """
    proposal = replace(cs.PROPOSED, enabled=True)
    result = cs.validate(proposal, cs.baseline_tiers(proposal),
                         server_max_connections=150, reserve=15)
    assert result["blocked"], (
        "the PRD's §5.3 table now fits its server — update the PRD and this test together")
    assert "over_connection_budget" in codes(result)
    assert result["capacity"]["connection_headroom"] < 0


def test_the_vcpu_quota_has_no_default_and_an_unparseable_one_is_not_guessed(monkeypatch):
    monkeypatch.delenv("ACP_ACA_VCPU_QUOTA", raising=False)
    assert cs.vcpu_quota() is None
    monkeypatch.setenv("ACP_ACA_VCPU_QUOTA", "not-a-number")
    assert cs.vcpu_quota() is None
    monkeypatch.setenv("ACP_ACA_VCPU_QUOTA", "120")
    assert cs.vcpu_quota() == 120.0


# ── Phase 4: holiday exceptions ──────────────────────────────────────────────────────────────
#
# §5.2's "optional holiday exceptions". A holiday is a LOCAL CALENDAR DAY in the schedule's own
# timezone — not a UTC window — so a US holiday does not begin at 16:00 the day before for a
# Pacific schedule. That distinction is the whole reason these are dates and not instants.

def test_a_holiday_is_off_hours_all_day():
    # 2026-01-19 is a Monday, and the proposal runs Monday to Friday.
    holiday = sched(holidays=("2026-01-19",))
    for hour in (14, 18, 23):        # 06:00, 10:00 and 15:00 Pacific — all inside the window
        assert cs.effective_mode(holiday, utc(2026, 1, 19, hour, 0)) == "off_hours", hour
    # The Monday before is unaffected, which is what says the exception is scoped to the date.
    assert cs.effective_mode(holiday, utc(2026, 1, 12, 18, 0)) == "business_hours"


def test_a_holiday_carries_no_transitions():
    """Both halves matter: business hours must not begin on the day, and must not end on it
    either — an 'end' transition on a day that never started would put a spurious entry in the
    tab's 'next transition' and in any log built from it."""
    holiday = sched(days=("mon",), holidays=("2026-01-19",))
    instant, mode = cs.next_transition(holiday, utc(2026, 1, 18, 0, 0))
    assert (instant, mode) == (utc(2026, 1, 26, 14, 0), "business_hours"), "the holiday was not skipped"


def test_a_holiday_is_the_local_calendar_day_not_a_utc_one():
    """16:00 UTC on the 19th is 08:00 Pacific ON the holiday — off hours. 06:00 UTC on the 20th
    is 22:00 Pacific on the 19th, still the holiday but outside business hours anyway; the
    discriminating case is the 20th's own morning, which must be a normal working day."""
    holiday = sched(holidays=("2026-01-19",))
    assert cs.effective_mode(holiday, utc(2026, 1, 19, 16, 0)) == "off_hours"
    assert cs.effective_mode(holiday, utc(2026, 1, 20, 16, 0)) == "business_hours"


def test_a_holiday_on_a_day_the_schedule_never_works_changes_nothing():
    weekend = sched(holidays=("2026-01-17",))            # a Saturday
    assert cs.effective_mode(weekend, utc(2026, 1, 17, 18, 0)) == "off_hours"
    assert cs.effective_mode(weekend, utc(2026, 1, 19, 18, 0)) == "business_hours"


def test_an_unparseable_holiday_blocks_the_save():
    """BLOCKING, not a warning. A holiday ACP cannot read is one it will not observe, and the
    administrator cannot tell from the tab: their date is listed and the capacity is warm anyway.
    Refusing is the only outcome that cannot mislead."""
    result = validate(sched(holidays=("2026-12-25", "christmas")))
    assert "unparseable_holiday" in codes(result)
    assert result["blocked"]
    assert "christmas" in " ".join(f["detail"] for f in result["findings"])


def test_a_duplicate_holiday_warns_without_blocking():
    result = validate(sched(holidays=("2026-12-25", "2026-12-25")))
    duplicate = [f for f in result["findings"] if f["code"] == "duplicate_holiday"]
    assert duplicate and not duplicate[0]["blocking"]


def test_a_schedule_with_valid_holidays_still_validates():
    assert "unparseable_holiday" not in codes(validate(sched(holidays=("2026-12-25", "2026-01-01"))))


# ── Phase 4: why capacity is where it is (AC 14) ─────────────────────────────────────────────

def test_a_rollout_outranks_every_other_explanation():
    """During a rollout the replica count says nothing about demand, and reading it as queue
    pressure is how a deploy gets mistaken for a spike."""
    answer = cs.attribute_capacity({"current_replicas": 9, "draining_replicas": 2},
                                   floor=5, authority="business_hours", queue_depth=40)
    assert answer["reason"] == "deployment"


def test_an_override_outranks_the_queue_but_not_a_rollout():
    assert cs.attribute_capacity({"current_replicas": 9}, floor=5,
                                 authority="manual_override")["reason"] == "manual_override"
    assert cs.attribute_capacity({"current_replicas": 9, "draining_replicas": 1}, floor=5,
                                 authority="manual_override")["reason"] == "deployment"


def test_above_the_floor_is_queue_driven_and_says_by_how_much():
    answer = cs.attribute_capacity({"current_replicas": 8}, floor=5,
                                   authority="business_hours", queue_depth=31)
    assert answer["reason"] == "queue"
    assert "3 replica(s) above" in answer["detail"]
    assert "31" in answer["detail"]


def test_exactly_the_floor_is_the_schedule():
    answer = cs.attribute_capacity({"current_replicas": 5}, floor=5, authority="business_hours")
    assert answer["reason"] == "scheduled"


def test_below_the_floor_is_named_rather_than_folded_into_scheduled():
    """The two look identical in a bare replica count and only one of them is a problem. A
    tier running four when the schedule asks for five is not 'scheduled' — it is a restart, a
    failed revision, or capacity Azure has not granted."""
    answer = cs.attribute_capacity({"current_replicas": 4}, floor=5, authority="business_hours")
    assert answer["reason"] == "below_floor"
    assert "short of" in answer["detail"]


def test_an_unreadable_app_is_never_attributed_to_a_cause():
    for block in ({}, {"app_unavailable": True}, {"current_replicas": None}):
        assert cs.attribute_capacity(block, floor=5, authority="business_hours")["reason"] == "unknown"


def test_a_service_with_no_known_floor_is_unknown_rather_than_guessed():
    answer = cs.attribute_capacity({"current_replicas": 3}, floor=None, authority="business_hours")
    assert answer["reason"] == "unknown"


def test_the_fleet_view_answers_per_service():
    answer = cs.attribute_fleet(
        {"acp-assess": {"current_replicas": 8}, "acp-remediate": {"current_replicas": 5}},
        floors={"assess": 5, "remediate": 5}, authority="business_hours",
        queue_depths={"assess": 12})
    assert answer["assess"]["reason"] == "queue"
    assert answer["remediate"]["reason"] == "scheduled"
    assert answer["gpu"]["reason"] == "unknown"
    assert set(answer) == set(cs.SERVICE_APPS)


def test_a_holiday_cannot_hide_the_next_transition():
    """The case that forced the horizon past a fortnight, found by the test above it.

    A schedule naming one weekday, with a holiday on the next occurrence of that weekday, has its
    next transition FIFTEEN days out. A nine-day window returned None, and None renders as "no
    scheduled transition" — so a valid schedule with a single holiday reported itself as having
    nothing scheduled, indefinitely.
    """
    holiday = sched(days=("mon",), holidays=("2026-01-19",))
    instant, mode = cs.next_transition(holiday, utc(2026, 1, 18, 0, 0))
    assert (instant, mode) == (utc(2026, 1, 26, 14, 0), "business_hours")


def test_a_schedule_whose_every_day_is_excluded_reports_nothing_rather_than_looping():
    """The horizon has to end somewhere, and None is the honest answer here — not a transition a
    year away that the schedule does not actually have."""
    from datetime import date, timedelta as td
    mondays = tuple((date(2026, 1, 5) + td(weeks=n)).isoformat() for n in range(60))
    assert cs.next_transition(sched(days=("mon",), holidays=mondays),
                              utc(2026, 1, 1, 0, 0)) is None
