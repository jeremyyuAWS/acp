"""Exceptions grouped by the response they need, and controls that promise only what ACP can do.

PRD §6E asks the panel to "lead with actionable exceptions, grouped by response". The grouping is
the product decision: a screen that lists twelve problems in one column asks the user to sort them,
and the sort they need is not by severity or by document but by WHO ACTS and WHAT HAPPENS — which
is why "needs authoring" is a separate group from "individual review" even though both end at the
same review queue, and why a delivery failure is not filed under "failed".

The controls are the other half, and the discipline there is subtraction. `RUN_STATES` has carried
`paused` since Phase 1 with a comment saying it is declared and never derived, because inferring a
pause from an idle queue reports a capacity fact as a decision. Pause is offered now because there
is a durable hold behind it — and its scope sentence says out loud that an attempt already in
flight runs to completion, because a Pause that silently let three documents keep being rewritten
would be a worse lie than no Pause at all.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import remediation_exceptions as exceptions          # noqa: E402
import remediation_run                                # noqa: E402

OWNER = "owner@example.com"
SID = "run-groups"


@pytest.fixture()
def store(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "groups.db")
    return store_mod.Store()


def _record(**overrides) -> dict:
    """A document with nothing wrong with it. Each test breaks exactly one thing."""
    return {"run_id": SID, "file": "a.docx", "provider": "sharepoint", "outcome": "completed",
            "artifact_stored_at": "2026-09-01T00:00:00Z", "artifact_digest": "d" * 64,
            "delivered_url": "http://sp/ok", "source_modified": "2026-08-01T00:00:00Z",
            "destination_drive_id": "b!library", "destination_folder": "Remediated",
            "destination_label": "Policies", "review_items": 0, "review_pending": False,
            "review_kind": None, "fixes_applied": 2, "fixes_verified": 2, **overrides}


# ── one document, one group ───────────────────────────────────────────────────

def test_a_healthy_document_is_not_an_exception():
    assert exceptions.classify_exception(_record()) is None


@pytest.mark.parametrize("record,group", [
    (_record(outcome="failed", reason="attempts_exhausted"), "document_failure"),
    (_record(delivered_url=None), "delivery_failure"),
    (_record(review_pending=True, review_items=1, review_kind="authoring"),
     "authoring_required"),
    (_record(review_pending=True, review_items=3, review_kind="decision"), "review_required"),
    (_record(fixes_verified=0), "verification_failure"),
])
def test_each_exception_lands_in_the_group_that_names_its_remedy(record, group):
    assert exceptions.classify_exception(record)[0] == group


def test_an_undelivered_copy_outranks_an_open_review_item():
    """Both are true of the document and the remedies are independent. Filing it under review
    would leave a corrected copy that never reached the customer sitting behind "somebody must
    decide something", which is how a lost artifact stays lost."""
    record = _record(delivered_url=None, review_pending=True, review_items=2,
                     review_kind="decision")
    assert exceptions.classify_exception(record)[0] == "delivery_failure"


def test_a_failed_document_outranks_everything():
    """No attempts remain. Whatever else is true of the document, "awaiting review" is not."""
    record = _record(outcome="failed", delivered_url=None, review_pending=True, review_items=1)
    assert exceptions.classify_exception(record)[0] == "document_failure"


def test_the_groups_partition_the_exceptions():
    """Every exception is counted once, so the group totals sum to the documents needing
    attention rather than double-counting whichever document has two problems."""
    records = [_record(file="a", outcome="failed"), _record(file="b", delivered_url=None),
               _record(file="c", review_pending=True, review_items=1, review_kind="authoring"),
               _record(file="d", review_pending=True, review_items=1, review_kind="decision"),
               _record(file="e", fixes_verified=1), _record(file="f")]
    groups = exceptions.build_exception_groups(records)
    assert sum(g["documents"] for g in groups) == 5, "one healthy document must contribute none"
    assert [g["key"] for g in groups] == list(exceptions.EXCEPTION_GROUPS)
    assert all(g["documents"] > 0 for g in groups), "an empty group is noise, not information"


