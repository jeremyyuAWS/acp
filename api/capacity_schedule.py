"""The capacity schedule: what warm capacity ACP intends, and when.

Phase 2 of docs/prd-capacity-scheduling.md — READ-ONLY BY CONSTRUCTION. This module computes
what a schedule means; nothing here writes to Azure, and there is no persistence yet. The
schedule served is the PRD's own proposal, labelled as proposed rather than applied, so the tab
can show the shape and its validation before anything is allowed to change infrastructure.

THREE THINGS LIVE HERE, and the first is the one with teeth.

**Time.** `next_transition` and `effective_mode` are pure functions of a schedule and an instant,
which is what makes AC 4 (Pacific schedules stay correct across daylight saving) testable without
Azure, a database, or a clock. Two DST edge cases are decided rather than left to whatever
`zoneinfo` happens to do:

  * A NONEXISTENT local time — 02:30 on the morning the clock jumps 02:00 to 03:00. There is no
    such instant, so the transition fires at the moment the clock passes it (fold=0 conversion
    puts it at 03:30 local). The alternative, skipping the day, would silently drop a whole
    business-hours window once a year.
  * An AMBIGUOUS local time — 01:30 on the morning the clock repeats 01:00 to 02:00. Business
    hours START on the FIRST occurrence and END on the LAST. Both choices err the same way: more
    warm capacity, never less. Ending on the first occurrence would shed capacity an hour early
    while people were still working, which is the failure this feature exists to prevent.

**Capacity.** `validate` composes the schedule's shape checks with `capacity_budget.evaluate`,
and it evaluates the WORST mode the schedule can enter rather than the mode in force at the time.
The deployment-overlap term is driven by the floors, and a schedule's whole purpose is to raise
floors during business hours — so a table validated at 2am can be over budget at 10am, which is
when somebody deploys. That is finding R2 of the PRD's review, and it is the reason this function
does not take a `now`.

**Reality.** `drift` and `scaler_health` compare what ACP intends against what Azure reports
(`GET /control/workers/capacity`, which already returns each app's `scale` block). §9 of the PRD
requires the tab to say "configuration drift" rather than claim a schedule is active, and AC 10
requires a scaler that cannot work to read as degraded. `scaler_health` distinguishes PINNED from
BROKEN for that reason: a rule on a tier whose floor equals its ceiling is neither — it is inert,
and reporting it as healthy is how acp-assess came to look autoscaled when it never has been.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import capacity_budget as budget

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# Service name -> Azure Container App. The PRD talks in services; Azure talks in apps, and the
# two vocabularies have to meet somewhere explicit. `gpu` maps to acp-ollama, which holds no ACP
# job and no Postgres connection — it appears in the vCPU budget and not the connection one.
SERVICE_APPS = {
    "web": "acp-app",
    "discovery": "acp-discovery",
    "assess": "acp-assess",
    "remediate": "acp-remediate",
    "gpu": "acp-ollama",
}

# The lanes a queue scaler is meaningful for. `web` scales on HTTP and `gpu` on demand; neither
# reads the jobs table, so "this service has no queue rule" is a finding for three apps and a
# fact about the other two.
QUEUE_SERVICES = ("discovery", "assess", "remediate")


@dataclass(frozen=True)
class Schedule:
    """One capacity schedule. Values are per SERVICE, not per Azure app."""

    enabled: bool
    timezone: str
    days: tuple[str, ...]
    start: str                       # "HH:MM", local to `timezone`
    end: str                         # "HH:MM", local to `timezone`
    business_hours: dict             # service -> warm floor
    off_hours: dict                  # service -> warm floor
    maximums: dict                   # service -> queue-driven ceiling
    version: int = 0
    applied: bool = False            # whether this shape is in force on Azure
    # §5.2's "optional holiday exceptions". ISO dates (YYYY-MM-DD) read in THIS schedule's
    # timezone: a holiday is a local calendar day, not a UTC window, so a US holiday does not
    # begin at 16:00 the day before for a Pacific schedule.
    #
    # THEY ARE NOT ENFORCEABLE BY THE PUBLISHED AZURE POLICY, and capacity_policy says so rather
    # than dropping them quietly — see holidays_are_enforceable() there. ACP honours them in
    # every place ACP decides (the mode, the next transition, validation, the tab); KEDA's cron
    # scaler has no way to express "every weekday except these dates".
    holidays: tuple[str, ...] = ()

    def floors(self, mode: str) -> dict:
        return dict(self.business_hours if mode == "business_hours" else self.off_hours)


# The PRD's §5.3 proposal, served as-is and marked `applied: False`.
#
# NOT A DEFAULT THAT ANYTHING FALLS BACK TO, and deliberately not merged with the reviewed
# baseline in deploy/public/rightsize-production.sh. tests/test_capacity_budget.py shows this
# table does not fit the production Postgres server at its own business-hours floors; serving it
# as the desired state with `applied: False` is what lets the tab show the proposal and its
# refusal side by side, which is the whole point of a read-only phase.
PROPOSED = Schedule(
    enabled=False,
    timezone="America/Los_Angeles",
    days=("mon", "tue", "wed", "thu", "fri"),
    start="06:00",
    end="20:00",
    business_hours={"web": 2, "discovery": 2, "assess": 5, "remediate": 5, "gpu": 1},
    off_hours={"web": 1, "discovery": 1, "assess": 1, "remediate": 1, "gpu": 0},
    maximums={"web": 3, "discovery": 4, "assess": 10, "remediate": 10, "gpu": 1},
    version=0,
    applied=False,
    holidays=(),
)


# The deployment facts a schedule does NOT set: what one replica of each app costs.
#
# Replica RANGES come from the schedule (its floors and its ceilings). Everything else — CPU per
# replica, worker threads, and the ACP_DB_MAX_CONN pin — is a property of the deployment, and
# inventing it here would produce a connection budget that answers for a fleet nobody runs.
#
# PINNED AGAINST deploy/public/rightsize-production.sh by tests/test_capacity_schedule.py, which
# parses the script rather than trusting this table. That script is the reviewed capacity
# baseline and it moves (acp-discovery's range changed on 2026-09-06); a copy nobody checks is
# how the last three capacity models went stale.
#
# `threads` is 0 for acp-app by design (ADR 0013: the API container runs no worker threads) and
# irrelevant for the worker apps, whose pool is pinned by the override rather than derived from
# the thread count — which is the coupling that pin exists to break.
DEPLOYED_SHAPE = {
    "acp-app":       {"cpu_cores": 1.0, "threads": 0, "db_pool_override": None},
    "acp-discovery": {"cpu_cores": 1.0, "threads": 2, "db_pool_override": 2},
    "acp-assess":    {"cpu_cores": 2.0, "threads": 2, "db_pool_override": 2},
    "acp-remediate": {"cpu_cores": 2.0, "threads": 2, "db_pool_override": 2},
}

# Postgres's own ceiling and the operational allowance held back from it. Both carried from
# docs/db-connection-budget.md — 150 is the server's measured max_connections, 15 is a STATED
# allowance for schema migrations, scripts/monitor.py, an admin psql session and Azure
# diagnostics, not a measurement. Overridable so a different server does not need a code change.
SERVER_MAX_CONNECTIONS = int(__import__("os").environ.get("ACP_PG_MAX_CONNECTIONS") or 150)
OPERATIONAL_RESERVE = int(__import__("os").environ.get("ACP_PG_RESERVED_CONNECTIONS") or 15)

# No artifact in this repository records the Container Apps environment's vCPU quota, so there is
# no default. Unset, `validate` reports the fleet's vCPU demand and states that the check was NOT
# performed — see capacity_budget.evaluate and PRD review finding R6.
_VCPU_QUOTA_ENV = "ACP_ACA_VCPU_QUOTA"


def vcpu_quota() -> float | None:
    raw = __import__("os").environ.get(_VCPU_QUOTA_ENV)
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def baseline_tiers(schedule: "Schedule") -> list[budget.Tier]:
    """The fleet as tiers, costed from DEPLOYED_SHAPE and ranged from the schedule.

    Only apps the schedule actually names are included: a service with no floor and no ceiling
    in the schedule is not part of what this schedule is proposing, and giving it an invented
    range would put connections in the budget that no decision here is asking for.
    """
    tiers = []
    for service, app_name in SERVICE_APPS.items():
        shape = DEPLOYED_SHAPE.get(app_name)
        if shape is None:
            continue          # acp-ollama holds no Postgres connection; it is not in this budget
        floor = min(schedule.business_hours.get(service, 0), schedule.off_hours.get(service, 0))
        ceiling = schedule.maximums.get(service)
        if ceiling is None:
            continue
        tiers.append(budget.Tier(app_name, floor, ceiling, shape["threads"],
                                 shape["db_pool_override"], shape["cpu_cores"]))
    return tiers


class ScheduleError(ValueError):
    """A schedule that cannot be interpreted at all — as opposed to one that is merely unsafe.

    Separate from `validate`'s findings on purpose: a bad timezone or an unparseable time means
    `next_transition` has no answer to give, while an over-budget fleet has a perfectly clear
    answer that must not be applied.
    """


def _zone(schedule: Schedule) -> ZoneInfo:
    try:
        return ZoneInfo(schedule.timezone)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ScheduleError(f"unknown timezone {schedule.timezone!r}") from e


def _hhmm(value: str, label: str) -> time:
    try:
        hour, minute = str(value).split(":")
        return time(int(hour), int(minute))
    except (ValueError, AttributeError) as e:
        raise ScheduleError(f"{label} is not HH:MM: {value!r}") from e


def _to_utc(local_naive: datetime, zone: ZoneInfo, *, prefer_last: bool) -> datetime:
    """One local wall-clock time as an instant, with both DST edge cases decided.

    `prefer_last` picks the SECOND occurrence of an ambiguous time (the hour that repeats when
    the clock falls back). Callers pass True for the end of business hours and False for the
    start, so both errors land on the side of more warm capacity.

    A nonexistent time — the hour that does not happen when the clock springs forward — has no
    `fold` that makes it exist. Both folds resolve to instants outside the gap; taking the
    earlier one means the transition fires as the clock passes the missing time rather than not
    at all that day.
    """
    first = local_naive.replace(tzinfo=zone, fold=0)
    second = local_naive.replace(tzinfo=zone, fold=1)
    if first.utcoffset() == second.utcoffset():
        return first.astimezone(timezone.utc)
    # The two folds disagree, so this wall-clock time is either ambiguous or nonexistent.
    first_utc, second_utc = first.astimezone(timezone.utc), second.astimezone(timezone.utc)
    if second_utc < first_utc:
        # Nonexistent: the "second fold" resolves EARLIER, because the offset shifted forward.
        # Neither instant has this wall-clock reading; the earlier one is the moment the clock
        # crosses it.
        return first_utc
    return second_utc if prefer_last else first_utc


def holiday_dates(schedule: Schedule) -> set:
    """The schedule's holidays as dates. An unparseable entry is REPORTED, never skipped here.

    Silently dropping a malformed holiday is the failure that matters: the administrator sees
    their date listed in the tab and gets business-hours capacity on it anyway. `_shape_findings`
    blocks the save instead, so a schedule that reaches this function has already been checked.
    """
    from datetime import date as _date
    out = set()
    for raw in schedule.holidays or ():
        try:
            out.add(_date.fromisoformat(str(raw)))
        except (TypeError, ValueError):
            continue
    return out


def _candidates(schedule: Schedule, zone: ZoneInfo, day: datetime.date):
    """The (instant, mode) transitions this local date carries, in local order."""
    if DAYS[day.weekday()] not in schedule.days:
        return []
    if day in holiday_dates(schedule):
        # A holiday is a working day the schedule names and ACP declines to warm. Returning no
        # transitions is what makes both `next_transition` skip it and the day read as off-hours
        # from the first minute to the last.
        return []
    start, end = _hhmm(schedule.start, "start"), _hhmm(schedule.end, "end")
    return [
        (_to_utc(datetime.combine(day, start), zone, prefer_last=False), "business_hours"),
        (_to_utc(datetime.combine(day, end), zone, prefer_last=True), "off_hours"),
    ]


def effective_mode(schedule: Schedule, now: datetime) -> str:
    """Which mode the schedule puts ACP in at `now`. A disabled schedule is always off-hours.

    Compared in LOCAL WALL-CLOCK TIME, which is what makes it survive DST without the schedule
    being rewritten: "business hours start at 06:00 Pacific" means 06:00 as the clock reads it,
    and the underlying instant moving by an hour twice a year is the correct behaviour, not drift.
    """
    if not schedule.enabled:
        return "off_hours"
    zone = _zone(schedule)
    start, end = _hhmm(schedule.start, "start"), _hhmm(schedule.end, "end")
    local = now.astimezone(zone)
    if DAYS[local.weekday()] not in schedule.days:
        return "off_hours"
    if local.date() in holiday_dates(schedule):
        return "off_hours"
    return "business_hours" if start <= local.time() < end else "off_hours"


def next_transition(schedule: Schedule, now: datetime) -> tuple[datetime, str] | None:
    """The next instant the mode changes, and what it changes to. None when nothing is scheduled.

    Walks forward day by day and stops at the FIRST day carrying a transition still ahead of
    `now`, so the cost is one day's arithmetic in the normal case.

    THE HORIZON IS A YEAR, not a week, and holidays are why. A nine-day window was enough for a
    schedule that names a single weekday — until a holiday lands on that weekday, at which point
    the next occurrence is fifteen days out and the search returned None. The tab renders None as
    "no scheduled transition", so a schedule with one holiday on it would have reported itself as
    having nothing scheduled, indefinitely, while remaining perfectly valid. A year absorbs any
    realistic holiday list; beyond that, None is the honest answer for a schedule whose days are
    all excluded.
    """
    if not schedule.enabled or not schedule.days:
        return None
    zone = _zone(schedule)
    today = now.astimezone(zone).date()
    for offset in range(0, 366):
        upcoming = [(instant, mode)
                    for instant, mode in _candidates(schedule, zone, today + timedelta(days=offset))
                    if instant > now]
        if upcoming:
            return min(upcoming, key=lambda pair: pair[0])
    return None


# ── validation ───────────────────────────────────────────────────────────────────────────────

def _shape_findings(schedule: Schedule) -> list[budget.Finding]:
    """What is wrong with the schedule as a SCHEDULE, before any capacity arithmetic."""
    findings: list[budget.Finding] = []
    try:
        _zone(schedule)
    except ScheduleError as e:
        findings.append(budget.Finding("unknown_timezone", True, str(e)))
    try:
        start, end = _hhmm(schedule.start, "start"), _hhmm(schedule.end, "end")
    except ScheduleError as e:
        findings.append(budget.Finding("unparseable_window", True, str(e)))
    else:
        if start == end:
            findings.append(budget.Finding(
                "empty_window", True,
                f"Business hours start and end are both {schedule.start}: the window is empty."))
        elif start > end:
            # An overnight window is a legitimate thing to want and is NOT supported here. Saying
            # so is better than accepting it and computing a window that means the opposite:
            # `start <= t < end` is false all day when start > end, so an accepted 20:00-06:00
            # schedule would put ACP in off-hours capacity permanently while reading as enabled.
            findings.append(budget.Finding(
                "overnight_window_unsupported", True,
                f"Business hours run {schedule.start} to {schedule.end}, which crosses midnight. "
                f"Overnight windows are not supported; split them or invert the off-hours "
                f"floors instead."))
    unknown = [d for d in schedule.days if d not in DAYS]
    if unknown:
        findings.append(budget.Finding(
            "unknown_days", True, f"Not day names: {', '.join(sorted(unknown))}."))
    if schedule.enabled and not schedule.days:
        findings.append(budget.Finding(
            "no_active_days", True,
            "The schedule is enabled but names no days, so business hours never begin."))
    for service, ceiling in schedule.maximums.items():
        for mode in ("business_hours", "off_hours"):
            floor = schedule.floors(mode).get(service)
            if floor is not None and floor > ceiling:
                findings.append(budget.Finding(
                    "min_exceeds_max", True,
                    f"{service}: the {mode.replace('_', '-')} floor {floor} is above its "
                    f"ceiling {ceiling}."))
    from datetime import date as _date
    bad_dates = []
    for raw in schedule.holidays or ():
        try:
            _date.fromisoformat(str(raw))
        except (TypeError, ValueError):
            bad_dates.append(str(raw))
    if bad_dates:
        # BLOCKING, not a warning. A holiday ACP cannot parse is one it will not observe, and the
        # administrator has no way to tell from the tab — their date is listed and the capacity
        # is warm anyway. Refusing the save is the only outcome that cannot mislead.
        findings.append(budget.Finding(
            "unparseable_holiday", True,
            f"Not YYYY-MM-DD dates: {', '.join(sorted(bad_dates))}. A holiday ACP cannot read is "
            f"one it will not observe."))
    if len(set(schedule.holidays or ())) != len(schedule.holidays or ()):
        findings.append(budget.Finding(
            "duplicate_holiday", False,
            "The same holiday is listed more than once; the duplicates have no effect."))

    for service in QUEUE_SERVICES:
        if schedule.off_hours.get(service, 0) < 1:
            findings.append(budget.Finding(
                "role_could_reach_zero", True,
                f"{service} would have no warm replica off-hours, and ACP has no verified "
                f"mechanism to wake a scaled-to-zero worker role."))
    return findings


def tiers_for(schedule: Schedule, baseline: list[budget.Tier]) -> list[budget.Tier]:
    """The fleet as this schedule would leave it, at the worst mode it can enter.

    `baseline` supplies each app's CPU size, thread count and pool — facts about the deployment
    that a schedule does not set and must not invent. The schedule supplies the floors and the
    ceilings. An app the schedule does not name keeps the baseline's own range, so a schedule
    covering the worker tiers alone is expressible.
    """
    by_app = {t.name: t for t in baseline}
    ceilings = {SERVICE_APPS[s]: c for s, c in schedule.maximums.items() if s in SERVICE_APPS}
    tiers = []
    for tier in baseline:
        ceiling = ceilings.get(tier.name)
        tiers.append(tier if ceiling is None else
                     budget.Tier(tier.name, tier.min_replicas, ceiling, tier.threads,
                                 tier.db_pool_override, tier.cpu_cores))
    floors_by_mode = {
        mode: {SERVICE_APPS[s]: f for s, f in schedule.floors(mode).items() if s in SERVICE_APPS}
        for mode in ("business_hours", "off_hours")
    }
    del by_app
    return budget.worst_case_tiers(tiers, floors_by_mode)


def validate(schedule: Schedule, baseline: list[budget.Tier], *,
             server_max_connections: int, reserve: int,
             vcpu_quota: float | None = None) -> dict:
    """The schedule's shape and its fleet cost, as one answer.

    Shape findings come first and are reported even when the capacity arithmetic cannot run —
    an unparseable window is a more useful thing to say than a connection count derived from
    half a schedule.
    """
    findings = _shape_findings(schedule)
    fatal = any(f.code in ("unknown_timezone", "unparseable_window") for f in findings)
    if fatal:
        return {
            "schedule_valid": False,
            "findings": [f.__dict__ for f in findings],
            "blocked": True,
            "capacity": None,
        }
    capacity = budget.evaluate(tiers_for(schedule, baseline),
                               server_max_connections=server_max_connections,
                               reserve=reserve, vcpu_quota=vcpu_quota)
    combined = [f.__dict__ for f in findings] + list(capacity["findings"])
    return {
        "schedule_valid": not any(f["blocking"] for f in combined),
        "findings": combined,
        "blocked": any(f["blocking"] for f in combined),
        "capacity": {k: v for k, v in capacity.items() if k != "findings"},
    }


# ── desired versus observed ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Difference:
    app: str
    field_name: str
    desired: object
    observed: object

    def as_dict(self) -> dict:
        return {"app": self.app, "field": self.field_name,
                "desired": self.desired, "observed": self.observed}


def drift(schedule: Schedule, mode: str, observed_apps: dict) -> list[dict]:
    """Where the schedule's intent and Azure's reported configuration disagree.

    `observed_apps` is `GET /control/workers/capacity`'s `apps` block — app name to a dict
    carrying at least `min_replicas` and `max_replicas`.

    AN APP AZURE DID NOT REPORT IS NOT DRIFT. A `min_replicas` of None means the reading failed,
    and calling that a difference would fill the tab with drift every time Azure was slow — which
    is precisely how a drift indicator stops being read. Unreadable is its own state, reported by
    `scaler_health`.
    """
    floors, ceilings = schedule.floors(mode), schedule.maximums
    out: list[Difference] = []
    for service, app_name in SERVICE_APPS.items():
        block = observed_apps.get(app_name)
        if not isinstance(block, dict):
            continue
        for field_name, desired in (("min_replicas", floors.get(service)),
                                    ("max_replicas", ceilings.get(service))):
            observed = block.get(field_name)
            if desired is None or observed is None:
                continue
            if int(observed) != int(desired):
                out.append(Difference(app_name, field_name, int(desired), int(observed)))
    return [d.as_dict() for d in out]


def scaler_health(observed_apps: dict, *, configured: bool = True) -> dict:
    """Per queue-driven service: can its scaler actually add a replica?

    FOUR STATES, and the third is the one AC 10 was missing. A rule on a tier whose floor equals
    its ceiling is not healthy and not broken — it is INERT, and reporting it as healthy is how
    acp-assess came to read as autoscaled when it has never had a rule that could fire.

      not_configured  Azure is not wired up here at all.
      unreadable      The app could not be read; state unknown, NOT assumed good.
      missing         The app is readable, can scale, and carries no queue rule.
      pinned          A rule exists (or does not) but min == max, so nothing can act on it.
      healthy         A queue rule is attached to a tier with room to grow.
    """
    out = {}
    for service in QUEUE_SERVICES:
        app_name = SERVICE_APPS[service]
        if not configured:
            out[service] = {"app": app_name, "state": "not_configured", "rules": []}
            continue
        block = observed_apps.get(app_name)
        if not isinstance(block, dict) or block.get("app_unavailable"):
            out[service] = {"app": app_name, "state": "unreadable", "rules": []}
            continue
        scale = block.get("scale") or {}
        rules = [r.get("name") for r in (scale.get("rules") or []) if isinstance(r, dict)]
        low, high = block.get("min_replicas"), block.get("max_replicas")
        if low is None or high is None:
            out[service] = {"app": app_name, "state": "unreadable", "rules": rules}
        elif int(low) == int(high):
            out[service] = {"app": app_name, "state": "pinned", "rules": rules,
                            "detail": f"{app_name} is pinned at {low}: a queue rule attached to "
                                      f"it cannot add a replica."}
        elif not rules:
            out[service] = {"app": app_name, "state": "missing", "rules": [],
                            "detail": f"{app_name} can scale to {high} but carries no queue "
                                      f"rule, so nothing asks it to."}
        else:
            out[service] = {"app": app_name, "state": "healthy", "rules": rules}
    return out


# ── why capacity is where it is (AC 14) ──────────────────────────────────────────────────────

def attribute_capacity(app_block: dict, *, floor: int | None, authority: str,
                       queue_depth: int | None = None) -> dict:
    """Why this app is running the number of replicas it is running.

    AC 14: "Monitor identifies whether scaling was scheduled, queue-driven, manual, or
    deployment-related." §10 asks the same thing of the metrics. Neither was built, and it is
    also the apparatus PRD Phase 4's tuning needs — "tune queue thresholds and cooldowns" is not
    a decision anybody can make from a replica count that does not say what asked for it.

    DERIVED, NOT RECORDED. There is no scale-event table and this deliberately does not add one:
    every input is already in `GET /control/workers/capacity` plus the schedule ACP holds, so the
    answer costs no storage, no migration and no background writer that can fall behind. What it
    cannot do is explain a scale event that has already finished — this says why capacity is
    where it is NOW. A durable history is a separate decision with a real cost, and it should be
    made against a week of this rather than in advance of it.

    ORDER MATTERS, because more than one cause can be true at once and the useful answer is the
    one that dominates:

      deployment       a rollout is in progress — replicas on more than one revision. This wins
                       outright: during a rollout the count says nothing about demand, and
                       reading it as queue pressure is how a deploy gets mistaken for a spike.
      manual_override  an administrator set the floor by hand, and it expires.
      queue            more replicas than the floor asks for, so something else asked.
      scheduled        exactly the floor in force. The quiet, expected case.
      below_floor      FEWER than the floor. Not a scaling reason at all — a restart, a failed
                       revision, or capacity Azure has not granted. Named rather than folded
                       into `scheduled`, because the two look identical in a bare count and only
                       one of them is a problem.
      unknown          the reading did not come back. Never inferred.
    """
    if not isinstance(app_block, dict) or app_block.get("app_unavailable"):
        return {"reason": "unknown", "detail": "Azure did not answer for this app."}
    current = app_block.get("current_replicas")
    if current is None:
        return {"reason": "unknown", "detail": "The running replica count could not be read."}
    current = int(current)

    draining = app_block.get("draining_replicas")
    if draining:
        return {"reason": "deployment", "current_replicas": current,
                "detail": f"{draining} replica(s) still on a previous revision: a rollout is in "
                          f"progress, so this count reflects the deploy rather than demand."}
    if authority == "manual_override":
        return {"reason": "manual_override", "current_replicas": current,
                "detail": f"An administrator set this floor by hand; it expires on its own."}
    if floor is None:
        return {"reason": "unknown", "current_replicas": current,
                "detail": "No scheduled floor is known for this service, so the count cannot be "
                          "attributed."}
    if current > floor:
        extra = current - floor
        depth = "" if queue_depth is None else f" Queue depth {queue_depth}."
        return {"reason": "queue", "current_replicas": current, "floor": floor,
                "detail": f"{extra} replica(s) above the scheduled floor of {floor}: the queue "
                          f"scaler asked for them.{depth}"}
    if current < floor:
        return {"reason": "below_floor", "current_replicas": current, "floor": floor,
                "detail": f"{floor - current} replica(s) short of the scheduled floor of "
                          f"{floor}. Not a scaling decision — a restart, a failed revision, or "
                          f"capacity Azure has not granted."}
    return {"reason": "scheduled", "current_replicas": current, "floor": floor,
            "detail": f"Exactly the scheduled floor of {floor} for the current mode."}


def attribute_fleet(observed_apps: dict, floors: dict, authority: str,
                    queue_depths: dict | None = None) -> dict:
    """`attribute_capacity` per service, keyed by service rather than by app name."""
    depths = queue_depths or {}
    out = {}
    for service, app_name in SERVICE_APPS.items():
        out[service] = attribute_capacity(
            observed_apps.get(app_name) or {},
            floor=floors.get(service), authority=authority,
            queue_depth=depths.get(service))
    return out
