"""Per-folder/document checkpoint tests (ADR 0004 item 6).

Validates the scan_folder job type, the folder-level fan-out from scan_discover,
mid-scan resume semantics, and the sweeper's rescue path for per-folder scans.

All tests use an isolated SQLite store and stub out Drive/SP API calls so they
run on a clean CI agent without any cloud credentials.
"""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def store(monkeypatch):
    import store as store_mod
    tmp = Path(tempfile.mkdtemp()) / "pfj-test.db"
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", tmp)
    return store_mod.Store()


@pytest.fixture()
def worker_and_store(store, monkeypatch):
    """Return (JobWorker, store) with core.store pointed at the test store."""
    import core
    import worker
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(store, "get_ai_enabled", lambda: True)
    w = worker.JobWorker(store, worker_id="w-pfj")
    return w, store


# ── helpers ─────────────────────────────────────────────────────────────────

def _init_scan(store, scan_id: str, source: str = "drive") -> None:
    """Create the scan_runs row that handlers expect to exist."""
    store.init_scan_run(scan_id, source, 0, "2026-01-01T00:00:00Z",
                        "test-rubric", "abc123", status="running")


def _jobs_by_type(store, scan_id: str) -> dict:
    """Count queued jobs per type for a scan."""
    counts: dict[str, int] = {}
    with store._db.cursor() as cur:
        store._db.execute(cur,
            "SELECT type, COUNT(*) AS n FROM jobs WHERE scan_id=%s AND status='queued' "
            "GROUP BY type", (scan_id,))
        for row in store._db.fetchall(cur):
            counts[row["type"]] = row["n"]
    return counts


def _scan_folder_progress(store, scan_id: str) -> tuple:
    """Return (completed_folders, total_folders) from scan_runs."""
    with store._db.cursor() as cur:
        store._db.execute(cur,
            "SELECT completed_folders, total_folders FROM scan_runs WHERE id=%s", (scan_id,))
        row = store._db.fetchone(cur)
    if not row:
        return (None, None)
    return (row.get("completed_folders"), row.get("total_folders"))


# ── test 1: scan_discover emits N scan_folder jobs ─────────────────────────

def test_discover_emits_scan_folder_jobs(monkeypatch):
    """scan_discover with ACP_PER_FOLDER_SCAN_JOBS=1 fans out to one scan_folder job per folder."""
    import store as store_mod
    import core
    import handlers
    import worker

    tmp = Path(tempfile.mkdtemp()) / "pfj-discover.db"
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", tmp)
    st = store_mod.Store()
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setattr(st, "get_ai_enabled", lambda: True)
    monkeypatch.setenv("ACP_PER_FOLDER_SCAN_JOBS", "1")
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "0")

    sid = "scan-discover-pfj"
    core.register_scan_tokens(sid, drive="dummy-token")

    # Stub out the heavy listing calls.
    FOLDERS = [
        {"folder_id": "fA", "name": "Legal"},
        {"folder_id": "fB", "name": "Finance"},
        {"folder_id": "fC", "name": "HR"},
    ]
    monkeypatch.setattr(handlers, "_list_top_level_folders",
                        lambda source, scope_folder, toks: FOLDERS)

    # _scan_discover also calls _list() and _drive_service(); stub both so no network/auth occurs.
    ITEMS = [
        {"name": "a.pdf", "id": "id-a", "mime": None},
        {"name": "b.docx", "id": "id-b", "mime": None},
        {"name": "c.xlsx", "id": "id-c", "mime": None},
    ]
    import scanner
    monkeypatch.setattr(scanner, "_drive_service", lambda tok: None)
    monkeypatch.setattr(scanner, "_list",
                        lambda *a, **kw: (
                            # _list fills scope_out via the out-arg kwarg; return the items list.
                            (kw.get("scope_out", {}) or {}).update({}),
                            ITEMS
                        )[-1])

    jid = st.enqueue_job("scan_discover",
                         {"source": "drive", "scan_id": sid, "ai": True},
                         scan_id=sid)
    w = worker.JobWorker(st, worker_id="w-discover")
    w.run_once()

    assert st.get_job(jid)["status"] == "done"
    # Three scan_folder jobs should have been queued.
    counts = _jobs_by_type(st, sid)
    assert counts.get("scan_folder", 0) == 3, f"expected 3 scan_folder jobs, got {counts}"
    # total_folders should be recorded on the scan_runs row.
    _, total = _scan_folder_progress(st, sid)
    assert total == 3