# ── what each group offers ────────────────────────────────────────────────────

def test_only_the_delivery_group_promises_not_to_re_apply_fixes():
    """The distinction the two retry buttons rest on, asserted in the data rather than in a
    label the UI happens to render."""
    reapply = {key: spec["reapplies_fixes"] for key, spec in exceptions.GROUP_SPECS.items()}
    assert reapply == {"document_failure": True, "delivery_failure": False,
                       "authoring_required": False, "review_required": False,
                       "verification_failure": True}


def test_a_review_group_offers_no_automatic_action():
    """ACP has no move to make on a decision only a person can take, and a button that does
    nothing is worse than no button."""
    for key in ("review_required", "authoring_required"):
        assert exceptions.GROUP_SPECS[key]["action"] is None


def test_a_cancelled_run_offers_no_retry_but_still_says_why():
    rows = exceptions.build_exception_groups([_record(delivered_url=None)], cancelled=True)
    item = rows[0]["items"][0]
    assert item["action_enabled"] is False
    assert item["action_code"] == "run_cancelled"
    assert "cancelled" in item["action_reason"]


def test_a_refused_row_still_names_its_destination_but_carries_no_key():
    """An administrator's next question is "where was it going" — and the idempotency key is
    an authorisation to write, which a refused row has not earned."""
    rows = exceptions.build_exception_groups([_record(delivered_url=None, artifact_digest=None)])
    item = rows[0]["items"][0]
    assert item["action_enabled"] is False
    assert item["destination"]["provider"] == "sharepoint"
    assert "key" not in item["destination"]


def test_no_exception_row_carries_document_content():
    """PRD §13: activity carries no extracted document content. The projection is a whitelist,
    so a column added upstream cannot arrive here by being added there."""
    row = exceptions.exception_row(_record(delivered_url=None,
                                           extracted_text="the patient's name is ...",
                                           access_token="SECRET"))
    assert "extracted_text" not in row and "access_token" not in row
    assert "SECRET" not in repr(row) and "patient" not in repr(row)


# ── run controls ──────────────────────────────────────────────────────────────

def _counters(**over):
    base = {"completed": 0, "processing": 0, "waiting": 0, "review": 0, "failed": 0, "skipped": 0}
    return {**base, **over}


def test_pause_says_out_loud_what_it_cannot_hold():
    controls = {c["action"]: c for c in exceptions.run_controls(
        state="running", counters=_counters(waiting=5, processing=3))}
    assert controls["pause"]["available"] is True
    assert controls["pause"]["holds"] == 5 and controls["pause"]["in_flight"] == 3
    assert "run to completion" in controls["pause"]["scope"]


def test_pause_is_refused_when_there_is_nothing_unclaimed_to_hold():
    """The honest refusal. A Pause that would hold zero documents while three are mid-fix
    promises a stop the backend cannot deliver."""
    controls = {c["action"]: c for c in exceptions.run_controls(
        state="running", counters=_counters(processing=3))}
    assert controls["pause"]["available"] is False
    assert "Nothing is waiting to be held" in controls["pause"]["reason"]
    assert "3 attempts already in flight will finish" in controls["pause"]["reason"]


def test_a_finished_run_offers_neither_cancel_nor_pause():
    controls = {c["action"]: c for c in exceptions.run_controls(
        state="completed", counters=_counters(completed=10), terminal=True)}
    assert controls["cancel"]["available"] is False and controls["pause"]["available"] is False
    assert controls["resume"]["available"] is False


def test_an_unavailable_control_is_reported_rather_than_hidden():
    """A control that disappears reads as a bug in the panel; one that says why reads as an
    answer."""
    for state, counters in (("completed", _counters(completed=1)),
                            ("running", _counters(processing=1))):
        actions = [c["action"] for c in exceptions.run_controls(state=state, counters=counters)]
        assert actions == ["cancel", "pause", "resume"]
        assert all(c["reason"] or c["available"]
                   for c in exceptions.run_controls(state=state, counters=counters))


