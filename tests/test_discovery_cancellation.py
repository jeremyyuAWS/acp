"""Discovery must actually stop when a scan is cancelled — and say so honestly.

#1079 made check_cancel() CAPABLE of firing on the discovery threads. It added no checkpoints, so
the listing walk still had none: a Stop pressed during discovery did nothing at all until the walk
finished on its own. This adds them, and closes the four places that were swallowing the result.

THREE STATES, and the whole point is that they are different:

  requested  jobs.cancel_requested_at is set. A user pressed Stop. Work is still running.
  observed   some thread's check_cancel() raised. THIS work knows. Siblings may still be in
             flight and the pool may still hold queued tasks.
  stopped    no task belonging to this job can still run or write — the discovery pool has been
             shut down with cancel_futures (queued tasks dropped) and joined (running ones
             finished) — and nothing was persisted after the observation.

Reporting "stopped" at the moment of "observed" is the lie this file exists to prevent, so
test_no_folder_fetch_is_still_running_or_queued_once_it_raises is the load-bearing one.

THE FOUR SWALLOWS, each a different wrong answer:

  scanner._search_folder BFS      `except Exception` per folder recorded cancellation as
                                  "listing failed, skipping subtree" and CARRIED ON to the next
                                  folder. Cancellation was not merely mis-reported here, it was
                                  ineffective — the walk completed.
  handlers._listing_progress      `except Exception` ("a diagnostic must never fail the scan")
                                  logged a Stop travelling through a progress tick at DEBUG and
                                  discarded it.
  handlers._scan_discover _list   `except Exception` set scan_runs.status='failed' and emitted
                                  scan.failed/'listing_failed' — the one outcome the user asked
                                  for, reported as a fault, and counted in dead-letter stats.
  handlers._scan_discover retry   the suspicious-zero path sleeps 5s and re-runs the ENTIRE
                                  listing, and its `except Exception` had no re-raise at all — a
                                  Stop there was dropped and the run went on to record an empty
                                  estate as fact.

NOT the complete cancellation story. This covers the discovery LISTING walk. Per-document
analysis fan-out already had its own checkpoints (handlers.py:1342/1345).
"""
from __future__ import annotations

import ast
import sys
import tempfile
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import scanner  # noqa: E402
import worker as worker_mod  # noqa: E402

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
FOLDER = "application/vnd.google-apps.folder"


def _doc(fid, name="doc.docx"):
    return {"id": fid, "name": name, "mimeType": DOCX}


def _folder(fid, name="subfolder"):
    return {"id": fid, "name": name, "mimeType": FOLDER}


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "disco.db")
    return store_mod.Store()


# ── a Drive fake that records what was actually asked for ─────────────────────────────────────

class _Req:
    def __init__(self, drive, fid, page_token):
        self.d, self.fid, self.page_token = drive, fid, page_token

    def execute(self, num_retries=0):
        d = self.d
        with d.lock:
            d.requests.append((self.fid, self.page_token))
            d.in_flight += 1
            d.max_in_flight = max(d.max_in_flight, d.in_flight)
        try:
            if d.on_request:
                d.on_request(d, self.fid, self.page_token)
            pages = d.pages.get(self.fid)
            if pages is not None:                       # a paginated folder
                idx = 0 if self.page_token is None else int(self.page_token)
                out = {"files": pages[idx]}
                if idx + 1 < len(pages):
                    out["nextPageToken"] = str(idx + 1)
                return out
            return {"files": d.children.get(self.fid, [])}
        finally:
            with d.lock:
                d.in_flight -= 1


class _Files:
    def __init__(self, drive):
        self.d = drive

    def list(self, **kw):
        q = kw.get("q", "")
        fid = q.split("'")[1] if q.startswith("'") else None
        return _Req(self.d, fid, kw.get("pageToken"))


class FakeDrive:
    """Records every (folder, page) actually requested, and tracks concurrency.

    `on_request` fires INSIDE execute(), which is how a test cancels part-way through a real
    parallel walk rather than before it starts.
    """

    def __init__(self, children=None, pages=None, on_request=None):
        self.children = children or {}
        self.pages = pages or {}
        self.on_request = on_request
        self.requests: list[tuple] = []
        self.lock = threading.Lock()
        self.in_flight = 0
        self.max_in_flight = 0

    def files(self):
        return _Files(self)

    def folders_listed(self):
        return {fid for fid, _ in self.requests}


