"""A dashboard GET burst must not starve mutating requests of every DB connection.

Production symptom (7 September 2026): PUT /hitl/queue returned 503 while simultaneous Live
Operations reads occupied the API replica's Postgres pool. Pool sizing alone cannot provide a
priority guarantee: however large the pool is, enough reads can consume all of it.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import store  # noqa: E402


class _PoolError(Exception):
    pass


class _CapacityPool:
    """The relevant ThreadedConnectionPool behavior: exhaustion raises; it does not wait."""

    def __init__(self, capacity: int):
        self.capacity = capacity
        self.used: set[object] = set()
        self.lock = threading.Lock()

    def getconn(self):
        with self.lock:
            if len(self.used) >= self.capacity:
                raise _PoolError("connection pool exhausted")
            conn = object()
            self.used.add(conn)
            return conn

    def putconn(self, conn):
        with self.lock:
            self.used.remove(conn)


def _adapter(monkeypatch, capacity: int = 3):
    import types

    fake_pool_module = types.ModuleType("psycopg2.pool")
    fake_pool_module.PoolError = _PoolError
    fake_pg = types.ModuleType("psycopg2")
    fake_pg.pool = fake_pool_module
    monkeypatch.setitem(sys.modules, "psycopg2", fake_pg)
    monkeypatch.setitem(sys.modules, "psycopg2.pool", fake_pool_module)

    adapter = store._PgAdapter.__new__(store._PgAdapter)
    adapter._MAX_CONN = capacity
    pool = _CapacityPool(capacity)
    monkeypatch.setattr(adapter, "_get_pool", lambda: pool)
    return adapter


def test_get_burst_leaves_a_physical_connection_for_mutation(monkeypatch):
    """Reads stop at pool-minus-reserve while a PUT-equivalent checkout still succeeds."""
    adapter = _adapter(monkeypatch, capacity=3)

    # Explicit classification is also useful for non-HTTP callers and makes the adapter contract
    # directly testable without manufacturing a FastAPI request.
    reads = [adapter._getconn(timeout=0.4, read_only=True) for _ in range(2)]
    started = threading.Event()
    finished = threading.Event()
    acquired: list[object] = []

    def third_read():
        started.set()
        acquired.append(adapter._getconn(timeout=0.5, read_only=True))
        finished.set()

    thread = threading.Thread(target=third_read)
    thread.start()
    assert started.wait(timeout=0.2)
    assert not finished.wait(timeout=0.1), "a third GET consumed the mutation reserve"

    mutation = adapter._getconn(timeout=0.1, read_only=False)
    assert mutation is not None

    adapter._putconn(mutation)
    adapter._putconn(reads.pop())
    assert finished.wait(timeout=0.3), "a returned read slot did not wake the queued GET"
    thread.join(timeout=0.2)

    adapter._putconn(acquired.pop())
    adapter._putconn(reads.pop())


def test_request_context_defaults_gets_to_read_gate_and_mutations_to_priority(monkeypatch):
    """HTTP middleware needs one request-scoped switch; workers default to mutation priority.

    ContextVar is important here: a module global would let concurrent GET and PUT requests
    overwrite each other's classification in FastAPI's thread pool.
    """
    adapter = _adapter(monkeypatch, capacity=3)
    assert store.DB_READ_REQUEST.get() is False

    token = store.DB_READ_REQUEST.set(True)
    try:
        reads = [adapter._getconn(timeout=0.3) for _ in range(2)]
    finally:
        store.DB_READ_REQUEST.reset(token)

    # No context marker is the safe default for PUT/POST/DELETE and background workers.
    mutation = adapter._getconn(timeout=0.1)
    assert mutation is not None

    adapter._putconn(mutation)
    for conn in reads:
        adapter._putconn(conn)


def test_mutation_reserve_is_bounded_and_never_zero():
    """Protect writes without serializing a read-heavy API."""
    assert 1 <= store._MUTATION_RESERVE_CONN < store._PgAdapter._MAX_CONN
