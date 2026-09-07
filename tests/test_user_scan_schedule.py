"""User scan recurrence is local-wall-clock correct and fleet-idempotent."""
import sys
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import scan_schedule as schedule


def _cfg(**overrides):
    out = {"owner_email": "Alice@Example.com", "enabled": True,
           "timezone": "America/Los_Angeles", "local_time": "09:30",
           "days": [0, 1, 2, 3, 4], "source": "drive"}
    out.update(overrides)
    return out


def test_local_time_tracks_daylight_saving_instead_of_a_fixed_utc_offset():
    assert schedule.occurrence_instant(date(2026, 1, 12), "09:30", "America/Los_Angeles") == datetime(
        2026, 1, 12, 17, 30, tzinfo=timezone.utc)
    assert schedule.occurrence_instant(date(2026, 7, 13), "09:30", "America/Los_Angeles") == datetime(
        2026, 7, 13, 16, 30, tzinfo=timezone.utc)


def test_fall_back_ambiguous_time_runs_on_first_occurrence_only():
    instant = schedule.occurrence_instant(date(2026, 11, 1), "01:30", "America/Los_Angeles")
    assert instant == datetime(2026, 11, 1, 8, 30, tzinfo=timezone.utc)
    cfg = _cfg(local_time="01:30", days=[6])
    first = schedule.due_occurrence(cfg, instant)
    second = schedule.due_occurrence(cfg, instant + timedelta(hours=1))
    assert first and second is None


def test_spring_forward_missing_time_still_has_one_deterministic_occurrence():
    assert schedule.occurrence_instant(
        date(2026, 3, 8), "02:30", "America/Los_Angeles") == datetime(
            2026, 3, 8, 10, 30, tzinfo=timezone.utc)


def test_occurrence_identity_is_owner_scoped_and_case_normalized():
    day = date(2026, 9, 7)
    assert schedule.occurrence_key(_cfg(), day) == schedule.occurrence_key(
        _cfg(owner_email="alice@example.com"), day)
    assert schedule.occurrence_key(_cfg(), day) != schedule.occurrence_key(
        _cfg(owner_email="bob@example.com"), day)


def test_weekday_filter_and_next_occurrence_use_the_users_calendar():
    cfg = _cfg(days=[0])
    sunday = datetime(2026, 9, 6, 20, tzinfo=timezone.utc)
    assert schedule.due_occurrence(cfg, sunday) is None
    assert schedule.next_occurrence(cfg, sunday) == datetime(
        2026, 9, 7, 16, 30, tzinfo=timezone.utc)


def test_invalid_timezone_time_and_days_are_rejected():
    for call in (
        lambda: schedule.zone("Mars/Olympus"),
        lambda: schedule.local_time("25:90"),
        lambda: schedule.normalize_days([7]),
    ):
        try:
            call()
        except schedule.ScheduleError:
            pass
        else:
            raise AssertionError("invalid schedule shape was accepted")


def test_scheduler_offers_each_users_due_occurrence_with_owner_snapshot(monkeypatch):
    import core
    now = datetime(2026, 9, 7, 16, 30, tzinfo=timezone.utc)  # Monday 09:30 Pacific
    offers = []

    class Store:
        def list_enabled_user_scan_schedules(self):
            return [_cfg(), _cfg(owner_email="bob@example.com")]

        def enqueue_scheduled_sweep(self, key, payload):
            offers.append((key, payload))
            return True

    monkeypatch.setattr(core, "get_store", lambda: Store())
    assert core._enqueue_scheduled_scan(now) is True
    assert len(offers) == 2
    assert {payload["owner_email"].lower() for _, payload in offers} == {
        "alice@example.com", "bob@example.com"}
    assert offers[0][0] != offers[1][0]
    assert all(payload["occurrence_key"] == key for key, payload in offers)


def test_durable_election_preserves_the_user_occurrence_snapshot(isolated_store):
    cfg = _cfg(owner_email="alice@example.com")
    due = schedule.due_occurrence(
        cfg, datetime(2026, 9, 7, 16, 30, tzinfo=timezone.utc))
    payload = {**due, "owner_email": cfg["owner_email"], "source": cfg["source"]}

    assert isolated_store.enqueue_scheduled_sweep(due["occurrence_key"], payload) is True
    assert isolated_store.enqueue_scheduled_sweep(due["occurrence_key"], payload) is False
    jobs = [job for job in isolated_store.list_jobs() if job["type"] == "scheduled_sweep"]
    saved = json.loads(jobs[0]["payload"])
    assert saved["owner_email"] == "alice@example.com"
    assert saved["local_date"] == "2026-09-07"
