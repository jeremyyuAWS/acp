"""Post-write validation is attributed to the exact reviewed AI call, never inferred."""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "outcomes.db")
    return store_mod.Store()


def _accepted_call(st, *, item_id="item-1", file="deck.pptx"):
    call_id = st.record_ai_call(surface="vision", provider="ollama", model="llava:13b",
                                zone="local", latency_ms=120, ok=True,
                                scan_id="scan-1", file=file)
    st.record_hitl_event("scan-1", file, "1.1.1", item_id, "approve",
                         model_call_id=call_id)
    return call_id


def test_post_write_outcome_links_the_exact_accepted_call(st):
    call_id = _accepted_call(st)
    assert st.record_ai_validation_outcomes(
        "scan-1", "deck.pptx", "1.1.1", ["item-1"], "verified_cleared",
        detail="cleared on re-scan") == 1
    with st._db.cursor() as cur:
        st._db.execute(cur, "SELECT * FROM ai_validation_outcomes")
        row = st._db.fetchone(cur)
    assert row["model_call_id"] == call_id
    assert row["outcome"] == "verified_cleared"
    assert row["item_id"] == "item-1"


def test_replay_is_idempotent_but_a_later_distinct_outcome_is_preserved(st):
    _accepted_call(st)
    args = ("scan-1", "deck.pptx", "1.1.1", ["item-1"])
    assert st.record_ai_validation_outcomes(*args, "could_not_verify") == 1
    assert st.record_ai_validation_outcomes(*args, "could_not_verify") == 0
    assert st.record_ai_validation_outcomes(*args, "verified_cleared") == 1
    with st._db.cursor() as cur:
        st._db.execute(cur, "SELECT outcome FROM ai_validation_outcomes ORDER BY created_at")
        assert {r["outcome"] for r in st._db.fetchall(cur)} == {
            "could_not_verify", "verified_cleared"}


def test_human_authored_review_creates_no_model_outcome(st):
    st.record_hitl_event("scan-1", "deck.pptx", "1.1.1", "human-item", "approve")
    assert st.record_ai_validation_outcomes(
        "scan-1", "deck.pptx", "1.1.1", ["human-item"], "verified_cleared") == 0


def test_outcome_keeps_the_review_items_actual_rule(st):
    _accepted_call(st, item_id="language-item")
    with st._db.cursor() as cur:
        st._db.execute(cur, "UPDATE hitl_events SET rule_id=%s WHERE item_id=%s",
                       ("3.1.2", "language-item"))
    assert st.record_ai_validation_outcomes(
        "scan-1", "deck.pptx", "display-lane", ["language-item"],
        "verified_cleared") == 1
    with st._db.cursor() as cur:
        st._db.execute(cur, "SELECT rule_id FROM ai_validation_outcomes")
        assert st._db.fetchone(cur)["rule_id"] == "3.1.2"


def test_unknown_outcome_is_rejected(st):
    with pytest.raises(ValueError, match="unsupported AI validation outcome"):
        st.record_ai_validation_outcomes(
            "scan-1", "deck.pptx", "1.1.1", ["item-1"], "probably_fixed")