# ── test 2: scan_folder processes one folder and calls check_cancel between docs ──

def test_scan_folder_processes_folder_and_calls_check_cancel(monkeypatch):
    """scan_folder lists files in its folder and calls check_cancel() between each document."""
    import store as store_mod
    import core
    import handlers
    import worker

    tmp = Path(tempfile.mkdtemp()) / "pfj-folder.db"
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", tmp)
    st = store_mod.Store()
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setattr(st, "get_ai_enabled", lambda: True)

    sid = "scan-folder-pfj"
    core.register_scan_tokens(sid, drive="tok")
    _init_scan(st, sid)
    st.set_total_folders(sid, 2)  # 2 folders total; this job is folder 1

    FILES = [{"name": "doc1.pdf", "id": "f1"}, {"name": "doc2.docx", "id": "f2"}]
    monkeypatch.setattr(handlers, "_list_folder_files", lambda src, fid, toks: FILES)

    processed = []
    cancel_calls = []

    def _fake_process(scan_id, item, *, source, ai, pii, user, job=None):
        processed.append(item["name"])

    def _fake_check_cancel():
        cancel_calls.append(len(processed))

    monkeypatch.setattr(handlers, "_process_scan_folder_item", _fake_process)
    monkeypatch.setattr("worker.check_cancel", _fake_check_cancel)

    jid = st.enqueue_job("scan_folder",
                         {"scan_id": sid, "folder_id": "fA", "source": "drive"},
                         scan_id=sid)
    w = worker.JobWorker(st, worker_id="w-folder")
    w.run_once()

    assert st.get_job(jid)["status"] == "done"
    assert processed == ["doc1.pdf", "doc2.docx"]
    # check_cancel is called twice per document (before and after), so ≥4 calls total.
    assert len(cancel_calls) >= 4, f"expected ≥4 check_cancel calls, got {len(cancel_calls)}"


# ── test 3: scan_finalize aggregates results and marks scan done ────────────

def test_scan_finalize_marks_scan_done(monkeypatch):
    """scan_finalize updates scan_runs to status='done' after folder jobs complete."""
    import store as store_mod
    import core
    import handlers  # noqa: F401 — registers scan_finalize handler
    import worker

    tmp = Path(tempfile.mkdtemp()) / "pfj-finalize.db"
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", tmp)
    st = store_mod.Store()
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setattr(st, "get_ai_enabled", lambda: True)

    sid = "scan-finalize-pfj"
    core.register_scan_tokens(sid, drive="tok")
    _init_scan(st, sid)

    # Simulate two files already analysed (written by two scan_folder jobs).
    with st._db.cursor() as cur:
        for name in ("a.pdf", "b.docx"):
            st._db.execute(cur,
                "INSERT INTO file_records(scan_id,file,engine,status,score,compliant,skipped_rules) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (sid, name, "python/html", "done", 80, 1, 0))

    jid = st.enqueue_job("scan_finalize",
                         {"scan_id": sid, "source": "drive", "ai": True, "pii": False},
                         scan_id=sid)
    w = worker.JobWorker(st, worker_id="w-finalize")
    w.run_once()

    assert st.get_job(jid)["status"] == "done"
    scan = st.get_scan(sid)
    assert scan is not None
    assert scan["run"]["status"] == "done"
    assert scan["run"]["files"] == 2


# ── test 4: worker crash mid-scan leaves unprocessed folders queued ─────────

def test_worker_crash_leaves_unprocessed_folders_queued(monkeypatch):
    """If a worker crashes after completing folder A, folder B stays queued for another worker."""
    import store as store_mod
    import core
    import handlers
    import worker

    tmp = Path(tempfile.mkdtemp()) / "pfj-crash.db"
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", tmp)
    st = store_mod.Store()
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setattr(st, "get_ai_enabled", lambda: True)

    sid = "scan-crash-pfj"
    core.register_scan_tokens(sid, drive="tok")
    _init_scan(st, sid)
    st.set_total_folders(sid, 2)

    processed = []
    monkeypatch.setattr(handlers, "_list_folder_files",
                        lambda src, fid, toks: [{"name": f"{fid}-file.pdf", "id": fid}])
    monkeypatch.setattr(handlers, "_process_scan_folder_item",
                        lambda scan_id, item, **kw: processed.append(item["name"]))

    # Enqueue two folder jobs.
    jid_a = st.enqueue_job("scan_folder",
                            {"scan_id": sid, "folder_id": "fA", "source": "drive"},
                            scan_id=sid)
    jid_b = st.enqueue_job("scan_folder",
                            {"scan_id": sid, "folder_id": "fB", "source": "drive"},
                            scan_id=sid)

    # Worker processes folder A successfully.
    w = worker.JobWorker(st, worker_id="w-crash")
    assert w.run_once() is True  # claims and runs fA

    assert st.get_job(jid_a)["status"] == "done"
    assert processed == ["fA-file.pdf"]
    # completed_folders should now be 1; scan NOT yet finalized.
    done, total = _scan_folder_progress(st, sid)
    assert done == 1
    assert total == 2

    # Folder B is still queued — a recovered worker can pick it up.
    assert st.get_job(jid_b)["status"] == "queued"

    # Simulate worker crash: folder B's lease expires and is reclaimed.
    st.claim_job("w-crash2")           # claim fB
    assert st.reclaim_stuck_jobs(lease_seconds=0) == 1
    assert st.get_job(jid_b)["status"] == "queued"


# ── test 5: sweeper rescues unfinalized per-folder scans ────────────────────

def test_sweeper_rescues_unfinalized_folder_scan(monkeypatch):
    """rescue_unfinalized_scans re-enqueues scan_finalize when all folder jobs are done
    but the finalize job was lost (e.g. worker crashed between increment and enqueue)."""
    import store as store_mod

    tmp = Path(tempfile.mkdtemp()) / "pfj-rescue.db"
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", tmp)
    st = store_mod.Store()

    sid = "scan-rescue-pfj"
    _init_scan(st, sid)
    st.set_total_folders(sid, 2)

    # Simulate both folders completing (completed_folders = 2) but finalize was not enqueued.
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "UPDATE scan_runs SET completed_folders=2 WHERE id=%s", (sid,))

    # No outstanding jobs → sweeper should detect and rescue.
    rescued = st.rescue_unfinalized_scans()
    assert rescued >= 1

    # scan_finalize should now be queued.
    counts = _jobs_by_type(st, sid)
    assert counts.get("scan_finalize", 0) == 1


