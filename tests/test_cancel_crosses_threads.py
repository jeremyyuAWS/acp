"""check_cancel() must fire on the threads that actually do the work.

THE DEFECT. The cancel hook lived in a `threading.local()`, installed on the thread that claimed
the job. `check_cancel()` read it with `getattr(_cancel_local, "check", None)` and returned
silently when absent — so on any other thread it was a NO-OP that looked exactly like "not
cancelled".

Every parallel path in the scan pipeline is another thread:

    scanner.py:915    ThreadPoolExecutor(_DISCOVERY_WORKERS)   folder listing
    scanner.py:3837   ThreadPoolExecutor(_SCAN_WORKERS)        per-document analysis
    handlers.py:2767  ThreadPoolExecutor(min(workers, ...))    scan_batch fan-out
    handlers.py:2303  threading.Thread(_work)                  per-file, inside the above

So a checkpoint added to any of those would have compiled, read correctly, passed a test written
on the main thread, and done nothing in production. That is the shape this file exists to make
impossible: the first test asserts cancellation fires on a POOL thread, and would pass trivially
if it only ever ran on the claiming one.

THE FIX is a ContextVar rather than a thread-local. ContextVars do not cross a thread start
either — but joblog.bind() already carries the calling context over exactly those hops (added in
#1068 for the diagnostics), and copy_context() carries EVERY var, not just logging's. So
cancellation now propagates wherever job identity does, and the two cannot drift apart.

Cancellation of the DISCOVERY LISTING WALK is not addressed here: that path still contains no
checkpoints at all. This makes checkpoints capable of working; it does not add them.
"""
from __future__ import annotations

import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "cancel.db")
    return store_mod.Store()


def test_check_cancel_fires_on_a_POOL_thread(st):
    """The whole point. Under the thread-local this returned None on the pool thread and the
    handler ran to completion as though nothing had been cancelled."""
    import worker as worker_mod

    outcome = {}

    def handler(payload, job):
        st.request_job_cancellation(job["id"])                      # flagged while the handler runs
        with ThreadPoolExecutor(max_workers=2) as ex:
            def work():
                try:
                    worker_mod.check_cancel()
                    outcome["fired"] = False          # reached => no-op => the defect
                except worker_mod.JobCancelledError:
                    outcome["fired"] = True
                    raise
            # bind() carries this context across the thread start — the same helper the
            # diagnostics use, and the reason cancellation and job identity stay together.
            import joblog
            ex.submit(joblog.bind(work)).result()      # .result() re-raises on this thread

    worker_mod.HANDLERS["t_pool"] = handler
    try:
        st.enqueue_job("t_pool", {})
        worker_mod.JobWorker(st, worker_id="worker-A").run_once()
    finally:
        worker_mod.HANDLERS.pop("t_pool", None)

    assert outcome.get("fired") is True, (
        "check_cancel() did not raise on the pool thread — a checkpoint there cannot stop "
        "anything, which is how every parallel path stayed uncancellable")


def test_check_cancel_still_fires_on_the_claiming_thread(st):
    """The invariant: the path that already worked must keep working. Passes before AND after."""
    import worker as worker_mod
    outcome = {}

    def handler(payload, job):
        st.request_job_cancellation(job["id"])
        try:
            worker_mod.check_cancel()
            outcome["fired"] = False
        except worker_mod.JobCancelledError:
            outcome["fired"] = True
            raise

    worker_mod.HANDLERS["t_main"] = handler
    try:
        jid = st.enqueue_job("t_main", {})
        worker_mod.JobWorker(st, worker_id="worker-A").run_once()
    finally:
        worker_mod.HANDLERS.pop("t_main", None)

    assert outcome.get("fired") is True
    assert st.get_job(jid)["status"] == "cancelled"


def test_an_UNBOUND_thread_still_does_not_inherit(st):
    """The negative control, so the need for bind() is measured rather than asserted. If a bare
    thread ever did inherit, bind() would be unnecessary and this fails to say so."""
    import worker as worker_mod
    seen = {}

    def handler(payload, job):
        st.request_job_cancellation(job["id"])

        def work():
            try:
                worker_mod.check_cancel()
                seen["fired"] = False
            except worker_mod.JobCancelledError:
                seen["fired"] = True

        t = threading.Thread(target=work)             # NOT bound
        t.start(); t.join()

    worker_mod.HANDLERS["t_unbound"] = handler
    try:
        st.enqueue_job("t_unbound", {})
        worker_mod.JobWorker(st, worker_id="worker-A").run_once()
    finally:
        worker_mod.HANDLERS.pop("t_unbound", None)

    assert seen.get("fired") is False, (
        "a bare thread inherited the context — if that ever becomes true, bind() at the fan-out "
        "sites is redundant and this test should be deleted along with it")


