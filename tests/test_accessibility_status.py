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


def test_not_applicable_leaves_the_denominator():
    # Two review criteria: the reviewer approves 1.4.1 and marks 1.4.11 out-of-scope (not applicable).
    d = _doc(evaluated=16, review=2, not_evaluated=2, review_criteria=["1.4.1", "1.4.11"])
    base = st.derive_file_status(d, [], 0)                       # nothing decided yet
    m = st.derive_file_status(d, ["1.4.1"], 0, na_review_scs=["1.4.11"])
    assert m["not_applicable"] == 1
    assert m["not_applicable_criteria"] == ["1.4.11"]
    assert m["human_verified"] == 1                              # 1.4.1 approved; NA is NOT human_verified
    assert m["needs_review"] == 0                                # both review items settled
    # N/A leaves the denominator: in_scope (and the coverage total) drop by exactly one vs baseline,
    # so the reported coverage % rises rather than counting an out-of-scope item as unmet.
    assert m["in_scope"] == base["in_scope"] - 1
    assert m["coverage"]["total"] == base["coverage"]["total"] - 1
    _invariant(m)


def test_not_applicable_only_counts_this_files_review_criteria():
    # An out-of-scope SC that is not a review criterion of this file removes nothing (no phantom).
    d = _doc(evaluated=16, review=1, not_evaluated=3, review_criteria=["1.4.1"])
    m = st.derive_file_status(d, [], 0, na_review_scs=["9.9.9"])
    assert m["not_applicable"] == 0
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
    def get_certification_facts(self, sid, apply_document_selection=False):
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


# ── scan-scope aggregation (ADR 0026 PR 3) ────────────────────────────────────
class _FakeStore2(_FakeStore):
    def __init__(self, docs, decisions, unapplied_by_file):
        super().__init__(docs, decisions, 0)
        self._by_file = unapplied_by_file
    def count_unapplied_approved_values(self, sid, file):
        return self._by_file.get(file, 0)


def test_scan_status_sums_files_and_rederives_state():
    docs = [
        _doc(file="a.pdf", evaluated=18, failing=0, review=2, not_evaluated=0,
             review_criteria=["1.4.1", "1.4.11"]),
        _doc(file="b.docx", evaluated=15, failing=2, review=1, not_evaluated=2,
             remediated=1, review_criteria=["1.3.3"]),
    ]
    decisions = [{"action": "hitl.approved", "file": "a.pdf", "rule_id": "1.4.1"}]
    m = st.scan_status(_FakeStore2(docs, decisions, {}), "s1")
    assert m["available"] and m["scope"] == "scan" and m["documents"] == 2
    assert m["in_scope"] == 38   # 20 (a.pdf) + 18 (b.docx: 15 evaluated + 1 review + 2 not_evaluated)
    # buckets sum across files and the identity still holds at scan scope
    assert sum(m[b] for b in ("automatically_verified", "human_verified", "needs_review",
                              "needs_remediation", "not_automatically_assessable")) == m["in_scope"]
    assert m["needs_review"] == 2          # (2-1 approved) on a.pdf + 1 on b.docx
    assert m["human_verified"] == 2        # 1 approved review + 1 remediated fail
    assert m["needs_remediation"] == 1     # b.docx: 2 failing − 1 remediated
    assert m["state"] == st.STATE_NEEDS_REMEDIATION   # fails dominate at scan scope too


def test_scan_status_ready_and_empty():
    clean = [_doc(file="a.pdf", evaluated=20)]
    m = st.scan_status(_FakeStore2(clean, [], {}), "s1")
    assert m["state"] == st.STATE_READY and m["needs_review"] == 0
    empty = st.scan_status(_FakeStore2([], [], {}), "s1")
    assert empty == {"available": False, "reason": "no_documents"}


def test_scan_status_unapplied_gate_aggregates():
    docs = [_doc(file="a.pdf", evaluated=20), _doc(file="b.pdf", evaluated=20)]
    m = st.scan_status(_FakeStore2(docs, [], {"b.pdf": 3}), "s1")
    assert m["unapplied_approved"] == 3
    assert m["state"] == st.STATE_APPLY_APPROVED


# ── confirm-the-pass (ADR 0026 / Epic 3) ──────────────────────────────────────
class _FakeStore3(_FakeStore):
    def __init__(self, trace_rows):
        super().__init__([], [], 0)
        self._traces = trace_rows
        self.logged = []
    def get_trace_row(self, sid, file, rule_id):
        return self._traces.get((file, rule_id))
    def log_decision(self, actor, action, *, scan_id=None, file=None, rule_id=None, detail=None):
        self.logged.append({"actor": actor, "action": action, "scan_id": scan_id,
                            "file": file, "rule_id": rule_id, "detail": detail})


def test_confirm_writes_the_same_immutable_approval():
    store = _FakeStore3({("a.pdf", "1.4.11"): {"outcome": "REVIEW"}})
    r = st.confirm_review_criterion(store, "s1", "a.pdf", "1.4.11", "reviewer@org")
    assert r["ok"] is True
    assert store.logged == [{
        "actor": "reviewer@org", "action": "hitl.approved", "scan_id": "s1",
        "file": "a.pdf", "rule_id": "1.4.11",
        "detail": "Criterion confirmed by human review (confirm-the-pass)"}]