def _run_in_worker_turn(st, body):
    """Run `body(job)` inside a real worker turn, so check_cancel() is installed exactly as it is
    in production. Returns (job_id, raised_exception_or_None).

    Deliberately goes through JobWorker.run_once rather than installing the ContextVar by hand:
    the hook's installation, its propagation to the pool threads (#1079) and the worker's
    JobCancelledError handling are all part of what these tests are about.
    """
    caught = {}

    def _handler(payload, job):
        try:
            body(job)
        except BaseException as e:
            caught["exc"] = e
            raise

    worker_mod.HANDLERS["t_discover"] = _handler
    try:
        jid = st.enqueue_job("t_discover", {})
        worker_mod.JobWorker(st, worker_id="worker-A").run_once()
    finally:
        worker_mod.HANDLERS.pop("t_discover", None)
    return jid, caught.get("exc")


# ── 1. between PAGE requests ──────────────────────────────────────────────────────────────────

def test_cancellation_between_pages_stops_before_the_next_request(st):
    """A folder with thousands of files is many sequential round-trips. Before this, the only
    cancellation opportunity in the whole walk was between whole FOLDERS, so a Stop during one
    large folder waited for every remaining page of it."""
    pages = {"root": [[_doc(f"f{i}")] for i in range(5)]}

    def on_request(d, fid, token):
        if token == "1":                       # cancel while serving the SECOND page
            st.request_job_cancellation(d.job_id)

    drive = FakeDrive(pages=pages, on_request=on_request)

    def body(job):
        drive.job_id = job["id"]
        scanner._search_folder(drive, "root", max_files=1000)

    jid, exc = _run_in_worker_turn(st, body)

    assert isinstance(exc, worker_mod.JobCancelledError), f"listing did not stop: {exc!r}"
    tokens = [t for _, t in drive.requests]
    assert tokens == [None, "1"], (
        f"pages requested after cancellation: {tokens} — the checkpoint must sit before the "
        "request, so a stopped scan stops spending Drive quota immediately")
    assert st.get_job(jid)["status"] == "cancelled"


# ── 2. during the PARALLEL folder walk ────────────────────────────────────────────────────────

def _wide_tree(n=60):
    return {"root": [_folder(f"F{i}") for i in range(n)],
            **{f"F{i}": [_doc(f"f{i}")] for i in range(n)}}


def test_cancellation_during_parallel_listing_is_not_a_skipped_subtree(st):
    """THE defect. The per-folder `except Exception` caught JobCancelledError, printed
    "listing failed, skipping subtree", recorded the folder as failed and moved to the next —
    so a Stop was absorbed one folder at a time and the walk ran to completion."""
    drive = FakeDrive(children=_wide_tree())

    def on_request(d, fid, token):
        if fid == "root":
            return
        with d.lock:
            n = len([1 for f, _ in d.requests if f != "root"])
        if n >= 3:
            st.request_job_cancellation(d.job_id)

    drive.on_request = on_request

    def body(job):
        drive.job_id = job["id"]
        scanner._search_folder(drive, "root", max_files=10_000)

    jid, exc = _run_in_worker_turn(st, body)

    assert isinstance(exc, worker_mod.JobCancelledError), (
        f"the walk absorbed the cancellation and returned {exc!r} — a Stop during discovery "
        "must not read as one inaccessible folder")
    listed = len(drive.folders_listed() - {"root"})
    assert listed < 60, (
        f"all {listed} folders were listed despite cancellation — the walk did not stop")
    assert st.get_job(jid)["status"] == "cancelled"


