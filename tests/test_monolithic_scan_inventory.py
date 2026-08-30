"""The MONOLITHIC scan path (store.save_scan) must also populate scan_inventory, not just
file_records/documents — PRD Phase 3's delta-sync reconstruction seam
(store.latest_scan_inventory_items) reads scan_inventory, and this path (core._do_scheduled_scan
always, routes/scans.py's sync/thread branches when ACP_DEFER_ANALYSIS_TO_ASSESS=0) is the ONE
production caller that runs unconditionally regardless of that setting. Before this, it silently
left scan_inventory empty for every scan it saved — see latest_scan_inventory_items's own
docstring for what that broke (a delta-sync reconstruction from an empty-but-real baseline,
discarding almost the whole estate) and test_drive_changes_sync.py's
test_a_completed_scan_with_no_inventory_rows_is_never_the_source for the guard that also closes
that gap independently.

run_scan() hands save_scan the raw `_list()` items via the report's `_inventory_items` hint —
the same items handlers._scan_discover's own `norm`/`inv` construction turns into scan_inventory
rows for the deferred (ADR 0020) path. This mirrors that conversion for the monolithic path.
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
    tmp = Path(tempfile.mkdtemp()) / "mono-inv-test.db"
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", tmp)
    return store_mod.Store()


def _report(*, source="drive", inventory_items=None, files=None):
    files = files if files is not None else []
    return {
        "_scan_id": "mono-inv-1",
        "_inventory_items": inventory_items,
        "rubric": {"name": "r", "version": "1", "hash": "h"},
        "summary": {"files": len(files), "certifiable": 0, "uncertain": 0, "error": 0, "avg_score": 50},
        "started_at": "2026-08-30T00:00:00+00:00",
        "completed_at": "2026-08-30T00:01:00+00:00",
        "source": source,
        "owner": "mono@test",
        "files": files,
    }


DRIVE_ITEMS = [
    {"name": "a.pdf", "id": "F1", "source_mime": "application/pdf", "checksum": "c1",
     "created_at": "2026-08-01T00:00:00Z", "source_modified": "2026-08-02T00:00:00Z",
     "owner": "alice", "parent_folder": "root", "size_kb": 12,
     "drive_account_id": "alice@gmail.com"},
    {"name": "b.docx",
     "id": "F2", "source_mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
     "checksum": "c2", "created_at": None, "source_modified": None, "owner": None,
     "parent_folder": None, "size_kb": 5, "drive_account_id": "alice@gmail.com"},
]


def test_save_scan_populates_scan_inventory_from_the_hint(store):
    store.save_scan(_report(inventory_items=DRIVE_ITEMS))
    items = store.latest_scan_inventory_items("mono@test", "drive")
    assert items is not None
    assert sorted(i["file"] for i in items) == ["a.pdf", "b.docx"]


def test_the_persisted_rows_carry_drive_account_id_for_later_verification(store):
    """core._drive_prior_inventory_for_account reads this back — a monolithic scan's own rows
    must carry the account identity just like the deferred path's do."""
    store.save_scan(_report(inventory_items=DRIVE_ITEMS))
    items = store.latest_scan_inventory_items("mono@test", "drive")
    assert all(i["drive_account_id"] == "alice@gmail.com" for i in items)


def test_no_inventory_items_hint_is_a_no_op_not_a_crash(store):
    """A hand-built report (most tests, and any caller that predates this hint) has no
    _inventory_items key — save_scan must behave exactly as it always did, not raise."""
    store.save_scan(_report(inventory_items=None))
    assert store.latest_scan_inventory_items("mono@test", "drive") is None


def test_a_failure_building_inventory_rows_does_not_fail_the_scan_save(store, monkeypatch):
    """Defensively wrapped, same as the documents-table block: a broken secondary write must
    never take the primary scan save down with it."""
    import classify
    def _boom(name, mime):
        raise RuntimeError("boom")
    monkeypatch.setattr(classify, "classify_from_metadata", _boom)
    sid = store.save_scan(_report(inventory_items=DRIVE_ITEMS))
    assert sid == "mono-inv-1"
    # The scan itself still saved (scan_runs row exists) even though inventory persistence blew up.
    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT id FROM scan_runs WHERE id=%s", (sid,))
        assert store._db.fetchone(cur) is not None


def test_a_second_completed_sweep_can_reconstruct_from_the_firsts_inventory(store):
    """The end-to-end scenario this whole fix is about: two monolithic scans in a row (as the
    scheduled sweep always is) — the second must be able to use the first's inventory as a real
    delta-sync baseline, not an empty one."""
    store.save_scan(_report(inventory_items=DRIVE_ITEMS))
    second_items = [dict(DRIVE_ITEMS[0], source_modified="2026-08-03T00:00:00Z")]
    r2 = _report(inventory_items=second_items)
    r2["_scan_id"] = "mono-inv-2"
    r2["completed_at"] = "2026-08-30T01:00:00+00:00"
    store.save_scan(r2)
    items = store.latest_scan_inventory_items("mono@test", "drive")
    assert [i["file"] for i in items] == ["a.pdf"]
    assert items[0]["source_modified"] == "2026-08-03T00:00:00Z"