def test_confirm_refuses_non_review_outcomes():
    store = _FakeStore3({("a.pdf", "1.4.3"): {"outcome": "FAIL"},
                         ("a.pdf", "2.4.2"): {"outcome": "PASS"}})
    fail = st.confirm_review_criterion(store, "s1", "a.pdf", "1.4.3", "r@org")
    assert fail == {"ok": False, "reason": "not_a_review_criterion", "outcome": "FAIL"}
    ok_pass = st.confirm_review_criterion(store, "s1", "a.pdf", "2.4.2", "r@org")
    assert ok_pass["ok"] is False                      # a PASS needs nothing — no wave-through
    assert store.logged == []                          # nothing written on refusal


def test_confirm_rejects_bad_input():
    store = _FakeStore3({})
    assert st.confirm_review_criterion(store, "s1", "a.pdf", "DROP TABLE", "r@org")["reason"] == "invalid_criterion"
    assert st.confirm_review_criterion(store, "s1", "a.pdf", "9.9.9", "r@org")["reason"] == "criterion_not_in_scan"
    assert store.logged == []


def test_confirmed_review_flows_into_human_verified():
    """The end-to-end honesty loop: confirm writes hitl.approved → file_status counts it."""
    store = _FakeStore3({("a.pdf", "1.4.11"): {"outcome": "REVIEW"}})
    st.confirm_review_criterion(store, "s1", "a.pdf", "1.4.11", "r@org")
    doc = _doc(file="a.pdf", evaluated=18, review=2, review_criteria=["1.4.1", "1.4.11"])
    store._docs = [doc]
    store._decisions = store.logged                    # the write IS the read
    m = st.file_status(store, "s1", "a.pdf")
    assert m["human_verified"] == 1 and m["needs_review"] == 1


# ── folder scope (ADR 0026 PR 3): the same summation over a path-prefix subset ────────────────
def test_folder_status_is_the_scan_summation_over_a_prefix_subset():
    docs = [
        _doc(file="reports/q1.pdf", evaluated=18, failing=0, review=2, not_evaluated=0,
             review_criteria=["1.4.1", "1.4.11"]),
        _doc(file="reports/q2.pdf", evaluated=20),
        _doc(file="slides/deck.pptx", evaluated=15, failing=2, review=1, not_evaluated=2,
             review_criteria=["1.3.3"]),
    ]
    store = _FakeStore2(docs, [], {})
    folder = st.scan_status(store, "s1", path_prefix="reports/")
    assert folder["available"] and folder["scope"] == "folder"
    assert folder["path_prefix"] == "reports/" and folder["documents"] == 2
    # the failing deck is outside the folder → the folder is only waiting on its reviews
    assert folder["needs_remediation"] == 0 and folder["needs_review"] == 2
    assert folder["state"] == st.STATE_READY_AFTER_REVIEW
    # identity holds at folder scope too
    assert sum(folder[b] for b in ("automatically_verified", "human_verified", "needs_review",
                                   "needs_remediation", "not_automatically_assessable")) == folder["in_scope"]
    # and folder + complement reconcile with the whole scan (sum-over-subset by construction)
    whole = st.scan_status(store, "s1")
    rest = st.scan_status(store, "s1", path_prefix="slides/")
    for k in ("in_scope", "resolved", "needs_review", "needs_remediation"):
        assert folder[k] + rest[k] == whole[k]


def test_folder_status_empty_prefix_degrades_honestly():
    docs = [_doc(file="reports/q1.pdf", evaluated=20)]
    m = st.scan_status(_FakeStore2(docs, [], {}), "s1", path_prefix="nope/")
    assert m == {"available": False, "reason": "no_documents"}


# ── F2/F3: the model names WHICH review criteria a human approved, not just how many ─────────────
def test_human_verified_criteria_lists_the_approved_intersection():
    d = _doc(evaluated=10, review=3, review_criteria=["1.4.1", "1.4.11", "1.3.3"])
    # approvals outside the file's review set are clamped out — never inflate the chips
    m = st.derive_file_status(d, ["1.4.11", "1.4.1", "9.9.9"], 0)
    assert m["human_verified_criteria"] == ["1.4.1", "1.4.11"]   # sorted, intersection only
    assert m["human_verified"] == len(m["human_verified_criteria"])
    m0 = st.derive_file_status(d, [], 0)
    assert m0["human_verified_criteria"] == []


# ── F4: scan_status prefers the batched store query (one call per scan, not per doc) ─────────────
def test_scan_status_uses_the_batched_unapplied_query_when_available():
    docs = [_doc(file="a.pdf", evaluated=20), _doc(file="b.pdf", evaluated=20)]

    class _BatchStore(_FakeStore2):
        def __init__(self):
            super().__init__(docs, [], {})
            self.batch_calls = 0
            self.per_file_calls = 0
        def count_unapplied_approved_values_by_file(self, sid):
            self.batch_calls += 1
            return {"b.pdf": 3}
        def count_unapplied_approved_values(self, sid, file):
            self.per_file_calls += 1
            return 0

    st_store = _BatchStore()
    m = st.scan_status(st_store, "s1")
    assert st_store.batch_calls == 1 and st_store.per_file_calls == 0
    assert m["unapplied_approved"] == 3 and m["state"] == st.STATE_APPLY_APPROVED

    # a store without the batch method still works (per-doc fallback)
    m2 = st.scan_status(_FakeStore2(docs, [], {"b.pdf": 2}), "s1")
    assert m2["unapplied_approved"] == 2
