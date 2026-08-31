"""A folder is counted once, however many times its job runs.

THE DEFECT. `_scan_folder` ends by calling `increment_completed_folders(scan_id)` and enqueuing
scan_finalize once `done >= total`. The increment was tied to the CALL, not to the folder, so a
folder job that ran twice counted twice. Two ordinary ways for that to happen, neither exotic and
neither leaving a trace:

  * the worker dies (or its lease expires) AFTER the increment and BEFORE the job row reaches
    'done'. reclaim_stuck_jobs requeues it, a worker re-lists the same folder, increment runs again.
  * the `enqueue_job("scan_finalize", …)` immediately after the increment raises. The job fails,
    retries, and increments again on the next attempt.

WHY THE OVERSHOOT IS NOT THE DAMAGE. `completed_folders > total_folders` looks like a cosmetic
counter bug and reads like one in the code. It is not. With two folders and one counted twice,
`done >= total` becomes true while the OTHER folder is still queued — so `_scan_folder`'s own
trigger enqueues scan_finalize, and `rescue_unfinalized_scans` agrees with it, and the run
finalizes over an estate it never finished reading and reports that as complete. The failure is a
silent wrong answer in the direction of claiming MORE coverage than was actually read, which is
the same class of failure as #1104's unreadable folder and the opposite of a visible one.

This is also why CLAMPING the counter at total_folders is not a fix and is not offered as one: in
the two-folder case above, clamping 2 to 2 changes nothing at all — `done >= total` still holds,
finalize still fires, the estate is still partial. Clamping bounds the number without touching the
harm. Deduplicating per folder is what makes `completed_folders` mean "folders done" rather than
"times the increment ran", and only that answers the question the finalize trigger asks.

Written to fail on unchanged code. test_a_reclaimed_folder_job_does_not_count_its_folder_twice is
the probe: before the fix it reported completed_folders == 2 of 2 with folder B still queued, and
a scan_finalize already enqueued behind it.
"""
from __future__ import annotations

import ast
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "folders-once.db")
    return store_mod.Store()


def _progress(st, scan_id: str) -> tuple:
    """(completed_folders, total_folders) read straight from the row the trigger reads."""
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "SELECT completed_folders, total_folders FROM scan_runs WHERE id=%s", (scan_id,))
        row = st._db.fetchone(cur)
    return (row.get("completed_folders"), row.get("total_folders"))


def _queued(st, scan_id: str, job_type: str) -> int:
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "SELECT COUNT(*) AS n FROM jobs WHERE scan_id=%s AND type=%s AND status='queued'",
            (scan_id, job_type))
        return st._db.fetchone(cur)["n"]


def _fan_out(st, sid: str, folders: list[str]):
    """A per-folder scan exactly as scan_discover emits one: total set, one job per folder."""
    st.init_scan_run(sid, "drive", 0, "2026-08-31T00:00:00Z", "test-rubric", "hash",
                     owner="demo@example.com", status="running")
    st.set_total_folders(sid, len(folders))
    return {f: st.enqueue_job("scan_folder", {"scan_id": sid, "folder_id": f, "source": "drive"},
                              scan_id=sid) for f in folders}


def _hold_back(st, job_id: str) -> None:
    """Park a queued job beyond claim_job's `run_after <= now` filter.

    Not a contrivance to force an ordering — it IS the scenario. The defect only matters while
    another folder is still outstanding, so the test needs folder B demonstrably not started when
    folder A runs its second time, and claim ordering between two ready jobs would otherwise
    decide that by accident.
    """
    with st._db.cursor() as cur:
        st._db.execute(cur, "UPDATE jobs SET run_after=%s WHERE id=%s", ("2099-01-01T00:00:00Z",
                                                                         job_id))


@pytest.fixture()
def folder_worker(st, monkeypatch):
    """A real JobWorker running the real _scan_folder handler, with only the Drive calls stubbed.

    Deliberately drives the handler rather than calling the store method directly: the claim that
    matters is about the scan_folder JOB running twice, and a test that only called
    increment_completed_folders twice would prove the store method idempotent while saying nothing
    about whether the handler passes a folder_id at all.
    """
    import core
    import handlers
    import worker

    monkeypatch.setattr(core, "store", st)
    monkeypatch.setattr(st, "get_ai_enabled", lambda: True)
    core.register_scan_tokens("s-once", drive="tok")
    core.register_scan_tokens("s-retry", drive="tok")

    listed: list[str] = []

    def _fake_list(source, folder_id, toks):
        listed.append(folder_id)
        return [{"name": f"{folder_id}-doc.pdf", "id": f"{folder_id}-1"}]

    monkeypatch.setattr(handlers, "_list_folder_files", _fake_list)
    monkeypatch.setattr(handlers, "_process_scan_folder_item",
                        lambda scan_id, item, **kw: None)
    return worker.JobWorker(st, worker_id="w-once"), listed


