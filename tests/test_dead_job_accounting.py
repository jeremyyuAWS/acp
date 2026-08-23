"""A dead-lettered per-file job must leave the document in the accounting.

THE STALL THIS FIXES. `count_files_done` counts file_records against `scan_runs.files`, and
`scan_finalize` fires only when they meet. Handlers already record an error row for failures they
CATCH, precisely so the counter advances. A job that DEAD-LETTERS never returns through that code —
retries exhausted, or `force_dead` (an expired Drive token takes that path immediately, with no
retries). No row was written, so the document was counted nowhere: not in files_done, not in
run.error, not in queued/running. `files - files_done` then reported it as NOT STARTED forever, the
finalize trigger could never fire, and `rescue_unfinalized_scans` could not help either — it
requires `file_records >= files`, the very thing missing.

Observed live as a 185-document run sitting at 0% with "12 active · 0 waiting".
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
    tmp = Path(tempfile.mkdtemp()) / "dead-acct.db"
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", tmp)
    return store_mod.Store()


def _scan(store, sid="s1", files=3):
    store.init_scan_run(sid, "drive", files, "2026-08-23T00:00:00Z", "rubric", "hash",
                        owner="demo")
    store.set_scan_files(sid, files)
    return sid


# ── the counter, which is what actually unwedges the run ─────────────────────
def test_a_dead_scan_file_job_still_advances_the_finalize_counter(store):
    sid = _scan(store, files=1)
    jid = store.enqueue_job("scan_file", {"scan_id": sid, "file": "a.docx"}, scan_id=sid)
    store.claim_job("w1")
    assert store.count_files_done(sid) == (0, 1)

    assert store.fail_job(jid, "boom", force_dead=True) == "dead"

    done, total = store.count_files_done(sid)
    assert (done, total) == (1, 1), "the dead document must count, or finalize can never fire"


def test_an_expired_token_force_dead_is_the_path_that_wedged_a_whole_estate(store):
    # force_dead fires on the FIRST attempt for a terminal Drive error — no retries — so this is
    # the fastest way a run loses every remaining document at once.
    sid = _scan(store, files=2)
    j1 = store.enqueue_job("scan_file", {"scan_id": sid, "file": "a.docx"}, scan_id=sid)
    j2 = store.enqueue_job("scan_file", {"scan_id": sid, "file": "b.pdf"}, scan_id=sid)
    store.claim_job("w1"); store.claim_job("w1")
    store.fail_job(j1, "Your Google Drive session expired", force_dead=True)
    store.fail_job(j2, "Your Google Drive session expired", force_dead=True)
    assert store.count_files_done(sid) == (2, 2)


def test_a_dead_BATCH_job_records_every_document_it_was_carrying(store):
    # The shape that loses the most: one scan_batch carries up to ACP_SCAN_BATCH_SIZE documents,
    # and missing this branch would drop all of them from the count together.
    sid = _scan(store, files=3)
    jid = store.enqueue_job("scan_batch", {"scan_id": sid, "items": [
        {"file": "a.docx"}, {"file": "b.pdf"}, {"file": "c.pptx"}]}, scan_id=sid)
    store.claim_job("w1")
    store.fail_job(jid, "batch died", force_dead=True)
    assert store.count_files_done(sid) == (3, 3)


# ── the document reads as an error, not as a silent gap ──────────────────────
def test_the_document_is_recorded_as_an_error_not_as_missing(store):
    sid = _scan(store, files=1)
    jid = store.enqueue_job("scan_file", {"scan_id": sid, "file": "a.docx"}, scan_id=sid)
    store.claim_job("w1")
    store.fail_job(jid, "boom", force_dead=True)
    run = store.get_scan(sid)["run"]
    # run.error is what live_snapshot publishes as "unable to assess".
    assert run.get("error") == 1


def test_the_reason_is_logged_where_the_ui_already_looks_for_it(store):
    # fileErrorReason.js reads `scan.file_error` rows and REFUSES to invent a reason when none was
    # recorded — so without this the drawer would correctly say the reason was unknown, while the
    # queue had it all along.
    sid = _scan(store, files=1)
    jid = store.enqueue_job("scan_file", {"scan_id": sid, "file": "a.docx"}, scan_id=sid)
    store.claim_job("w1")
    store.fail_job(jid, "Your Google Drive session expired", force_dead=True)
    rows = [d for d in store.list_decisions(scan_id=sid)
            if d.get("action") == "scan.file_error" and d.get("file") == "a.docx"]
    assert rows, "the dead-letter reason must reach the decision log"
    assert "Drive session expired" in rows[0]["detail"]


# ── what must NOT change ─────────────────────────────────────────────────────
def test_a_retryable_failure_records_nothing_it_is_not_dead_yet(store):
    # Requeued with backoff → the document is still coming. Writing an error row here would report
    # a failure that has not happened and let finalize fire while work is outstanding.
    sid = _scan(store, files=1)
    jid = store.enqueue_job("scan_file", {"scan_id": sid, "file": "a.docx"}, scan_id=sid)
    store.claim_job("w1")
    assert store.fail_job(jid, "transient", backoff_seconds=30) == "queued"
    assert store.count_files_done(sid) == (0, 1)


def test_a_dead_NON_file_job_records_nothing(store):
    # scan_discover / scan_finalize / assess_trace name no document; inventing a file_records row
    # for them would inflate the count past the real population.
    sid = _scan(store, files=2)
    jid = store.enqueue_job("scan_discover", {"scan_id": sid, "source": "drive"}, scan_id=sid)
    store.claim_job("w1")
    store.fail_job(jid, "source unreachable", force_dead=True)
    assert store.count_files_done(sid) == (0, 2)


def test_a_late_real_result_replaces_the_error_row_rather_than_double_counting(store):
    # save_file_result upserts, so an orphaned worker thread finishing after the dead-letter
    # overwrites the placeholder instead of adding a second row.
    sid = _scan(store, files=1)
    jid = store.enqueue_job("scan_file", {"scan_id": sid, "file": "a.docx"}, scan_id=sid)
    store.claim_job("w1")
    store.fail_job(jid, "boom", force_dead=True)
    store.save_file_result(sid, {"file": "a.docx", "engine": "docx", "status": "analysed",
                                 "score": 92, "compliant": 1, "skipped_rules": 0, "issues": []},
                           "2026-08-23T00:00:00Z")
    assert store.count_files_done(sid) == (1, 1)
    assert store.get_scan(sid)["run"].get("error") == 0


def test_a_dead_job_with_no_scan_id_is_ignored_rather_than_raising(store):
    # The queue must never be broken by this bookkeeping.
    jid = store.enqueue_job("scan_file", {"file": "orphan.docx"})
    store.claim_job("w1")
    assert store.fail_job(jid, "boom", force_dead=True) == "dead"
