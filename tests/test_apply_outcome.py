"""apply_outcome — a refused write is readable on the approved row it refused.

_apply_one_value_kind writes an approved value into a working copy, re-scans, and on a criterion
that still fails (or a re-scan that could not run) logs `apply.unverified` and returns the
pre-write bytes. The row stays approved + unapplied and the document is unchanged. These tests
pin the read side: the decision is parsed conservatively, matched to the row it explains, and
attached as `apply_outcome` by list_hitl_queue — nothing more, and never to a pending row.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import store as store_mod  # noqa: E402
from apply_outcome import (  # noqa: E402
    COULD_NOT_VERIFY, STILL_FAILING, annotate_apply_outcomes, apply_outcome_for, normalise_sc,
    parse_unverified,
)

# The two detail strings _apply_one_value_kind actually writes (handlers.py), verbatim in shape.
STILL = "wrote 1 image-of-text alt text value(s) but ['1.4.5', '1.4.9'] still fails on re-scan"
COULD_NOT = ("wrote 2 alt text value(s) but could not verify ['1.1.1']: engine missing: "
             "tesseract. Credit withheld; the approved value is kept for retry")


# ── parsing ───────────────────────────────────────────────────────────────────

def test_parse_still_failing_names_every_criterion():
    assert parse_unverified(STILL) == {"outcome": STILL_FAILING,
                                       "criteria": ["1.4.5", "1.4.9"], "reason": ""}


def test_parse_could_not_verify_keeps_the_reason_and_drops_the_boilerplate():
    p = parse_unverified(COULD_NOT)
    assert p["outcome"] == COULD_NOT_VERIFY
    assert p["criteria"] == ["1.1.1"]
    assert p["reason"] == "engine missing: tesseract"


def test_parse_refuses_to_assert_on_an_unrecognised_detail():
    assert parse_unverified("wrote 1 value(s); something new happened") == {}
    assert parse_unverified(None) == {}
    assert parse_unverified("") == {}


def test_normalise_sc_accepts_every_rule_id_form_the_queue_uses():
    assert normalise_sc("1.4.5") == "1.4.5"
    assert normalise_sc("SC_1_4_5") == "1.4.5"
    assert normalise_sc("1.4.5 Images of Text") == "1.4.5"
    assert normalise_sc("") == ""
    assert normalise_sc(None) == ""


# ── matching a decision to a row ──────────────────────────────────────────────

def _row(**kw) -> dict:
    base = {"id": "it1", "scan_id": "s1", "file": "deck.pptx", "rule_id": "1.4.5",
            "status": "approved", "applied": 0, "reviewed_at": "2026-09-07T03:00:00+00:00"}
    base.update(kw)
    return base


def _dec(ts="2026-09-07T03:01:00+00:00", detail=STILL, **kw) -> dict:
    base = {"ts": ts, "action": "apply.unverified", "scan_id": "s1", "file": "deck.pptx",
            "detail": detail}
    base.update(kw)
    return base


def test_matching_decision_becomes_the_outcome():
    out = apply_outcome_for(_row(), [_dec()])
    assert out == {"outcome": STILL_FAILING, "criteria": ["1.4.5", "1.4.9"], "reason": "",
                   "ts": "2026-09-07T03:01:00+00:00"}


def test_pending_and_applied_rows_get_nothing():
    assert apply_outcome_for(_row(status="pending"), [_dec()]) is None
    assert apply_outcome_for(_row(applied=1), [_dec()]) is None
    assert apply_outcome_for(None, [_dec()]) is None


def test_a_decision_from_before_this_approval_is_not_about_it():
    assert apply_outcome_for(_row(), [_dec(ts="2026-09-07T02:59:00+00:00")]) is None


def test_a_missing_reviewed_at_does_not_hide_a_real_outcome():
    assert apply_outcome_for(_row(reviewed_at=None), [_dec()]) is not None


def test_a_decision_naming_other_criteria_or_another_file_is_ignored():
    assert apply_outcome_for(_row(rule_id="1.1.1"), [_dec()]) is None
    assert apply_outcome_for(_row(), [_dec(file="other.pptx")]) is None
    assert apply_outcome_for(_row(), [_dec(scan_id="s2")]) is None
    assert apply_outcome_for(_row(), [_dec(action="apply.applied")]) is None


def test_the_rule_id_form_on_the_row_does_not_matter():
    assert apply_outcome_for(_row(rule_id="SC_1_4_5"), [_dec()]) is not None


def test_the_newest_matching_decision_wins():
    older = _dec(ts="2026-09-07T03:01:00+00:00", detail=COULD_NOT.replace("'1.1.1'", "'1.4.5'"))
    newer = _dec(ts="2026-09-07T03:05:00+00:00", detail=STILL)
    out = apply_outcome_for(_row(), [newer, older])
    assert out["outcome"] == STILL_FAILING and out["ts"] == newer["ts"]


def test_annotate_adds_the_key_only_where_it_applies():
    rows = [_row(), _row(id="it2", status="pending")]
    annotate_apply_outcomes(rows, [_dec()])
    assert rows[0]["apply_outcome"]["outcome"] == STILL_FAILING
    assert "apply_outcome" not in rows[1]


# ── through the store: list_hitl_queue carries it on the wire ─────────────────

@pytest.fixture()
def st(monkeypatch):
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "outcome.db")
    s = store_mod.Store()
    s.init_scan_run("s1", "drive", 1, "t0", "r", "h")
    return s


def _queue(st, item_id: str, rule_id: str = "1.4.5") -> None:
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "INSERT INTO hitl_queue(id,created_at,scan_id,file,rule_id,rule_name,finding_count,"
            "status,proposals,evidence) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (item_id, "2026-09-07T02:00:00+00:00", "s1", "deck.pptx", rule_id, "Images of Text",
             1, "pending", "[]", "[]"))


def test_list_hitl_queue_attaches_the_outcome_to_the_refused_row(st):
    _queue(st, "it1")
    st.update_hitl_item("it1", "approved", approved_value="Benefits at a glance")
    st.log_decision("system", "apply.unverified", scan_id="s1", file="deck.pptx", detail=STILL)
    rows = {r["id"]: r for r in st.list_hitl_queue(scan_id="s1")}
    out = rows["it1"]["apply_outcome"]
    assert out["outcome"] == STILL_FAILING
    assert out["criteria"] == ["1.4.5", "1.4.9"]
    assert out["ts"]


def test_a_pending_row_in_the_same_scan_is_untouched(st):
    _queue(st, "it1")
    _queue(st, "it2", rule_id="1.1.1")
    st.update_hitl_item("it1", "approved", approved_value="x")
    st.log_decision("system", "apply.unverified", scan_id="s1", file="deck.pptx", detail=STILL)
    rows = {r["id"]: r for r in st.list_hitl_queue(scan_id="s1")}
    assert "apply_outcome" in rows["it1"]
    assert "apply_outcome" not in rows["it2"]


def test_a_credited_row_carries_no_outcome_even_after_an_earlier_refusal(st):
    _queue(st, "it1")
    st.update_hitl_item("it1", "approved", approved_value="x")
    st.log_decision("system", "apply.unverified", scan_id="s1", file="deck.pptx", detail=STILL)
    st.mark_row_applied("it1")
    rows = {r["id"]: r for r in st.list_hitl_queue(scan_id="s1")}
    assert "apply_outcome" not in rows["it1"]


def test_no_decision_no_key(st):
    _queue(st, "it1")
    st.update_hitl_item("it1", "approved", approved_value="x")
    rows = {r["id"]: r for r in st.list_hitl_queue(scan_id="s1")}
    assert "apply_outcome" not in rows["it1"]
