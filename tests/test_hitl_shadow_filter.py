"""The review inbox must not ask a human to fix ACP's own output.

get_scan already drops ACP-generated copies that shadow their source (shadowed_acp_outputs).
list_hitl_queue did not, so a scan showing ONE document in the dashboard showed TWO identical
"19 findings · Non-text Content" cards in the inbox — one of them the remediated copy ACP
itself wrote. Worse, the vision proposals landed on that phantom's row, so the reviewer opened
the real document's card and found no AI draft at all.

Observed live (Langfuse, scan d191fec760a3): all 19 llava calls described
'Movate_AccessOps_Healthcare_v6 (1).pptx' — ACP's own remediated copy.
"""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "hsf.db")
    return store_mod.Store()


def _rec(name, stamped):
    return {"file": name, "engine": "office", "status": "analysed", "score": 40, "compliant": 0,
            "skipped_rules": 0, "acp_stamped": stamped,
            "issues": [{"ruleId": "PPTX-ALT-001", "wcag": "1.1.1", "severity": "CRITICAL"}]}


def _queue(st, sid, f, rule="1.1.1"):
    st.queue_hitl_review_for_file(sid, f, [{"rule_id": rule, "rule_name": "Non-text Content",
                                            "finding_count": 19}])


def _shadow_pair(st, sid="s1"):
    st.init_scan_run(sid, "drive", 2, "t0", "r", "h")
    st.save_file_result(sid, _rec("deck.pptx", None), "t1")
    st.save_file_result(sid, _rec("deck (1).pptx", "2026-07-09"), "t1")
    _queue(st, sid, "deck.pptx")
    _queue(st, sid, "deck (1).pptx")


def test_inbox_hides_review_items_for_acp_generated_shadow_copies(st):
    _shadow_pair(st)
    files = [f["file"] for f in st.get_scan("s1")["files"]]
    inbox = [r["file"] for r in st.list_hitl_queue(scan_id="s1")]
    assert files == ["deck.pptx"]           # dashboard already got this right
    assert inbox == ["deck.pptx"]           # the inbox must agree with it


def test_the_phantom_card_is_gone_not_merely_deduped(st):
    _shadow_pair(st)
    assert len(st.list_hitl_queue(scan_id="s1")) == 1


def test_a_stamped_file_standing_alone_is_still_reviewable(st):
    """A certified document published back into the estate shadows nothing. It must still be
    scanned, counted and reviewed — dropping it would hide a real document."""
    st.init_scan_run("s2", "drive", 1, "t0", "r", "h")
    st.save_file_result("s2", _rec("published.pptx", "2026-07-09"), "t1")
    _queue(st, "s2", "published.pptx")
    assert [r["file"] for r in st.list_hitl_queue(scan_id="s2")] == ["published.pptx"]


def test_filtering_is_per_scan_not_global(st):
    """'deck (1).pptx' is a shadow in s1. In s3, where no unstamped sibling exists, it is a
    document in its own right."""
    _shadow_pair(st, "s1")
    st.init_scan_run("s3", "drive", 1, "t0", "r", "h")
    st.save_file_result("s3", _rec("deck (1).pptx", "2026-07-09"), "t1")
    _queue(st, "s3", "deck (1).pptx")
    assert [r["file"] for r in st.list_hitl_queue(scan_id="s1")] == ["deck.pptx"]
    assert [r["file"] for r in st.list_hitl_queue(scan_id="s3")] == ["deck (1).pptx"]


def test_the_unscoped_inbox_filters_every_scan(st):
    """The inbox is normally read without a scan_id — the filter must still apply."""
    _shadow_pair(st, "s1")
    _shadow_pair(st, "s4")
    assert [r["file"] for r in st.list_hitl_queue()] == ["deck.pptx", "deck.pptx"]


def test_the_row_is_hidden_from_the_read_not_deleted(st):
    """Same posture as get_scan: filter the read, never destroy evidence."""
    _shadow_pair(st)
    with st._db.cursor() as cur:
        st._db.execute(cur, "SELECT COUNT(*) AS n FROM hitl_queue WHERE scan_id=%s", ("s1",))
        assert st._db.fetchone(cur)["n"] == 2       # both rows still on disk


def test_status_filter_still_applies_alongside_the_shadow_filter(st):
    _shadow_pair(st)
    assert [r["file"] for r in st.list_hitl_queue(status="pending", scan_id="s1")] == ["deck.pptx"]


def test_a_scan_with_no_file_records_does_not_crash(st):
    st.init_scan_run("s5", "drive", 0, "t0", "r", "h")
    _queue(st, "s5", "ghost.pptx")
    assert [r["file"] for r in st.list_hitl_queue(scan_id="s5")] == ["ghost.pptx"]
