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
