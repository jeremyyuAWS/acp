"""A failure in `claim_job` itself (e.g. Postgres out of connections) happens before
run_once's own try block, so every worker thread in the pool is about to hit the same
wall at once. Retrying at the normal poll_interval (0.5s default) turns one exhausted
database into a reconnect storm — N workers per replica, hammering every half second,
which prolongs the outage it's reacting to instead of waiting it out.

`run_forever` must back off further with each consecutive claim failure, and drop back
to the normal poll cadence the moment a poll succeeds again (job found, or genuinely
empty queue) — see the incident this pins: 2026-08-26, acp-worker's `claim_job` calls
started failing with `FATAL: remaining connection slots are reserved for roles with the
SUPERUSER attribute` once Postgres's max_connections was saturated.
"""
from __future__ import annotations
import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


class _FailThenEmptyStore:
    """claim_job raises the first `fail_times` calls, then behaves like an empty queue."""
    def __init__(self, fail_times: int, exc: Exception):
        self.fail_times = fail_times
        self.exc = exc
        self.calls = 0

    def claim_job(self, worker_id):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return None


def _stop_after(n):
    calls = {"i": 0}
    def _stop():
        calls["i"] += 1
        return calls["i"] > n
    return _stop


def test_claim_failures_back_off_and_the_streak_resets_on_success(monkeypatch):
    import worker

    sleeps = []
    monkeypatch.setattr(worker.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(worker.random, "uniform", lambda lo, hi: hi)  # deterministic: no jitter

    store = _FailThenEmptyStore(fail_times=3, exc=RuntimeError("connection slots exhausted"))
    w = worker.JobWorker(store, worker_id="w1", poll_interval=0.5)

    # 3 failing claims, then 1 successful (empty-queue) poll.
    w.run_forever(stop=_stop_after(4))

    assert store.calls == 4
    # Backoff climbs across the failing streak: 2s, 4s, 8s (base=2.0, jitter pinned to max).
    assert sleeps[:3] == [2.0, 4.0, 8.0]
    # The poll right after the streak ends uses the normal short interval — proof the
    # consecutive-error counter reset instead of continuing to climb from an empty queue.
    assert sleeps[3] == 0.5


def test_backoff_is_capped_so_a_long_outage_does_not_stall_recovery(monkeypatch):
    import worker

    sleeps = []
    monkeypatch.setattr(worker.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(worker.random, "uniform", lambda lo, hi: hi)

    store = _FailThenEmptyStore(fail_times=10, exc=RuntimeError("db down"))
    w = worker.JobWorker(store, worker_id="w1")

    w.run_forever(stop=_stop_after(10))

    assert store.calls == 10
    assert max(sleeps) <= 30.0
    # It actually reaches the cap rather than backing off forever below it.
    assert sleeps[-1] == 30.0


def test_a_healthy_worker_keeps_the_short_poll_interval(monkeypatch):
    """No exceptions at all: behaviour for an empty queue must be unchanged."""
    import worker

    sleeps = []
    monkeypatch.setattr(worker.time, "sleep", lambda s: sleeps.append(s))

    store = _FailThenEmptyStore(fail_times=0, exc=RuntimeError("unused"))
    w = worker.JobWorker(store, worker_id="w1", poll_interval=0.5)

    w.run_forever(stop=_stop_after(3))

    assert sleeps == [0.5, 0.5, 0.5]
