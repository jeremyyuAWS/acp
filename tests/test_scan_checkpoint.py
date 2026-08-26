"""Sparse Postgres recovery checkpoint for live Discover progress (Redis live-state spec,
2026-08-26). Redis is the fast, frequent live source — but ephemeral: gone if unreachable, a key
TTLs out, or a replica with no Redis falls to a JOBS dict no other replica can see. Without a
durable fallback, a caller reading progress with Redis down gets nothing to show instead of "last
known state, N seconds ago". These tests pin the throttled write side (core._maybe_checkpoint,
wired into set_job/update_job) — deliberately sparse, since a checkpoint written on every tick
would approach the write volume that caused 2026-08-26's Postgres connection exhaustion.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


class _FakeStore:
    def __init__(self):
        self.calls = []

    def checkpoint_scan_progress(self, scan_id, state, at):
        self.calls.append((scan_id, dict(state), at))


@pytest.fixture()
def checkpoint_env(monkeypatch):
    import core
    fake_store = _FakeStore()
    monkeypatch.setattr(core, "get_store", lambda: fake_store)
    monkeypatch.setattr(core, "_get_redis", lambda: None)   # exercise the in-memory path; irrelevant here
    monkeypatch.setattr(core, "JOBS", {})
    monkeypatch.setattr(core, "_JOB_SCAN_ID", {})
    monkeypatch.setattr(core, "_JOB_CHECKPOINT_STATE", {})
    monkeypatch.setattr(core, "_JOB_LAST_CHECKPOINT", {})
    return core, fake_store


def test_set_job_writes_an_immediate_checkpoint_when_scan_id_is_present(checkpoint_env):
    core, store = checkpoint_env
    core.set_job("j1", {"scan_id": "s1", "phase": "queued"})
    assert len(store.calls) == 1
    scan_id, state, at = store.calls[0]
    assert scan_id == "s1"
    assert state["phase"] == "queued"


def test_set_job_without_scan_id_writes_no_checkpoint(checkpoint_env):
    core, store = checkpoint_env
    core.set_job("j2", {"phase": "queued"})   # scan_id not yet known (thread path, pre-assignment)
    assert store.calls == []


def test_update_job_checkpoints_on_phase_change_even_within_the_throttle_window(checkpoint_env):
    core, store = checkpoint_env
    core.set_job("j3", {"scan_id": "s3", "phase": "queued"})
    store.calls.clear()
    core.update_job("j3", {"phase": "listing", "files_found": 5})
    assert len(store.calls) == 1
    assert store.calls[0][1]["phase"] == "listing"


def test_update_job_coalesces_non_phase_ticks_within_the_throttle_window(checkpoint_env):
    core, store = checkpoint_env
    core.set_job("j4", {"scan_id": "s4", "phase": "listing"})
    store.calls.clear()
    core.update_job("j4", {"files_found": 5})
    core.update_job("j4", {"files_found": 10})
    core.update_job("j4", {"files_found": 15})
    assert store.calls == []   # all within _CHECKPOINT_INTERVAL_S of set_job's own write


def test_update_job_checkpoints_again_once_the_interval_elapses(checkpoint_env):
    core, store = checkpoint_env
    core.set_job("j5", {"scan_id": "s5", "phase": "listing"})
    store.calls.clear()
    core._JOB_LAST_CHECKPOINT["j5"] = 0.0   # force "long ago" without sleeping in a test
    core.update_job("j5", {"files_found": 42})
    assert len(store.calls) == 1
    assert store.calls[0][1]["files_found"] == 42


def test_checkpoint_state_accumulates_across_calls_not_just_the_latest_patch(checkpoint_env):
    """The checkpoint is meant to show a useful last-known snapshot — files_found from an
    earlier tick must survive into a later phase-change checkpoint that doesn't repeat it."""
    core, store = checkpoint_env
    core.set_job("j6", {"scan_id": "s6", "phase": "listing"})
    core.update_job("j6", {"files_found": 100})           # coalesced, no checkpoint, but accumulated
    core.update_job("j6", {"phase": "lifecycle"})          # phase change forces a checkpoint
    scan_id, state, at = store.calls[-1]
    assert state["files_found"] == 100
    assert state["phase"] == "lifecycle"


def test_each_job_checkpoints_under_its_own_scan_id(checkpoint_env):
    core, store = checkpoint_env
    core.set_job("j7", {"scan_id": "s7", "phase": "queued"})
    core.set_job("j8", {"scan_id": "s8", "phase": "queued"})
    scan_ids = {c[0] for c in store.calls}
    assert scan_ids == {"s7", "s8"}


def test_a_checkpoint_write_failure_never_raises(checkpoint_env, monkeypatch):
    """A diagnostic write must never fail the scan it is merely describing."""
    core, store = checkpoint_env
    def _boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(store, "checkpoint_scan_progress", _boom)
    core.set_job("j9", {"scan_id": "s9", "phase": "queued"})   # must not raise


# ── store.checkpoint_scan_progress — the real write/read round trip ────────────────────────────

OWNER = "owner@example.com"


def test_checkpoint_round_trips_through_get_scan(isolated_store):
    from datetime import datetime, timezone
    s = isolated_store
    s.init_scan_run("s-cp1", "drive", total=10, started_at=datetime.now(timezone.utc).isoformat(),
                    rubric_name="r", rubric_hash="h", owner=OWNER, status="running")
    at = datetime.now(timezone.utc).isoformat()
    s.checkpoint_scan_progress("s-cp1", {"phase": "lifecycle", "files_evaluated": 40}, at)
    run = s.get_scan("s-cp1", owner=OWNER)["run"]
    assert run["live_checkpoint"] == {"phase": "lifecycle", "files_evaluated": 40}
    assert run["live_checkpoint_at"] == at


def test_a_scan_with_no_checkpoint_yet_reads_as_none_not_an_error(isolated_store):
    from datetime import datetime, timezone
    s = isolated_store
    s.init_scan_run("s-cp2", "drive", total=1, started_at=datetime.now(timezone.utc).isoformat(),
                    rubric_name="r", rubric_hash="h", owner=OWNER, status="running")
    assert s.get_scan("s-cp2", owner=OWNER)["run"]["live_checkpoint"] is None


def test_checkpointing_an_unknown_scan_id_does_not_raise(isolated_store):
    """The row may not exist (deleted, or a race with the write). A checkpoint is a diagnostic
    write, not a source of truth — it must no-op, not error."""
    isolated_store.checkpoint_scan_progress("does-not-exist", {"phase": "listing"}, "2026-08-26T00:00:00Z")
