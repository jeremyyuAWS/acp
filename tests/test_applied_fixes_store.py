"""applied_fixes persistence — the real value an AI fix wrote + image thumbnail, for the
'Recent AI fixes' surface (GET /scans/{sid}/applied-fixes)."""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture()
def st():
    import store as store_mod
    store_mod._SQLITE_PATH = Path(tempfile.mkdtemp()) / "applied-fixes-test.db"
    store_mod._SCHEMA[:] = [s for s in store_mod._SCHEMA
                            if not s.strip().upper().startswith("ALTER TABLE")]
    return store_mod.Store()


def test_record_and_list_roundtrip(st):
    st.record_applied_fix("s1", "deck.pptx", "SC_1_1_1", "A bar chart of Q3 revenue",
                          source="AI vision model (llava)", thumb="data:image/png;base64,AAAA", seq=0)
    st.record_applied_fix("s1", "deck.pptx", "SC_1_1_1", "A team photo",
                          source="AI vision model (llava)", thumb=None, seq=1)
    rows = st.list_applied_fixes("s1")
    assert len(rows) == 2
    vals = {r["value"] for r in rows}
    assert vals == {"A bar chart of Q3 revenue", "A team photo"}
    chart = next(r for r in rows if r["value"].startswith("A bar chart"))
    assert chart["thumb"] == "data:image/png;base64,AAAA"
    assert chart["file"] == "deck.pptx" and chart["rule_id"] == "SC_1_1_1"


def test_upsert_same_key_updates(st):
    st.record_applied_fix("s1", "d.pptx", "SC_1_1_1", "first", seq=0)
    st.record_applied_fix("s1", "d.pptx", "SC_1_1_1", "second", seq=0)   # same (scan,file,rule,seq)
    rows = st.list_applied_fixes("s1")
    assert len(rows) == 1 and rows[0]["value"] == "second"


def test_scoped_by_scan(st):
    st.record_applied_fix("s1", "a.pptx", "SC_1_1_1", "x", seq=0)
    st.record_applied_fix("s2", "b.pptx", "SC_1_1_1", "y", seq=0)
    assert [r["value"] for r in st.list_applied_fixes("s1")] == ["x"]
    assert [r["value"] for r in st.list_applied_fixes("s2")] == ["y"]
