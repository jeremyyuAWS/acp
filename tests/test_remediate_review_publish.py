"""remediate → review → publish must be one connected loop.

Regression for the dead-end where "Remediate all" on a file with human-judgment
findings (contrast 1.4.3, link purpose 2.4.4) left the review queue empty, so the
reviewer had nothing to approve, so the file never re-validated to compliant, so
Publish (gated on f.compliant) stayed silently empty.
"""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


@pytest.fixture()
def store(monkeypatch):
    import store as store_mod
    tmp = Path(tempfile.mkdtemp()) / "rrp-test.db"
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", tmp)
    return store_mod.Store()


def _seed_pptx(store, scan_id="s1", file="deck.pptx"):
    """A remediated pptx scoring 39/100 with a contrast (1.4.3) and a link-purpose
    (2.4.4) finding — exactly the shape that stranded the review queue. save_file_result
    derives the scan_rule_traces from the issues (contrast → auto, link → ai-assisted)."""
    store.init_scan_run(scan_id, "drive", 1, "2026-07-08T00:00:00Z", "rubric", "hash")
    store.save_file_result(scan_id, {
        "file": file, "engine": "office", "status": "pass", "score": 39,
        "compliant": 0, "skipped_rules": 0, "drive_file_id": "drv1",
        "issues": [
            {"ruleId": "PPTX_LOW_CONTRAST", "wcag": "SC_1_4_3", "severity": "SERIOUS",
             "detail": "text below 4.5:1"},
            {"ruleId": "PPTX_LINK_PURPOSE", "wcag": "SC_2_4_4", "severity": "MODERATE",
             "detail": "'click here'"},
        ],
    }, "2026-07-08T00:00:00Z")
    store.record_remediation(scan_id, file, drive_write_url=None, blob_url="blob://x")


def _residual_review_rules(store, scan_id, file, cleared):
    """Mirror handlers._remediate_file: the FAILing rules NOT verifiably auto-cleared."""
    return [
        {"rule_id": r["rule_id"], "rule_name": r.get("rule_name"),
         "finding_count": r.get("finding_count")}
        for r in store.get_scan_traces(scan_id, file=file)
        if r.get("outcome") == "FAIL" and r["rule_id"] not in cleared
    ]


def test_remediate_routes_residual_findings_to_review(store):
    _seed_pptx(store)
    # Contrast recolor is credited as cleared; link purpose is not (needs a human rewrite).
    review = _residual_review_rules(store, "s1", "deck.pptx", cleared={"1.4.3"})
    created = store.queue_hitl_review_for_file("s1", "deck.pptx", review)
    ids = {c["rule_id"] for c in created}
    assert "2.4.4" in ids                       # the human-judgment finding reached a person
    pending = store.list_hitl_queue(status="pending", scan_id="s1")
    assert {p["rule_id"] for p in pending} == {"2.4.4"}
    # Idempotent — a second remediate click never duplicates the queue item.
    assert store.queue_hitl_review_for_file("s1", "deck.pptx", review) == []
    assert len(store.list_hitl_queue(scan_id="s1")) == 1


def test_stuck_auto_finding_still_reaches_review(store):
    """1.4.3 contrast is fix_mode='auto', so queue_hitl_items would never see it — but if
    the remediator can't clear it, it must still route to review, not vanish."""
    _seed_pptx(store)
    review = _residual_review_rules(store, "s1", "deck.pptx", cleared=set())  # nothing cleared
    store.queue_hitl_review_for_file("s1", "deck.pptx", review)
    assert {p["rule_id"] for p in store.list_hitl_queue(scan_id="s1")} == {"1.4.3", "2.4.4"}


