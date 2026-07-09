"""HITL review telemetry — reviewer-time + edit/reject signal for the Review Workspace."""
import sys, tempfile
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture()
def st():
    import store as store_mod
    store_mod._SQLITE_PATH = Path(tempfile.mkdtemp()) / "hitl-events.db"
    store_mod._SCHEMA[:] = [s for s in store_mod._SCHEMA if not s.strip().upper().startswith("ALTER TABLE")]
    return store_mod.Store()


def test_events_and_analytics(st):
    st.record_hitl_event("s1", "a.pptx", "1.1.1", "i1", "approve", review_ms=4000)
    st.record_hitl_event("s1", "a.pptx", "1.1.1", "i2", "edit", edited=True, review_ms=12000,
                         ai_value="A dog", final_value="A guide dog in a harness")
    st.record_hitl_event("s1", "b.pptx", "1.4.3", "i3", "reject", review_ms=2000)
    st.record_hitl_event("s1", "c.pptx", "2.1.1", "i4", "skip")
    a = st.hitl_analytics("s1")
    assert a["total"] == 4
    assert a["by_action"] == {"approve": 1, "edit": 1, "reject": 1, "skip": 1}
    assert a["reviewed"] == 3                              # total - skip
    assert a["approval_rate"] == round(2 / 3, 3)          # (approve+edit)/reviewed
    assert a["edit_rate"] == round(1 / 2, 3)              # edited/approvals — the calibration signal
    assert a["avg_review_ms"] == 6000                     # (4000+12000+2000)/3; skip excluded


def test_analytics_scoped_by_scan(st):
    st.record_hitl_event("s1", "a", "1.1.1", "i1", "approve")
    st.record_hitl_event("s2", "b", "1.1.1", "i2", "approve")
    assert st.hitl_analytics("s1")["total"] == 1
    assert st.hitl_analytics()["total"] == 2              # global (no scan filter)


def test_empty_analytics_no_divide_by_zero(st):
    a = st.hitl_analytics("nope")
    assert a["total"] == 0 and a["approval_rate"] is None and a["avg_review_ms"] is None