# ── the durable hold, end to end ──────────────────────────────────────────────

def _queue(store, files, *, claim=0):
    store.init_scan_run(SID, "sharepoint", len(files), "2026-09-01T00:00:00Z", "r", "h",
                        owner=OWNER)
    ids = [store.enqueue_job("remediate_file", {"scan_id": SID, "file": f, "source": "sharepoint"},
                             scan_id=SID, batch_id="b1") for f in files]
    for _ in range(claim):
        store.claim_job("w1")
    return ids


def test_pause_holds_only_unclaimed_work_and_resume_releases_exactly_that(store):
    _queue(store, ["a.docx", "b.docx", "c.docx"], claim=1)
    held = store.pause_remediation_run(SID, actor=OWNER)
    assert held["held"] == 2, "the claimed attempt must not be deferred"
    assert store.remediation_run_paused(SID) is True

    released = store.resume_remediation_run(SID, actor=OWNER)
    assert released["released"] == 2
    assert store.remediation_run_paused(SID) is False


def test_resume_does_not_drag_a_backoff_retry_forward(store):
    """The `run_after` predicate is exact, so a document genuinely waiting on its own backoff
    keeps its schedule when somebody presses Resume for the rest of the run."""
    ids = _queue(store, ["a.docx", "b.docx"])
    later = "2030-01-01T00:00:00+00:00"
    with store._db.cursor() as cur:
        store._db.execute(cur, "UPDATE jobs SET run_after=%s WHERE id=%s", (later, ids[1]))
    before = {jid: store.get_job(jid)["run_after"] for jid in ids}
    store.pause_remediation_run(SID, actor=OWNER)
    assert all(store.get_job(jid)["run_after"] not in before.values() for jid in ids), \
        "the hold must actually defer both rows while it stands"
    store.resume_remediation_run(SID, actor=OWNER)
    assert {jid: store.get_job(jid)["run_after"] for jid in ids} == before, (
        "resume restored something other than each job's own schedule — clearing the column "
        "instead would make the backoff retry happen EARLIER than it was due")
    assert store.get_job(ids[1])["run_after"] == later


def test_paused_is_derived_from_the_hold_and_never_from_an_idle_queue(store):
    """The rule remediation_run.py has carried since Phase 1, now that something can produce the
    state: an idle queue with no hold row is `waiting`, exactly as before."""
    _queue(store, ["a.docx", "b.docx"])
    idle = remediation_run.build_snapshot(store.remediation_run_facts(SID))
    assert idle["state"] != "paused" and idle["paused"] is False

    store.pause_remediation_run(SID, actor=OWNER)
    held = remediation_run.build_snapshot(store.remediation_run_facts(SID))
    assert held["state"] == "paused" and held["paused"] is True
    assert held["reason"] == "held_by_operator"


def test_a_finished_run_is_never_reported_as_paused():
    """A hold over a run with no outstanding work holds nothing. Saying "Run paused" there is the
    same class of error as saying "Applying fixes" over an idle queue."""
    counters = _counters(completed=4)
    resolved = remediation_run.derive_run_state(counters, total=4, claimed_any=True, paused=True)
    assert resolved["state"] == "completed"


def test_a_pause_taken_mid_flight_still_reports_the_work_that_is_finishing():
    counters = _counters(processing=3, waiting=5, completed=2)
    resolved = remediation_run.derive_run_state(counters, total=10, claimed_any=True, paused=True)
    assert resolved["state"] == "paused"
    assert "running" in resolved["also"], (
        "the headline is paused, and the three attempts still finishing must remain visible")