def test_a_reclaimed_folder_job_does_not_count_its_folder_twice(st, folder_worker, monkeypatch):
    """The headline case, end to end. Folder A runs, increments, and its worker dies before the
    job row reaches 'done'. The sweeper requeues it and it runs again — while folder B has not
    started. The scan must NOT be finalizable on the strength of folder A alone."""
    w, listed = folder_worker
    jobs = _fan_out(st, "s-once", ["fA", "fB"])
    _hold_back(st, jobs["fB"])

    # The crash: complete_job never lands for the FIRST run, so the row stays 'running' with the
    # increment already done. That is exactly what a worker killed between the two looks like to
    # everyone else. Scoped to one call rather than undone later, so the Drive stubs this fixture
    # installed stay in place for the second run.
    real_complete, crashed = st.complete_job, []

    def _complete(*a, **k):
        if not crashed:
            crashed.append(1)
            return "stale"
        return real_complete(*a, **k)

    monkeypatch.setattr(st, "complete_job", _complete)
    assert w.run_once() is True
    assert crashed == [1]
    assert listed == ["fA"]
    assert _progress(st, "s-once") == (1, 2)

    # The sweeper reclaims the lease and folder A becomes claimable again.
    assert st.reclaim_stuck_jobs(lease_seconds=0) == 1
    assert st.get_job(jobs["fA"])["status"] == "queued"

    assert w.run_once() is True
    assert listed == ["fA", "fA"], "the second run must really have re-processed folder A"

    done, total = _progress(st, "s-once")
    assert (done, total) == (1, 2), (
        f"folder A was counted {done} times over {total} folders — the finalize trigger reads "
        f"this as the whole estate being done")
    assert st.get_job(jobs["fB"])["status"] == "queued", "folder B has not been scanned"
    assert _queued(st, "s-once", "scan_finalize") == 0, (
        "the scan was finalized while folder B was still outstanding — it would report a partial "
        "estate as a complete one")


def test_a_folder_that_succeeded_then_dead_lettered_is_counted_once(st, folder_worker,
                                                                    monkeypatch):
    """The two counting paths must not both count the same folder.

    store._record_dead_scan_folder (#1104) advances this counter for a folder job that dies, so a
    dead-letter cannot wedge the run. Its docstring guards against over-counting by ORDERING —
    call it only once the terminal UPDATE has won — which correctly suppresses a zombie worker's
    refused dead-letter. It cannot reach this case: folder A increments on its success path, dies
    before its row reaches 'done', is requeued, and then exhausts its retries. Both calls are
    legitimate, neither is a loser to suppress, and the folder gets counted twice — finalizing the
    scan while folder B has not been read.

    Ordering cannot decide this; naming the folder can.
    """
    from conftest import held

    w, listed = folder_worker
    jobs = _fan_out(st, "s-dead", ["fA", "fB"])
    _hold_back(st, jobs["fB"])

    real_complete, crashed = st.complete_job, []

    def _complete(*a, **k):
        if not crashed:
            crashed.append(1)
            return "stale"
        return real_complete(*a, **k)

    monkeypatch.setattr(st, "complete_job", _complete)
    assert w.run_once() is True                      # counted folder A, then "crashed"
    assert _progress(st, "s-dead") == (1, 2)

    assert st.reclaim_stuck_jobs(lease_seconds=0) == 1
    again = st.claim_job("w-dead")
    assert again["id"] == jobs["fA"]
    assert st.fail_job(again["id"], "drive 500", force_dead=True,
                       **held(st, again["id"])) == "dead"

    done, total = _progress(st, "s-dead")
    assert (done, total) == (1, 2), (
        f"folder A was counted {done} times — once on its success path and again when it "
        f"dead-lettered")
    assert st.get_job(jobs["fB"])["status"] == "queued"
    assert _queued(st, "s-dead", "scan_finalize") == 0, (
        "the scan was finalized while folder B had not been read")


def test_a_retry_after_the_finalize_enqueue_fails_does_not_count_twice(st, folder_worker,
                                                                      monkeypatch):
    """The second path: the increment succeeds, then the enqueue right after it raises. The job
    fails and retries, and the retry must not count the folder again."""
    w, listed = folder_worker
    _fan_out(st, "s-retry", ["fA"])

    real_enqueue = st.enqueue_job
    blown = []

    def _enqueue(job_type, payload=None, **kw):
        if job_type == "scan_finalize" and not blown:
            blown.append(1)
            raise RuntimeError("queue write failed")
        return real_enqueue(job_type, payload, **kw)

    monkeypatch.setattr(st, "enqueue_job", _enqueue)

    assert w.run_once() is True          # increments, then the finalize enqueue blows up
    assert blown == [1]
    assert _progress(st, "s-retry") == (1, 1)

    # The job is queued again for retry. Let it through this time.
    st.reclaim_stuck_jobs(lease_seconds=0)
    with st._db.cursor() as cur:
        st._db.execute(cur, "UPDATE jobs SET run_after=%s WHERE scan_id=%s",
                       ("2000-01-01T00:00:00Z", "s-retry"))
    assert w.run_once() is True
    assert listed == ["fA", "fA"]

    done, total = _progress(st, "s-retry")
    assert done == 1, f"the retry counted folder A a second time ({done} of {total})"
    assert done <= total


