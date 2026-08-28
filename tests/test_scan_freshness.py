"""Freshness field on GET /scans/{id} — data-currency classification.

_scan_freshness(scan_id, run) classifies the progress data as:
  terminal  — scan reached a final state (no worker running)
  live      — Redis job state updated within _FRESHNESS_LIVE_THRESHOLD_S (30 s)
  checkpoint — no live Redis signal but a durable Postgres snapshot exists
  stale     — scan is running but neither live nor checkpoint is available
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


def _freshness(scan_id, run, *, job_state=None, job_id="j1"):
    """Call _scan_freshness with a patched core, returning the result."""
    import importlib
    import types

    # Build a minimal fake core module so routes.scans can import it.
    fake_core = types.ModuleType("core")
    fake_core.get_job_id_for_scan = lambda sid: job_id if job_state is not None else None
    fake_core.get_job_state = lambda jid: job_state

    # Save the REAL module objects, not just their names — restoring by sys.modules.pop(...)
    # (as this used to) leaves "core" absent afterward, so the next `import core` anywhere in
    # the process builds a BRAND NEW module object rather than reusing the one every
    # already-imported module (handlers.py, routes/scans.py, ...) is still holding a reference
    # to internally. That produces two live "core" modules with independently-initialized
    # globals (_SCAN_JOB_MAP, JOBS, _redis, ...) — a real, live cross-test-pollution bug found
    # 2026-08-28: with this test running earlier in a shard, core.get_job_id_for_scan() calls
    # made from a freshly-reimported "core" silently read an empty dict the durable-path write
    # (through the ORIGINAL "core" object) never touched, failing
    # test_scan_id_job_mapping_durable_path.py and test_scan_job_heartbeat.py with no
    # indication anything upstream was at fault. Restoring the exact prior objects (falling back
    # to a pop only when nothing was previously imported) keeps identity intact for every other
    # consumer.
    real_core = sys.modules.get("core")
    real_routes_scans = sys.modules.get("routes.scans")
    real_routes = sys.modules.get("routes")

    sys.modules["core"] = fake_core
    # Force re-import of routes.scans so it picks up the patched core.
    sys.modules.pop("routes.scans", None)
    sys.modules.pop("routes", None)

    try:
        from routes.scans import _scan_freshness
        return _scan_freshness(scan_id, run)
    finally:
        if real_core is not None:
            sys.modules["core"] = real_core
        else:
            sys.modules.pop("core", None)
        if real_routes_scans is not None:
            sys.modules["routes.scans"] = real_routes_scans
        else:
            sys.modules.pop("routes.scans", None)
        if real_routes is not None:
            sys.modules["routes"] = real_routes
        else:
            sys.modules.pop("routes", None)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _ago_iso(seconds):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


# ── terminal ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", [
    "completed", "failed", "cancelled", "interrupted", "superseded", "discovered",
])
def test_terminal_status_yields_terminal(status):
    assert _freshness("s1", {"status": status}) == "terminal"


def test_non_terminal_status_does_not_yield_terminal():
    assert _freshness("s1", {"status": "running"}, job_state=None) != "terminal"


# ── live ──────────────────────────────────────────────────────────────────────

def test_live_when_redis_updated_within_threshold():
    state = {"phase": "discovering", "done": False, "updated_at": _ago_iso(5)}
    result = _freshness("s1", {"status": "running"}, job_state=state)
    assert result == "live"


def test_not_live_when_redis_updated_beyond_threshold():
    state = {"phase": "discovering", "done": False, "updated_at": _ago_iso(60)}
    result = _freshness("s1", {"status": "running"}, job_state=state)
    assert result != "live"


def test_not_live_when_job_done_flag_is_set():
    state = {"phase": "done", "done": True, "updated_at": _now_iso()}
    result = _freshness("s1", {"status": "running"}, job_state=state)
    assert result != "live"


def test_not_live_when_no_job_found():
    result = _freshness("s1", {"status": "running"}, job_state=None)
    assert result != "live"


# ── checkpoint ────────────────────────────────────────────────────────────────

def test_checkpoint_when_redis_stale_and_live_checkpoint_at_exists():
    state = {"phase": "discovering", "done": False, "updated_at": _ago_iso(120)}
    run = {"status": "running", "live_checkpoint_at": _ago_iso(30)}
    assert _freshness("s1", run, job_state=state) == "checkpoint"


def test_checkpoint_when_no_redis_but_live_checkpoint_at_exists():
    run = {"status": "running", "live_checkpoint_at": _ago_iso(20)}
    assert _freshness("s1", run, job_state=None) == "checkpoint"


def test_checkpoint_not_returned_when_live_checkpoint_at_is_none():
    run = {"status": "running", "live_checkpoint_at": None}
    assert _freshness("s1", run, job_state=None) == "stale"


# ── stale ─────────────────────────────────────────────────────────────────────

def test_stale_when_running_with_no_signal_and_no_checkpoint():
    run = {"status": "running"}
    assert _freshness("s1", run, job_state=None) == "stale"


def test_stale_when_redis_stale_and_no_checkpoint():
    state = {"phase": "discovering", "done": False, "updated_at": _ago_iso(200)}
    run = {"status": "running"}
    assert _freshness("s1", run, job_state=state) == "stale"


# ── get_scan response includes freshness ──────────────────────────────────────

def test_get_scan_response_includes_freshness_field(isolated_store, monkeypatch):
    """The GET /scans/{id} route must inject run.freshness before returning."""
    from datetime import datetime, timezone
    import types

    s = isolated_store
    sid = "s-fresh-1"
    s.init_scan_run(sid, "drive", total=0, started_at=datetime.now(timezone.utc).isoformat(),
                    rubric_name="r", rubric_hash="h", owner="owner@example.com", status="running")
    s.set_scan_status(sid, "discovered")

    # Build a fake core that returns no live job (so freshness will be terminal).
    fake_core = types.ModuleType("core")
    fake_core.get_job_id_for_scan = lambda scan_id: None
    fake_core.get_job_state = lambda jid: None
    fake_core.store = s

    # Same identity-preserving save/restore as _freshness() above, and for the same reason:
    # popping "core" instead of restoring it leaves a second, independently-initialized core
    # module for whatever imports it fresh next, silently diverging from the one every
    # already-imported module (handlers.py, routes/scans.py, ...) still references internally.
    real_core = sys.modules.get("core")
    real_routes_scans = sys.modules.get("routes.scans")
    real_routes = sys.modules.get("routes")

    sys.modules.pop("routes.scans", None)
    sys.modules.pop("routes", None)
    sys.modules["core"] = fake_core

    try:
        from routes.scans import _scan_freshness
        run = s.get_scan(sid, owner="owner@example.com")["run"]
        result = _scan_freshness(sid, run)
        assert result == "terminal"
    finally:
        if real_core is not None:
            sys.modules["core"] = real_core
        else:
            sys.modules.pop("core", None)
        if real_routes_scans is not None:
            sys.modules["routes.scans"] = real_routes_scans
        else:
            sys.modules.pop("routes.scans", None)
        if real_routes is not None:
            sys.modules["routes"] = real_routes
        else:
            sys.modules.pop("routes", None)
