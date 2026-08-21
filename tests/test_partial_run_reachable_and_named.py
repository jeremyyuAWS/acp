"""A stopped assessment must reach its results, and must name what it never got to.

Board 7, state 4 ("partially completed"): a run that stopped after 9 of 22 documents has to show
the 9 it assessed AND name the 13 it did not — a partial run that reads as a complete one is the
exact failure the seven-state screen exists to prevent.

Two things the backend was not doing, both fixed here:

  · A cancelled or interrupted fan-out never stamped `assessed_at`, so the results views — which
    gate on it — showed NOTHING for a stopped run, not even the documents that were assessed.

  · `get_scan` returns only the files that ran, so the not-started documents were nowhere in the
    payload. The screen could not name them because it never received them.

The selected set is the per-file jobs (one 'scan_file' per document); the assessed set is
file_records; the difference is what was left. cancel_scan marks the outstanding jobs 'dead' but
does not delete them, so their payloads survive to be named.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "jeremyyu.movate@gmail.com"
TS = "2026-08-20T16:00:00Z"


def _running_assess(store, sid, selected, assessed):
    """A running fan-out: one scan_file job per selected document, file_records for the assessed."""
    store.init_scan_run(sid, "drive", len(selected), TS, "default", "rh1", owner=OWNER, status="running")
    for name in selected:
        store.enqueue_job("scan_file", {"scan_id": sid, "file": name}, scan_id=sid)
    for name in assessed:
        store.save_file_result(sid, {
            "file": name, "engine": "python/pdf", "status": "analysed", "score": 90,
            "compliant": 1, "skipped_rules": 0, "issues": [],
        }, TS)


def test_cancel_stamps_assessed_so_the_partial_results_are_reachable(isolated_store):
    store = isolated_store
    _running_assess(store, "s-partial", selected=["a.docx", "b.pdf", "c.docx", "d.pdf"],
                    assessed=["a.docx", "b.pdf"])
    assert store.cancel_scan("s-partial", owner=OWNER) is True

    g = store.get_scan("s-partial", owner=OWNER)
    run = g["run"]
    assert run["status"] == "cancelled"
    # The whole point: a stopped run that assessed something is now reachable by the results views.
    assert run.get("assessed_at"), "a cancelled run that assessed 2 documents was left unassessed"


def test_a_discover_only_cancel_is_not_marked_assessed(isolated_store):
    # No file_records means nothing was assessed — cancelling that is not a partial assessment, and
    # stamping assessed_at would send an empty run to the results screen.
    store = isolated_store
    store.init_scan_run("s-disc", "drive", 3, TS, "default", "rh1", owner=OWNER, status="running")
    for name in ["a.docx", "b.pdf", "c.docx"]:
        store.enqueue_job("scan_file", {"scan_id": "s-disc", "file": name}, scan_id="s-disc")
    assert store.cancel_scan("s-disc", owner=OWNER) is True

    run = store.get_scan("s-disc", owner=OWNER)["run"]
    assert run["status"] == "cancelled"
    assert not run.get("assessed_at"), "a discover-only cancel was wrongly marked assessed"


def test_get_scan_names_the_documents_that_were_never_started(isolated_store):
    store = isolated_store
    _running_assess(store, "s-name", selected=["a.docx", "b.pdf", "c.docx", "d.pdf"],
                    assessed=["a.docx", "b.pdf"])
    store.cancel_scan("s-name", owner=OWNER)

    run = store.get_scan("s-name", owner=OWNER)["run"]
    na = run.get("not_assessed")
    assert na is not None, "a partial run did not expose its not-started documents"
    assert na["count"] == 2
    assert na["selected"] == 4
    names = {d["name"] for d in na["documents"]}
    assert names == {"c.docx", "d.pdf"}, f"named the wrong not-started documents: {names}"


def test_selected_survives_purged_done_jobs(isolated_store):
    # `selected` is assessed + not_started, so it holds even if the completed documents' jobs were
    # already garbage-collected (only 'done' jobs are ever purged). Here the two assessed documents
    # have NO job at all — the count must still be 4, from the file_records plus the two dead jobs.
    store = isolated_store
    store.init_scan_run("s-purge", "drive", 4, TS, "default", "rh1", owner=OWNER, status="running")
    for name in ["c.docx", "d.pdf"]:                        # only the not-started keep their jobs
        store.enqueue_job("scan_file", {"scan_id": "s-purge", "file": name}, scan_id="s-purge")
    for name in ["a.docx", "b.pdf"]:
        store.save_file_result("s-purge", {
            "file": name, "engine": "python/pdf", "status": "analysed", "score": 90,
            "compliant": 1, "skipped_rules": 0, "issues": [],
        }, TS)
    store.cancel_scan("s-purge", owner=OWNER)

    na = store.get_scan("s-purge", owner=OWNER)["run"]["not_assessed"]
    assert na["count"] == 2
    assert na["selected"] == 4


def test_a_completed_run_exposes_no_not_assessed_block(isolated_store):
    # A finalized run has nothing outstanding; the field is absent so no consumer mistakes an empty
    # not-started list for a partial run.
    store = isolated_store
    store.init_scan_run("s-done", "drive", 2, TS, "default", "rh1", owner=OWNER, status="running")
    for name in ["a.docx", "b.pdf"]:
        store.save_file_result("s-done", {
            "file": name, "engine": "python/pdf", "status": "analysed", "score": 90,
            "compliant": 1, "skipped_rules": 0, "issues": [],
        }, TS)
    store.finalize_scan_run("s-done", TS)

    run = store.get_scan("s-done", owner=OWNER)["run"]
    assert run["status"] != "cancelled"
    assert "not_assessed" not in run
