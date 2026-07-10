"""Approval certifies a file only when the approval IS the resolution.

Regression under test: approving a HITL item called mark_file_compliant_if_reviewed(), which
set compliant=1 and score=100 and advanced the file to Publish. But `approved_value` is only
ever stored as evidence — no remediator consumes it, no job is enqueued (routes/hitl.py). So
a reviewer could type alt text for a PPTX's ten undescribed images, click approve, and the
file was certified 100/100 as WCAG 1.1.1 conformant with its images still undescribed.

The split: a JUDGEMENT approval (no value — a contrast ratio accepted, a link text deemed
adequate) genuinely resolves the finding, because a re-scan can never clear it. A VALUE-FIX
approval (alt text, a title, a label) is a promise until the bytes are written.
"""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "certify.db")
    return store_mod.Store()


def _remediated_file(st, scan_id="s1", file="deck.pptx"):
    """A file that has been auto-remediated — the precondition for certify-on-approve."""
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "INSERT INTO file_records(scan_id,file,engine,status,score,compliant,skipped_rules,remediated_at) "
            "VALUES(%s,%s,'office','fail',60,0,0,'2026-07-09T00:00:00')", (scan_id, file))
        st._db.execute(cur,
            "INSERT INTO scan_runs(id,completed_at) VALUES(%s,'2026-07-09T00:00:00')", (scan_id,))
    return scan_id, file


def _queue(st, scan_id, file, rule_id, item_id):
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "INSERT INTO hitl_queue(id,scan_id,file,rule_id,status,created_at) "
            "VALUES(%s,%s,%s,%s,'pending','2026-07-09T00:00:00')", (item_id, scan_id, file, rule_id))


def test_judgement_approval_certifies(st):
    """1.4.3 contrast: the human sign-off IS the resolution — no value, nothing to write."""
    scan_id, file = _remediated_file(st)
    _queue(st, scan_id, file, "1.4.3", 1)
    st.update_hitl_item(1, "approved", None, None)          # approved with NO value
    assert st.count_unapplied_approved_values(scan_id, file) == 0
    assert st.mark_file_compliant_if_reviewed(scan_id, file) is True


def test_value_fix_approval_does_not_certify(st):
    """1.1.1 alt text: the value is stored as evidence but never written into the document."""
    scan_id, file = _remediated_file(st)
    _queue(st, scan_id, file, "1.1.1", 1)
    st.update_hitl_item(1, "approved", None, "A nurse reviews a chart with a patient.")
    assert st.count_unapplied_approved_values(scan_id, file) == 1
    assert st.mark_file_compliant_if_reviewed(scan_id, file) is False   # ← was True before the fix

    with st._db.cursor() as cur:
        st._db.execute(cur, "SELECT compliant, score FROM file_records WHERE scan_id=%s AND file=%s",
                       (scan_id, file))
        rec = st._db.fetchone(cur)
    assert rec["compliant"] == 0 and rec["score"] == 60   # untouched — not 100/100


def test_one_unapplied_value_blocks_an_otherwise_clean_file(st):
    """Mixed file: a judgement item and a value item, both approved. The value blocks it."""
    scan_id, file = _remediated_file(st)
    _queue(st, scan_id, file, "1.4.3", 1)
    _queue(st, scan_id, file, "1.1.1", 2)
    st.update_hitl_item(1, "approved", None, None)
    st.update_hitl_item(2, "approved", None, "Bar chart of Q3 revenue by region.")
    assert st.mark_file_compliant_if_reviewed(scan_id, file) is False


def test_blank_value_is_treated_as_a_judgement(st):
    """An empty or whitespace-only value is not content — it must not block certification."""
    scan_id, file = _remediated_file(st)
    _queue(st, scan_id, file, "1.4.3", 1)
    st.update_hitl_item(1, "approved", None, "   ")
    assert st.count_unapplied_approved_values(scan_id, file) == 0
    assert st.mark_file_compliant_if_reviewed(scan_id, file) is True


def test_still_blocked_while_an_item_is_unresolved(st):
    """Pre-existing behaviour, still enforced: any pending/rejected/skipped item blocks."""
    scan_id, file = _remediated_file(st)
    _queue(st, scan_id, file, "1.4.3", 1)
    _queue(st, scan_id, file, "1.4.6", 2)
    st.update_hitl_item(1, "approved", None, None)          # item 2 left pending
    assert st.mark_file_compliant_if_reviewed(scan_id, file) is False


def test_unremediated_file_never_certifies(st):
    scan_id, file = "s2", "raw.pptx"
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "INSERT INTO file_records(scan_id,file,engine,status,score,compliant,skipped_rules) "
            "VALUES(%s,%s,'office','fail',60,0,0)", (scan_id, file))
    _queue(st, scan_id, file, "1.4.3", 1)
    st.update_hitl_item(1, "approved", None, None)
    assert st.mark_file_compliant_if_reviewed(scan_id, file) is False
