"""A queued review item must retract when the finding underneath it stops being work.

`queue_hitl_items` is additive and idempotent, and nothing in api/ ever withdrew a `hitl_queue`
row — there is no `DELETE FROM hitl_queue` anywhere. Rule traces, meanwhile, DO refresh:
`save_file_result` upserts `scan_rule_traces` with `ON CONFLICT(scan_id,file,rule_id) DO UPDATE
SET outcome=...`. So a re-scan or a remediation that clears a FAIL updated the trace and left
the queue row pending forever, counted in the inbox badge. On 2026-07-29 the deployed inbox
showed 225 items over a 258-document scan.

WHICH OUTCOMES RETRACT, and why it is not simply "the finding now passes". Measured against
`_rule_outcome` for every ai-assisted criterion, a clean scan almost never yields PASS:

    1.1.1 · 1.4.5 · 2.4.4 · 3.1.2    REVIEW on every format
    1.4.9 · 2.4.9 · 2.1.2(office)    NOT_EVALUATED
    3.3.2 docx/html · 4.1.2 html     PASS

(4.1.2 office was here, but docx/xlsx/pptx all migrated to the capability registry; a clean
scan now returns REVIEW for those pairs. 2.1.2 pptx is the exemplar that remains in
REVIEW_FORMATS, so it still falls back to NOT_EVALUATED when controls are absent.)

REVIEW is the resting state of the criteria the inbox mostly holds, because those detectors
find whether alt text EXISTS and cannot certify that it is any good. Retracting on REVIEW would
empty the inbox of exactly the work it exists for. So retraction is PASS or NOT_EVALUATED only.

The rows stay on disk and are retrievable via include_superseded — the same posture as the
shadow-copy filter directly above it in `list_hitl_queue`, and for the same reason: this
product's claim is auditability, so "what was once flagged" must survive "what is flagged now".
"""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "hqr.db")
    return store_mod.Store()


# 3.3.2 Labels or Instructions on docx is the one ai-assisted pair that reaches a real PASS on a
# clean scan, so it is the only one that can demonstrate a FAIL -> PASS retraction end to end.
def _docx(name="form.docx", *, failing=True):
    issues = [{"ruleId": "DOCX-LBL-001", "wcag": "3.3.2", "severity": "CRITICAL"}] if failing else []
    return {"file": name, "engine": "office", "status": "analysed",
            "score": 40 if failing else 100, "compliant": 0 if failing else 1,
            "skipped_rules": 0, "issues": issues}


def _pptx_alt(name="deck.pptx", *, failing=True):
    """1.1.1 on pptx — clean state is REVIEW, never PASS. The control case."""
    issues = [{"ruleId": "PPTX-ALT-001", "wcag": "1.1.1", "severity": "CRITICAL"}] if failing else []
    return {"file": name, "engine": "office", "status": "analysed",
            "score": 40 if failing else 100, "compliant": 0 if failing else 1,
            "skipped_rules": 0, "issues": issues}


def _start(st, rec, sid="s1"):
    st.init_scan_run(sid, "drive", 1, "t0", "r", "h")
    st.save_file_result(sid, rec(failing=True), "t1")
    return st.queue_hitl_items(sid)


def _ids(rows):
    return [r["rule_id"] for r in rows]


def _outcome(st, sid, file, rule):
    return {t["rule_id"]: t["outcome"] for t in st.get_scan_traces(sid, file)}[rule]


# ── the premise ───────────────────────────────────────────────────────────────────────

def test_the_item_is_queued_while_the_finding_fails(st):
    assert "3.3.2" in _ids(_start(st, _docx))
    assert "3.3.2" in _ids(st.list_hitl_queue(scan_id="s1"))


def test_the_trace_really_does_refresh(st):
    """Guards the premise. If the trace did not update, retraction would solve nothing."""
    _start(st, _docx)
    assert _outcome(st, "s1", "form.docx", "3.3.2") == "FAIL"
    st.save_file_result("s1", _docx(failing=False), "t2")
    assert _outcome(st, "s1", "form.docx", "3.3.2") == "PASS"


