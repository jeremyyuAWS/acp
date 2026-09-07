"""Owner isolation and backward compatibility for user wall-clock scan schedules."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


class _Request:
    def __init__(self, email: str | None):
        self.state = SimpleNamespace(user_email=email)


def test_store_keeps_user_schedules_isolated_and_lists_only_enabled(isolated_store):
    alice = isolated_store.save_user_scan_schedule(
        "Alice@Example.com", True, "America/Los_Angeles", "08:30", [0, 2, 4])
    isolated_store.save_user_scan_schedule(
        "bob@example.com", False, "Europe/London", "17:05", [1, 3])

    assert alice["owner_email"] == "alice@example.com"
    assert alice["days"] == [0, 2, 4]
    assert isolated_store.get_user_scan_schedule("bob@example.com")["timezone"] == "Europe/London"
    assert isolated_store.get_user_scan_schedule("nobody@example.com") == {
        "owner_email": "nobody@example.com", "enabled": False, "timezone": "UTC",
        "local_time": "09:00", "days": [0, 1, 2, 3, 4], "source": "drive",
        "updated_at": None, "last_enqueued_occurrence": None,
        "metrics": {"scheduled": 0, "delayed": 0, "skipped": 0, "failed": 0},
    }
    assert [row["owner_email"] for row in isolated_store.list_enabled_user_scan_schedules()] == [
        "alice@example.com"]


@pytest.mark.parametrize("timezone,local_time,days", [
    ("Not/AZone", "09:00", [0]),
    ("UTC", "25:00", [0]),
    ("UTC", "09:00", [7]),
])
def test_store_rejects_invalid_wall_clock_values_without_writing(
        isolated_store, timezone, local_time, days):
    with pytest.raises(ValueError):
        isolated_store.save_user_scan_schedule(
            "alice@example.com", True, timezone, local_time, days)
    assert isolated_store.get_user_scan_schedule("alice@example.com")["updated_at"] is None


def test_route_reads_and_updates_only_the_callers_schedule(isolated_store, monkeypatch):
    import routes.system as system

    monkeypatch.setattr(system.core, "store", isolated_store)
    monkeypatch.setattr(system.core, "reload_scheduler", lambda: None)
    isolated_store.save_user_scan_schedule(
        "bob@example.com", True, "Europe/London", "17:05", [1, 3])

    body = system.ScheduleUpdate(
        enabled=True, timezone="America/New_York", local_time="07:15", days=[0, 1, 2, 3, 4])
    answer = system.update_schedule(body, _Request("alice@example.com"))

    assert answer["owner_email"] == "alice@example.com"
    assert answer["timezone"] == "America/New_York"
    assert answer["local_time"] == "07:15"
    assert answer["days"] == [0, 1, 2, 3, 4]
    assert system.schedule(_Request("bob@example.com"))["timezone"] == "Europe/London"


def test_route_does_not_expose_another_users_sweep_outcome(isolated_store, monkeypatch):
    import routes.system as system

    monkeypatch.setattr(system.core, "store", isolated_store)
    isolated_store.save_user_scan_schedule(
        "alice@example.com", True, "UTC", "09:00", [0, 1, 2, 3, 4])
    isolated_store.record_sweep_outcome(
        ok=False, when="2026-09-07T12:00:00+00:00", source="drive",
        error="alice-only failure", owner="alice@example.com")

    assert system.schedule(_Request("alice@example.com"))["last_sweep"]["ok"] is False
    assert system.schedule(_Request("bob@example.com"))["last_sweep"] is None
    assert system.schedule(_Request("alice@example.com"))["metrics"]["failed"] == 1


def test_schedule_metrics_count_admission_catch_up_skip_and_failure(isolated_store):
    isolated_store.save_user_scan_schedule(
        "alice@example.com", True, "UTC", "09:00", [0, 1, 2, 3, 4])
    assert isolated_store.enqueue_scheduled_sweep(
        "alice:on-time", {"owner_email": "alice@example.com", "catch_up": False}) is True
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "UPDATE jobs SET status='done' WHERE scheduled_owner=%s", ("alice@example.com",))
    assert isolated_store.enqueue_scheduled_sweep(
        "alice:catch-up", {"owner_email": "alice@example.com", "catch_up": True}) is True
    isolated_store.record_sweep_outcome(
        ok=True, when="2026-09-07T12:00:00+00:00", source="drive", skipped=True,
        owner="alice@example.com")
    isolated_store.record_sweep_outcome(
        ok=False, when="2026-09-08T12:00:00+00:00", source="drive", error="unavailable",
        owner="alice@example.com")

    assert isolated_store.get_user_scan_schedule("alice@example.com")["metrics"] == {
        "scheduled": 2, "delayed": 1, "skipped": 1, "failed": 1,
    }


def test_authenticated_schedule_status_does_not_use_another_users_scan(
        isolated_store, monkeypatch):
    import routes.system as system

    monkeypatch.setattr(system.core, "store", isolated_store)
    isolated_store.init_scan_run(
        "bob-scan", "drive", 1, "2026-09-06T15:00:00+00:00", "wcag-aa", "hash",
        owner="bob@example.com", status="running", scope={"kind": "drive"})
    isolated_store.set_scan_status("bob-scan", "discovered")

    assert system.schedule(_Request("alice@example.com"))["last_at"] is None
    assert system.schedule(_Request("bob@example.com"))["last_at"] is not None


def test_legacy_interval_put_remains_supported(isolated_store, monkeypatch):
    import routes.system as system

    monkeypatch.setattr(system.core, "store", isolated_store)
    monkeypatch.setattr(system.core, "reload_scheduler", lambda: None)
    monkeypatch.setattr(system.core.scheduler, "get_job", lambda _name: None)

    answer = system.update_schedule(
        system.ScheduleUpdate(enabled=True, interval_minutes=60), _Request("alice@example.com"))

    assert answer["schedule_type"] == "interval"
    assert answer["interval_minutes"] == 60
    assert answer["owner_email"] == "alice@example.com"


def test_invalid_wall_clock_request_is_a_422_and_does_not_replace_schedule(
        isolated_store, monkeypatch):
    import routes.system as system
    from fastapi import HTTPException

    monkeypatch.setattr(system.core, "store", isolated_store)
    monkeypatch.setattr(system.core, "reload_scheduler", lambda: None)
    with pytest.raises(HTTPException) as raised:
        system.update_schedule(
            system.ScheduleUpdate(enabled=True, timezone="Mars/Olympus", local_time="09:00", days=[0]),
            _Request("alice@example.com"))
    assert raised.value.status_code == 422
    assert isolated_store.get_user_scan_schedule("alice@example.com")["updated_at"] is None