def test_cancel_stops_outstanding_work_and_keeps_finished_corrections(store):
    _queue(store, ["a.docx", "b.docx"], claim=1)
    store.save_file_result(SID, {"file": "a.docx", "engine": "office", "status": "pass",
                                 "score": 40, "compliant": 0, "skipped_rules": 0, "issues": []},
                           "2026-09-01T00:00:00Z")
    store.record_remediation(SID, "a.docx", blob_url="http://b/1", corrected_sha256="a" * 64)
    asked = store.request_remediation_cancel(SID)
    assert asked == 2, "both the running attempt and the queued document are asked to stop"
    facts = store.remediation_run_facts(SID)
    assert facts["cancel_requested"] is True
    assert facts["corrected_stored"] == 1, "a cancel must not retract a finished correction"


# ── linking an outcome to what it produced ────────────────────────────────────

def test_a_completed_outcome_links_to_its_corrected_copy_and_its_evidence():
    """PRD §13 requires every automatic decision to record before/after artifacts. A panel that
    reports "140 documents complete" and offers no way to see one of them makes the operator go
    and check in SharePoint whether ACP did what it said."""
    rows = exceptions.completed_outcomes([_record(file="a.docx")])
    assert rows[0]["links"] == {
        "corrected_copy": f"/scans/{SID}/files/a.docx/remediated",
        "evidence": f"/scans/{SID}/files/a.docx/remediation-diffs",
        "delivered": "http://sp/ok"}


def test_a_link_is_a_reference_and_never_an_access_grant():
    """Both paths are owner-scoped routes that already exist, so handing one to somebody
    unauthorised gets them a 404. A pre-signed blob URL would be the opposite — a link that IS
    the permission — and the store holds one; it is deliberately not built here."""
    links = exceptions.outcome_links(_record())
    assert not any("sig=" in value or "token" in value.lower() for value in links.values())
    assert links["corrected_copy"].startswith("/scans/")


def test_a_document_with_no_corrected_copy_gets_no_link_to_one():
    """Absent, not null: a `corrected_copy` link on a document ACP never corrected would 404, and
    nothing can tell an empty string from a broken one until somebody clicks it."""
    assert "corrected_copy" not in exceptions.outcome_links(
        _record(artifact_stored_at=None))
    assert "evidence" not in exceptions.outcome_links(_record(fixes_verified=0))
    assert "delivered" not in exceptions.outcome_links(_record(delivered_url=None))


def test_a_terminal_document_with_nothing_to_show_is_not_reported_as_completed():
    """`skipped` is the partition's slot for "in scope, no eligible fix applied". Listing one
    here would offer a corrected copy that does not exist."""
    assert exceptions.completed_outcomes([_record(outcome="skipped")]) == []
    assert exceptions.completed_outcomes([_record(artifact_stored_at=None)]) == []


def test_a_stored_but_undelivered_copy_is_both_completed_and_a_delivery_exception():
    """Both facts are true of the document and the panel says both: the copy is real and
    downloadable, and it has not reached the provider."""
    record = _record(file="b.docx", delivered_url=None)
    assert exceptions.classify_exception(record)[0] == "delivery_failure"
    completed = exceptions.completed_outcomes([record])
    assert completed[0]["delivered"] is False
    assert "corrected_copy" in completed[0]["links"] and "delivered" not in completed[0]["links"]


def test_the_completed_list_is_bounded_and_newest_first():
    records = [_record(file=f"doc-{i}.docx", artifact_stored_at=f"2026-09-0{i}T00:00:00Z")
               for i in range(1, 10)]
    rows = exceptions.completed_outcomes(records)
    assert len(rows) == exceptions.COMPLETED_LIMIT
    assert rows[0]["file"] == "doc-9.docx"
    assert [row["file"] for row in rows] == sorted(
        (r["file"] for r in rows), key=lambda f: f, reverse=True)


def test_every_exception_row_carries_the_same_links():
    """The delivery-failure row is where an operator asks "what would you re-send?" — and the
    answer is a file they can open before authorising the write."""
    row = exceptions.exception_row(_record(delivered_url=None))
    assert row["links"]["corrected_copy"].endswith("/remediated")
