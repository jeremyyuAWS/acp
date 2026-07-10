"""Tests for the fan-out scan store layer (ADR 0007) — the parts that don't need
the analysis engines: the discover→per-file→finalize counter and the summary
aggregation (which must match Rubric.aggregate)."""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "fanout-test.db")
    return store_mod.Store()


def _file(name, status="analysed", score=90, compliant=1, issues=None):
    return {"file": name, "engine": "python/html", "status": status, "score": score,
            "compliant": compliant, "skipped_rules": 0, "issues": issues or []}


def test_counter_and_finalize_aggregation(st):
    st.init_scan_run("s1", "drive", total=3, started_at="t0", rubric_name="r", rubric_hash="h")

    # 3 files: one clean (certifiable), one with an issue (not compliant), one error.
    st.save_file_result("s1", _file("a.html", score=100, compliant=1), "t1")
    st.save_file_result("s1", _file("b.html", score=70, compliant=0,
                                    issues=[{"ruleId": "1.1.1", "wcag": "1.1.1 Non-text Content", "severity": "SERIOUS"}]), "t1")
    st.save_file_result("s1", _file("c.html", status="error", score=None, compliant=0), "t1")

    # Counter: only the 3rd bump reaches total → triggers finalize.
    assert st.bump_files_done("s1") == (1, 3)
    assert st.bump_files_done("s1") == (2, 3)
    assert st.bump_files_done("s1") == (3, 3)

    summary = st.finalize_scan_run("s1", "t2")
    assert summary["files"] == 3           # COUNT(file_records)
    assert summary["certifiable"] == 1     # Σ compliant
    assert summary["error"] == 1           # status='error'
    assert summary["uncertain"] == 0
    assert summary["avg_score"] == 85      # mean(100, 70), error excluded

    res = st.get_scan("s1")
    assert res["run"]["status"] == "done"
    assert len(res["files"]) == 3          # get_scan returns the file rows


def test_per_user_isolation(st):
    # Two users each run a scan; each only sees their own.
    st.init_scan_run("sA", "drive", 1, "t0", "r", "h", owner="alice@x.com")
    st.save_file_result("sA", _file("a.html"), "t1"); st.finalize_scan_run("sA", "t2")
    st.init_scan_run("sB", "drive", 1, "t0", "r", "h", owner="bob@x.com")
    st.save_file_result("sB", _file("b.html"), "t1"); st.finalize_scan_run("sB", "t2")

    assert [s["id"] for s in st.list_scans(owner="alice@x.com")] == ["sA"]
    assert [s["id"] for s in st.list_scans(owner="bob@x.com")] == ["sB"]
    assert st.get_scan("sA", owner="alice@x.com") is not None     # own scan: visible
    assert st.get_scan("sA", owner="bob@x.com") is None           # other's scan: hidden
    assert st.get_scan("sA") is not None                          # no owner = no check (internal)


def test_save_file_result_idempotent(st):
    st.init_scan_run("s2", "drive", total=1, started_at="t0", rubric_name="r", rubric_hash="h")
    f = _file("x.html", issues=[{"ruleId": "3.1.1", "wcag": "3.1.1 Language of Page", "severity": "SERIOUS"}])
    st.save_file_result("s2", f, "t1")
    st.save_file_result("s2", f, "t1")     # retried — must not double-insert
    res = st.get_scan("s2")
    assert len(res["files"]) == 1
    # exactly one issue row (delete-then-insert), not two
    with st._db.cursor() as cur:
        st._db.execute(cur, "SELECT COUNT(*) AS n FROM issue_records WHERE scan_id='s2'")
        assert st._db.fetchone(cur)["n"] == 1
