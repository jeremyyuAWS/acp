"""Pure wall-clock recurrence rules for user-owned scheduled scans.

Schedules are expressed in an IANA timezone because a fixed UTC offset drifts twice a year.
One occurrence is identified by the user's normalized owner, timezone, local date and local
time.  That identity is stable across replicas and across a scheduler restart, so the jobs table
can elect exactly one worker by primary key.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DAYS = tuple(range(7))  # Monday=0, matching datetime.weekday() and the HTTP contract.
DEFAULT_CATCH_UP = timedelta(days=7)


class ScheduleError(ValueError):
    pass


def normalize_days(days) -> tuple[int, ...]:
    try:
        values = tuple(dict.fromkeys(int(day) for day in (days or ())))
    except (TypeError, ValueError) as exc:
        raise ScheduleError("schedule days must be integers from 0 (Monday) to 6 (Sunday)") from exc
    unknown = [day for day in values if day not in DAYS]
    if unknown:
        raise ScheduleError(f"unknown schedule day: {unknown[0]}")
    return tuple(day for day in DAYS if day in values)


def zone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(str(timezone_name))
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ScheduleError(f"unknown timezone {timezone_name!r}") from exc


def local_time(value: str) -> time:
    try:
        hour, minute = str(value).split(":")
        parsed = time(int(hour), int(minute))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ScheduleError(f"local_time is not HH:MM: {value!r}") from exc
    return parsed


def occurrence_instant(day: date, at: str, timezone_name: str) -> datetime:
    """Resolve one local occurrence to UTC, choosing a deterministic DST policy.

    An ambiguous fall-back time runs on its first occurrence, once. A nonexistent spring-forward
    time runs as the clock passes the missing reading. This matches the conservative start-time
    policy already used by ``capacity_schedule``.
    """
    tz = zone(timezone_name)
    naive = datetime.combine(day, local_time(at))
    first = naive.replace(tzinfo=tz, fold=0)
    second = naive.replace(tzinfo=tz, fold=1)
    if first.utcoffset() == second.utcoffset():
        return first.astimezone(timezone.utc)
    first_utc = first.astimezone(timezone.utc)
    second_utc = second.astimezone(timezone.utc)
    # In a gap fold=1 resolves backwards. fold=0 is the instant after the clock crosses it.
    return first_utc if second_utc < first_utc else min(first_utc, second_utc)


def occurrence_key(schedule: dict, day: date) -> str:
    owner = str(schedule.get("owner_email") or "").strip().lower()
    source = str(schedule.get("source") or "drive").strip().lower()
    tz_name = str(schedule.get("timezone") or "UTC")
    at = str(schedule.get("local_time") or "00:00")
    return f"user-scan:{owner}:{source}:{tz_name}:{day.isoformat()}:{at}"


def due_occurrence(schedule: dict, now: datetime, *, grace: timedelta = timedelta(minutes=5)) -> dict | None:
    """Return the current due occurrence, including a short scheduler/restart grace window."""
    if not schedule.get("enabled"):
        return None
    days = normalize_days(schedule.get("days"))
    if not days:
        return None
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    tz_name = str(schedule.get("timezone") or "UTC")
    local_day = now.astimezone(zone(tz_name)).date()
    if local_day.weekday() not in days:
        return None
    instant = occurrence_instant(local_day, str(schedule.get("local_time")), tz_name)
    if instant <= now < instant + grace:
        return {
            "occurrence_key": occurrence_key(schedule, local_day),
            "scheduled_for": instant.isoformat(),
            "local_date": local_day.isoformat(),
        }
    return None


def due_or_most_recent_occurrence(
        schedule: dict, now: datetime, *, grace: timedelta = timedelta(minutes=5),
        catch_up: timedelta = DEFAULT_CATCH_UP) -> dict | None:
    """Return the on-time occurrence or at most one newest missed occurrence.

    Catch-up is bounded both by ``catch_up`` and by the schedule's ``updated_at``. The latter
    prevents enabling a schedule after today's chosen time from manufacturing a historic run.
    A durable occurrence key makes repeated scheduler ticks harmless.
    """
    current = due_occurrence(schedule, now, grace=grace)
    if current:
        return {**current, "catch_up": False}
    if not schedule.get("enabled"):
        return None
    days = normalize_days(schedule.get("days"))
    if not days or catch_up <= timedelta(0):
        return None
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    floor = now - catch_up
    updated_at = schedule.get("updated_at")
    if updated_at:
        try:
            saved = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
            if saved.tzinfo is None:
                saved = saved.replace(tzinfo=timezone.utc)
            floor = max(floor, saved.astimezone(timezone.utc))
        except (TypeError, ValueError):
            return None  # corrupt state must not manufacture background work
    tz_name = str(schedule.get("timezone") or "UTC")
    local_today = now.astimezone(zone(tz_name)).date()
    for offset in range(8):
        day = local_today - timedelta(days=offset)
        if day.weekday() not in days:
            continue
        instant = occurrence_instant(day, str(schedule.get("local_time")), tz_name)
        if floor <= instant <= now:
            return {
                "occurrence_key": occurrence_key(schedule, day),
                "scheduled_for": instant.isoformat(),
                "local_date": day.isoformat(),
                "catch_up": True,
            }
    return None


def next_occurrence(schedule: dict, now: datetime) -> datetime | None:
    if not schedule.get("enabled"):
        return None
    days = normalize_days(schedule.get("days"))
    if not days:
        return None
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    tz_name = str(schedule.get("timezone") or "UTC")
    today = now.astimezone(zone(tz_name)).date()
    for offset in range(8):
        day = today + timedelta(days=offset)
        if day.weekday() not in days:
            continue
        instant = occurrence_instant(day, str(schedule.get("local_time")), tz_name)
        if instant > now:
            return instant
    return None


def in_blackout(schedule: dict, instant: datetime) -> bool:
    """Whether ``instant`` falls in one of the schedule's local blackout windows.

    A window that crosses midnight belongs to the weekday on which it starts.  Thus a
    Friday 22:00-02:00 window includes early Saturday, which is how operators describe it.
    Invalid persisted windows fail closed: a malformed guardrail must not silently permit work.
    """
    windows = schedule.get("blackout_windows") or ()
    if not windows:
        return False
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    local = instant.astimezone(zone(str(schedule.get("timezone") or "UTC")))
    current = local.timetz().replace(tzinfo=None)
    for window in windows:
        days = normalize_days(window.get("days"))
        start = local_time(window.get("start"))
        end = local_time(window.get("end"))
        if start == end:
            raise ScheduleError("a blackout start and end cannot be equal")
        if start < end:
            if local.weekday() in days and start <= current < end:
                return True
        else:
            if local.weekday() in days and current >= start:
                return True
            if (local.weekday() - 1) % 7 in days and current < end:
                return True
    return False


def prewarm_candidates(schedules, now: datetime, *, default_lead_minutes: int = 15) -> list[dict]:
    """Return upcoming occurrences whose configured pre-warm window has opened.

    This is only a forecast.  The caller persists an idempotent capacity intent; it does not
    mutate Azure from the scheduler process.  Existing queue-driven scale-down therefore keeps
    its claimed-work protection and drain semantics.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    due = []
    for cfg in schedules:
        try:
            lead = int((cfg.get("queue_policy") or {}).get(
                "prewarm_minutes", cfg.get("prewarm_minutes", default_lead_minutes)))
            upcoming = next_occurrence(cfg, now)
            if lead <= 0 or upcoming is None or not (now <= upcoming <= now + timedelta(minutes=lead)):
                continue
            if in_blackout(cfg, upcoming):
                continue
            local_day = upcoming.astimezone(zone(str(cfg.get("timezone") or "UTC"))).date()
            due.append({
                "occurrence_key": occurrence_key(cfg, local_day),
                "owner_email": cfg.get("owner_email"),
                "source": cfg.get("source") or "drive",
                "scheduled_for": upcoming.isoformat(),
                "lead_minutes": lead,
            })
        except (ScheduleError, TypeError, ValueError):
            continue
    return due
