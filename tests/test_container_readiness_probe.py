"""GET /probe/readyz — the one health route a platform probe may be pointed at.

WHY A THIRD HEALTH ROUTE, given /healthz and /readyz already exist. Neither can be the
rollout gate, for opposite reasons:

  * /healthz touches no dependency, so it answers 200 from a replica that cannot reach the
    database — precisely the replica a gate has to hold traffic away from.
  * /readyz answers for the whole DEPLOYMENT (worker tier, PDF engine). Pointing a probe at
    it would let a worker-tier outage evict the API container, which cannot fix a worker
    tier and loses the API too. Its own docstring says so.

THE WINDOW THIS CLOSES, measured live during the deploy of #1151 against the single-replica
app being swapped revision-for-revision:

    t+20s   /healthz 200 in 0.39s   /readyz 000 after 25s   /config 000 after 25s
    t+40s   /healthz 200 in 0.43s   /readyz 200 in 0.46s    /config 200 in 0.75s

The non-database route was fast throughout while every database-backed route hung for the
whole window, then recovered unaided. Without a probe, ACA admits a replica as soon as its
port accepts TCP, which is why traffic reached one that could not answer a database read.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


class _Store:
    """Just enough Store for the probe: a ping that does what the test asks of it."""

    def __init__(self, raises: Exception | None = None, blocks: threading.Event | None = None):
        self._raises = raises
        self._blocks = blocks
        self.calls = 0

    def ping(self) -> None:
        self.calls += 1
        if self._blocks is not None:
            self._blocks.wait(5)
        if self._raises is not None:
            raise self._raises


class _Res:
    """Stands in for the FastAPI Response the route mutates."""
    status_code = 200


def _probe(monkeypatch, store):
    import core
    from routes import system

    monkeypatch.setattr(core, "store", store, raising=False)
    res = _Res()
    body = system.probe_readyz(res)
    return res.status_code, body


# ── the two answers ───────────────────────────────────────────────────────────────────────
def test_a_reachable_database_is_200_and_ready(monkeypatch):
    code, body = _probe(monkeypatch, _Store())
    assert code == 200
    assert body["ready"] is True
    assert body["checks"]["db"] == "ok"


def test_an_unreachable_database_is_503_not_a_200_carrying_false(monkeypatch):
    """An httpGet probe reads the STATUS CODE and nothing else. A 200 with {"ready": false}
    would admit the replica — the failure this assertion exists to prevent."""
    code, body = _probe(monkeypatch, _Store(raises=OSError("connection refused")))
    assert code == 503
    assert body["ready"] is False
    assert body["checks"]["db"].startswith("db_unreachable")


def test_the_failure_names_the_class_and_never_the_message(monkeypatch):
    """This body is served to an unauthenticated caller. A psycopg2 OperationalError's message
    carries the host, port and user out of the DSN, so only the class name may travel."""
    secret = "could not connect to host=acp-pg.postgres.database.azure.com user=acpadmin"
    code, body = _probe(monkeypatch, _Store(raises=RuntimeError(secret)))
    assert code == 503
    assert body["checks"]["db"] == "db_unreachable: RuntimeError"
    assert "acp-pg" not in str(body) and "acpadmin" not in str(body)


# ── the narrowness IS the feature ─────────────────────────────────────────────────────────
def test_a_dead_worker_tier_and_a_missing_pdf_engine_do_not_make_this_replica_unready(monkeypatch):
    """The whole reason /readyz cannot be the probe target.

    Both faults below flip /readyz's `ready` to false. Neither is this container's doing and
    neither is repaired by restarting it — so a probe that honoured them would evict a healthy
    API over an outage it cannot cure, and lose the API on top of the worker tier.
    """
    import core
    from routes import system

    monkeypatch.setattr(core, "WORKERS", 0, raising=False)
    monkeypatch.setattr(system, "pdf_engine_status",
                        lambda: {"available": False, "path": "/x", "reason": "not importable"})

    class _NoWorkers(_Store):
        def worker_tier_status(self, window_s: int = 120):
            return {"alive": False, "heartbeat_at": None, "age_s": None,
                    "window_s": window_s, "ever_seen": False, "pool_size": None, "version": None}

    store = _NoWorkers()
    monkeypatch.setattr(core, "store", store, raising=False)

    # /readyz says the deployment is degraded, and it is right to.
    assert system.readyz()["ready"] is False

    # The probe says this container can serve, and it is right to.
    res = _Res()
    body = system.probe_readyz(res)
    assert res.status_code == 200 and body["ready"] is True


def test_the_probe_asks_the_database_and_nothing_else(monkeypatch):
    """One round-trip per call — no worker heartbeat read, no engine import."""
    store = _Store()
    code, _ = _probe(monkeypatch, store)
    assert code == 200 and store.calls == 1


# ── it must not eat the threadpool when the database stops answering ──────────────────────
def test_a_second_probe_answers_immediately_while_the_first_is_still_waiting(monkeypatch):
    """The availability regression an unguarded implementation would introduce.

    A sync FastAPI route runs on anyio's bounded worker threadpool (40 by default), and a
    probe fires every few seconds forever. If a hung database parked one pooled thread per
    probe, the threadpool would be gone in minutes and the replica would stop serving
    everything — caused by the route added to detect that the database is unreachable.
    """
    import core

    release = threading.Event()
    store = _Store(blocks=release)
    monkeypatch.setattr(core, "store", store, raising=False)

    from routes import system

    first: dict = {}
    started = threading.Event()

    def _run_first():
        started.set()
        res = _Res()
        first["body"] = system.probe_readyz(res)
        first["code"] = res.status_code

    t = threading.Thread(target=_run_first, daemon=True)
    t.start()
    started.wait(2)
    # Wait for the first call to be genuinely inside ping(), holding the gate.
    for _ in range(200):
        if store.calls:
            break
        threading.Event().wait(0.01)
    assert store.calls == 1

    try:
        res = _Res()
        body = system.probe_readyz(res)
        # Not "unknown": a replica whose outstanding database read has not come back is not ready.
        assert res.status_code == 503
        assert body["checks"]["db"] == "db_check_in_flight"
        # And it did NOT start a second round-trip of its own.
        assert store.calls == 1
    finally:
        # Even on a failed assertion — otherwise the parked thread holds the process-wide gate
        # and every later test in this module reads `db_check_in_flight`, turning one real
        # failure into a cascade that hides which assertion actually broke.
        release.set()
        t.join(5)
    assert first["code"] == 200 and first["body"]["ready"] is True


def test_the_gate_is_released_after_a_failure_so_one_outage_does_not_wedge_the_probe(monkeypatch):
    """If the lock leaked on the error path, the first database failure would pin the route at
    `db_check_in_flight` forever and the replica could never be readmitted."""
    import core
    from routes import system

    monkeypatch.setattr(core, "store", _Store(raises=OSError("down")), raising=False)
    for _ in range(3):
        res = _Res()
        assert system.probe_readyz(res)["checks"]["db"] == "db_unreachable: OSError"

    monkeypatch.setattr(core, "store", _Store(), raising=False)
    res = _Res()
    assert system.probe_readyz(res)["ready"] is True and res.status_code == 200


# ── Store.ping over a real database ───────────────────────────────────────────────────────
def test_ping_round_trips_against_a_real_store(isolated_store):
    """Not a mock: the adapter's own cursor/execute/fetch path, which is what the probe rides."""
    assert isolated_store.ping() is None


def test_ping_raises_when_the_database_is_gone(isolated_store, monkeypatch):
    """A ping that swallowed its error would report every replica ready."""
    import contextlib

    @contextlib.contextmanager
    def _broken():
        raise OSError("connection refused")
        yield  # pragma: no cover

    monkeypatch.setattr(isolated_store._db, "cursor", _broken)
    with pytest.raises(OSError):
        isolated_store.ping()


# ── wiring ────────────────────────────────────────────────────────────────────────────────
def test_the_route_is_registered_and_public(monkeypatch, isolated_store):
    """The platform's probe carries no credential and never will — a gate that needed one
    would fail every replica it was meant to admit."""
    import core
    from fastapi.testclient import TestClient

    from app import app

    assert "/probe/readyz" in {r.path for r in core.enumerate_api_routes(app)}
    assert core.is_public("/probe/readyz") is True

    # Production shape: the GIS gate live, no bypass.
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    client = TestClient(app)

    assert client.get("/scans").status_code == 401          # the gate really is live
    res = client.get("/probe/readyz")
    assert res.status_code == 200, res.text
    assert res.json()["ready"] is True
