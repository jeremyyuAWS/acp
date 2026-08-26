"""supersede_scan() must never let an auto-cancelled scan attempt outrank the real result it
replaced. Found live 2026-08-26: the single-flight guard (PR #841) originally called
cancel_scan(), which stamps completed_at=now() — so a scan superseded seconds into a fresh start
(files=0, since nothing was saved yet) sorted as the NEWEST row in list_scans() (ORDER BY
completed_at DESC), ahead of a real, complete scan. Production's automated monitor caught this
within minutes of a real supersede: "newest has 0 documents but a recent scan had 999" — the exact
fingerprint scripts/monitor.py's collapse check exists to catch (COLLAPSE_RATIO).

supersede_scan() now uses a distinct 'superseded' status (vs. cancel_scan()'s 'cancelled', used by
the explicit Stop button and left untouched — a user-initiated stop is meant to stay visible in
scan history). These tests pin that every "give me the latest/recent scans" query excludes it.
"""
from __future__ import annotations
import sys
from datetime import datetime, timezone
from pathlib import Path

from pathlib import Path as _P
sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "api"))

OWNER = "owner@example.com"


def _init_running(store, sid, *, source="drive", started_at=None):
    store.init_scan_run(sid, source, total=0, started_at=started_at or datetime.now(timezone.utc).isoformat(),
                        rubric_name="r", rubric_hash="h", owner=OWNER, status="running")


def _seed_completed(store, sid, *, files, source="drive", started_at, completed_at):
    """A real, finished scan with a specific file count — inserted directly rather than through
    finalize_scan_run (which derives 'files' from file_records rows, awkward to seed at volume)."""
    with store._db.cursor() as cur:
        store._db.execute(cur,
            "INSERT INTO scan_runs (id, owner_email, source, started_at, completed_at, status, "
            "files, certifiable, uncertain, error, avg_score) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (sid, OWNER, source, started_at, completed_at, "done", files, files, 0, 0, 100))


def test_supersede_scan_marks_superseded_not_cancelled(isolated_store):
    s = isolated_store
    _init_running(s, "sup1")
    assert s.supersede_scan("sup1", owner=OWNER) is True
    run = s.get_scan("sup1", owner=OWNER)["run"]
    assert run["status"] == "superseded"
    assert run["completed_at"] is not None


def test_supersede_scan_kills_outstanding_jobs_like_cancel_scan(isolated_store):
    s = isolated_store
    _init_running(s, "sup2")
    s.enqueue_job("scan_file", {"scan_id": "sup2", "file": "a.pdf"}, scan_id="sup2")
    s.supersede_scan("sup2", owner=OWNER)
    stats = s.job_stats(owner=None)
    assert stats.get("queued", 0) == 0  # the job was marked dead, not left queued forever


def test_supersede_scan_only_touches_a_running_scan(isolated_store):
    s = isolated_store
    s.init_scan_run("sup3", "drive", total=0, started_at=datetime.now(timezone.utc).isoformat(),
                    rubric_name="r", rubric_hash="h", owner=OWNER, status="queued")
    assert s.supersede_scan("sup3", owner=OWNER) is False
    assert s.get_scan("sup3", owner=OWNER)["run"]["status"] == "queued"


def test_supersede_scan_is_owner_scoped(isolated_store):
    s = isolated_store
    _init_running(s, "sup4")
    assert s.supersede_scan("sup4", owner="someone-else@example.com") is False
    assert s.get_scan("sup4", owner=OWNER)["run"]["status"] == "running"


# ── The actual regression: superseded scans must not outrank real ones in every listing ────────

def test_list_scans_excludes_a_superseded_scan_even_though_it_has_completed_at(isolated_store):
    s = isolated_store
    _seed_completed(s, "real1", files=999, started_at="2026-08-26T10:00:00Z",
                    completed_at="2026-08-26T10:05:00Z")
    _init_running(s, "sup5", started_at="2026-08-26T10:10:00Z")
    s.supersede_scan("sup5", owner=OWNER)  # completed_at stamped NOW — later than real1's

    ids = [r["id"] for r in s.list_scans(owner=OWNER)]
    assert "sup5" not in ids
    assert ids[0] == "real1"  # the real scan is still reported as the newest


def test_list_scans_admin_excludes_superseded(isolated_store):
    s = isolated_store
    _init_running(s, "sup6")
    s.supersede_scan("sup6", owner=OWNER)
    ids = [r["id"] for r in s.list_scans_admin()]
    assert "sup6" not in ids


def test_list_scans_including_discovered_excludes_superseded(isolated_store):
    s = isolated_store
    _seed_completed(s, "real2", files=170, started_at="2026-08-26T10:00:00Z",
                    completed_at="2026-08-26T10:05:00Z")
    _init_running(s, "sup7", started_at="2026-08-26T10:10:00Z")
    s.supersede_scan("sup7", owner=OWNER)

    ids = [r["id"] for r in s.list_scans_including_discovered(owner=OWNER)]
    assert "sup7" not in ids
    assert ids[0] == "real2"


def test_previous_run_for_source_skips_a_superseded_run(isolated_store):
    s = isolated_store
    _seed_completed(s, "real3", files=50, source="drive", started_at="2026-08-26T09:00:00Z",
                    completed_at="2026-08-26T09:05:00Z")
    _init_running(s, "sup8", source="drive", started_at="2026-08-26T09:10:00Z")
    s.supersede_scan("sup8", owner=OWNER)
    _seed_completed(s, "current", files=52, source="drive", started_at="2026-08-26T09:20:00Z",
                    completed_at="2026-08-26T09:25:00Z")

    prev = s.previous_run_for_source("current", owner=OWNER)
    assert prev == "real3"  # not the superseded attempt in between


def test_monitor_estate_no_longer_reports_a_collapse_from_a_supersede(isolated_store):
    """End-to-end regression pin for the exact production failure: 'newest has 0 documents but a
    recent scan had 999' must not fire when the 0-document row is a superseded attempt."""
    s = isolated_store
    _seed_completed(s, "prodreal", files=999, started_at="2026-08-26T18:00:00Z",
                    completed_at="2026-08-26T18:10:00Z")
    _init_running(s, "prodsup", started_at="2026-08-26T18:40:00Z")
    s.supersede_scan("prodsup", owner=OWNER)  # stamps completed_at ~now, files=0

    scans = s.list_scans()  # owner=None — same call /monitor/estate makes
    recent_files = [int(r.get("files") or 0) for r in scans[:10]]
    assert recent_files[0] == 999  # the real scan, not the superseded 0-document one
