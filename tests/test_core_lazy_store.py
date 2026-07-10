"""core.store must be built on first USE, never at import.

Store() opens (and creates) the database in its constructor. While core.py did
`store = Store()` at module level, merely importing core touched the disk — a CLI script, a
pytest collection pass, a tool reading the route table — and froze whatever store._SQLITE_PATH
said at that instant into core.store for the life of the process. Anything that repointed the
path afterwards was silently talking to a different database than core held.

The import-time check runs in a SUBPROCESS: by the time this module executes, sibling tests
have long since imported core, so an in-process `import core` would prove nothing.
"""
from __future__ import annotations
import subprocess
import sys
import tempfile
import types
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


@pytest.fixture()
def unbuilt_core():
    """core with its `store` global removed, restored exactly as found afterwards.

    Forcing the unbuilt state means publishing a new singleton into core's globals — which
    would outlive this test and hand every later one a Store pointed at this test's temp file.
    That is precisely the leak these tests exist to prevent, so undo it here rather than
    trusting monkeypatch (which records nothing when the attribute was merely lazy).
    """
    import core
    had = "store" in vars(core)
    prev = vars(core).get("store")
    vars(core).pop("store", None)
    try:
        yield core
    finally:
        vars(core).pop("store", None)
        if had:
            core.store = prev


def _run(body: str) -> str:
    """Execute `body` in a fresh interpreter with api/ importable, returning its stdout.

    Store.__init__ is stubbed out before core is imported, so a REGRESSION cannot create a
    real database (least of all the developer's <repo>/acp.db) on its way to failing.
    """
    prelude = (
        "import sys; sys.path.insert(0, %r)\n"
        "import store as _s\n"
        "_built = []\n"
        "_s.Store.__init__ = lambda self: _built.append(1)\n"
    ) % str(ACP / "api")
    r = subprocess.run([sys.executable, "-c", prelude + body],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"subprocess failed:\n{r.stdout}\n{r.stderr}"
    return r.stdout.strip()


def test_importing_core_constructs_no_store():
    out = _run("import core\n"
               "print('BUILT' if _built else 'LAZY')\n"
               "print('PUBLISHED' if 'store' in vars(core) else 'ABSENT')\n")
    assert out.splitlines() == ["LAZY", "ABSENT"]


def test_importing_core_creates_no_database_file():
    # The default path is <repo>/acp.db — the developer's real data. Importing must not make it.
    out = _run("import pathlib, store as s\n"
               "p = pathlib.Path(s._SQLITE_PATH)\n"
               "before = p.exists()\n"
               "import core\n"
               "print('SAME' if p.exists() == before else 'CREATED')\n")
    assert out == "SAME"


def test_store_attribute_and_get_store_are_one_lazy_singleton(unbuilt_core, monkeypatch):
    core = unbuilt_core
    import store as store_mod

    tmp = Path(tempfile.mkdtemp()) / "lazy.db"
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", tmp)

    assert "store" not in vars(core)              # nothing built yet
    st = core.store                               # PEP 562 __getattr__ builds it here
    assert core.get_store() is st                 # …and both names resolve to it
    assert core.store is st                       # …now a plain module global
    assert str(st._db._path) == str(tmp)          # honoured the path set AFTER import


def test_core_internals_honour_a_monkeypatched_store(monkeypatch):
    """`monkeypatch.setattr(core, "store", fake)` must reach core's OWN callers.

    finalize_scan and the scheduled scan live in core.py and used the bare `store` global. If
    get_store() read a private slot instead of the module attribute, they would quietly keep
    using the real database while the test believed it had swapped it out.
    """
    import core

    calls = []
    fake = types.SimpleNamespace(mark_finalized=lambda sid: calls.append(sid) or False)
    monkeypatch.setattr(core, "store", fake)

    assert core.get_store() is fake
    core.finalize_scan("scan-1", False, "local")   # internal caller → get_store() → fake
    assert calls == ["scan-1"], "core.finalize_scan bypassed the patched store"


def test_get_store_builds_exactly_once_under_concurrent_first_access(unbuilt_core, monkeypatch):
    import threading
    core = unbuilt_core
    import store as store_mod

    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "race.db")

    built = []
    real_init = store_mod.Store.__init__

    def slow_init(self):
        import time
        time.sleep(0.02)          # widen the window a naive `if store is None` would lose
        built.append(1)
        real_init(self)

    monkeypatch.setattr(store_mod.Store, "__init__", slow_init)

    got, barrier = [], threading.Barrier(12)
    def go():
        barrier.wait()
        got.append(core.get_store())
    threads = [threading.Thread(target=go) for _ in range(12)]
    for t in threads: t.start()
    for t in threads: t.join()

    assert len(built) == 1, f"Store constructed {len(built)} times under a race"
    assert len({id(s) for s in got}) == 1


def test_core_does_not_arm_the_scheduler_at_import():
    """reload_scheduler() reads the schedule from the database. Calling it at import would
    rebuild the very Store this module keeps lazy — and would arm a scheduled scan inside any
    process that merely imports core (a job worker, a script). app.py arms it at startup."""
    out = _run("import core\n"
               "print('ARMED' if core.scheduler.get_jobs() else 'IDLE')\n"
               "print('BUILT' if _built else 'LAZY')\n")
    assert out.splitlines() == ["IDLE", "LAZY"]


def test_core_does_not_start_a_scheduler_thread_at_import():
    """scheduler.start() used to run at module level, so every pytest process and every CLI
    script that imported core was running an APScheduler thread. app.py starts it at startup
    and stops it on shutdown."""
    out = _run("import threading\n"
               "_before = threading.active_count()\n"
               "import core\n"
               "print('SPAWNED' if threading.active_count() > _before else 'NO_THREAD')\n"
               "print('RUNNING' if core.scheduler.running else 'STOPPED')\n")
    assert out.splitlines() == ["NO_THREAD", "STOPPED"]


def test_start_scheduler_is_idempotent_and_stop_is_safe():
    import core
    assert core.stop_scheduler() is None          # never started: a no-op, not an error
    try:
        assert core.start_scheduler() is True     # this call started it
        assert core.scheduler.running
        assert core.start_scheduler() is False    # already running → no second thread
    finally:
        core.stop_scheduler()
    assert not core.scheduler.running
    core.stop_scheduler()                         # stopping twice is safe


def test_reload_scheduler_arms_a_stopped_scheduler(monkeypatch):
    """The load-bearing assumption behind starting the scheduler *after* arming it: APScheduler
    holds jobs added before start() as pending, and get_job() (routes/system.py) finds them."""
    import core

    monkeypatch.setattr(core, "store", types.SimpleNamespace(
        get_schedule=lambda: {"enabled": True, "interval_minutes": 15}))
    assert not core.scheduler.running
    try:
        core.reload_scheduler()
        assert len(core.scheduler.get_jobs()) == 1
        assert core.scheduler.get_job("scheduled_local_scan") is not None
    finally:
        core.scheduler.remove_all_jobs()
    assert not core.scheduler.running             # arming must not have started it
