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
replica and is still lost if that replica restarts. The durable queue is the answer to that, and
is already the default.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


class FakeRedis:
    """Shared backing store — the thing two replicas have in common and a dict does not."""

    def __init__(self):
        self.kv: dict[str, str] = {}
        self.sets = 0

    def set(self, k, v, ex=None):
        self.kv[k] = v
        self.sets += 1

    def get(self, k):
        return self.kv.get(k)

    def delete(self, k):
        self.kv.pop(k, None)


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

    class Broken:
        def set(self, *a, **k): raise RuntimeError("connection reset")
        def get(self, *a, **k): raise RuntimeError("connection reset")

    monkeypatch.setattr(core, "_get_redis", lambda: Broken())
    monkeypatch.setattr(core, "JOBS", {})
    core.set_job("j5", {"phase": "queued", "files_found": 0})
    core.update_job("j5", {"files_found": 3})
    assert core.get_job_state("j5")["files_found"] == 3


def test_the_route_reads_through_the_helper_not_the_dict(two_replicas):
    """Guards the actual regression: reverting the route to core.JOBS.get would pass every test
    above while quietly reinstating the affinity requirement."""
    src = (Path(__file__).resolve().parent.parent / "api" / "routes" / "scans.py").read_text()
    body = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "core.get_job_state(job_id)" in body
    assert "core.JOBS.get(" not in body
    assert "core.JOBS[job_id]" not in body