def test_the_hook_does_not_leak_after_the_turn(st):
    """Outside a worker turn check_cancel() must be a no-op, or every test and script that
    imports it starts raising."""
    import worker as worker_mod

    worker_mod.HANDLERS["t_leak"] = lambda p, j: None
    try:
        st.enqueue_job("t_leak", {})
        worker_mod.JobWorker(st, worker_id="worker-A").run_once()
    finally:
        worker_mod.HANDLERS.pop("t_leak", None)

    worker_mod.check_cancel()                          # must not raise


def test_a_cancelled_job_is_recorded_as_cancelled_not_failed(st):
    """Cancellation is not an error path: it must not consume a retry or dead-letter."""
    import worker as worker_mod

    def handler(payload, job):
        st.request_job_cancellation(job["id"])
        worker_mod.check_cancel()

    worker_mod.HANDLERS["t_status"] = handler
    try:
        jid = st.enqueue_job("t_status", {})
        worker_mod.JobWorker(st, worker_id="worker-A").run_once()
    finally:
        worker_mod.HANDLERS.pop("t_status", None)

    assert st.get_job(jid)["status"] == "cancelled"


# ── the REAL production fan-out boundaries ────────────────────────────────────────────────────
# Everything above uses a ThreadPoolExecutor this file constructs. That proves the mechanism and
# proves nothing about the three places the pipeline actually crosses a thread, which is where
# the defect lived.

def test_cancellation_crosses_the_REAL_per_file_thread(st, monkeypatch):
    """handlers._analyse_and_persist_one spawns threading.Thread(target=joblog.bind(_work)) at
    handlers.py:2307 — the innermost hop, and the one furthest from run_once. The heavy work
    (_impl) is stubbed, so this is about the boundary rather than about Drive."""
    import worker as worker_mod
    import handlers as handlers_mod

    seen = {}

    def fake_impl(*a, **kw):
        try:
            worker_mod.check_cancel()
            seen["fired"] = False
        except worker_mod.JobCancelledError:
            seen["fired"] = True
            raise

    monkeypatch.setattr(handlers_mod, "_analyse_and_persist_one_impl", fake_impl)

    def handler(payload, job):
        st.request_job_cancellation(job["id"])
        handlers_mod._analyse_and_persist_one(
            "scan-1", {"file": "a.docx"}, "drive", False, None, None, None, None)

    worker_mod.HANDLERS["t_realthread"] = handler
    try:
        st.enqueue_job("t_realthread", {})
        worker_mod.JobWorker(st, worker_id="worker-A").run_once()
    finally:
        worker_mod.HANDLERS.pop("t_realthread", None)

    assert seen.get("fired") is True, (
        "the per-file Thread did not inherit the cancel hook — this is the hop every document "
        "crosses on its way to the native parsers")


def test_every_job_path_thread_start_is_bound():
    """A structural guard, because the behavioural tests can only cover the sites that exist
    today. A fourth fan-out added without joblog.bind() would be silently uncancellable again
    and would look correct in review — which is exactly how the first three came to be.

    Reads the source rather than the runtime: every `threading.Thread(target=...)` and every
    `.submit(` / `.map(` in the two scan modules must name bind() in the same call."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "api"
    offenders = []
    for mod in ("handlers.py", "scanner.py"):
        for n, line in enumerate((root / mod).read_text().splitlines(), 1):
            if re.search(r"threading\.Thread\(\s*target=", line) or re.search(r"\.(submit|map)\(", line):
                if "bind(" not in line:
                    offenders.append(f"{mod}:{n}: {line.strip()}")

    assert not offenders, (
        "a thread start in the scan path does not carry the calling context, so check_cancel() "
        "and the job diagnostics are both blind there:\n  " + "\n  ".join(offenders))


# ── one job's cancellation must not reach another ─────────────────────────────────────────────

def test_the_hook_does_not_leak_from_one_job_to_the_next(st):
    """Job A is cancelled; job B is not. B must not inherit A's hook — a ContextVar set without
    being reset by token would do exactly that, and B would abort for a reason belonging to
    someone else's job."""
    import worker as worker_mod
    outcome = {}

    def cancelled_handler(payload, job):
        st.request_job_cancellation(job["id"])
        worker_mod.check_cancel()

    def clean_handler(payload, job):
        try:
            worker_mod.check_cancel()
            outcome["b_survived"] = True
        except worker_mod.JobCancelledError:
            outcome["b_survived"] = False
            raise

    worker_mod.HANDLERS["t_a"] = cancelled_handler
    worker_mod.HANDLERS["t_b"] = clean_handler
    try:
        a = st.enqueue_job("t_a", {})
        w = worker_mod.JobWorker(st, worker_id="worker-A")
        w.run_once()
        assert st.get_job(a)["status"] == "cancelled"

        b = st.enqueue_job("t_b", {})
        w.run_once()
        assert st.get_job(b)["status"] == "done"
    finally:
        worker_mod.HANDLERS.pop("t_a", None)
        worker_mod.HANDLERS.pop("t_b", None)

    assert outcome.get("b_survived") is True, (
        "job B saw job A's cancel hook — the reset is not restoring the previous value")