def test_a_second_fan_out_over_the_same_scan_can_still_count_its_folders(st):
    """set_total_folders clears the claims along with the counter.

    The bite check on the fix's own failure mode. Deduplication that outlived the counter it
    explains would turn a re-fan-out into a permanent wedge — every folder already claimed, so
    every increment a no-op and completed_folders stuck at 0 — which is a worse bug than the one
    being fixed. Reverting the DELETE in set_total_folders reddens this and nothing else.
    """
    _fan_out(st, "s-again", ["fA", "fB"])
    assert st.increment_completed_folders("s-again", "fA") == (1, 2)
    assert st.increment_completed_folders("s-again", "fB") == (2, 2)

    st.set_total_folders("s-again", 2)
    assert _progress(st, "s-again") == (0, 2)
    assert st.increment_completed_folders("s-again", "fA") == (1, 2)
    assert st.increment_completed_folders("s-again", "fB") == (2, 2)


def test_a_repeat_call_still_reports_the_truth(st):
    """A repeat does not advance the counter, but must still return live numbers — a caller
    re-running after a reclaim is entitled to act on a genuine done >= total."""
    _fan_out(st, "s-truth", ["fA"])
    assert st.increment_completed_folders("s-truth", "fA") == (1, 1)
    assert st.increment_completed_folders("s-truth", "fA") == (1, 1)


def test_different_scans_do_not_share_a_folders_claim(st):
    """The claim is keyed on (scan_id, folder_id). Two scans over the same Drive folder are
    ordinary — a re-scan of the same estate is the common case — and one must never consume the
    other's count."""
    _fan_out(st, "s-one", ["shared"])
    _fan_out(st, "s-two", ["shared"])
    assert st.increment_completed_folders("s-one", "shared") == (1, 1)
    assert st.increment_completed_folders("s-two", "shared") == (1, 1)


def test_the_claim_is_decided_by_the_database(st):
    """The mechanic the fix rests on, asserted rather than assumed: after INSERT … ON CONFLICT DO
    NOTHING, rowcount is 1 for the insert that happened and 0 for the one that did not.

    Checked directly because the whole fix reduces to trusting that number. If a future engine or
    driver reported 1 for a suppressed insert, every test above would still pass — they would
    simply be exercising a first call — while production silently double-counted again. The
    PostgreSQL half of the same claim is in tests/test_pg_job_queue.py; neither engine's answer is
    taken as evidence for the other's.
    """
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "INSERT INTO scan_folder_completions(scan_id, folder_id, counted_at) "
            "VALUES (%s,%s,%s) ON CONFLICT(scan_id, folder_id) DO NOTHING", ("s", "f", "t0"))
        assert getattr(cur, "rowcount", 0) == 1
        st._db.execute(cur,
            "INSERT INTO scan_folder_completions(scan_id, folder_id, counted_at) "
            "VALUES (%s,%s,%s) ON CONFLICT(scan_id, folder_id) DO NOTHING", ("s", "f", "t1"))
        assert getattr(cur, "rowcount", 1) == 0, (
            "a suppressed insert reported a row — the counter would advance twice for one folder")
        st._db.execute(cur,
            "SELECT COUNT(*) AS n FROM scan_folder_completions WHERE scan_id=%s", ("s",))
        assert st._db.fetchone(cur)["n"] == 1
    assert sqlite3.sqlite_version_info >= (3, 24), "ON CONFLICT needs SQLite 3.24+"


def test_every_folder_counter_caller_names_its_folder():
    """No production caller may increment without saying WHICH folder it counted.

    `folder_id` is optional on the store method — a caller that cannot name a folder has nothing
    to deduplicate on, and inventing a key for it would be worse than counting twice — so nothing
    in the signature stops a new call site from omitting it and silently reintroducing the
    premature finalize. This is that stop. It reads the call sites rather than the behaviour,
    because the behaviour of the omission is indistinguishable from correct until an estate
    finalizes early in production.

    If this fails on a call you are adding: pass the folder id the job payload already carries
    (`payload["folder_id"]`), rather than relaxing the test.
    """
    offenders = []
    for path in sorted((ACP / "api").rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if name != "increment_completed_folders":
                continue
            named = any(k.arg == "folder_id" for k in node.keywords)
            if len(node.args) < 2 and not named:
                offenders.append(f"{path.relative_to(ACP)}:{node.lineno}")
    assert not offenders, (
        "these call increment_completed_folders without a folder_id, so a rerun of the same "
        f"folder counts twice and can finalize the scan early: {offenders}")