# ── retraction ────────────────────────────────────────────────────────────────────────

def test_a_review_item_retracts_once_its_finding_passes(st):
    _start(st, _docx)
    st.save_file_result("s1", _docx(failing=False), "t2")
    assert "3.3.2" not in _ids(st.list_hitl_queue(scan_id="s1"))


def test_retraction_filters_the_read_and_keeps_the_audit_row(st):
    _start(st, _docx)
    st.save_file_result("s1", _docx(failing=False), "t2")
    audit = st.list_hitl_queue(scan_id="s1", include_superseded=True)
    assert _ids(audit) == ["3.3.2"], "the row must survive, and be retrievable"
    assert audit[0]["superseded"] is True


def test_a_still_failing_item_is_untouched(st):
    _start(st, _docx)
    st.save_file_result("s1", _docx(failing=True), "t2")     # re-scan, still failing
    assert "3.3.2" in _ids(st.list_hitl_queue(scan_id="s1"))


def test_a_retracted_item_comes_back_if_the_finding_regresses(st):
    """Derived at read time, so recovery needs no sweep and cannot be missed."""
    _start(st, _docx)
    st.save_file_result("s1", _docx(failing=False), "t2")
    assert "3.3.2" not in _ids(st.list_hitl_queue(scan_id="s1"))
    st.save_file_result("s1", _docx(failing=True), "t3")
    assert "3.3.2" in _ids(st.list_hitl_queue(scan_id="s1"))


def test_a_migrated_pptx_412_item_does_not_retract_on_review(st):
    """pptx 4.1.2 was migrated from REVIEW_FORMATS to the capability registry (PR #696).

    Before the migration: clearing all findings dropped the outcome to NOT_EVALUATED, and the
    hitl item retracted (NOT_EVALUATED is in _SUPERSEDING_OUTCOMES).

    After the migration: the registry reports PARTIAL coverage, so a clean scan now returns
    REVIEW instead. REVIEW is deliberately NOT in _SUPERSEDING_OUTCOMES — naming every visible
    control in a presentation does not answer the question for controls the technique cannot
    reach (embedded OLE objects, focusable regions only exposed at runtime), so the question
    remains genuinely open for a human. The item stays.

    This makes pptx 4.1.2 consistent with docx 4.1.2 (already migrated before PR #696) and
    pdf 4.1.2. The no-longer-reachable NOT_EVALUATED retraction path has no natural ai-assisted
    exemplar remaining in REVIEW_FORMATS, so it is not separately pinned.
    """
    def _rec(*, failing):
        issues = [{"ruleId": "PPTX-NRV-001", "wcag": "4.1.2", "severity": "CRITICAL"}] if failing else []
        return {"file": "app.pptx", "engine": "office", "status": "analysed",
                "score": 40 if failing else 100, "compliant": 0 if failing else 1,
                "skipped_rules": 0, "issues": issues}

    st.init_scan_run("s1", "drive", 1, "t0", "r", "h")
    st.save_file_result("s1", _rec(failing=True), "t1")
    assert "4.1.2" in _ids(st.queue_hitl_items("s1"))
    assert _outcome(st, "s1", "app.pptx", "4.1.2") == "FAIL"

    st.save_file_result("s1", _rec(failing=False), "t2")
    assert _outcome(st, "s1", "app.pptx", "4.1.2") == "REVIEW"
    assert "4.1.2" in _ids(st.list_hitl_queue(scan_id="s1"))