def test_nothing_is_still_running_when_discovery_reports_stopped(st):
    """`stopped` means no task can still run or write. Note what this does NOT prove: the `with`
    block's own shutdown(wait=True) would satisfy it too. It is the invariant, not the argument
    for cancel_futures — that is the next test, and it took a bite check to tell them apart.

    THE PARALLELISM IS ARRANGED, NOT HOPED FOR, and that is a repair rather than a decoration.

    This test used to cancel on the FIRST non-root request and then assert, at the end, that at
    least two folder fetches had been in flight at once. Those two things fight each other:
    cancelling on the first child request is exactly what stops the siblings, because every task
    that has not already entered execute() hits `_cancel_checkpoint()` and raises before its
    Drive call. Whether a second thread got in first was a pure race that the test itself
    started.

    Measured on this machine it resolved to 2, 4, 5 or 6 across every condition tried — the test
    alone, the whole file, CI's exact `-n auto --dist loadfile --splits 4 --group 2` invocation,
    every core saturated, and pinned to a single core. On a GitHub runner it resolved to 1, and
    the `max_in_flight > 1` guard failed the shard (#1190's CI, 2026-09-02) on a PR that touches
    nothing in this file. The guard was right: on that run the test genuinely had not exercised
    the parallel path.

    So the fixture now HOLDS the first few child requests inside execute() on a barrier until
    that many are concurrently in flight, and only then requests cancellation. The assertion
    below is unchanged and is now satisfied by construction rather than by scheduling luck — and
    the test is strictly stronger for it, because cancellation provably arrives with siblings
    genuinely mid-flight, which is the situation the drain exists to handle.
    """
    drive = FakeDrive(children=_wide_tree())

    # Two is all the assertion needs; three exercises the drain a little harder without getting
    # close to the pool width. Capped at the real pool so a deployment that narrowed
    # ACP_DISCOVERY_WORKERS cannot deadlock this on a barrier that can never fill.
    want = min(3, scanner._DISCOVERY_WORKERS)
    assert want > 1, (
        f"ACP_DISCOVERY_WORKERS={scanner._DISCOVERY_WORKERS} — the discovery pool is serial, so "
        f"there is no parallel path for this test to exercise")
    # Timeout, not a bare wait: a barrier that never fills must fail with THIS message rather
    # than hang the suite until the job times out and someone reads a traceback about nothing.
    gate = threading.Barrier(want, timeout=10)

    def on_request(d, fid, token):
        if fid == "root":
            return
        try:
            # Every arriving child blocks here, INSIDE execute(), so `in_flight` is already
            # incremented for each of them — which is what makes max_in_flight reach `want`.
            gate.wait()
        except threading.BrokenBarrierError:
            return                      # timed out or already broken; the assertions below judge
        st.request_job_cancellation(d.job_id)

    drive.on_request = on_request

    def body(job):
        drive.job_id = job["id"]
        scanner._search_folder(drive, "root", max_files=10_000)

    try:
        _run_in_worker_turn(st, body)
    finally:
        # A later arrival must never block on a barrier the walk has finished with; aborting it
        # makes every subsequent wait() raise immediately instead of waiting out the timeout.
        gate.abort()

    with drive.lock:
        assert drive.in_flight == 0, (
            f"{drive.in_flight} folder fetches were still running when discovery reported "
            "stopped — a task that is still running can still write")
    settled = len(drive.requests)
    threading.Event().wait(0.25)          # give any surviving queued task time to show itself
    assert len(drive.requests) == settled, (
        f"{len(drive.requests) - settled} more Drive requests arrived AFTER discovery raised")
    assert drive.max_in_flight >= want, (
        f"only {drive.max_in_flight} folder fetch(es) were ever concurrent, not {want} — the "
        f"barrier did not hold them, so this run never exercised the parallel path and proves "
        f"nothing about draining it")


def test_the_drain_stops_a_burst_of_cancellation_checks(st):
    """What cancel_futures ACTUALLY buys, measured rather than asserted.

    The first version of this file justified the drain as "otherwise a cancelled scan keeps
    listing folders". That is false: a queued task that starts after cancellation hits
    _cancel_checkpoint() before its Drive call and raises. Deleting the drain left every other
    test in this file green — a bite check that did not bite, which is a finding about the claim.

    The real cost is DATABASE reads, and it lands at the worst moment. check_cancel() reads
    jobs.cancel_requested_at, so every queued task that runs far enough to reach its checkpoint
    issues one query. On a wide tree that is one per remaining folder, all fired while the user
    is pressing Stop and reloading the queue view. cancel_futures drops them unstarted.

    Measured on this 60-folder tree: 61 checks without the drain, 9 with it. The threshold is
    deliberately loose — the point is the order of magnitude, not the exact scheduling.
    """
    calls = {"n": 0}
    real = st.is_job_cancelled

    def counting(job_id):
        calls["n"] += 1
        return real(job_id)

    st.is_job_cancelled = counting
    drive = FakeDrive(children=_wide_tree(60))

    def on_request(d, fid, token):
        if fid != "root":
            st.request_job_cancellation(d.job_id)

    drive.on_request = on_request

    def body(job):
        drive.job_id = job["id"]
        scanner._search_folder(drive, "root", max_files=10_000)

    _run_in_worker_turn(st, body)

    assert calls["n"] < 30, (
        f"{calls['n']} cancellation-check queries were issued for a 60-folder tree — the queued "
        "folder tasks were not cancelled, so each one woke up, queried the database and only "
        "then stopped. That burst arrives exactly when the user has pressed Stop.")


def test_nothing_partial_is_returned_to_be_persisted(st):
    """Cancellation must RAISE, never return a short list. A partial return is indistinguishable
    from a small estate, and the caller would persist it as the discovered set."""
    drive = FakeDrive(children=_wide_tree())
    out = {}

    def on_request(d, fid, token):
        if fid != "root":
            st.request_job_cancellation(d.job_id)

    drive.on_request = on_request

    def body(job):
        drive.job_id = job["id"]
        out["result"] = scanner._search_folder(drive, "root", max_files=10_000)

    _run_in_worker_turn(st, body)

    assert "result" not in out, (
        f"discovery returned {len(out.get('result', []))} files instead of raising — a truncated "
        "listing would be persisted as the complete one")


