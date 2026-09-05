"""Threaded-scan progress must be readable from a replica that did not run the scan.

`core.JOBS` was written by the scan thread and read by the UI's poll, and both only worked when
they landed on the SAME replica — so acp-app carried ingress session affinity to guarantee it.
That affinity is what blocks multi-revision mode, and therefore blue-green: ACA refuses outright
with `ContainerAppInvalidIngressStickySessionRevisionMode`, which is exactly how the first
blue-green deploy failed on 2026-07-29.

Routing the state through core.set_job/update_job/get_job_state (Redis when REDIS_URL is set, the
in-memory dict when it is not — the same shape SCAN_TOKENS already used) makes the poll
replica-independent, which is the only thing affinity was buying.

What it does NOT do, and must not be described as doing: the work still runs as a thread on one
replica and is still lost if that replica restarts. A durable queue exists as an answer to that,
but it is NOT the default in practice: the frontend's actual default is queuedScan=false
("session-scoped is the pilot default", App.jsx) and the switch to opt into it was deliberately
removed from the UI (ScanReviewModal.jsx) — so the thread-based path below is effectively the
only one reachable today. See test_job_staleness below for what that implies: a dead replica has
to be detectable from here, because there is no other path most scans take.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


class _FakePipeline:
    """Queues commands and executes them atomically (in this fake, sequentially)."""

    def __init__(self, redis):
        self._r = redis
        self._cmds = []

    def delete(self, k):                   self._cmds.append(('del', k)); return self
    def hset(self, k, mapping=None):       self._cmds.append(('hset', k, mapping)); return self
    def hincrby(self, k, f, n):            self._cmds.append(('hincrby', k, f, n)); return self
    def expire(self, k, s):                return self  # TTL not modelled

    def execute(self):
        for cmd in self._cmds:
            if cmd[0] == 'del':      self._r.delete(cmd[1])
            elif cmd[0] == 'hset':   self._r.hset(cmd[1], mapping=cmd[2])
            elif cmd[0] == 'hincrby': self._r.hincrby(cmd[1], cmd[2], cmd[3])
        return [None] * len(self._cmds)


class FakeRedis:
    """Shared backing store — the thing two replicas have in common and a dict does not.
    Stores hashes as {key: {field: json_str}} to mirror the HSET-based core.set_job/update_job.
    Also stores plain string keys (scan_to_job:, scantok:) used by the mapping helpers."""

    def __init__(self):
        self.kv: dict[str, dict[str, str]] = {}   # key → {field: json_encoded_value}
        self.string_kv: dict[str, str] = {}        # key → plain string value
        self.sets = 0

    # ── Hash operations (current interface) ──────────────────────────────────

    def hset(self, k, mapping=None):
        if k not in self.kv:
            self.kv[k] = {}
        if mapping:
            self.kv[k].update(mapping)
        self.sets += 1

    def hgetall(self, k):
        return self.kv.get(k, {})

    def hincrby(self, k, field, amount):
        import json as _j
        if k not in self.kv:
            self.kv[k] = {}
        cur = int(self.kv[k].get(field, "0"))
        self.kv[k][field] = str(cur + amount)
        return cur + amount

    def expire(self, k, seconds): pass

    def delete(self, k):
        self.kv.pop(k, None)
        self.string_kv.pop(k, None)

    def pipeline(self):
        return _FakePipeline(self)

    # ── String operations (scan_to_job: mapping and backward-compat fallback) ─

    def get(self, k):
        return self.string_kv.get(k)

    def set(self, k, v, ex=None):
        self.string_kv[k] = v


@pytest.fixture()
def two_replicas(monkeypatch):
    """One shared Redis, and a JOBS dict that is cleared to prove nothing leans on it."""
    import core
    fake = FakeRedis()
    monkeypatch.setattr(core, "_get_redis", lambda: fake)
    monkeypatch.setattr(core, "JOBS", {})
    return core, fake


def test_a_replica_that_never_saw_the_scan_can_serve_the_poll(two_replicas):
    core, fake = two_replicas
    core.set_job("j1", {"phase": "queued", "files_found": 0, "done": False})
    core.update_job("j1", {"phase": "scanning", "files_found": 258})

    # The poll lands elsewhere: that replica's in-memory dict is empty.
    core.JOBS.clear()
    got = core.get_job_state("j1")
    assert got is not None, "a second replica could not answer the poll — affinity is still required"
    assert got["files_found"] == 258
    assert got["phase"] == "scanning"


def test_a_partial_progress_update_does_not_drop_earlier_keys(two_replicas):
    """run_scan's progress callback sends partial dicts. A field-wise write would lose keys and
    show the poller a scan that went backwards."""
    core, _ = two_replicas
    core.set_job("j2", {"phase": "queued", "files_found": 0, "scan_id": None, "source": "drive"})
    core.update_job("j2", {"files_found": 12})
    s = core.get_job_state("j2")
    assert s["files_found"] == 12
    assert s["source"] == "drive", "an unrelated key was dropped by the merge"
    assert "scan_id" in s


def test_completion_is_visible_to_the_polling_replica(two_replicas):
    core, _ = two_replicas
    core.set_job("j3", {"phase": "queued", "files_found": 0, "done": False, "scan_id": None})
    core.update_job("j3", {"files_found": 40})
    core.update_job("j3", {"phase": "done", "done": True, "scan_id": "s-abc"})
    core.JOBS.clear()
    s = core.get_job_state("j3")
    assert s["done"] is True and s["scan_id"] == "s-abc"


def test_an_unknown_job_is_none_not_an_empty_dict(two_replicas):
    """The route turns None into a 404. An empty dict would render as a scan stuck at 0%."""
    core, _ = two_replicas
    assert core.get_job_state("nope") is None


def test_it_falls_back_to_memory_with_no_redis(monkeypatch):
    """Local dev and the test suite have no REDIS_URL; behaviour there must be unchanged."""
    import core
    monkeypatch.setattr(core, "_get_redis", lambda: None)
    monkeypatch.setattr(core, "JOBS", {})
    core.set_job("j4", {"phase": "queued", "files_found": 0})
    core.update_job("j4", {"files_found": 7})
    assert core.get_job_state("j4")["files_found"] == 7
    assert core.JOBS["j4"]["files_found"] == 7


def test_a_broken_redis_degrades_to_memory_instead_of_failing_the_scan(monkeypatch):
    """A Redis blip must not take a running scan's progress with it. Degrading to this replica's
    memory is strictly better than raising into the progress callback."""
    import core

    class _BrokenPipeline:
        def delete(self, *a): return self
        def hset(self, *a, **k): return self
        def hincrby(self, *a): return self
        def expire(self, *a): return self
        def execute(self): raise RuntimeError("connection reset")

    class Broken:
        def pipeline(self): return _BrokenPipeline()
        def hgetall(self, *a): raise RuntimeError("connection reset")
        def get(self, *a): raise RuntimeError("connection reset")

    monkeypatch.setattr(core, "_get_redis", lambda: Broken())
    monkeypatch.setattr(core, "JOBS", {})
    core.set_job("j5", {"phase": "queued", "files_found": 0})
    core.update_job("j5", {"files_found": 3})
    assert core.get_job_state("j5")["files_found"] == 3


def test_a_redis_blip_repairs_the_complete_shared_record_on_the_next_update(monkeypatch):
    """One failed patch must not leave every other replica with permanently stale fields."""
    import core

    fake = FakeRedis()
    calls = 0

    class _FailsOnce(_FakePipeline):
        def execute(self):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("connection reset")
            return super().execute()

    fake.pipeline = lambda: _FailsOnce(fake)
    monkeypatch.setattr(core, "_get_redis", lambda: fake)
    monkeypatch.setattr(core, "JOBS", {})
    monkeypatch.setattr(core, "_JOB_REDIS_DIRTY", set())

    core.set_job("j-repair", {"phase": "queued", "files_found": 0, "source": "drive"})
    core.update_job("j-repair", {"files_found": 9})       # Redis write fails
    core.update_job("j-repair", {"phase": "scanning"})   # full repair succeeds

    core.JOBS.clear()                                      # poll on another replica
    repaired = core.get_job_state("j-repair")
    assert repaired["phase"] == "scanning"
    assert repaired["files_found"] == 9
    assert repaired["source"] == "drive"


def test_a_coalesced_field_is_included_in_the_next_immediate_flush(two_replicas, monkeypatch):
    """Coalescing delays a patch; it must not silently discard fields absent from the next one."""
    import time as _t

    core, _ = two_replicas
    core.set_job("j-coalesced", {"phase": "queued", "files_found": 0, "done": False})
    monkeypatch.setattr(core, "_JOB_COALESCE_SECONDS", 9999.0)
    core._JOB_LAST_REDIS_WRITE["j-coalesced"] = _t.monotonic()
    core.update_job("j-coalesced", {"files_found": 17})          # local mirror only
    core.update_job("j-coalesced", {"phase": "scanning"})       # forces full repair

    core.JOBS.clear()
    shared = core.get_job_state("j-coalesced")
    assert shared["phase"] == "scanning"
    assert shared["files_found"] == 17


def test_the_route_reads_through_the_helper_not_the_dict(two_replicas):
    """Guards the actual regression: reverting the route to core.JOBS.get would pass every test
    above while quietly reinstating the affinity requirement."""
    src = (Path(__file__).resolve().parent.parent / "api" / "routes" / "scans.py").read_text()
    body = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "core.get_job_state(job_id)" in body
    assert "core.JOBS.get(" not in body
    assert "core.JOBS[job_id]" not in body


# ── Staleness (2026-08-21 live incident: a scan interrupted by a redeploy sat at
#    phase="queued" forever, no error, no timeout — Assess correctly reported 0 eligible
#    documents because there was, and would always be, no scan to be eligible under) ──────────

def _age_iso(seconds_ago):
    import datetime as _dt
    return (_dt.datetime.now(_dt.timezone.utc) -
            _dt.timedelta(seconds=seconds_ago)).isoformat()


def test_set_job_and_update_job_always_stamp_updated_at(two_replicas):
    core, _ = two_replicas
    core.set_job("j6", {"phase": "queued"})
    assert core.get_job_state("j6")["updated_at"]
    core.update_job("j6", {"phase": "scanning"})
    assert core.get_job_state("j6")["updated_at"]


def test_a_freshly_written_unfinished_job_is_not_stale(two_replicas):
    core, _ = two_replicas
    core.set_job("j7", {"phase": "queued", "done": False, "scan_id": None})
    got = core.get_job_state("j7")
    assert got["phase"] == "queued" and got["done"] is False, (
        "a job written moments ago must read back as-is, not pre-emptively failed"
    )


def test_an_unfinished_job_with_no_recent_liveness_signal_reads_as_failed(two_replicas, monkeypatch):
    core, fake = two_replicas
    monkeypatch.setattr(core, "_JOB_STALE_SECONDS", 90)
    core.set_job("j8", {"phase": "queued", "done": False, "scan_id": None, "files_found": 0})
    # Simulate the replica having died: back-date updated_at past the threshold, as if the last
    # write (the initial set_job) happened long ago and nothing has touched it since.
    # Hash storage: each field is json-encoded; patch the field directly.
    import json as _j
    fake.kv["job:j8"]["updated_at"] = _j.dumps(_age_iso(200))

    got = core.get_job_state("j8")
    assert got["done"] is True and got["phase"] == "error"
    assert "restart" in got["error"] or "interrupted" in got["error"]
    # Other fields survive the read-time rewrite — the caller can still see what it knew.
    assert got["files_found"] == 0


def test_a_job_with_no_updated_at_at_all_is_treated_as_stale_not_exempt(two_replicas):
    """A job written before this instrumentation existed (or whose replica died before its first
    heartbeat) has no updated_at. That must fail the staleness check, not skip it — exempting a
    missing timestamp would leave the exact live incident this exists for undetected forever."""
    core, fake = two_replicas
    core.JOBS["j9"] = {"phase": "queued", "done": False, "scan_id": None}  # bypass set_job
    got = core.get_job_state("j9")
    assert got["done"] is True and got["phase"] == "error"


def test_staleness_is_computed_at_read_time_and_never_persisted(two_replicas, monkeypatch):
    """The decorated error state must not be written back — every replica has to compute it fresh
    from the same shared record, or replicas could disagree about whether a job is dead."""
    core, fake = two_replicas
    monkeypatch.setattr(core, "_JOB_STALE_SECONDS", 90)
    core.set_job("j10", {"phase": "queued", "done": False})
    import json as _j
    fake.kv["job:j10"]["updated_at"] = _j.dumps(_age_iso(200))

    core.get_job_state("j10")
    # Still stored as a hash; decode each field to verify no mutation.
    still_raw = {k: _j.loads(v) for k, v in fake.kv["job:j10"].items()}
    assert still_raw["phase"] == "queued" and still_raw.get("done") is False, (
        "get_job_state must not mutate the stored record — staleness is a read-time judgment"
    )


def test_a_completed_job_is_never_reported_stale_regardless_of_age(two_replicas, monkeypatch):
    core, fake = two_replicas
    monkeypatch.setattr(core, "_JOB_STALE_SECONDS", 90)
    core.set_job("j11", {"phase": "done", "done": True, "scan_id": "s-old"})
    import json as _j
    fake.kv["job:j11"]["updated_at"] = _j.dumps(_age_iso(999999))

    got = core.get_job_state("j11")
    assert got["done"] is True and got["phase"] == "done" and got["scan_id"] == "s-old"


def test_a_retrying_job_is_never_reported_stale_within_the_max_backoff_window(two_replicas, monkeypatch):
    """PRD Discover-card §16.8: worker.py's on_retry hook writes phase='retrying' when a job is
    requeued after a transient failure, then goes quiet — no heartbeat, because nothing is
    running while a job sits out its backoff. Rate-limit backoff alone can run up to 600s, well
    past the normal 90s staleness window, so phase=='retrying' needs the same exemption 'done'
    already gets — otherwise a job legitimately waiting to retry would flip to a false
    phase:'error' done:true mid-backoff, exactly the dishonest-progress bug this module exists
    to avoid elsewhere."""
    core, fake = two_replicas
    monkeypatch.setattr(core, "_JOB_STALE_SECONDS", 90)
    core.set_job("j-retry", {"phase": "retrying", "done": False, "attempt": 2, "max_attempts": 5,
                             "last_error": "429 rate limit exceeded"})
    import json as _j
    fake.kv["job:j-retry"]["updated_at"] = _j.dumps(_age_iso(500))   # past 90s, within 600s cap

    got = core.get_job_state("j-retry")
    assert got["phase"] == "retrying" and got["done"] is False
    assert got["attempt"] == 2 and got["max_attempts"] == 5
    assert got["last_error"] == "429 rate limit exceeded"


def test_an_existing_error_message_is_not_overwritten_by_the_generic_one(two_replicas, monkeypatch):
    """A job that failed with a specific message (e.g. from the except Exception clause in
    routes/scans.py's work()) keeps that message even if it also happens to be old — done=True
    already exempts it from staleness, but this pins the precedence explicitly."""
    core, fake = two_replicas
    core.set_job("j12", {"phase": "error", "done": True, "error": "PermissionError: token expired"})
    got = core.get_job_state("j12")
    assert got["error"] == "PermissionError: token expired"


# ── scan_id → job_id mapping (for scan-based SSE endpoint) ───────────────────────────────────

def test_scan_id_mapping_written_when_set_job_includes_scan_id(two_replicas):
    """When set_job is called with a scan_id (durable queue path: the worker knows the scan_id
    from the start), get_job_id_for_scan must resolve immediately."""
    core, _ = two_replicas
    core.set_job("j-map1", {"phase": "claimed", "done": False, "scan_id": "s-xyz"})
    assert core.get_job_id_for_scan("s-xyz") == "j-map1"


def test_scan_id_mapping_written_when_update_job_introduces_scan_id(two_replicas):
    """Thread path: set_job is called with scan_id=None; the scan_id is only known after the
    discover completes and update_job is called. The mapping must be written at that point."""
    core, _ = two_replicas
    core.set_job("j-map2", {"phase": "queued", "done": False, "scan_id": None})
    assert core.get_job_id_for_scan("s-thread") is None
    core.update_job("j-map2", {"phase": "done", "done": True, "scan_id": "s-thread"})
    assert core.get_job_id_for_scan("s-thread") == "j-map2"


def test_scan_id_mapping_survives_coalesce_suppression(two_replicas, monkeypatch):
    """Even when the coalesce window suppresses the main job-state Redis write, the
    scan_to_job mapping must still be written — otherwise the scan-based SSE stream
    can never find the job."""
    import time as _t
    core, _ = two_replicas
    core.set_job("j-map3", {"phase": "queued", "done": False, "scan_id": None})
    # Force the coalesce window to be very long so the next update is suppressed.
    monkeypatch.setattr(core, "_JOB_COALESCE_SECONDS", 9999.0)
    # Touch the clock so the coalesce guard thinks a recent write just happened.
    core._JOB_LAST_REDIS_WRITE["j-map3"] = _t.monotonic()
    # This update carries scan_id — the mapping must be written even though the coalesce
    # window would suppress the job-state write.
    core.update_job("j-map3", {"scan_id": "s-coalesce"})
    assert core.get_job_id_for_scan("s-coalesce") == "j-map3"


def test_unknown_scan_id_returns_none(two_replicas):
    core, _ = two_replicas
    assert core.get_job_id_for_scan("s-never-seen") is None
