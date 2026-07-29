"""A scheduled sweep that fails must say so, instead of leaving stale data looking current.

`core._do_scheduled_scan` deliberately saves NOTHING when it cannot reach its source — the
alternative, substituting the bundled samples, displaced a 258-document estate every five
minutes. Correct about the data, silent about the UI: the only trace was a container log line,
so every surface went on presenting an hours-old scan as the live estate. That is how the Drive
403 insufficient-scopes loop of 2026-07-29 ran unnoticed while `last_at` still looked healthy —
`last_at` is the last SUCCESSFUL scan, so a failing sweep never moves it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture()
def sched(monkeypatch, isolated_store):
    """core wired to an isolated store, with the schedule on and pointed at drive."""
    import core
    monkeypatch.setattr(core, "store", isolated_store)
    isolated_store.save_schedule(True, 5, owner="owner@example.com", source="drive")
    return core, isolated_store


def test_nothing_recorded_before_a_sweep_has_run(isolated_store):
    assert isolated_store.get_last_sweep() is None


def test_a_failed_sweep_round_trips_through_the_real_store(sched, monkeypatch, capsys):
    """End-to-end over a real Store, not the double in test_scheduled_sweep.py.

    That file asserts _do_scheduled_scan CALLS record_sweep_outcome; this one asserts the value
    survives the app_settings round-trip and comes back parsed.
    """
    core, store = sched

    def boom(*a, **k):
        raise RuntimeError('returned "Request had insufficient authentication scopes."')

    monkeypatch.setattr(core, "run_scan", boom)

    core._do_scheduled_scan()

    rec = store.get_last_sweep()
    assert rec is not None, "the failure left no trace anywhere but the log — the whole defect"
    assert rec["ok"] is False
    assert rec["source"] == "drive"
    assert "insufficient authentication scopes" in rec["error"]
    assert rec["at"]
    assert store.list_scans() == [], "the previous-scan-stands behaviour is unchanged"
    # And the log line is still there — this adds a surface, it does not replace one.
    assert "sweep FAILED" in capsys.readouterr().out


def test_a_successful_sweep_records_ok_and_clears_the_previous_failure(sched, monkeypatch):
    core, store = sched
    monkeypatch.setattr(core, "run_scan", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("nope")))
    core._do_scheduled_scan()
    assert store.get_last_sweep()["ok"] is False

    report = {
        "started_at": "2026-07-29T21:00:00+00:00", "completed_at": "2026-07-29T21:05:00+00:00",
        "source": "drive", "owner": "owner@example.com",
        "rubric": {"name": "wcag-aa", "hash": "h"},
        "summary": {"files": 3, "certifiable": 3, "uncertain": 0, "error": 0, "avg_score": 91},
        "files": [],
    }
    monkeypatch.setattr(core, "run_scan", lambda *a, **k: dict(report))
    monkeypatch.setattr(core, "finalize_scan", lambda *a, **k: None)

    core._do_scheduled_scan()

    rec = store.get_last_sweep()
    assert rec["ok"] is True and rec["files"] == 3 and rec["error"] is None
    assert rec["scan_id"]


def test_the_recorded_error_is_truncated_before_it_reaches_a_browser(sched, monkeypatch):
    """A Google HttpError repr carries the whole request URL; the banner needs the gist."""
    core, store = sched
    monkeypatch.setattr(core, "run_scan",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x" * 5000)))

    core._do_scheduled_scan()

    assert len(store.get_last_sweep()["error"]) == 400


def test_schedule_endpoint_reports_the_outcome_not_just_the_last_success(sched, monkeypatch):
    """`last_at` cannot express this: it is the last scan that SAVED."""
    core, store = sched
    from fastapi.testclient import TestClient

    from app import app

    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    store.record_sweep_outcome(ok=False, when="2026-07-29T21:27:59+00:00", source="drive",
                              error="insufficient authentication scopes")

    body = TestClient(app).get("/schedule").json()

    assert body["last_sweep"]["ok"] is False
    assert "insufficient authentication scopes" in body["last_sweep"]["error"]
    assert body["last_at"] is None, "no scan ever saved, yet the schedule looked healthy before"


def test_bookkeeping_failure_cannot_take_the_sweep_down_with_it(sched, monkeypatch):
    """record_sweep_outcome is best-effort — a sweep must not fail because its telemetry did."""
    core, store = sched
    monkeypatch.setattr(store, "set_setting",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db gone")))
    monkeypatch.setattr(core, "run_scan", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("nope")))

    core._do_scheduled_scan()      # must not raise


# ── the debug flag that could not be turned off ────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    ("1", True), ("true", True), ("TRUE", True), ("yes", True), ("on", True), (" on ", True),
    ("0", False), ("false", False), ("no", False), ("off", False), ("", False),
])
def test_discovery_debug_flag_reads_0_as_off(monkeypatch, value, expected):
    """`os.environ.get(name)` is truthy for the string "0".

    The live container had ACP_DRIVE_DISCOVERY_DEBUG="0" and was still running the extra
    unfiltered Drive listing on every sweep — which is why the incident log is full of
    `[scan] discovery DEBUG:` lines for a diagnostic the operator had turned off.
    """
    import scanner
    monkeypatch.setenv("ACP_DRIVE_DISCOVERY_DEBUG", value)

    assert scanner._flag_on("ACP_DRIVE_DISCOVERY_DEBUG") is expected


def test_discovery_debug_flag_is_off_when_unset(monkeypatch):
    import scanner
    monkeypatch.delenv("ACP_DRIVE_DISCOVERY_DEBUG", raising=False)

    assert scanner._flag_on("ACP_DRIVE_DISCOVERY_DEBUG") is False
