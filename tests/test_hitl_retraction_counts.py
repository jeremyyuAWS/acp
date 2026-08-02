"""Every count sourced from the queue must read LIVE items — including the certification gate.

#75 made `list_hitl_queue` drop superseded rows (queued while a finding failed, since
re-verified to PASS or NOT_EVALUATED) and every reader funnelled through it, so the inbox
badge, the bell and the Remediate header all stopped over-reporting together.

One count did not funnel through it. `mark_file_compliant_if_reviewed` carried its own
`SELECT status, COUNT(*) ... GROUP BY status` over `hitl_queue` — the last raw queue count in
api/ — and a retracted row still answers 'pending' there, because retraction filters the READ
and deliberately leaves the stored status alone. So `approved != total` and the file never
certified. That is the same defect as the inflated badge, pointing the other way and far
quieter: the reviewer is shown an EMPTY queue beside a document that will not certify, and
there is nothing left to click. It propagates too — `certifiable` is Σ`file_records.compliant`
(refresh_scan_aggregate), so the Overview under-reported for exactly the reason the inbox once
over-reported.

The direction matters as much as the fix. Counting live items must not certify a file that
still has real work on it, so the still-FAIL, rejected and REVIEW cases are pinned here
alongside the retraction. A file is only certified when every LIVE item is approved — a
retracted row is not work, a pending one still is.
"""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

SID, FILE = "s1", "form.docx"


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "hrc.db")
    return store_mod.Store()


# 3.3.2 on docx is the one ai-assisted pair that reaches a real PASS on a clean scan, so it is
# the criterion that can demonstrate a FAIL -> PASS retraction. 1.1.1 stays failing to hold the
# file non-compliant, giving the human something genuine to approve.
def _rec(*, labels_fail, alt_fail):
    issues = []
    if labels_fail:
        issues.append({"ruleId": "DOCX-LBL-001", "wcag": "3.3.2", "severity": "CRITICAL"})
    if alt_fail:
        issues.append({"ruleId": "DOCX-ALT-001", "wcag": "1.1.1", "severity": "CRITICAL"})
    return {"file": FILE, "engine": "office", "status": "analysed",
            "score": 40 if issues else 100, "compliant": 0 if issues else 1,
            "skipped_rules": 0, "issues": issues}


def _remediated(st):
    """A scan with both criteria failing and both queued, the file marked remediated."""
    st.init_scan_run(SID, "drive", 1, "t0", "r", "h")
    st.save_file_result(SID, _rec(labels_fail=True, alt_fail=True), "t1")
    st.queue_hitl_items(SID)
    with st._db.cursor() as cur:
        st._db.execute(cur, "UPDATE file_records SET remediated_at='2026-07-30T00:00:00' "
                            "WHERE scan_id=%s AND file=%s", (SID, FILE))


def _ids(rows):
    return sorted(r["rule_id"] for r in rows)


def _compliant(st):
    with st._db.cursor() as cur:
        st._db.execute(cur, "SELECT compliant FROM file_records WHERE scan_id=%s AND file=%s",
                       (SID, FILE))
        return st._db.fetchone(cur)["compliant"]


# ── the defect ────────────────────────────────────────────────────────────────────────

def test_a_retracted_item_does_not_block_certification(st):
    """The reproduction. Remediation clears 3.3.2, so its row retracts; the human approves the
    one item that is still live. Nothing outstanding remains, so the file must certify."""
    _remediated(st)
    st.save_file_result(SID, _rec(labels_fail=False, alt_fail=True), "t2")   # 3.3.2 -> PASS
    live = st.list_hitl_queue(scan_id=SID)
    assert _ids(live) == ["1.1.1"], "3.3.2 retracted from the queue"
    for r in live:
        st.update_hitl_item(r["id"], "approved")

    assert st.mark_file_compliant_if_reviewed(SID, FILE) is True
    assert _compliant(st) == 1


def test_the_scan_rollup_counts_the_certified_file(st):
    """`certifiable` is Σcompliant — the Overview tile the blocked certification fed."""
    _remediated(st)
    st.save_file_result(SID, _rec(labels_fail=False, alt_fail=True), "t2")
    for r in st.list_hitl_queue(scan_id=SID):
        st.update_hitl_item(r["id"], "approved")
    assert st.mark_file_compliant_if_reviewed(SID, FILE) is True
    assert ((st.get_scan(SID) or {}).get("run") or {}).get("certifiable") == 1


def test_the_retracted_row_survives_as_audit(st):
    """Certifying on live items must not cost the record that the finding was ever raised."""
    _remediated(st)
    st.save_file_result(SID, _rec(labels_fail=False, alt_fail=True), "t2")
    for r in st.list_hitl_queue(scan_id=SID):
        st.update_hitl_item(r["id"], "approved")
    st.mark_file_compliant_if_reviewed(SID, FILE)

    audit = st.list_hitl_queue(scan_id=SID, include_superseded=True)
    assert _ids(audit) == ["1.1.1", "3.3.2"]
    by_rule = {r["rule_id"]: r for r in audit}
    assert by_rule["3.3.2"]["superseded"] is True
    assert by_rule["3.3.2"]["status"] == "pending", "retraction filters the read, it does not rewrite status"
    assert by_rule["1.1.1"]["status"] == "approved"


