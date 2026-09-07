"""Scheduled scan execution obeys policy without weakening durable fleet election."""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import scan_schedule


def _cfg(**extra):
    cfg = {"owner_email": "alice@example.com", "enabled": True, "source": "drive",
           "timezone": "America/Los_Angeles", "local_time": "09:00", "days": list(range(7)),
           "queue_policy": {"prewarm_minutes": 15}}
    cfg.update(extra)
    return cfg


def test_blackout_windows_use_local_wall_clock_and_cross_midnight():
    cfg = _cfg(blackout_windows=[{"days": [4], "start": "22:00", "end": "02:00"}])
    assert scan_schedule.in_blackout(
        cfg, datetime(2026, 9, 5, 8, 0, tzinfo=timezone.utc))  # Saturday 01:00, Friday window
    assert not scan_schedule.in_blackout(
        cfg, datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc))


def test_prewarm_forecast_is_idempotently_keyed_and_excludes_blackouts():
    now = datetime(2026, 9, 7, 15, 50, tzinfo=timezone.utc)  # Monday 08:50 Pacific
    ready = scan_schedule.prewarm_candidates([_cfg()], now)
    assert ready[0]["scheduled_for"] == "2026-09-07T16:00:00+00:00"
    assert ready[0]["occurrence_key"].endswith(":2026-09-07:09:00")
    blocked = _cfg(blackout_windows=[{"days": [0], "start": "08:00", "end": "10:00"}])
    assert scan_schedule.prewarm_candidates([blocked], now) == []


def test_scheduler_defers_one_occurrence_and_records_prewarm(monkeypatch):
    import core
    now = datetime(2026, 9, 7, 16, 0, tzinfo=timezone.utc)
    calls = {"prewarm": [], "defer": [], "enqueue": []}

    class Store:
        def list_enabled_user_scan_schedules(self): return [_cfg()]
        def request_schedule_prewarm(self, *args): calls["prewarm"].append(args); return True
        def schedule_admission(self, owner, key, planned, current):
            return {"admit": False, "reason": "interactive_work_active",
                    "run_after": "2026-09-07T16:05:00+00:00", "terminal": False}
        def defer_scheduled_sweep(self, *args): calls["defer"].append(args); return True
        def enqueue_scheduled_sweep(self, key, payload, run_after=None):
            calls["enqueue"].append((key, payload, run_after)); return True

    monkeypatch.setattr(core, "get_store", lambda: Store())
    assert core._enqueue_scheduled_scan(now)
    assert calls["defer"][0][3] == "interactive_work_active"
    assert calls["enqueue"][0][2] == "2026-09-07T16:05:00+00:00"


def test_handler_rechecks_queue_policy_and_retries_same_durable_job(monkeypatch):
    import handlers
    payload = {"owner_email": "alice@example.com", "occurrence_key": "alice:monday",
               "scheduled_for": "2026-09-07T16:00:00+00:00"}
    deferred = []

    class Store:
        def defer_scheduled_sweep(self, *args): deferred.append(args); return True

    monkeypatch.setattr(handlers.core, "get_store", lambda: Store())
    monkeypatch.setattr(handlers.core, "_scheduled_scan_admission", lambda payload: {
        "admit": False, "reason": "queue_depth_limit",
        "run_after": "2026-09-07T16:05:00+00:00", "terminal": False})
    with pytest.raises(RuntimeError, match="queue_depth_limit"):
        handlers._scheduled_sweep(payload, {"id": "sweep-one"})
    assert deferred[0][1] == "alice:monday"


def test_handler_does_not_count_its_own_owner_slot_as_a_conflict(monkeypatch):
    import handlers
    payload = {"owner_email": "alice@example.com", "occurrence_key": "alice:monday"}
    ran = []
    monkeypatch.setattr(handlers.core, "_scheduled_scan_admission", lambda payload: {
        "admit": False, "reason": "owner_concurrency_limit", "owner_active": 1,
        "run_after": None, "terminal": False})
    monkeypatch.setattr(handlers.core, "_do_scheduled_scan", lambda value: ran.append(value))
    handlers._scheduled_sweep(payload, {"id": "sweep-one"})
    assert ran == [payload]


def test_scoped_schedule_passes_roots_and_exclusions_without_delta(monkeypatch):
    import core
    calls = {}

    class Store:
        def get_user_scan_schedule(self, owner):
            return _cfg(source_scope={"include_ids": ["root-a"], "exclude_ids": ["private"]})
        def get_ai_enabled(self): return False
        def save_scan(self, report): return "scan-1"
        def record_sweep_outcome(self, **kwargs): pass
        def begin_schedule_occurrence(self, *args, **kwargs): return True
        def complete_schedule_occurrence(self, *args, **kwargs): return {}
        def emit_schedule_notification_for_occurrence(self, *args, **kwargs): return None

    monkeypatch.setattr(core, "get_store", lambda: Store())
    monkeypatch.setattr(core, "run_scan", lambda source, **kwargs: calls.update(kwargs) or {
        "summary": {"files": 2}})
    monkeypatch.setattr(core, "finalize_scan", lambda *args: None)
    monkeypatch.setattr(core, "_drive_sync_plan", lambda *args: (_ for _ in ()).throw(
        AssertionError("narrow scopes must not use whole-drive delta")))
    occurrence = {"owner_email": "alice@example.com", "occurrence_key":
                  "user-scan:alice@example.com:drive:America/Los_Angeles:2026-09-07:09:00",
                  "local_date": "2026-09-07", "scheduled_for": "2026-09-07T16:00:00+00:00"}
    core._do_scheduled_scan(occurrence)
    assert calls["folders"] == ["root-a"]
    assert calls["exclude_folders"] == ["private"]
    assert calls["drive_delta"] is None
