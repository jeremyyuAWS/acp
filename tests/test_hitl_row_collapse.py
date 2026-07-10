"""One row per (scan, file, WCAG criterion).

Three writers put items on the queue for the same criterion:
  * queue_hitl_review_for_file  → rule_id '1.1.1'      (residual FAILs after remediation)
  * enqueue_proposals           → rule_id '1.1.1'      (the AI's drafted values)
  * queue_hitl_deferral         → rule_id '1.1.1/deferred'

scOf() strips the suffix, so the last one rendered as a SECOND "WCAG 1.1.1" card for the same
file. The reviewer opened one of them; the AI proposals were on the other. And the report's
evidence assembly does `setdefault((file, sc), row)`, so whichever row sorted first silently
won.

'auto/verify' is NOT a criterion — it is "an automatic fix was applied, please eyeball it" —
and must keep its own row.
"""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import store as store_mod  # noqa: E402


@pytest.fixture()
def st(monkeypatch):
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "rc.db")
    s = store_mod.Store()
    s.init_scan_run("s1", "drive", 1, "t0", "r", "h")
    return s


_P = [{"locator": "a", "before": "", "proposed_value": "A checkmark icon.",
       "rationale": "vision", "source": "AI vision model (llava)"}]


def _rows(st):
    return st.list_hitl_queue(scan_id="s1")


# ── the canonical id ──────────────────────────────────────────────────────────

def test_a_deferral_is_the_same_criterion_as_its_proposals():
    assert store_mod._canonical_rule_id("1.1.1/deferred") == "1.1.1"
    assert store_mod._canonical_rule_id("1.4.3/deferred") == "1.4.3"


def test_a_pseudo_rule_is_left_alone():
    """'auto/verify' is not a WCAG criterion and must not be folded into an SC row."""
    assert store_mod._canonical_rule_id("auto/verify") == "auto/verify"
    assert store_mod._canonical_rule_id("1.1.1") == "1.1.1"


# ── the collapse, in every writer order ───────────────────────────────────────

def test_proposals_then_deferral_is_one_row(st):
    st.enqueue_proposals("s1", "d.pptx", "1.1.1", _P, rule_name="Non-text Content")
    st.queue_hitl_deferral("s1", "d.pptx", "18 image(s) lack a faithful alt source", 18)
    assert len(_rows(st)) == 1
    assert len(_rows(st)[0]["proposals"]) == 1        # the AI's work survived the merge


def test_deferral_then_proposals_is_one_row_and_the_reviewer_sees_the_draft(st):
    """The failing order. The deferral used to open the row a reviewer opened, while the
    proposals opened a second one they never saw."""
    st.queue_hitl_deferral("s1", "d.pptx", "18 image(s) lack a faithful alt source", 18)
    st.enqueue_proposals("s1", "d.pptx", "1.1.1", _P, rule_name="Non-text Content")
    rows = _rows(st)
    assert len(rows) == 1
    assert len(rows[0]["proposals"]) == 1


def test_deferral_then_residual_review_is_one_row(st):
    st.queue_hitl_deferral("s1", "d.pptx", "14 image(s) lack a faithful alt source", 14)
    st.queue_hitl_review_for_file("s1", "d.pptx",
                                  [{"rule_id": "1.1.1", "rule_name": "Non-text Content",
                                    "finding_count": 19}])
    assert len(_rows(st)) == 1


def test_a_deferral_never_creates_a_second_item_to_webhook(st):
    """It returns None when it merged — callers fire a 'new item' webhook on the id."""
    st.enqueue_proposals("s1", "d.pptx", "1.1.1", _P, rule_name="Non-text Content")
    assert st.queue_hitl_deferral("s1", "d.pptx", "18 image(s) lack alt", 18) is None


# ── the finding count must never shrink ───────────────────────────────────────

def test_one_drafted_image_does_not_turn_19_findings_into_1(st):
    """enqueue_proposals overwrote finding_count with len(proposals). A deck with 19
    unlabelled images whose model drafted one announced '1 finding' — telling the reviewer
    18 images had gone away."""
    st.queue_hitl_review_for_file("s1", "d.pptx",
                                  [{"rule_id": "1.1.1", "rule_name": "Non-text Content",
                                    "finding_count": 19}])
    st.enqueue_proposals("s1", "d.pptx", "1.1.1", _P)
    assert _rows(st)[0]["finding_count"] == 19


def test_the_scan_count_wins_over_the_deferral_count(st):
    st.queue_hitl_deferral("s1", "d.pptx", "14 image(s) lack a faithful alt source", 14)
    st.queue_hitl_review_for_file("s1", "d.pptx",
                                  [{"rule_id": "1.1.1", "rule_name": "Non-text Content",
                                    "finding_count": 19}])
    assert _rows(st)[0]["finding_count"] == 19


def test_an_explicit_finding_count_still_wins(st):
    st.queue_hitl_review_for_file("s1", "d.pptx",
                                  [{"rule_id": "1.1.1", "rule_name": "Non-text Content",
                                    "finding_count": 19}])
    st.enqueue_proposals("s1", "d.pptx", "1.1.1", _P, finding_count=3)
    assert _rows(st)[0]["finding_count"] == 3


# ── the pseudo-rule keeps its own row ─────────────────────────────────────────

def test_auto_verify_coexists_with_the_criterion_row(st):
    st.queue_hitl_deferral("s1", "d.pptx", "Automatic fix applied — verify the result", 1,
                           rule_id="auto/verify")
    st.queue_hitl_deferral("s1", "d.pptx", "2 image(s) lack a faithful alt source", 2)
    assert {r["rule_id"] for r in _rows(st)} == {"auto/verify", "1.1.1"}


# ── certification is not blocked by a phantom sibling ─────────────────────────

def test_approving_the_one_row_certifies_the_file(st):
    """Two rows meant two approvals. mark_file_compliant_if_reviewed counts EVERY row for the
    file, so a sibling the reviewer never saw would block certification forever."""
    st.save_file_result("s1", {"file": "d.pptx", "engine": "office", "status": "pass",
                               "score": 39, "compliant": 0, "skipped_rules": 0, "issues": []}, "t1")
    st.record_remediation("s1", "d.pptx", drive_write_url=None, blob_url="blob://x")
    st.queue_hitl_deferral("s1", "d.pptx", "2 image(s) lack a faithful alt source", 2)
    st.enqueue_proposals("s1", "d.pptx", "1.1.1", _P, rule_name="Non-text Content")
    rows = _rows(st)
    assert len(rows) == 1
    st.update_hitl_item(rows[0]["id"], "approved", None, None)
    assert st.mark_file_compliant_if_reviewed("s1", "d.pptx") is True
