"""core._spawn_worker() must wire JobWorker's on_retry hook to core.update_job.

PRD Discover-card §16.8 (Retrying): worker.py deliberately does not import core (see its own
docstring — infrastructure-only), so the "job failed, waiting to retry" signal has to be
dependency-injected in by whoever constructs JobWorker. This test pins THAT wiring, not the
retry-detection logic itself (that's tests/test_jobs.py) or the staleness exemption it depends
on (tests/test_job_state_cross_replica.py) — a worker spawned without this callback would run
correctly but silently drop the retry signal on the floor.
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import core


class _NoOpThread:
    """Stands in for threading.Thread so _spawn_worker doesn't actually start a background
    run_forever() loop in the test process."""
    def __init__(self, *a, **k):
        pass

    def start(self):
        pass


def test_spawn_worker_passes_update_job_as_on_retry(monkeypatch):
    monkeypatch.setattr(core, "_worker_seq", 0, raising=False)
    monkeypatch.setattr(threading, "Thread", _NoOpThread)
    monkeypatch.setattr(core, "get_store", lambda: object())

    captured = {}

    class _SpyJobWorker:
        def __init__(self, store, *, worker_id=None, on_retry=None):
            captured["store"] = store
            captured["worker_id"] = worker_id
            captured["on_retry"] = on_retry

        def run_forever(self):
            pass

    import worker as worker_module
    monkeypatch.setattr(worker_module, "JobWorker", _SpyJobWorker)
    monkeypatch.setattr(core, "_worker_handles", [], raising=False)

    core._spawn_worker()

    assert captured["on_retry"] is core.update_job, (
        "a worker spawned without this callback would run correctly but silently drop the "
        "'retrying' progress signal on the floor — see worker.py's on_retry docstring"
    )
