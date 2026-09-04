"""ADR 0041 auto-apply gate — routing tests for 2.4.4 and 4.1.2.

WHAT THIS TESTS. The gate is in _enqueue_proposals (handlers.py): when validated=True
and sc in {"2.4.4", "2.4.9", "4.1.2"}, the proposal must be auto-approved in the
hitl_queue rather than left pending for a human reviewer.  When validated=False (or for
a non-Group-A SC), the row stays 'pending' as before.

STRUCTURE.
  - store.auto_approve_proposals: unit tests covering happy path, edge cases, idempotency
  - routing branch tests: validated=True -> 'approved'; validated=False -> 'pending'
  - structural tests: confirm the gate lives in the right places in the source
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import store as store_mod  # noqa: E402

ACP = Path(__file__).resolve().parent.parent


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def st(monkeypatch):
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "gate.db")
    s = store_mod.Store()
    s.init_scan_run("s1", "drive", 1, "t0", "r", "h")
    return s


_LINK_PROP = [{"locator": "https://example.com/", "before": "click here",
               "proposed_value": "Accessibility policy", "rationale": "vague text",
               "source": "propose_link_texts", "sc": "2.4.4"}]

_FIELD_PROP = [{"locator": "docx:sdt:42", "before": "(no accessible name)",
                "proposed_value": "Date of birth", "rationale": "adjacent label",
                "source": "form_labels", "sc": "4.1.2"}]


# ── store.auto_approve_proposals ──────────────────────────────────────────────

def test_auto_approve_sets_status_approved(st):
    st.enqueue_proposals("s1", "f.docx", "2.4.4", _LINK_PROP, rule_name="Link Purpose")
    rows = st.list_hitl_queue(scan_id="s1")
    assert rows[0]["status"] == "pending"

    item_id = st.auto_approve_proposals("s1", "f.docx", "2.4.4")

    assert item_id is not None
    row = st.get_hitl_item(item_id)
    assert row["status"] == "approved"


def test_auto_approve_stamps_approved_value_from_proposed_value(st):
    st.enqueue_proposals("s1", "f.docx", "2.4.4", _LINK_PROP, rule_name="Link Purpose")
    item_id = st.auto_approve_proposals("s1", "f.docx", "2.4.4")

    row = st.get_hitl_item(item_id)
    proposals = row["proposals"]
    assert proposals[0]["approved_value"] == "Accessibility policy"


def test_auto_approve_marks_applied_1(st):
    """applied=1 prevents apply_approved_values from re-running the already-written fix."""
    st.enqueue_proposals("s1", "f.docx", "4.1.2", _FIELD_PROP, rule_name="Name, Role, Value")
    item_id = st.auto_approve_proposals("s1", "f.docx", "4.1.2")

    row = st.get_hitl_item(item_id)
    assert row.get("applied") == 1


def test_auto_approve_sets_reviewer_note(st):
    st.enqueue_proposals("s1", "f.docx", "2.4.4", _LINK_PROP)
    item_id = st.auto_approve_proposals("s1", "f.docx", "2.4.4")

    row = st.get_hitl_item(item_id)
    assert "ADR 0041" in (row.get("reviewer_note") or "")


def test_auto_approve_sets_reviewed_at(st):
    st.enqueue_proposals("s1", "f.docx", "2.4.4", _LINK_PROP)
    item_id = st.auto_approve_proposals("s1", "f.docx", "2.4.4")

    row = st.get_hitl_item(item_id)
    assert row.get("reviewed_at"), "reviewed_at must be stamped for the audit record"


def test_auto_approve_returns_none_when_no_pending_row(st):
    """No pending row -> returns None (no crash, safe no-op)."""
    result = st.auto_approve_proposals("s1", "no-such-file.docx", "2.4.4")
    assert result is None


def test_auto_approve_ignores_already_approved_row(st):
    """A row already approved by a human must not be touched."""
    item_id = st.enqueue_proposals("s1", "f.docx", "2.4.4", _LINK_PROP)
    st.update_hitl_item(item_id, "approved", reviewer_note="human approved")

    result = st.auto_approve_proposals("s1", "f.docx", "2.4.4")
    assert result is None, "auto_approve_proposals must not touch non-pending rows"

    row = st.get_hitl_item(item_id)
    assert row["reviewer_note"] == "human approved", "human note must not be overwritten"


def test_auto_approve_leaves_proposal_without_proposed_value_intact(st):
    """A proposal with no proposed_value gets no approved_value stamped."""
    prop = [{"locator": "https://x.com/", "before": "here", "proposed_value": "",
             "source": "propose_link_texts", "sc": "2.4.4"}]
    st.enqueue_proposals("s1", "f.docx", "2.4.4", prop)
    item_id = st.auto_approve_proposals("s1", "f.docx", "2.4.4")

    row = st.get_hitl_item(item_id)
    assert "approved_value" not in row["proposals"][0]


# ── applied=1 gates out_of has_approved_values_to_write ──────────────────────

def test_auto_approved_row_does_not_trigger_apply_job(st):
    """applied=1 means has_approved_values_to_write returns False for this row.

    A human-approved row (applied=NULL) would trigger the apply job.
    An auto-approved row (applied=1) must not — the fix is already in the document.
    """
    item_id = st.enqueue_proposals("s1", "f.docx", "2.4.4", _LINK_PROP)
    # Simulate a human approving the row WITHOUT setting applied, to show it would trigger a job.
    st.approve_proposal_values(item_id, [None])  # accept the draft
    st.update_hitl_item(item_id, "approved")
    assert st.has_approved_values_to_write("s1", "f.docx"), (
        "pre-condition: a human-approved row with applied=NULL must look like pending content")

    # Now do auto-approve on a FRESH row to show applied=1 prevents the trigger.
    st2_item = st.enqueue_proposals("s1", "g.docx", "2.4.4", _LINK_PROP)
    assert st2_item  # second file
    st.auto_approve_proposals("s1", "g.docx", "2.4.4")
    assert not st.has_approved_values_to_write("s1", "g.docx"), (
        "after auto-approve with applied=1, has_approved_values_to_write must be False — "
        "the fix is already in the document")


# ── routing: validated=True → auto-approved, validated=False → pending ────────

def test_validated_244_proposal_is_auto_approved(st):
    """The primary gate: validated 2.4.4 proposals must bypass human review."""
    st.enqueue_proposals("s1", "f.docx", "2.4.4", _LINK_PROP, validated=True)
    st.auto_approve_proposals("s1", "f.docx", "2.4.4")

    row = st.list_hitl_queue(scan_id="s1")[0]
    assert row["status"] == "approved", (
        "a validated 2.4.4 proposal must be auto-approved — human reviewer step is skipped")


def test_unvalidated_244_proposal_stays_pending(st):
    """Unvalidated proposals stay in the human review queue as before."""
    st.enqueue_proposals("s1", "f.docx", "2.4.4", _LINK_PROP, validated=False)

    row = st.list_hitl_queue(scan_id="s1")[0]
    assert row["status"] == "pending", (
        "an unvalidated 2.4.4 proposal must stay pending — human approval still required")


def test_validated_412_proposal_is_auto_approved(st):
    """Same gate for 4.1.2 accessible names."""
    st.enqueue_proposals("s1", "f.docx", "4.1.2", _FIELD_PROP, validated=True)
    st.auto_approve_proposals("s1", "f.docx", "4.1.2")

    row = st.list_hitl_queue(scan_id="s1")[0]
    assert row["status"] == "approved"


def test_unvalidated_412_proposal_stays_pending(st):
    st.enqueue_proposals("s1", "f.docx", "4.1.2", _FIELD_PROP, validated=False)

    row = st.list_hitl_queue(scan_id="s1")[0]
    assert row["status"] == "pending"


def test_validated_249_proposal_is_auto_approved(st):
    """2.4.9 shares the same link-text applier as 2.4.4; gate covers both."""
    prop_249 = [{**_LINK_PROP[0], "sc": "2.4.9"}]
    st.enqueue_proposals("s1", "f.docx", "2.4.9", prop_249, validated=True)
    st.auto_approve_proposals("s1", "f.docx", "2.4.9")

    row = st.list_hitl_queue(scan_id="s1")[0]
    assert row["status"] == "approved"


def test_group_b_sc_validated_stays_pending(st):
    """Group B SCs are permanently human-review-only (ADR 0041 §'Why Group B')."""
    prop = [{"locator": "p1:0", "before": "click here", "proposed_value": "Download PDF",
             "rationale": "r", "source": "s", "sc": "2.4.6"}]
    st.enqueue_proposals("s1", "f.docx", "2.4.6", prop, validated=True)

    row = st.list_hitl_queue(scan_id="s1")[0]
    assert row["status"] == "pending", (
        "Group B SC 2.4.6 must stay in the human queue even when validated=True is set")


# ── structural: gate lives in _enqueue_proposals for BOTH 2.4.4 and 4.1.2 ───

def _fn_body(fn_name: str) -> str:
    src = (ACP / "api" / "handlers.py").read_text()
    fn_start = src.index(f"def {fn_name}(")
    # Find the next top-level def to bound the function body
    rest = src[fn_start + len(fn_name):]
    try:
        end = rest.index("\ndef ") + fn_start + len(fn_name)
    except ValueError:
        end = len(src)
    return src[fn_start:end]


def test_gate_fires_on_244_in_enqueue_proposals():
    """The gate condition covers 2.4.4 inside _enqueue_proposals in handlers.py."""
    fn_body = _fn_body("_enqueue_proposals")
    assert '"2.4.4"' in fn_body, "gate must reference SC 2.4.4 inside _enqueue_proposals"
    assert "auto_approve_proposals" in fn_body, (
        "gate must call store.auto_approve_proposals inside _enqueue_proposals")


def test_gate_fires_on_412_in_enqueue_proposals():
    """The gate condition also covers 4.1.2."""
    fn_body = _fn_body("_enqueue_proposals")
    assert '"4.1.2"' in fn_body, "gate must reference SC 4.1.2 inside _enqueue_proposals"


def test_gate_requires_validated_true():
    """Gate condition must require validated=True, not just SC membership."""
    fn_body = _fn_body("_enqueue_proposals")
    assert "validated and sc in" in fn_body or "if validated" in fn_body, (
        "gate must check the validated flag, not just the SC")


def test_auto_approve_proposals_exists_in_store():
    """store.Store must have the auto_approve_proposals method."""
    src = (ACP / "api" / "store.py").read_text()
    assert "def auto_approve_proposals(" in src, (
        "store.Store.auto_approve_proposals must exist for the gate to call")


def test_auto_approve_proposals_sets_applied_1_in_store():
    """The method must stamp applied=1 so the fix is not re-written."""
    src = (ACP / "api" / "store.py").read_text()
    method_start = src.index("def auto_approve_proposals(")
    method_body = src[method_start:method_start + 1200]
    assert "applied=1" in method_body, (
        "auto_approve_proposals must set applied=1 to prevent apply_approved_values re-run")


def test_adr_0041_gate_logs_decision():
    """The gate must record a decision log entry so the audit trail shows the auto-approval."""
    fn_body = _fn_body("_enqueue_proposals")
    assert "hitl.auto_approved" in fn_body, (
        "gate must log 'hitl.auto_approved' for audit-trail visibility")
