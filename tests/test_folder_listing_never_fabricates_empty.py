"""A folder ACP could not read is not a folder with nothing in it.

WHAT WAS WRONG. `handlers._list_folder_files` answered every failure with `return []`:

    if not drive_token:
        return []
    …
    except Exception:
        return []
    return []                       # any source that is not "drive"

Three different facts — no credential, the listing failed, an unsupported source — all reported
as the same one: the folder is empty. The caller cannot tell them apart, because there is nothing
to tell apart by the time it looks. `_scan_folder` then processes zero files, increments
completed_folders, and the run finalizes claiming FULL coverage of an estate it never read.

That is the worst shape a failure can take. A visible failure gets retried, dead-lettered, and
shown in the queue's incident view; a wrong result that looks complete gets certified. The old
comment in that function called `return []` "a defensible answer to 'we could not list it'" — it
is not, and it was written while correctly refusing the SAME shortcut for cancellation two lines
above.

WHY THE FIX NEEDED TWO HALVES. Raising here was not safe on its own. A dead-lettered scan_folder
job used to return through nothing that advances completed_folders, and rescue_unfinalized_scans
finalizes a per-folder scan only when completed >= total — so raising would have traded a silent
wrong answer for a permanently wedged run. store._record_dead_scan_folder closes that, and
tests/test_dead_folder_job_wedges_the_scan.py measures it. The two ship together.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


@pytest.fixture()
def store(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "folder-listing.db")
    return store_mod.Store()


@pytest.fixture()
def env(store, monkeypatch):
    import core
    import worker
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(store, "get_ai_enabled", lambda: True)
    return worker.JobWorker(store, worker_id="w-listing"), store


def _scan(store, sid, folders=1):
    store.init_scan_run(sid, "drive", 0, "2026-08-31T00:00:00Z", "r", "h", status="running")
    store.set_total_folders(sid, folders)


# ── the listing function itself ───────────────────────────────────────────────────────────────

def test_a_drive_error_is_raised_rather_than_reported_as_an_empty_folder():
    import handlers
    import scanner

    def _boom(_svc, _fid):
        raise RuntimeError("drive: rateLimitExceeded")

    orig = scanner._search_folder
    scanner._search_folder = _boom
    scanner._drive_service = lambda _t: object()
    try:
        with pytest.raises(Exception) as ei:
            handlers._list_folder_files("drive", "fA", {"drive": "tok"})
        assert "fA" in str(ei.value), "the error must name the folder it could not list"
        assert "rateLimitExceeded" in str(ei.value), "the underlying cause must survive"
    finally:
        scanner._search_folder = orig


def test_a_missing_credential_dead_letters_immediately_instead_of_retrying_five_times():
    """No credential is an auth failure, and no number of retries produces one. FatalJobError is
    the queue's word for that — spending five attempts and four backoffs on it delays the only
    useful outcome, which is telling somebody."""
    import handlers
    from worker import FatalJobError
    with pytest.raises(FatalJobError):
        handlers._list_folder_files("drive", "fA", {})


def test_an_unsupported_source_is_an_error_not_an_empty_estate():
    import handlers
    from worker import FatalJobError
    with pytest.raises(FatalJobError) as ei:
        handlers._list_folder_files("sharepoint", "fA", {"drive": "tok"})
    assert "sharepoint" in str(ei.value)


def test_a_readable_empty_folder_still_reports_empty():
    """The control. Narrowing what counts as empty must not make a genuinely empty folder into an
    error — that would turn every empty subfolder in an estate into a dead-lettered job."""
    import handlers
    import scanner
    orig = scanner._search_folder
    scanner._search_folder = lambda _svc, _fid: []
    scanner._drive_service = lambda _t: object()
    try:
        assert handlers._list_folder_files("drive", "fA", {"drive": "tok"}) == []
    finally:
        scanner._search_folder = orig


# ── end to end, through the queue ─────────────────────────────────────────────────────────────

def test_a_folder_that_could_not_be_listed_does_not_finalize_as_fully_covered(env, monkeypatch):
    """The consequence in the shape the operator meets it: the run must not end up looking like a
    complete scan of an estate nothing ever read."""
    import handlers
    w, st = env
    _scan(st, "s-unread", folders=1)

    def _fail(_src, _fid, _toks):
        raise RuntimeError("could not list folder fA: drive 500")

    monkeypatch.setattr(handlers, "_list_folder_files", _fail)
    monkeypatch.setattr(handlers, "_process_scan_folder_item",
                        lambda *a, **k: pytest.fail("nothing may be processed from a failed listing"))

    jid = st.enqueue_job("scan_folder", {"scan_id": "s-unread", "folder_id": "fA",
                                         "source": "drive"}, scan_id="s-unread")
    for _ in range(8):                      # exhaust the retries
        with st._db.cursor() as cur:        # clear the backoff so the next claim is eligible
            st._db.execute(cur, "UPDATE jobs SET run_after=%s WHERE id=%s",
                           ("1970-01-01T00:00:00+00:00", jid))
        if not w.run_once():
            break
        if st.get_job(jid)["status"] == "dead":
            break

    assert st.get_job(jid)["status"] == "dead", (
        "the failed listing was not recorded as a failure at all")
    assert "fA" in (st.get_job(jid)["last_error"] or "")

    out = st.dead_letter_breakdown()
    assert out["by_type"].get("scan_folder") == 1, (
        f"the unreadable folder is not in the incident view: {out['by_type']}")
    assert any("drive 500" in (g["error"] or "") for g in out["top_errors"]), (
        "the reason the folder could not be read did not reach the operator")


def test_the_run_can_still_reach_a_terminal_state_afterwards(env, monkeypatch):
    """The other half, from the handler's side. Refusing to fabricate an empty folder is only
    safe if the run can still end — otherwise the fix is a hang."""
    import handlers
    w, st = env
    _scan(st, "s-terminal", folders=1)
    monkeypatch.setattr(handlers, "_list_folder_files",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("drive 500")))

    jid = st.enqueue_job("scan_folder", {"scan_id": "s-terminal", "folder_id": "fA",
                                         "source": "drive"}, scan_id="s-terminal")
    for _ in range(8):
        with st._db.cursor() as cur:
            st._db.execute(cur, "UPDATE jobs SET run_after=%s WHERE id=%s",
                           ("1970-01-01T00:00:00+00:00", jid))
        if not w.run_once():
            break
        if st.get_job(jid)["status"] == "dead":
            break
    assert st.get_job(jid)["status"] == "dead"

    assert st.rescue_unfinalized_scans() == 1, (
        "the run is wedged: its only folder job is dead and nothing can finalize it")