# ── 3. the progress callback must not swallow it ──────────────────────────────────────────────

def test_a_cancellation_raised_through_the_progress_callback_propagates(st):
    """progress_cb runs on the BFS thread. If a checkpoint there is swallowed, the Stop is lost
    on the exact path the UI is watching."""
    drive = FakeDrive(children=_wide_tree(4))
    seen = {"ticks": 0}

    def progress_cb(count, folders=None, active=None, recent=None):
        seen["ticks"] += 1
        raise worker_mod.JobCancelledError("stopped inside a progress tick")

    def body(job):
        scanner._search_folder(drive, "root", max_files=10_000, progress_cb=progress_cb)

    _, exc = _run_in_worker_turn(st, body)

    assert seen["ticks"] >= 1, "the callback never ran, so this asserts nothing"
    assert isinstance(exc, worker_mod.JobCancelledError), (
        f"a cancellation raised through progress_cb was swallowed, got {exc!r}")


# ── 4. it must not be converted into a retry ──────────────────────────────────────────────────

def test_cancellation_does_not_consume_an_attempt_or_requeue(st):
    """Cancellation is not an error. Converted to one it would burn a retry and re-run the very
    listing the user stopped — and eventually dead-letter, which is how a Stop ends up in the
    dead-letter breakdown as a Drive failure."""
    drive = FakeDrive(children=_wide_tree(8))

    def on_request(d, fid, token):
        if fid != "root":
            st.request_job_cancellation(d.job_id)

    drive.on_request = on_request

    def body(job):
        drive.job_id = job["id"]
        scanner._search_folder(drive, "root", max_files=10_000)

    jid, _ = _run_in_worker_turn(st, body)

    row = st.get_job(jid)
    assert row["status"] == "cancelled", f"recorded as {row['status']!r}, not cancelled"
    assert row["status"] != "queued", "the job was requeued — cancellation was retried"
    assert row["last_error"] in (None, ""), (
        f"cancellation left an error on the row ({row['last_error']!r}) — it will read as a "
        "failure in the dead-letter breakdown")


# ── 5. an ordinary listing failure must STILL be a skipped subtree ────────────────────────────

def test_an_ordinary_folder_error_still_only_skips_that_subtree(st):
    """The control. Narrowing the blanket handler must not turn a genuinely inaccessible folder
    into an aborted scan — that per-folder tolerance is deliberate and load-bearing."""
    tree = _wide_tree(4)

    def on_request(d, fid, token):
        if fid == "F1":
            raise RuntimeError("403 insufficient permissions")

    drive = FakeDrive(children=tree, on_request=on_request)
    result = scanner._search_folder(drive, "root", max_files=10_000)

    ids = {r["id"] for r in result}
    assert ids == {"f0", "f2", "f3"}, (
        f"one inaccessible folder aborted the walk instead of skipping its subtree: {ids}")


# ── 6. structural: a blanket handler over cancellable work must declare its stance ────────────

def test_no_blanket_handler_over_cancellable_work_omits_a_cancellation_clause():
    """The behavioural tests can only cover today's call sites. Every swallow this change fixed
    looked correct in review — each had a comment explaining why catching everything was right,
    and each was right about the case its author had in mind and wrong about cancellation.

    So: any `try` in the scan path whose body calls something that can raise JobCancelledError
    (_list, _search_folder, check_cancel, _cancel_checkpoint, or a progress callback) and which
    handles bare Exception/BaseException must name JobCancelledError FIRST. Ordering matters —
    a clause after `except Exception` is dead code.
    """
    root = Path(__file__).resolve().parent.parent / "api"
    RAISERS = ("_list", "_search_folder", "check_cancel", "_cancel_checkpoint", "progress_cb")
    offenders = []

    for mod in ("handlers.py", "scanner.py"):
        tree = ast.parse((root / mod).read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            called = {
                n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
                for n in ast.walk(ast.Module(body=node.body, type_ignores=[]))
                if isinstance(n, ast.Call)
            }
            if not (called & set(RAISERS)):
                continue
            names = []
            for h in node.handlers:
                t = h.type
                names.append(t.id if isinstance(t, ast.Name) else
                             getattr(t, "attr", None) if t is not None else "bare")
            if "Exception" in names or "BaseException" in names or "bare" in names:
                blanket = min(i for i, n in enumerate(names)
                              if n in ("Exception", "BaseException", "bare"))
                if "JobCancelledError" not in names[:blanket]:
                    offenders.append(f"{mod}:{node.lineno}: handlers={names}")

    assert not offenders, (
        "a blanket handler sits over work that can raise JobCancelledError without saying what "
        "it does with a cancellation — which is how a Stop becomes a skipped subtree, a DEBUG "
        "log line, or a failed scan:\n  " + "\n  ".join(offenders))