def test_compliant_flips_only_when_every_item_approved(store):
    _seed_pptx(store)
    review = _residual_review_rules(store, "s1", "deck.pptx", cleared={"1.4.3"})
    created = store.queue_hitl_review_for_file("s1", "deck.pptx", review)
    # Extra item so we can prove partial approval does NOT certify.
    created += store.queue_hitl_review_for_file("s1", "deck.pptx",
                                                [{"rule_id": "1.4.3", "rule_name": "Contrast"}])

    assert store.mark_file_compliant_if_reviewed("s1", "deck.pptx") is False  # all pending

    store.update_hitl_item(created[0]["id"], "approved")
    assert store.mark_file_compliant_if_reviewed("s1", "deck.pptx") is False  # one still pending

    for c in created[1:]:
        store.update_hitl_item(c["id"], "approved")
    assert store.mark_file_compliant_if_reviewed("s1", "deck.pptx") is True   # all approved → certify

    rec = store.get_file_record("s1", "deck.pptx")
    assert rec["compliant"] == 1 and rec["score"] == 100
    agg = store.refresh_scan_aggregate("s1")
    assert agg["certifiable"] == 1
    # Idempotent — a re-approval doesn't re-flip or double-count.
    assert store.mark_file_compliant_if_reviewed("s1", "deck.pptx") is False


def test_rejected_item_blocks_certification(store):
    _seed_pptx(store)
    created = store.queue_hitl_review_for_file(
        "s1", "deck.pptx", _residual_review_rules(store, "s1", "deck.pptx", cleared={"1.4.3"}))
    store.update_hitl_item(created[0]["id"], "rejected")   # a human said the fix is wrong
    assert store.mark_file_compliant_if_reviewed("s1", "deck.pptx") is False
    assert store.get_file_record("s1", "deck.pptx")["compliant"] == 0


def _req(user_email=None):
    """Stand-in for the FastAPI Request the auth middleware has already annotated."""
    from types import SimpleNamespace
    return SimpleNamespace(state=SimpleNamespace(user_email=user_email))


def _approve(store, monkeypatch, user_email):
    import core
    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(core, "fire_webhook", lambda *a, **k: None)
    from routes.hitl import hitl_update, HitlUpdate

    _seed_pptx(store)
    created = store.queue_hitl_review_for_file(
        "s1", "deck.pptx", _residual_review_rules(store, "s1", "deck.pptx", cleared={"1.4.3"}))
    assert len(created) == 1                                   # just the link-purpose residual
    return hitl_update(created[0]["id"], HitlUpdate(status="approved"), _req(user_email))


def _approval_actor(store):
    return next(d for d in store.list_decisions("s1") if d["action"] == "hitl.approved")["actor"]


def test_hitl_approve_endpoint_certifies_file(store, monkeypatch):
    """The real PUT /hitl/queue/{id} handler must drive the compliant flip — not just the
    store method in isolation. Wire the test store into core and call the route directly."""
    res = _approve(store, monkeypatch, "ada@movate.com")
    assert res["status"] == "approved"
    rec = store.get_file_record("s1", "deck.pptx")
    assert rec["compliant"] == 1 and rec["score"] == 100       # certified & bound for Publish


def test_approval_records_the_authenticated_reviewer_identity(store, monkeypatch):
    """Chain of custody: a report that says a human signed off must be able to say WHICH
    human. The immutable decision_log actor is the authenticated reviewer's email."""
    _approve(store, monkeypatch, "ada@movate.com")
    assert _approval_actor(store) == "ada@movate.com"


def test_approval_without_signed_in_identity_falls_back_to_reviewer(store, monkeypatch):
    """No authenticated identity (the demo / SSO-less path) → record the literal 'reviewer'.
    We log what we actually know, and never invent a name."""
    _approve(store, monkeypatch, None)
    assert _approval_actor(store) == "reviewer"


def test_unremediated_file_never_certifies_on_approval(store):
    """Approval alone can't certify a file that was never remediated."""
    store.save_file_result("s1", {
        "file": "raw.pptx", "engine": "office", "status": "pass", "score": 39,
        "compliant": 0, "skipped_rules": 0,
        "issues": [{"ruleId": "X", "wcag": "SC_2_4_4", "severity": "MODERATE", "detail": "d"}],
    }, "2026-07-08T00:00:00Z")
    created = store.queue_hitl_review_for_file("s1", "raw.pptx",
                                               [{"rule_id": "2.4.4", "rule_name": "Link"}])
    store.update_hitl_item(created[0]["id"], "approved")
    assert store.mark_file_compliant_if_reviewed("s1", "raw.pptx") is False
