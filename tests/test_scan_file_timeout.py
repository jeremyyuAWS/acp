"""Per-file wall-clock safety net (handlers._analyse_and_persist_one).

One document must never be able to hold its worker forever — a step that slips its own timeout,
a retry loop, or a future analyser added without one would stall the whole scan at "0 of N" with
a small worker pool. The wrapper caps each file at ACP_SCAN_FILE_TIMEOUT_S: past the cap it
records the file as an error and returns, so the worker frees and the scan finalizes. These pin
that behaviour without touching the real download/analyse work."""
from __future__ import annotations

import sys
import time
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import handlers  # noqa: E402


class _FakeStore:
    def __init__(self):
        self.saved = []
        self.decisions = []

    def save_file_result(self, scan_id, fdict, now):
        self.saved.append(fdict)

    def log_decision(self, *a, **k):
        self.decisions.append((a, k))


@pytest.fixture()
def store(monkeypatch):
    s = _FakeStore()
    monkeypatch.setattr(handlers.core, "store", s)
    return s


def _call(**over):
    kw = dict(scan_id="s1", item={"file": "big.pptx", "drive_file_id": "d1"}, source="sharepoint",
              pii=False, svc=None, toks={}, now="2026-08-20T00:00:00Z", _lf=None, user="u@x")
    kw.update(over)
    handlers._analyse_and_persist_one("s1" if False else kw["scan_id"], kw["item"], kw["source"],
                                      kw["pii"], kw["svc"], kw["toks"], kw["now"], kw["_lf"],
                                      user=kw["user"])


def test_a_file_over_the_cap_is_recorded_as_error_and_returns(store, monkeypatch):
    monkeypatch.setenv("ACP_SCAN_FILE_TIMEOUT_S", "1")
    started = threading.Event()

    def _slow(*a, **k):
        started.set()
        time.sleep(5)                       # far past the 1s cap

    monkeypatch.setattr(handlers, "_analyse_and_persist_one_impl", _slow)
    t0 = time.monotonic()
    _call()
    elapsed = time.monotonic() - t0
    assert started.is_set()
    assert elapsed < 3                       # returned near the cap, did NOT wait out the 5s work
    assert len(store.saved) == 1
    rec = store.saved[0]
    assert rec["file"] == "big.pptx" and rec["status"] == "error" and rec["score"] is None
    assert store.decisions and store.decisions[0][1].get("file") == "big.pptx"


def test_a_fast_file_runs_the_real_work_and_records_no_timeout_error(store, monkeypatch):
    monkeypatch.setenv("ACP_SCAN_FILE_TIMEOUT_S", "5")
    calls = []
    monkeypatch.setattr(handlers, "_analyse_and_persist_one_impl", lambda *a, **k: calls.append(a))
    _call()
    assert len(calls) == 1                   # the real work ran
    assert store.saved == []                 # the wrapper wrote no error row (impl owns the real save)


def test_cap_zero_disables_the_watchdog(store, monkeypatch):
    monkeypatch.setenv("ACP_SCAN_FILE_TIMEOUT_S", "0")
    ran = []
    monkeypatch.setattr(handlers, "_analyse_and_persist_one_impl", lambda *a, **k: ran.append(True))
    _call()
    assert ran == [True] and store.saved == []


def test_impl_errors_still_propagate(store, monkeypatch):
    monkeypatch.setenv("ACP_SCAN_FILE_TIMEOUT_S", "5")

    def _boom(*a, **k):
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(handlers, "_analyse_and_persist_one_impl", _boom)
    with pytest.raises(RuntimeError, match="engine exploded"):
        _call()