# ── test 6: last scan_folder triggers finalize directly ─────────────────────

def test_last_scan_folder_triggers_finalize(monkeypatch):
    """When the last scan_folder job completes (done == total), it enqueues scan_finalize."""
    import store as store_mod
    import core
    import handlers
    import worker

    tmp = Path(tempfile.mkdtemp()) / "pfj-trigger.db"
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", tmp)
    st = store_mod.Store()
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setattr(st, "get_ai_enabled", lambda: True)

    sid = "scan-trigger-pfj"
    core.register_scan_tokens(sid, drive="tok")
    _init_scan(st, sid)
    st.set_total_folders(sid, 2)

    # Pre-set completed_folders to 1 (folder A already done).
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "UPDATE scan_runs SET completed_folders=1 WHERE id=%s", (sid,))

    monkeypatch.setattr(handlers, "_list_folder_files",
                        lambda src, fid, toks: [])  # folder B happens to be empty

    jid_b = st.enqueue_job("scan_folder",
                            {"scan_id": sid, "folder_id": "fB", "source": "drive"},
                            scan_id=sid)
    w = worker.JobWorker(st, worker_id="w-trigger")
    w.run_once()

    assert st.get_job(jid_b)["status"] == "done"
    # The scan_folder handler should have enqueued scan_finalize (done=2 == total=2).
    counts = _jobs_by_type(st, sid)
    assert counts.get("scan_finalize", 0) == 1, (
        f"expected scan_finalize to be queued, got {counts}")


# ── test 7: set_total_folders and increment_completed_folders store methods ──

def test_folder_progress_tracking_store_methods(monkeypatch):
    """set_total_folders and increment_completed_folders correctly track per-folder progress."""
    import store as store_mod

    tmp = Path(tempfile.mkdtemp()) / "pfj-tracking.db"
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", tmp)
    st = store_mod.Store()

    sid = "scan-tracking-pfj"
    _init_scan(st, sid)

    # set_total_folders initialises both columns.
    st.set_total_folders(sid, 3)
    done, total = _scan_folder_progress(st, sid)
    assert total == 3
    assert done == 0

    # Each increment advances completed_folders.
    d, t = st.increment_completed_folders(sid)
    assert (d, t) == (1, 3)
    d, t = st.increment_completed_folders(sid)
    assert (d, t) == (2, 3)
    d, t = st.increment_completed_folders(sid)
    assert (d, t) == (3, 3)
    # done == total: caller knows to enqueue finalize.
    assert d >= t