def test_a_partial_coverage_pair_does_not_retract_when_its_findings_clear(st):
    """The consequence of declaring coverage, stated as an assertion rather than discovered.

    A registry pair with PARTIAL coverage resolves to REVIEW on a clean scan — the technique ran
    and covered part of the criterion. REVIEW is deliberately NOT in _SUPERSEDING_OUTCOMES, so
    naming every content control in a Word file does NOT retract its 4.1.2 item: the criterion
    also covers ActiveX and embedded OLE controls, which nothing here examines, so the question
    is genuinely still open for a human.

    That is a change in queue behaviour, not only in a token — before the migration a cleared
    docx 4.1.2 item disappeared. PDF 4.1.2 has behaved this way since its own migration, so this
    makes the two consistent rather than introducing a new shape. Worth revisiting if the queue
    proves noisy: the lever is coverage, not this test.
    """
    def _rec(*, failing):
        issues = [{"ruleId": "DOCX-NRV-001", "wcag": "4.1.2", "severity": "CRITICAL"}] if failing else []
        return {"file": "app.docx", "engine": "office", "status": "analysed",
                "score": 40 if failing else 100, "compliant": 0 if failing else 1,
                "skipped_rules": 0, "issues": issues}

    st.init_scan_run("s1", "drive", 1, "t0", "r", "h")
    st.save_file_result("s1", _rec(failing=True), "t1")
    assert "4.1.2" in _ids(st.queue_hitl_items("s1"))
    assert _outcome(st, "s1", "app.docx", "4.1.2") == "FAIL"

    st.save_file_result("s1", _rec(failing=False), "t2")
    assert _outcome(st, "s1", "app.docx", "4.1.2") == "REVIEW"
    assert "4.1.2" in _ids(st.list_hitl_queue(scan_id="s1"))


# ── what must NOT retract ─────────────────────────────────────────────────────────────

def test_a_review_outcome_never_retracts(st):
    """1.1.1 on pptx cannot reach PASS — REVIEW is its clean state, and REVIEW means a human
    still has to judge the alt text. This is the case that would have emptied the inbox."""
    _start(st, _pptx_alt)
    st.save_file_result("s1", _pptx_alt(failing=False), "t2")
    assert _outcome(st, "s1", "deck.pptx", "1.1.1") == "REVIEW"
    assert "1.1.1" in _ids(st.list_hitl_queue(scan_id="s1"))


def test_an_item_a_human_already_decided_is_never_retracted(st):
    """An approved item is the record of a decision, not a work-list entry. Its finding passing
    now is the consequence of that approval, not a reason to hide it."""
    created = _start(st, _docx)
    st.update_hitl_item(created[0]["id"], "approved")
    st.save_file_result("s1", _docx(failing=False), "t2")
    assert "3.3.2" in _ids(st.list_hitl_queue(scan_id="s1", status="approved"))


def test_an_item_with_no_matching_trace_is_left_alone(st):
    """Deferrals and auto/verify items carry rule_ids ('1.1.1/deferred', 'auto/verify') that
    scan_rule_traces never holds. Absence of a trace is not evidence of a pass."""
    _start(st, _docx)
    st.queue_hitl_deferral("s1", "form.docx", "Automatic fix applied — verify the result", 1,
                           rule_id="auto/verify")
    st.save_file_result("s1", _docx(failing=False), "t2")
    assert "auto/verify" in _ids(st.list_hitl_queue(scan_id="s1"))


def test_another_scans_still_failing_item_is_not_retracted_by_this_one(st):
    """The join must be per (scan, file, rule) — a clean re-scan elsewhere must not clear it."""
    _start(st, _docx, sid="s1")
    st.init_scan_run("s2", "drive", 1, "t0", "r", "h")
    st.save_file_result("s2", _docx(failing=False), "t1")
    assert "3.3.2" in _ids(st.list_hitl_queue(scan_id="s1"))
    assert st.list_hitl_queue(scan_id="s2") == []


# ── the route ─────────────────────────────────────────────────────────────────────────

def test_the_endpoint_omits_superseded_items_and_can_return_them(st, monkeypatch):
    """The inbox badge reads this endpoint, so the count is only honest if the route agrees
    with the store."""
    from fastapi.testclient import TestClient
    import core
    import app as app_mod

    _start(st, _docx)
    st.save_file_result("s1", _docx(failing=False), "t2")
    monkeypatch.setattr(core, "store", st)
    client = TestClient(app_mod.app)

    assert client.get("/hitl/queue?scan_id=s1").json() == []
    audit = client.get("/hitl/queue?scan_id=s1&include_superseded=true").json()
    assert [r["rule_id"] for r in audit] == ["3.3.2"]
    assert audit[0]["superseded"] is True
