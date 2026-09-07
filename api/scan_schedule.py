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
