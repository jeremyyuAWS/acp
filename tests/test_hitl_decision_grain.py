"""One human decision counts once, however many drafts it covered.

routes/hitl.py writes one hitl_events row per model call on a card, because the per-draft
ai_value/final_value pair is what the edit-rate calibration reads. Every REVIEWER count then
read that fan-out as separate reviews: a .docx with five unlabelled images is one card and one
decision, and it counted as five reviews, repeated its single review_ms five times in the
median, and moved the rule five approvals closer to the gate that nominates a criterion for
AI-Assisted mode.

decision_primary marks the row that stands for the decision. These tests pin both grains: work
counts over decisions, the edit signal over drafts.
"""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "hitl-grain.db")
    return store_mod.Store()


def _card(st, item_id, *, drafts, review_ms, action="approve", edited_index=None, file="report.docx"):
    """One decision on a card carrying `drafts` model calls, written as routes/hitl.py writes it."""
    for index in range(drafts):
        st.record_hitl_event("s1", file, "1.1.1", item_id, action,
                             edited=(index == edited_index),
                             review_ms=review_ms,
                             ai_value="a draft",
                             final_value=("a rewrite" if index == edited_index else "a draft"),
                             model_call_id=f"call-{item_id}-{index}",
                             decision_primary=(index == 0))


def test_multi_draft_card_counts_as_one_review(st):
    _card(st, "i1", drafts=5, review_ms=60000)          # 5 images, 60s, accepted as drafted
    _card(st, "i2", drafts=1, review_ms=20000, edited_index=0)

    a = st.hitl_analytics("s1")
    assert a["total"] == 2                               # two decisions, not six rows
    assert a["reviewed"] == 2
    assert a["by_action"] == {"approve": 2}
    assert a["timed_reviews"] == 2
    assert a["median_review_ms"] == 40000                # median of {20000, 60000}
    assert a["avg_review_ms"] == 40000
    # The drafts are still all there — the fan-out is kept, only the counting is split.
    assert a["drafts"] == 6
    assert a["approved_drafts"] == 6
    assert a["edit_rate"] == round(1 / 6, 3)             # one rewritten draft in six accepted


def test_maturity_gate_counts_human_decisions_not_drafts(st):
    """_MATURITY_MIN_APPROVALS asks for ten reviews. Two five-image cards are two."""
    for n in range(2):
        _card(st, f"i{n}", drafts=5, review_ms=30000)

    a = st.hitl_analytics("s1")
    rule = next(b for b in a["by_rule"] if b["key"] == "1.1.1")
    assert rule["approved"] == 2                          # decisions
    assert rule["approved_drafts"] == 10                  # drafts they covered
    assert rule["reviewed"] == 2
    assert a["promotable_rules"] == []                    # two reviews is not ten

    for n in range(2, 10):
        _card(st, f"i{n}", drafts=1, review_ms=30000)
    assert st.hitl_analytics("s1")["promotable_rules"] == ["1.1.1"]


def test_edit_rate_is_per_draft_not_per_card(st):
    """A reviewer who rewrote one image of five edited one draft in five, not one card in one."""
    _card(st, "i1", drafts=5, review_ms=90000, action="edit", edited_index=1)

    a = st.hitl_analytics("s1")
    assert a["by_action"] == {"edit": 1}
    assert a["approval_rate"] == 1.0
    assert a["edit_rate"] == 0.2
    rule = next(b for b in a["by_rule"] if b["key"] == "1.1.1")
    assert (rule["edited"], rule["approved_drafts"], rule["edit_rate"]) == (1, 5, 0.2)


def test_rejection_histogram_counts_decisions(st):
    """One rejected card is one rejection, whatever it held — the histogram ranks reviewer acts."""
    _card(st, "i1", drafts=4, review_ms=15000, action="reject")
    st.record_hitl_event("s1", "report.docx", "1.1.1", "i1", "reject",
                         reject_reason="hallucinated", review_ms=15000, decision_primary=False)

    a = st.hitl_analytics("s1")
    assert a["by_action"] == {"reject": 1}
    assert a["reviewed"] == 1


def test_legacy_rows_without_the_flag_are_grouped_back_to_decisions(st):
    """Rows written before the column existed carry NULL and are still not five reviews.

    They share item, action and the card-level review_ms, which is the burst's fingerprint.
    Written through the DB directly because record_hitl_event can no longer produce a NULL."""
    with st._db.cursor() as cur:
        for index in range(5):
            st._db.execute(cur,
                "INSERT INTO hitl_events(id,scan_id,file,rule_id,item_id,action,edited,review_ms,"
                "created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (f"legacy-{index}", "s1", "old.docx", "1.1.1", "i-old", "approve", 0, 45000,
                 "2026-09-01T00:00:00Z"))

    a = st.hitl_analytics("s1")
    assert a["total"] == 1
    assert a["timed_reviews"] == 1
    assert a["median_review_ms"] == 45000
    assert a["drafts"] == 5


def test_flagged_and_legacy_rows_coexist(st):
    """A backfill is not needed and not attempted: the flag wins where it is set, and legacy
    rows are grouped independently, so a database mid-migration reports both correctly."""
    with st._db.cursor() as cur:
        for index in range(3):
            st._db.execute(cur,
                "INSERT INTO hitl_events(id,scan_id,file,rule_id,item_id,action,edited,review_ms,"
                "created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (f"legacy-{index}", "s1", "old.docx", "1.1.1", "i-old", "approve", 0, 10000,
                 "2026-09-01T00:00:00Z"))
    _card(st, "i-new", drafts=4, review_ms=30000)

    a = st.hitl_analytics("s1")
    assert a["total"] == 2                                # one legacy decision + one new one
    assert a["drafts"] == 7


def test_analytics_are_scoped_to_the_owner(st):
    st.init_scan_run("mine", "drive", 1, "t0", "r", "h", owner="deva@example.com")
    st.init_scan_run("theirs", "drive", 1, "t0", "r", "h", owner="someone@else.com")
    st.record_hitl_event("mine", "a.docx", "1.1.1", "i1", "approve", review_ms=1000)
    st.record_hitl_event("theirs", "b.docx", "1.1.1", "i2", "approve", review_ms=1000)

    assert st.hitl_analytics(None, owner="deva@example.com")["total"] == 1
    assert st.hitl_analytics(None, owner="someone@else.com")["total"] == 1
    assert st.hitl_analytics(None)["total"] == 2          # unscoped is still available in-process
