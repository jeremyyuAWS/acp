"""ADR 0038 — pausable/resumable scans. This PR is the store-layer mechanism only (pause_scan/
resume_scan CAS, the pause marker, undone_scan_items, and the job-handler checkpoints that make
the marker actually stop new dispatch) — no HTTP routes and no frontend control yet, per the ADR's
own "small, seam-aligned change" framing. Nothing in production calls pause_scan/resume_scan or
sets the marker until that follow-up lands, so this is additive and dormant.

Six of the ADR's own §6 test list live here; the sweeper-leaves-paused-alone case lives in
test_discovery_guard.py-adjacent reasoning but is re-proven directly below too, since
sweep_orphaned_scans' existing status='running' filter is what makes it correct and that is
exactly the kind of invariant a later "helpful" WHERE-clause change could quietly break.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


def _iso(dt):
    return dt.isoformat()


def _running_scan(store, sid, owner="a@x.io", started_ago_s=0, jobs=0, files=5):
    started = _iso(datetime.now(timezone.utc) - timedelta(seconds=started_ago_s))
    store.init_scan_run(sid, "drive", total=files, started_at=started,
                        rubric_name="r", rubric_hash="h", owner=owner)
    for i in range(jobs):
        store.enqueue_job("scan_file", {"scan_id": sid, "file": f"f{i}.docx"}, scan_id=sid)
    return sid


def _persist_files(store, sid, names):
    now = datetime.now(timezone.utc).isoformat()
    for name in names:
        store.save_file_result(sid, {"file": name, "engine": "t", "status": "ok",
                                     "score": 90, "compliant": 1, "skipped_rules": 0,
                                     "issues": []}, now)


def _inventory(store, sid, names):
    store.add_inventory(sid, [{"file": n} for n in names])


# ── pause_scan ───────────────────────────────────────────────────────────────────

def test_pause_flips_running_to_paused_without_stamping_completed_at(isolated_store):
    s = isolated_store
    _running_scan(s, "s1", jobs=2)
    assert s.pause_scan("s1", owner="a@x.io") is True
    run = s.get_scan("s1")["run"]
    assert run["status"] == "paused"
    assert not run.get("completed_at")


def test_pause_does_not_kill_outstanding_jobs(isolated_store):
    """The one hard difference from cancel_scan: pause is cooperative, never a mid-file kill —
    an already-claimed job must be left alone to finish and persist its row."""
    s = isolated_store
    _running_scan(s, "s1", jobs=3)
    s.pause_scan("s1", owner="a@x.io")
    assert s.job_stats().get("queued", 0) == 3
    assert s.job_stats().get("dead", 0) == 0


def test_pause_refused_on_completed_cancelled_other_owner_or_already_paused(isolated_store):
    s = isolated_store
    _running_scan(s, "done", jobs=0)
    s.set_scan_status("done", "discovered")
    assert s.pause_scan("done", owner="a@x.io") is False

    _running_scan(s, "cancelled", jobs=0)
    s.cancel_scan("cancelled", owner="a@x.io")
    assert s.pause_scan("cancelled", owner="a@x.io") is False

    _running_scan(s, "mine", jobs=0)
    assert s.pause_scan("mine", owner="intruder@x.io") is False

    _running_scan(s, "twice", jobs=0)
    assert s.pause_scan("twice", owner="a@x.io") is True
    assert s.pause_scan("twice", owner="a@x.io") is False   # already paused, not running

    assert s.pause_scan("nope", owner="a@x.io") is False    # doesn't exist


def test_paused_run_does_not_finalize_even_when_the_pool_drains(isolated_store):
    """count < files must keep the run legitimately open — pausing must never look like
    completion just because nothing is left in the job queue."""
    s = isolated_store
    _running_scan(s, "s1", jobs=0, files=5)
    _persist_files(s, "s1", ["f0.docx", "f1.docx"])   # 2 of 5 analysed before the pause
    s.pause_scan("s1", owner="a@x.io")
    done, total = s.count_files_done("s1")
    assert (done, total) == (2, 5)
    assert s.get_scan("s1")["run"]["status"] == "paused"


# ── resume_scan ──────────────────────────────────────────────────────────────────

def test_resume_flips_paused_to_running(isolated_store):
    s = isolated_store
    _running_scan(s, "s1", jobs=0)
    s.pause_scan("s1", owner="a@x.io")
    assert s.resume_scan("s1", owner="a@x.io") is True
    assert s.get_scan("s1")["run"]["status"] == "running"


def test_resume_refused_on_a_non_paused_run(isolated_store):
    s = isolated_store
    _running_scan(s, "running", jobs=0)
    assert s.resume_scan("running", owner="a@x.io") is False

    _running_scan(s, "mine", jobs=0)
    s.pause_scan("mine", owner="a@x.io")
    assert s.resume_scan("mine", owner="intruder@x.io") is False

    assert s.resume_scan("nope", owner="a@x.io") is False


# ── undone_scan_items ────────────────────────────────────────────────────────────

def test_undone_scan_items_excludes_files_with_a_current_record(isolated_store):
    s = isolated_store
    _running_scan(s, "s1", jobs=0, files=3)
    _inventory(s, "s1", ["a.docx", "b.docx", "c.docx"])
    _persist_files(s, "s1", ["a.docx"])   # a.docx already has a row
    undone = s.undone_scan_items("s1")
    assert sorted(i["file"] for i in undone) == ["b.docx", "c.docx"]


def test_undone_scan_items_empty_when_everything_is_done(isolated_store):
    s = isolated_store
    _running_scan(s, "s1", jobs=0, files=2)
    _inventory(s, "s1", ["a.docx", "b.docx"])
    _persist_files(s, "s1", ["a.docx", "b.docx"])
    assert s.undone_scan_items("s1") == []


def test_undone_scan_items_is_scoped_to_its_own_scan(isolated_store):
    s = isolated_store
    _running_scan(s, "s1", jobs=0, files=1)
    _running_scan(s, "s2", jobs=0, files=1)
    _inventory(s, "s1", ["a.docx"])
    _inventory(s, "s2", ["a.docx"])
    _persist_files(s, "s2", ["a.docx"])   # s2's copy is done; s1's is not
    assert [i["file"] for i in s.undone_scan_items("s1")] == ["a.docx"]
    assert s.undone_scan_items("s2") == []


# ── the sweeper must leave a paused run alone (ADR 0038 §4) ─────────────────────

def test_sweeper_does_not_mark_a_paused_run_interrupted(isolated_store):
    """A paused scan has, by design, zero outstanding jobs — indistinguishable from a crashed
    one to the sweeper's own job-count query unless 'paused' is excluded up front. It is:
    sweep_orphaned_scans only ever selects status='running', so a scan already flipped to
    'paused' can never match, regardless of how long it sits with no jobs. Proven directly
    rather than trusted, since a future widening of that WHERE clause is exactly how this
    regression would reappear."""
    s = isolated_store
    _running_scan(s, "s1", started_ago_s=1200, jobs=0)   # old, zero jobs — sweeper bait
    s.pause_scan("s1", owner="a@x.io")
    assert s.sweep_orphaned_scans() == 0
    assert s.get_scan("s1")["run"]["status"] == "paused"


def test_sweeper_still_catches_a_genuinely_crashed_running_scan(isolated_store):
    """Unchanged behavior, proven alongside the paused case above so the two are read together."""
    s = isolated_store
    _running_scan(s, "s1", started_ago_s=1200, jobs=0)
    assert s.sweep_orphaned_scans() == 1
    assert s.get_scan("s1")["run"]["status"] == "interrupted"


# ── job-handler checkpoint: the marker actually stops new dispatch ──────────────

def _wire(monkeypatch, st, count_files_done_fn):
    import core
    import handlers
    import lf
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setattr(lf, "flush", lambda: None)
    monkeypatch.setattr(core, "get_scan_tokens", lambda sid: {})
    monkeypatch.setattr(core, "active_rubric", lambda: type("R", (), {"hash": "test-hash"})())
    monkeypatch.setattr(handlers, "_make_svc", lambda source, toks: None)
    monkeypatch.setattr(st, "count_files_done", count_files_done_fn)


def test_scan_batch_skips_every_item_while_paused(isolated_store, monkeypatch):
    import handlers
    _wire(monkeypatch, isolated_store, lambda sid: (0, 3))
    analysed = []
    monkeypatch.setattr(handlers, "_analyse_and_persist_one",
                        lambda scan_id, item, *a, **k: analysed.append(item["file"]))
    isolated_store.set_setting(handlers._PAUSE_KEY % "s1", "1")

    handlers._scan_batch({"scan_id": "s1", "source": "local",
                          "items": [{"file": f"f{i}.docx"} for i in range(3)]}, {})

    assert analysed == [], "no item should be analysed while the pause marker is set"


def test_scan_batch_analyses_normally_once_unpaused(isolated_store, monkeypatch):
    import handlers
    _wire(monkeypatch, isolated_store, lambda sid: (0, 1))
    analysed = []
    monkeypatch.setattr(handlers, "_analyse_and_persist_one",
                        lambda scan_id, item, *a, **k: analysed.append(item["file"]))
    isolated_store.set_setting(handlers._PAUSE_KEY % "s1", "")   # never paused / cleared

    handlers._scan_batch({"scan_id": "s1", "source": "local", "items": [{"file": "f0.docx"}]}, {})

    assert analysed == ["f0.docx"]


def test_scan_file_skips_while_paused(isolated_store, monkeypatch):
    import handlers
    _wire(monkeypatch, isolated_store, lambda sid: (0, 1))
    analysed = []
    monkeypatch.setattr(handlers, "_analyse_and_persist_one",
                        lambda scan_id, item, *a, **k: analysed.append(item.get("file")))
    isolated_store.set_setting(handlers._PAUSE_KEY % "s1", "1")

    handlers._scan_file({"scan_id": "s1", "source": "local", "file": "f0.docx"}, {})

    assert analysed == []


def test_enqueue_analysis_clears_a_stale_pause_marker(isolated_store, monkeypatch):
    """Same reasoning as clear_drive_stop: any re-dispatch through _enqueue_analysis (resume
    included) must not find a leftover marker from an earlier pause and silently no-op every
    file all over again."""
    import core
    import handlers
    monkeypatch.setattr(core, "store", isolated_store)
    isolated_store.set_setting(handlers._PAUSE_KEY % "s1", "1")
    assert handlers.scan_paused("s1") is True

    handlers._enqueue_analysis("s1", "local", [], ai=False, pii=False, user=None,
                               incremental=True, exclude_remediated=False)

    assert handlers.scan_paused("s1") is False


# ── full cycle ────────────────────────────────────────────────────────────────────

def test_full_pause_resume_cycle_keeps_analysed_so_far_rows_intact(isolated_store):
    s = isolated_store
    _running_scan(s, "s1", jobs=0, files=3)
    _inventory(s, "s1", ["a.docx", "b.docx", "c.docx"])
    _persist_files(s, "s1", ["a.docx"])   # analysed before the pause

    assert s.pause_scan("s1", owner="a@x.io") is True
    assert s.get_scan("s1")["run"]["status"] == "paused"

    undone = s.undone_scan_items("s1")
    assert sorted(i["file"] for i in undone) == ["b.docx", "c.docx"]

    assert s.resume_scan("s1", owner="a@x.io") is True
    assert s.get_scan("s1")["run"]["status"] == "running"

    _persist_files(s, "s1", ["b.docx", "c.docx"])   # the "re-dispatch" landing its results
    done, total = s.count_files_done("s1")
    assert (done, total) == (3, 3)
    assert s.undone_scan_items("s1") == []
