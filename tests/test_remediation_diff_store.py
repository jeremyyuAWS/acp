"""remediation_diff persistence — before→after evidence for the certification report."""
import sys, tempfile
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "remdiff.db")
    return store_mod.Store()


def test_record_and_get(st):
    st.record_remediation_diffs("s1", "d.pptx", [
        {"rule_id": "1.1.1", "before": "(no alt)", "after": "A red barn", "note": "vision"},
        {"rule_id": "1.4.3", "before": "#bbb", "after": "#111", "note": "contrast"},
    ])
    rows = st.get_remediation_diffs("s1", "d.pptx")
    assert [r["rule_id"] for r in rows] == ["1.1.1", "1.4.3"]
    assert rows[0]["after"] == "A red barn" and rows[0]["note"] == "vision"


def test_rerun_replaces_not_accumulates(st):
    st.record_remediation_diffs("s1", "d.pptx", [{"rule_id": "1.1.1", "before": "a", "after": "b"}])
    st.record_remediation_diffs("s1", "d.pptx", [{"rule_id": "2.4.2", "before": "c", "after": "d"}])
    rows = st.get_remediation_diffs("s1", "d.pptx")
    assert [r["rule_id"] for r in rows] == ["2.4.2"]   # replaced, not appended


def test_scoped_by_file(st):
    st.record_remediation_diffs("s1", "a.pptx", [{"rule_id": "1.1.1", "before": "a", "after": "b"}])
    st.record_remediation_diffs("s1", "b.pptx", [{"rule_id": "1.3.1", "before": "c", "after": "d"}])
    assert [r["rule_id"] for r in st.get_remediation_diffs("s1", "a.pptx")] == ["1.1.1"]
    assert [r["rule_id"] for r in st.get_remediation_diffs("s1", "b.pptx")] == ["1.3.1"]


# R15 — undo one applied fix. There is nothing to restore on the DOCUMENT (remediation never
# overwrites the source), so undo only ever means "stop claiming this finding is fixed" — clearing
# both evidence tables ACP's own resolution logic can key on.

def test_undo_removes_only_the_named_rule(st):
    st.record_remediation_diffs("s1", "d.pptx", [
        {"rule_id": "1.1.1", "before": "(no alt)", "after": "A red barn"},
        {"rule_id": "1.4.3", "before": "#bbb", "after": "#111"},
    ])
    undone = st.undo_applied_fix("s1", "d.pptx", "1.1.1")
    assert undone is True
    rows = st.get_remediation_diffs("s1", "d.pptx")
    assert [r["rule_id"] for r in rows] == ["1.4.3"]   # the other fix is untouched


def test_undo_also_clears_the_older_applied_fixes_table(st):
    # autoFixRows falls back to applied_fixes when remediation_diff has nothing for a scan (older
    # runs, or fix types the newer table doesn't cover) — undo has to clear whichever one is
    # actually claiming the fix, or the finding stays "resolved" through the fallback path.
    st.record_applied_fix("s1", "d.docx", "1.1.1", "A red barn", source="vision")
    undone = st.undo_applied_fix("s1", "d.docx", "1.1.1")
    assert undone is True


def test_undoing_a_fix_that_was_never_applied_reports_false(st):
    # Distinguishes "undone" from "there was nothing here to begin with" — the caller (and a test
    # of the route) can tell the two apart rather than reading a blanket 200 as success either way.
    assert st.undo_applied_fix("s1", "d.pptx", "9.9.9") is False


def test_undo_is_scoped_to_the_named_file(st):
    st.record_remediation_diffs("s1", "a.pptx", [{"rule_id": "1.1.1", "before": "a", "after": "b"}])
    st.record_remediation_diffs("s1", "b.pptx", [{"rule_id": "1.1.1", "before": "c", "after": "d"}])
    st.undo_applied_fix("s1", "a.pptx", "1.1.1")
    assert [r["rule_id"] for r in st.get_remediation_diffs("s1", "a.pptx")] == []
    assert [r["rule_id"] for r in st.get_remediation_diffs("s1", "b.pptx")] == ["1.1.1"]  # untouched
