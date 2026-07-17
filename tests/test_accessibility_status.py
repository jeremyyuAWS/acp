"""ADR 0026 — Accessibility Status model (file scope, PR 1).

Tests the pure derivation over a certification-facts document: the bucket identity (the honesty
invariant), the coverage-vs-status split, the human-verification overlay, clamping, the state
machine, and the compose seam over a fake store.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import accessibility_status as st  # noqa: E402

BUCKETS = ("automatically_verified", "human_verified", "needs_review",
           "needs_remediation", "not_automatically_assessable")


def _doc(**kw):
    d = {"file": "f.pdf", "evaluated": 0, "failing": 0, "review": 0, "not_evaluated": 0,
         "remediated": 0, "review_criteria": []}
    d.update(kw)
    return d


def _invariant(m):
    assert sum(m[b] for b in BUCKETS) == m["in_scope"]


# ── the identity holds across a spread of shapes ──────────────────────────────
def test_bucket_identity_holds():
    cases = [
        _doc(evaluated=18, failing=0, review=2, not_evaluated=0),
        _doc(evaluated=10, failing=4, review=3, not_evaluated=5, remediated=1,
             review_criteria=["1.4.1", "1.4.11", "1.3.3"]),
        _doc(evaluated=0, failing=0, review=0, not_evaluated=20),
        _doc(evaluated=20, failing=20, review=0, not_evaluated=0, remediated=20),
    ]
    for d in cases:
        m = st.derive_file_status(d, [], 0)
        _invariant(m)


def test_ready_when_all_verified():
    m = st.derive_file_status(_doc(evaluated=20, failing=0, review=0), [], 0)
    assert m["state"] == st.STATE_READY
    assert m["automatically_verified"] == 20 and m["needs_review"] == 0
    assert m["cta"] == "Generate Report"
    _invariant(m)


def test_ready_after_review_and_estimate():
    d = _doc(evaluated=16, review=2, not_evaluated=2, review_criteria=["1.4.1", "1.4.11"])
    m = st.derive_file_status(d, [], 0, per_item_secs=60)
    assert m["state"] == st.STATE_READY_AFTER_REVIEW
    assert m["needs_review"] == 2
    assert m["est_review_secs"] == 120           # 2 items × 60s, a labeled estimate
    assert m["cta"] == "Review Findings"


def test_human_verified_overlay_moves_out_of_needs_review():
    d = _doc(evaluated=16, review=2, not_evaluated=2, review_criteria=["1.4.1", "1.4.11"])
    m = st.derive_file_status(d, ["1.4.1"], 0)   # human approved one review
    assert m["needs_review"] == 1
    assert m["human_verified"] == 1
    assert m["state"] == st.STATE_READY_AFTER_REVIEW
    _invariant(m)


def test_needs_remediation_wins():
    d = _doc(evaluated=10, failing=3, review=1, remediated=1, review_criteria=["1.4.1"])
    m = st.derive_file_status(d, [], 5)          # even with unapplied, fails come first
    assert m["state"] == st.STATE_NEEDS_REMEDIATION
    assert m["needs_remediation"] == 2           # 3 failing − 1 remediated
    assert m["human_verified"] == 1              # the remediated fail
    assert m["cta"] == "Start Remediation"
    _invariant(m)


def test_apply_approved_gate():
    # No open fails/reviews, but approved values not yet written → promise ≠ fix.
    d = _doc(evaluated=12, failing=1, review=0, remediated=1)   # the fail is remediated
    m = st.derive_file_status(d, [], 2)
    assert m["state"] == st.STATE_APPLY_APPROVED
    assert m["cta"] == "Apply Approved Fixes"


def test_remediated_over_failing_is_clamped():
    # remediated distinct-SC count can exceed the current failing count; buckets must stay honest.
    d = _doc(evaluated=5, failing=2, review=0, remediated=9)
    m = st.derive_file_status(d, [], 0)
    assert m["needs_remediation"] == 0
    assert m["human_verified"] == 2              # clamped to failing, not 9
    _invariant(m)


def test_coverage_vs_status_split():
    d = _doc(evaluated=16, review=2, not_evaluated=2)
    m = st.derive_file_status(d, [], 0)
    assert m["in_scope"] == 20
    assert m["coverage"]["evaluable"] == 18      # ACP had a method for 18 of 20 ("did ACP look?")
    assert m["coverage"]["total"] == 20
    assert m["not_automatically_assessable"] == 2


def test_transient_states_override():
    d = _doc(evaluated=20)
    assert st.derive_file_status(d, [], 0, assessing=True)["state"] == st.STATE_ASSESSING
    assert st.derive_file_status(d, [], 0, revalidating=True)["state"] == st.STATE_REVALIDATING
    assert st.derive_file_status(d, [], 0, certified=True)["state"] == st.STATE_CERTIFIED


# ── compose seam over a fake store ────────────────────────────────────────────
class _FakeStore:
    def __init__(self, docs, decisions, unapplied):
        self._docs, self._decisions, self._unapplied = docs, decisions, unapplied
    def get_certification_facts(self, sid):
        return {"documents": self._docs}
    def list_decisions(self, sid, limit=500):
        return self._decisions
    def count_unapplied_approved_values(self, sid, file):
        return self._unapplied


def test_file_status_composes():
    docs = [_doc(file="a.pdf", evaluated=16, review=2, not_evaluated=2,
                 review_criteria=["1.4.1", "1.4.11"])]
    decisions = [{"action": "hitl.approved", "file": "a.pdf", "rule_id": "1.4.1"}]
    store = _FakeStore(docs, decisions, 0)
    m = st.file_status(store, "s1", "a.pdf")
    assert m["available"] is True
    assert m["human_verified"] == 1 and m["needs_review"] == 1


def test_file_status_missing_file():
    store = _FakeStore([_doc(file="a.pdf")], [], 0)
    m = st.file_status(store, "s1", "gone.pdf")
    assert m == {"available": False, "reason": "file_not_in_scan"}
