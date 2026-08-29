"""Overview snapshot cache (workspace-bootstrap redesign, Phase 1).

Covers:
  1. Snapshot generation from scan_inventory/file_records/issue_records/scan_decisions.
  2. Caching for a terminal (completed_at set) scan, vs. recompute-every-call for one
     still in progress.
  3. Invalidation: the write paths named in the design doc (assessment finishing,
     remediation, a review decision, publishing, a single-file rescore) each bump
     scan_runs.revision, which is part of the overview_snapshots cache key.
  4. Tenant isolation — owner is part of the cache key, not just a filter.
  5. delete_scan purges the cached snapshot along with everything else scan-keyed.
"""
from __future__ import annotations

import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import store as store_mod


def _seed_scan(s: store_mod.Store, scan_id: str, owner: str, *, completed_at: str | None,
               rubric_hash: str = "rh1") -> None:
    with s._db.cursor() as cur:
        s._db.execute(cur,
            "INSERT INTO scan_runs (id, owner_email, source, rubric_hash, completed_at, "
            "started_at, discovered_at, assessed_at, certifiable, uncertain, error, avg_score) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (scan_id, owner, "drive", rubric_hash, completed_at,
             "2026-08-01T00:00:00", "2026-08-01T00:01:00",
             "2026-08-01T00:02:00" if completed_at else None, 1, 0, 0, 90))
        # A three-document estate: one assessed+compliant, one assessed+failing, one
        # excluded at discovery (never reaches file_records).
        s._db.execute(cur,
            "INSERT INTO scan_inventory (scan_id, file, doc_class) VALUES (%s,%s,%s)",
            (scan_id, "a.pdf", "pdf"))
        s._db.execute(cur,
            "INSERT INTO scan_inventory (scan_id, file, doc_class) VALUES (%s,%s,%s)",
            (scan_id, "b.pdf", "pdf"))
        s._db.execute(cur,
            "INSERT INTO scan_inventory (scan_id, file, doc_class, exclusion_reason) "
            "VALUES (%s,%s,%s,%s)",
            (scan_id, "c.pdf", "pdf", "lifecycle: archive candidate"))
        s._db.execute(cur,
            "INSERT INTO file_records (scan_id, file, engine, status, score, compliant, "
            "remediated_at, published_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (scan_id, "a.pdf", "pdf", "analysed", 100, 1, None, None))
        s._db.execute(cur,
            "INSERT INTO file_records (scan_id, file, engine, status, score, compliant, "
            "remediated_at, published_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (scan_id, "b.pdf", "pdf", "uncertain", 40, 0, None, None))
        s._db.execute(cur,
            "INSERT INTO issue_records (scan_id, file, rule_id, wcag, severity) "
            "VALUES (%s,%s,%s,%s,%s)",
            (scan_id, "b.pdf", "pdf.tagged", "SC_1_3_1", "CRITICAL"))


def _snapshot_row_count(s: store_mod.Store, scan_id: str) -> int:
    with s._db.cursor() as cur:
        s._db.execute(cur, "SELECT COUNT(*) AS n FROM overview_snapshots WHERE scan_id=%s",
                      (scan_id,))
        return s._db.fetchone(cur)["n"]


def _revision(s: store_mod.Store, scan_id: str) -> int:
    with s._db.cursor() as cur:
        s._db.execute(cur, "SELECT revision FROM scan_runs WHERE id=%s", (scan_id,))
        return int((s._db.fetchone(cur) or {}).get("revision") or 0)


# ── generation ────────────────────────────────────────────────────────────

def test_snapshot_counts_match_seeded_data(isolated_store):
    _seed_scan(isolated_store, "s1", "alice@example.com", completed_at="2026-08-01T01:00:00")
    snap = isolated_store.get_overview_snapshot("s1", "alice@example.com")
    assert snap["estate"]["discovered"] == 3
    assert snap["estate"]["assessable"] == 2          # 3 discovered - 1 excluded
    assert snap["documents"]["assessed"] == 2
    assert snap["documents"]["excluded"] == 1
    assert snap["documents"]["unassessable"] == 0      # 2 assessable - 2 assessed
    assert snap["documents"]["certifiable"] == 1
    assert snap["severity_distribution"] == {"CRITICAL": 1}
    assert snap["file_type_distribution"] == {"pdf": 2}
    assert snap["source"] == "drive"
    assert snap["scan_revision"] == 0
    assert snap["rubric_hash"] == "rh1"


def test_unknown_scan_returns_none(isolated_store):
    assert isolated_store.get_overview_snapshot("nope", "alice@example.com") is None


# ── caching: terminal vs. in-progress ────────────────────────────────────

def test_terminal_scan_snapshot_is_persisted_and_served_from_cache(isolated_store):
    _seed_scan(isolated_store, "s1", "alice@example.com", completed_at="2026-08-01T01:00:00")
    first = isolated_store.get_overview_snapshot("s1", "alice@example.com")
    assert first["cached"] is False
    assert _snapshot_row_count(isolated_store, "s1") == 1

    second = isolated_store.get_overview_snapshot("s1", "alice@example.com")
    assert second["cached"] is True
    assert second["documents"] == first["documents"]
    # still exactly one row — the second read did not insert a duplicate
    assert _snapshot_row_count(isolated_store, "s1") == 1


def test_in_progress_scan_is_not_cached(isolated_store):
    _seed_scan(isolated_store, "s1", "alice@example.com", completed_at=None)
    snap = isolated_store.get_overview_snapshot("s1", "alice@example.com")
    assert snap["cached"] is False
    assert _snapshot_row_count(isolated_store, "s1") == 0

    # Called again — still recomputed fresh every time, never persisted.
    snap2 = isolated_store.get_overview_snapshot("s1", "alice@example.com")
    assert snap2["cached"] is False
    assert _snapshot_row_count(isolated_store, "s1") == 0


# ── invalidation ──────────────────────────────────────────────────────────

def test_record_remediation_bumps_revision_and_busts_cache(isolated_store):
    _seed_scan(isolated_store, "s1", "alice@example.com", completed_at="2026-08-01T01:00:00")
    before = isolated_store.get_overview_snapshot("s1", "alice@example.com")
    assert before["remediation"]["remediated"] == 0
    assert _revision(isolated_store, "s1") == 0

    isolated_store.record_remediation("s1", "b.pdf", drive_write_url="https://drive/b.pdf")
    assert _revision(isolated_store, "s1") == 1

    after = isolated_store.get_overview_snapshot("s1", "alice@example.com")
    assert after["cached"] is False           # new revision -> cache miss -> recomputed
    assert after["remediation"]["remediated"] == 1
    assert after["scan_revision"] == 1
    # both revisions' snapshots persisted — the old one is simply never looked up again
    assert _snapshot_row_count(isolated_store, "s1") == 2


def test_save_and_delete_decision_bump_revision(isolated_store):
    _seed_scan(isolated_store, "s1", "alice@example.com", completed_at="2026-08-01T01:00:00")
    isolated_store.get_overview_snapshot("s1", "alice@example.com")
    assert _revision(isolated_store, "s1") == 0

    isolated_store.save_decision("s1", "b.pdf", "triage", "inscope", "alice@example.com",
                                 "2026-08-01T02:00:00")
    assert _revision(isolated_store, "s1") == 1
    snap = isolated_store.get_overview_snapshot("s1", "alice@example.com")
    assert snap["remediation"]["review"] == {"triage": 1}

    isolated_store.delete_decision("s1", "b.pdf", "triage")
    assert _revision(isolated_store, "s1") == 2


def test_mark_published_bumps_revision_once(isolated_store):
    _seed_scan(isolated_store, "s1", "alice@example.com", completed_at="2026-08-01T01:00:00")
    assert _revision(isolated_store, "s1") == 0
    isolated_store.mark_published("s1", at="2026-08-01T03:00:00")
    assert _revision(isolated_store, "s1") == 1
    # SET ONCE contract: a second call is a no-op and must not bump again.
    isolated_store.mark_published("s1", at="2026-08-01T04:00:00")
    assert _revision(isolated_store, "s1") == 1


def test_record_publish_bumps_revision(isolated_store):
    _seed_scan(isolated_store, "s1", "alice@example.com", completed_at="2026-08-01T01:00:00")
    assert _revision(isolated_store, "s1") == 0
    isolated_store.record_publish("s1", "a.pdf")
    assert _revision(isolated_store, "s1") == 1
    snap = isolated_store.get_overview_snapshot("s1", "alice@example.com")
    assert snap["remediation"]["published"] == 1


def test_finalize_scan_run_bumps_revision(isolated_store):
    _seed_scan(isolated_store, "s1", "alice@example.com", completed_at=None)
    assert _revision(isolated_store, "s1") == 0
    isolated_store.finalize_scan_run("s1", "2026-08-01T05:00:00")
    assert _revision(isolated_store, "s1") == 1
    # now terminal — the next read is cacheable
    snap = isolated_store.get_overview_snapshot("s1", "alice@example.com")
    assert snap["cached"] is False
    assert _snapshot_row_count(isolated_store, "s1") == 1


def test_rubric_change_produces_new_cache_key(isolated_store):
    """rubric_hash is part of the cache key (design doc): a rubric change must never
    serve a snapshot computed under the old rubric, even if the revision counter hasn't
    moved (this store has no write path that changes an existing scan's own rubric_hash,
    so the key component is exercised directly here)."""
    _seed_scan(isolated_store, "s1", "alice@example.com", completed_at="2026-08-01T01:00:00",
              rubric_hash="rh1")
    first = isolated_store.get_overview_snapshot("s1", "alice@example.com")
    assert first["rubric_hash"] == "rh1"
    assert _snapshot_row_count(isolated_store, "s1") == 1

    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur, "UPDATE scan_runs SET rubric_hash=%s WHERE id=%s",
                                   ("rh2", "s1"))

    second = isolated_store.get_overview_snapshot("s1", "alice@example.com")
    assert second["cached"] is False
    assert second["rubric_hash"] == "rh2"
    # the rh1 row is untouched; a new rh2 row was added alongside it
    assert _snapshot_row_count(isolated_store, "s1") == 2


# ── tenant isolation ──────────────────────────────────────────────────────

def test_owner_mismatch_returns_none_even_with_a_cached_snapshot(isolated_store):
    _seed_scan(isolated_store, "s1", "alice@example.com", completed_at="2026-08-01T01:00:00")
    isolated_store.get_overview_snapshot("s1", "alice@example.com")   # populates the cache
    assert isolated_store.get_overview_snapshot("s1", "mallory@example.com") is None


# ── deletion ──────────────────────────────────────────────────────────────

def test_delete_scan_purges_cached_snapshot(isolated_store):
    _seed_scan(isolated_store, "s1", "alice@example.com", completed_at="2026-08-01T01:00:00")
    isolated_store.get_overview_snapshot("s1", "alice@example.com")
    assert _snapshot_row_count(isolated_store, "s1") == 1

    isolated_store.delete_scan("s1", "alice@example.com")
    assert _snapshot_row_count(isolated_store, "s1") == 0
