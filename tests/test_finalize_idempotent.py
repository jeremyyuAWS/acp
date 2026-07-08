"""ADR 0013 — the finalize trigger is idempotent, and finalize runs exactly once.

A crash between a fan-out file's persistence and its job completing used to re-run the
job, double-count a running counter, and finalize the scan early / twice. The count-based
trigger + finalized_at guard remove both failure modes.
"""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


@pytest.fixture()
def st():
    import store as store_mod
    store_mod._SQLITE_PATH = Path(tempfile.mkdtemp()) / "finalize-test.db"
    # SQLite can't run "ALTER TABLE ... ADD COLUMN IF NOT EXISTS" — the base CREATE TABLE
    # carries every column (incl. finalized_at), so drop the Postgres-only ALTERs here.
    store_mod._SCHEMA[:] = [s for s in store_mod._SCHEMA
                            if not s.strip().upper().startswith("ALTER TABLE")]
    return store_mod.Store()


def _f(name, compliant=0):
    return {"file": name, "engine": "python/html", "status": "analysed", "score": 70,
            "compliant": compliant, "skipped_rules": 0, "issues": []}


def test_count_trigger_is_idempotent_and_never_overshoots(st):
    st.init_scan_run("s1", "drive", total=3, started_at="t0", rubric_name="r", rubric_hash="h")
    st.save_file_result("s1", _f("a.html", compliant=1), "t1")
    st.save_file_result("s1", _f("b.html"), "t1")
    assert st.count_files_done("s1") == (2, 3)          # 2 of 3 → no finalize yet

    st.save_file_result("s1", _f("c.html"), "t1")
    assert st.count_files_done("s1") == (3, 3)          # triggers finalize

    # Simulate a crash-retry of the c.html job: it re-saves the SAME row (upsert).
    st.save_file_result("s1", _f("c.html"), "t1")
    # A running counter would now read 4/3 and could have finalized early; the count-based
    # trigger stays at the true distinct count.
    assert st.count_files_done("s1") == (3, 3)


def test_finalize_runs_exactly_once(st):
    st.init_scan_run("s2", "drive", total=1, started_at="t0", rubric_name="r", rubric_hash="h")
    st.save_file_result("s2", _f("a.html"), "t1")
    assert st.mark_finalized("s2") is True              # first caller wins → emits HITL/audit
    assert st.mark_finalized("s2") is False             # duplicate/concurrent → no-op
    assert st.mark_finalized("s2") is False