# ── the direction that would be worse ─────────────────────────────────────────────────

def test_a_still_failing_item_still_blocks_certification(st):
    """Counting live items must not become 'ignore what is inconvenient'. 1.1.1 is untouched
    and still FAIL, so it is live, pending, and the file may not certify."""
    _remediated(st)
    st.save_file_result(SID, _rec(labels_fail=False, alt_fail=True), "t2")
    assert _ids(st.list_hitl_queue(scan_id=SID)) == ["1.1.1"]
    assert st.mark_file_compliant_if_reviewed(SID, FILE) is False
    assert _compliant(st) == 0


def test_a_rejected_item_still_blocks_certification(st):
    """A decided-but-not-approved row is never superseded, so it stays in the count."""
    _remediated(st)
    st.save_file_result(SID, _rec(labels_fail=False, alt_fail=True), "t2")
    for r in st.list_hitl_queue(scan_id=SID):
        st.update_hitl_item(r["id"], "rejected")
    assert st.mark_file_compliant_if_reviewed(SID, FILE) is False


def test_a_file_whose_only_item_retracted_is_not_certified_by_this_path(st):
    """No live item means no human resolved anything, so this gate asserts nothing — the
    re-scan owns that case (a genuinely clean file comes back compliant=1 on its own, and the
    early guard then returns False). Certifying on an empty queue here would hand a 100/100 to
    any remediated file that never had a review item at all."""
    st.init_scan_run(SID, "drive", 1, "t0", "r", "h")
    st.save_file_result(SID, _rec(labels_fail=True, alt_fail=False), "t1")
    st.queue_hitl_items(SID)
    with st._db.cursor() as cur:
        st._db.execute(cur, "UPDATE file_records SET remediated_at='2026-07-30T00:00:00' "
                            "WHERE scan_id=%s AND file=%s", (SID, FILE))
    # Clear the finding but hold the record non-compliant, so the early guard cannot mask this.
    st.save_file_result(SID, _rec(labels_fail=False, alt_fail=True), "t2")
    with st._db.cursor() as cur:
        st._db.execute(cur, "DELETE FROM scan_rule_traces WHERE scan_id=%s AND rule_id='1.1.1'", (SID,))

    assert st.list_hitl_queue(scan_id=SID) == []
    assert st.mark_file_compliant_if_reviewed(SID, FILE) is False
    assert _compliant(st) == 0


def test_an_unapplied_approved_value_still_blocks_a_retracted_neighbour(st):
    """The approved-but-unwritten gate must survive the change: approving alt text records the
    text, it does not put it in the document."""
    _remediated(st)
    st.save_file_result(SID, _rec(labels_fail=False, alt_fail=True), "t2")
    for r in st.list_hitl_queue(scan_id=SID):
        st.update_hitl_item(r["id"], "approved", approved_value="A chart of Q3 revenue")
    assert st.count_unapplied_approved_values(SID, FILE) == 1
    assert st.mark_file_compliant_if_reviewed(SID, FILE) is False


# ── the readers agree ─────────────────────────────────────────────────────────────────

def test_every_queue_count_reports_the_same_live_set(st, monkeypatch):
    """The failure class of #77/#84/#101/#118 — a badge disagreeing with the list it labels.

    Three UI counts read this endpoint differently: the Remediate header and the nav badge ask
    for status=pending, HitlBell asks for everything and filters client-side, and the scan
    report asks for everything and tallies by status. They may only ever describe one set.
    """
    from fastapi.testclient import TestClient
    import core
    import app as app_mod

    _remediated(st)
    st.save_file_result(SID, _rec(labels_fail=False, alt_fail=True), "t2")
    monkeypatch.setattr(core, "store", st)
    client = TestClient(app_mod.app)

    # Remediate header + nav inbox badge: GET /hitl/queue?scan_id&status=pending
    header = client.get(f"/hitl/queue?scan_id={SID}&status=pending").json()
    # HitlBell: GET /hitl/queue, filtered to pending in the browser
    bell = [r for r in client.get("/hitl/queue").json() if r["status"] == "pending"]
    # Scan report: GET /hitl/queue?scan_id, tallied by status
    report = client.get(f"/hitl/queue?scan_id={SID}").json()

    assert _ids(header) == ["1.1.1"]
    assert _ids(bell) == ["1.1.1"]
    assert _ids(report) == ["1.1.1"]
    assert len(header) == len(bell) == len(report) == 1

    # And the audit view is the only one that still sees the retracted item.
    audit = client.get(f"/hitl/queue?scan_id={SID}&include_superseded=true").json()
    assert _ids(audit) == ["1.1.1", "3.3.2"]
