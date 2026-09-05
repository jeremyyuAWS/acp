"""Durable structured remediation progress, and the reconnect contract built on it — ADR 0052.

ADR 0051 shipped `Last-Event-ID` resume over a log whose remediation rows carried a filename in a
JSON blob, no correlation, and no notion of what counted as progress. This file covers the four
things that changed, and it is organised around the ones that are QUIET when they break:

  * Material progress vs lease heartbeat. A wedged worker used to refresh the run's progress clock
    every few seconds through `touch_job`, so the stall predicate could never fire and the panel
    reported progress on the strength of a thread still breathing. Nothing about that looks wrong.
  * Retention. ADR 0051 wrote the "pruned past your cursor" branch for a condition nothing could
    produce. Now something can, so the branch is exercised against a REAL prune rather than a
    hand-built DELETE — the day retention lands is the day resume would otherwise start losing
    events in the window nobody is watching.
  * Filename suppression. A disclosure is not recoverable, so both read paths are asserted, not
    just the one a client normally uses.
  * The stream's close. `in_flight == 0` is a statement about jobs; the client's `onDone` drives
    the batch's finalization, so closing there finalizes over delivery that has not happened.
"""
from __future__ import annotations
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "owner@example.com"
OTHER = "stranger@example.com"


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _ago(**kw) -> str:
    return _iso(datetime.now(timezone.utc) - timedelta(**kw))


# ── the structured record ────────────────────────────────────────────────────

def test_an_event_records_document_attempt_phase_time_id_and_correlation(isolated_store):
    """Every field PRD §8 names, on the row, addressable by name.

    `document` and `correlation_id` are the two that are new, and they are COLUMNS: the reads
    below (one document's history; one run's material progress) are indexed reads that a JSON
    blob cannot serve, and a name reachable from exactly one place can be suppressed in exactly
    one place.
    """
    seq = isolated_store.append_scan_event(
        "s-shape", "remediate.fix_applied", owner_email=OWNER,
        document="Board Pack.pdf", correlation_id="batch-1",
        phase="applying", attempt=2, job_id="job-9", detail={"fixes": 3})
    assert seq == 1

    (event,) = isolated_store.list_scan_events("s-shape")
    assert event["document"] == "Board Pack.pdf"
    assert event["correlation_id"] == "batch-1"
    assert event["attempt"] == 2
    assert event["phase"] == "applying"
    assert event["seq"] == 1
    assert event["event_id"]                      # the stable identity, distinct from the cursor
    assert event["occurred_at"]
    # The filename is NOT duplicated into detail. Two copies of one fact is two places for a
    # suppression rule to be applied to only one of them.
    assert event["detail"] == {"fixes": 3}


def test_the_filename_is_written_to_the_column_and_not_into_detail(monkeypatch, isolated_store):
    """The emit site, not just the store. `_rem_event` is the one wrapper every remediation
    handler narrates through, so where IT puts the name is where the name is."""
    import core
    import handlers
    monkeypatch.setattr(core, "store", isolated_store)

    handlers._rem_event("s-emit", "remediate.verified",
                        {"id": "job-3", "attempts": 1, "batch_id": "batch-7"},
                        "Q3 Report.docx", fixes=2)

    (event,) = isolated_store.list_scan_events("s-emit")
    assert event["document"] == "Q3 Report.docx"
    assert event["correlation_id"] == "batch-7"
    assert event["detail"] == {"fixes": 2}
    assert "file" not in (event["detail"] or {})


def test_the_correlation_falls_back_to_the_payloads_stage_execution(monkeypatch, isolated_store):
    """A job row read back through a path that does not carry `batch_id` still correlates: the
    payload has held `stage_execution_id` since enqueue_stage_batch wrote it."""
    import core
    import handlers
    monkeypatch.setattr(core, "store", isolated_store)

    handlers._rem_event("s-payload", "remediate.delivered",
                        {"id": "job-4", "attempts": 1,
                         "payload": '{"stage_execution_id": "batch-99"}'},
                        "Notes.pptx")

    (event,) = isolated_store.list_scan_events("s-payload")
    assert event["correlation_id"] == "batch-99"


# ── parallel documents keep independent, ordered histories ───────────────────

def test_parallel_documents_keep_independent_ordered_histories(isolated_store):
    """PRD §6D. Three documents remediate at once and interleave in one log; each one's own
    account must come back complete and in order.

    Ordered by `seq`, which is the whole reason `seq` exists — `occurred_at` is a wall clock
    written by whichever replica ran the job, and two replicas writing for one scan can stamp
    out of order (ADR 0042's reason for rejecting a timestamp cursor).
    """
    interleaved = [
        ("A.pdf", "remediate.fix_applied"), ("B.docx", "remediate.fix_applied"),
        ("C.pptx", "remediate.fix_applied"), ("B.docx", "remediate.verified"),
        ("A.pdf", "remediate.verified"), ("B.docx", "remediate.delivered"),
        ("C.pptx", "remediate.verification_failed"), ("A.pdf", "remediate.delivered"),
    ]
    for document, kind in interleaved:
        isolated_store.append_scan_event("s-par", kind, owner_email=OWNER,
                                         document=document, correlation_id="batch-1")

    a = isolated_store.list_scan_events("s-par", document="A.pdf")
    b = isolated_store.list_scan_events("s-par", document="B.docx")
    c = isolated_store.list_scan_events("s-par", document="C.pptx")

    assert [e["kind"] for e in a] == ["remediate.fix_applied", "remediate.verified",
                                      "remediate.delivered"]
    assert [e["kind"] for e in b] == ["remediate.fix_applied", "remediate.verified",
                                      "remediate.delivered"]
    assert [e["kind"] for e in c] == ["remediate.fix_applied", "remediate.verification_failed"]
    # Independent, and each ordered: no document's history borrows another's position.
    for history in (a, b, c):
        assert [e["seq"] for e in history] == sorted(e["seq"] for e in history)
    assert {e["seq"] for e in a}.isdisjoint({e["seq"] for e in b})


def test_a_second_run_over_one_scan_is_separable_by_correlation(isolated_store):
    """`scan_id` cannot separate two remediation batches over the same scan, and the panel is
    scoped to the latest one — an unscoped count is what reported `failed: 294` against a
    147-document batch."""
    for kind in ("remediate.accepted", "remediate.fix_applied"):
        isolated_store.append_scan_event("s-two", kind, document="A.pdf",
                                         correlation_id="batch-old")
    isolated_store.append_scan_event("s-two", "remediate.fix_applied", document="A.pdf",
                                     correlation_id="batch-new")

    assert len(isolated_store.list_scan_events("s-two", correlation_id="batch-old")) == 2
    assert len(isolated_store.list_scan_events("s-two", correlation_id="batch-new")) == 1


# ── material progress is not a heartbeat ─────────────────────────────────────

def test_the_classification_names_progress_and_liveness_apart(isolated_store):
    for kind in isolated_store.MATERIAL_SCAN_EVENT_KINDS:
        assert isolated_store.is_material_event(kind), kind
    for kind in isolated_store.LEASE_SCAN_EVENT_KINDS:
        assert not isolated_store.is_material_event(kind), kind
    # The two sets are disjoint by construction; asserting it stops a future kind being added to
    # both and quietly making a lease signal count as progress.
    assert isolated_store.MATERIAL_SCAN_EVENT_KINDS.isdisjoint(
        isolated_store.LEASE_SCAN_EVENT_KINDS)


def test_an_unknown_kind_is_not_material(isolated_store):
    """The direction matters. Treating an unrecognised kind as progress would let any telemetry
    line added later silently reset a stall clock — unknown must stay unknown, never success."""
    assert not isolated_store.is_material_event("remediate.something_new")
    assert not isolated_store.is_material_event(None)
    assert not isolated_store.is_material_event("")


def test_latest_material_event_ignores_lease_activity(isolated_store):
    isolated_store.append_scan_event("s-mat", "remediate.fix_applied", document="A.pdf",
                                     occurred_at=_ago(minutes=40))
    isolated_store.append_scan_event("s-mat", "scan.interrupted", occurred_at=_ago(minutes=1))
    isolated_store.append_scan_event("s-mat", "scan.retrying", occurred_at=_ago(seconds=5))

    newest = isolated_store.latest_material_event_at("s-mat")
    # The reclaim and the retry are the two most recent rows and neither may advance this.
    assert newest is not None and newest < _ago(minutes=30)


def test_an_empty_log_reports_unknown_progress_not_zero_and_not_now(isolated_store):
    """`None` is UNKNOWN. Returning a timestamp would assert progress that nothing recorded;
    returning an epoch zero would assert a run that has been stalled since 1970."""
    assert isolated_store.latest_material_event_at("s-silent") is None


def test_a_run_predating_correlation_ids_is_not_read_as_having_made_no_progress(isolated_store):
    """Rolling deploy. An older replica writes NULL into `correlation_id`; scoping the material
    read strictly to a batch would report those events as belonging to no run at all."""
    isolated_store.append_scan_event("s-mixed", "remediate.fix_applied", document="A.pdf")
    assert isolated_store.latest_material_event_at("s-mixed", correlation_id="batch-1") is not None


def test_a_heartbeat_does_not_advance_the_runs_progress_clock(monkeypatch, isolated_store):
    """THE DEFECT, end to end, through the facts the snapshot is built from.

    `touch_job` writes `updated_at` on every lease heartbeat. While `remediation_run_facts` read
    `max(updated_at)` as the run's latest progress, a worker wedged inside one document refreshed
    that clock indefinitely: `progress_age_s` never exceeded the stall threshold, so the stall
    predicate was not merely wrong, it was UNREACHABLE.
    """
    import core
    monkeypatch.setattr(core, "store", isolated_store)
    isolated_store.enqueue_scan("s-hb", "local", OWNER, "scan_discover", {})
    jid = isolated_store.enqueue_job("remediate_file", {"scan_id": "s-hb", "file": "A.pdf"},
                                     scan_id="s-hb", batch_id="batch-1")
    job = isolated_store.claim_job("worker-1", job_types=("remediate_file",))
    assert job and job["id"] == jid

    before = isolated_store.remediation_run_facts("s-hb")
    isolated_store.touch_job(jid, worker_id="worker-1", attempt=job["attempts"])
    after = isolated_store.remediation_run_facts("s-hb")

    # No material event was written, so the progress clock has nothing to say — and says nothing.
    assert before["latest_progress_at"] == after["latest_progress_at"] is None
    # The heartbeat is not lost, it is reported as what it is: evidence of a live worker.
    assert after["latest_heartbeat_at"] is not None


def test_a_material_event_does_advance_it(monkeypatch, isolated_store):
    """The other half of the bite check: if nothing can advance the clock, the test above would
    pass against a progress clock that is simply broken."""
    import core
    monkeypatch.setattr(core, "store", isolated_store)
    isolated_store.enqueue_scan("s-mv", "local", OWNER, "scan_discover", {})
    isolated_store.enqueue_job("remediate_file", {"scan_id": "s-mv", "file": "A.pdf"},
                               scan_id="s-mv", batch_id="batch-1")
    isolated_store.claim_job("worker-1", job_types=("remediate_file",))

    assert isolated_store.remediation_run_facts("s-mv")["latest_progress_at"] is None
    isolated_store.append_scan_event("s-mv", "remediate.fix_applied", document="A.pdf",
                                     correlation_id="batch-1")
    assert isolated_store.remediation_run_facts("s-mv")["latest_progress_at"] is not None


def test_a_live_lease_stops_a_slow_document_being_called_stalled():
    """PRD §22, both clauses: stalled needs a stale progress clock AND an unhealthy lease.

    This gate only became necessary when the progress clock became honest. Previously a heartbeat
    kept the age under the threshold, so the lease half was unreachable; now a genuinely slow
    document — one honest attempt, a live lease, a large PDF mid-render — would be announced as
    "Progress has stopped" without it.
    """
    import remediation_run
    counters = {k: 0 for k in remediation_run.DOCUMENT_OUTCOMES}
    counters["processing"] = 1

    healthy = remediation_run.derive_run_state(
        counters, total=1, claimed_any=True, progress_age_s=10_000, lease_healthy=True)
    assert healthy["state"] == "running"
    assert "stalled" not in healthy["also"]

    expired = remediation_run.derive_run_state(
        counters, total=1, claimed_any=True, progress_age_s=10_000, lease_healthy=False)
    assert expired["state"] == "stalled"


def test_an_unknown_progress_age_is_never_resolved_to_stalled():
    import remediation_run
    counters = {k: 0 for k in remediation_run.DOCUMENT_OUTCOMES}
    counters["processing"] = 1
    resolved = remediation_run.derive_run_state(
        counters, total=1, claimed_any=True, progress_age_s=None, lease_healthy=False)
    assert resolved["state"] == "running"


def test_the_snapshot_names_progress_and_liveness_apart():
    """One number called "latest progress" that a heartbeat could move is how the two facts got
    confused in the first place. They are separate keys now, and an unknown age is None — never
    0, which would assert the stamp was written just now."""
    import remediation_run
    snapshot = remediation_run.build_snapshot({
        "scan_id": "s", "run_id": "s", "jobs": [],
        "latest_progress_at": None, "latest_heartbeat_at": None,
    })
    assert snapshot["progress"]["material_at"] is None
    assert snapshot["progress"]["material_age_s"] is None
    assert snapshot["progress"]["heartbeat_at"] is None
    assert snapshot["progress"]["heartbeat_age_s"] is None
    assert snapshot["progress"]["lease_healthy"] is False


# ── retention (PRD §22) ──────────────────────────────────────────────────────

def test_retention_keeps_a_recent_event_however_many_follow_it(isolated_store):
    """"24 hours OR 10,000 events, whichever is GREATER" — so age alone never deletes."""
    for _ in range(30):
        isolated_store.append_scan_event("s-young", "remediate.fix_applied", document="A.pdf")
    assert isolated_store.prune_scan_events("s-young", max_age_hours=0, max_events=10) == 20
    oldest, newest = isolated_store.scan_event_bounds("s-young")
    assert (oldest, newest) == (21, 30)


def test_retention_keeps_an_old_event_that_is_inside_the_count_window(isolated_store):
    """The other half of "whichever is greater": a quiet run does not lose a 200-event history to
    nothing but the passage of a day."""
    for _ in range(30):
        isolated_store.append_scan_event("s-quiet", "remediate.fix_applied", document="A.pdf",
                                         occurred_at=_ago(days=9))
    assert isolated_store.prune_scan_events("s-quiet", max_age_hours=24, max_events=10_000) == 0
    assert isolated_store.scan_event_bounds("s-quiet") == (1, 30)


def test_retention_deletes_only_what_is_outside_both_windows(isolated_store):
    for _ in range(10):
        isolated_store.append_scan_event("s-both", "remediate.fix_applied", document="A.pdf",
                                         occurred_at=_ago(days=3))
    for _ in range(5):
        isolated_store.append_scan_event("s-both", "remediate.fix_applied", document="A.pdf")
    # Outside the count window: seq <= 15-6 = 9. Outside the age window: the first ten. The
    # intersection is nine rows; row 10 is old but still inside the count window.
    assert isolated_store.prune_scan_events("s-both", max_age_hours=24, max_events=6) == 9
    assert isolated_store.scan_event_bounds("s-both") == (10, 15)


def test_the_defaults_are_the_prds_decision(isolated_store):
    assert isolated_store.SCAN_EVENT_RETENTION_HOURS == 24
    assert isolated_store.SCAN_EVENT_RETENTION_COUNT == 10_000


def test_a_sweep_visits_runs_with_old_events_and_leaves_the_rest(isolated_store):
    for _ in range(12):
        isolated_store.append_scan_event("s-old", "remediate.fix_applied",
                                         occurred_at=_ago(days=5))
    for _ in range(12):
        isolated_store.append_scan_event("s-new", "remediate.fix_applied")
    removed = isolated_store.prune_scan_events(max_age_hours=24, max_events=4)
    assert removed == 8
    assert isolated_store.scan_event_bounds("s-old") == (9, 12)
    assert isolated_store.scan_event_bounds("s-new") == (1, 12)


def test_a_real_prune_makes_a_stale_cursor_reconcile(monkeypatch, isolated_store):
    """ADR 0051's pruned branch, exercised against retention rather than a hand-built DELETE.

    That branch was written for a condition nothing in production could produce, precisely so
    resume would not begin losing events silently on the day pruning landed. This is the fixture
    that proves the two halves meet.
    """
    import core
    import routes.scans as scans
    monkeypatch.setattr(core, "store", isolated_store)
    for _ in range(20):
        isolated_store.append_scan_event("s-pruned-real", "remediate.fix_applied",
                                         occurred_at=_ago(days=2))
    for _ in range(3):
        isolated_store.append_scan_event("s-pruned-real", "remediate.fix_applied")

    assert scans._resume_plan("s-pruned-real", "5") == (5, None)   # honourable before the prune
    isolated_store.prune_scan_events("s-pruned-real", max_age_hours=24, max_events=8)
    # 5 now needs events 6..23, and 6..15 are gone. Replaying from 5 would silently skip them.
    assert scans._resume_plan("s-pruned-real", "5") == (None, "events_pruned")
    # A cursor inside what survived is still a resume, not a reconcile.
    oldest, _newest = isolated_store.scan_event_bounds("s-pruned-real")
    assert scans._resume_plan("s-pruned-real", str(oldest)) == (oldest, None)


def test_retention_never_raises_on_an_unreadable_log(isolated_store, monkeypatch):
    """Housekeeping must never be able to fail the sweep that runs it — an exception here would
    stop lease reclamation, which is the sweep that actually recovers work."""
    class _Boom:
        def cursor(self, *a, **k):
            raise RuntimeError("database is away")
        supports_skip_locked = False
    monkeypatch.setattr(isolated_store, "_db", _Boom())
    assert isolated_store.prune_scan_events("s-any") == 0


def test_the_sweeper_runs_retention_and_reports_it():
    import sweeper

    class _Store:
        def __init__(self):
            self.pruned_with = None
        def reclaim_stuck_jobs(self, **kw): return 0
        def sweep_exhausted_jobs(self): return 0
        def sweep_orphaned_scans(self, **kw): return 0
        def rescue_unfinalized_scans(self): return 0
        def prune_scan_events(self, **kw):
            self.pruned_with = kw
            return 7

    store = _Store()
    sweeper._last_event_prune = 0.0
    result = sweeper.run_sweep(store, derive_interval_seconds=10 ** 9,
                              event_prune_interval_seconds=0)
    assert result["events_pruned"] == 7
    assert store.pruned_with is not None


def test_a_failing_prune_does_not_fail_the_sweep():
    import sweeper

    class _Store:
        def reclaim_stuck_jobs(self, **kw): return 3
        def sweep_exhausted_jobs(self): return 0
        def sweep_orphaned_scans(self, **kw): return 0
        def rescue_unfinalized_scans(self): return 0
        def prune_scan_events(self, **kw): raise RuntimeError("nope")

    sweeper._last_event_prune = 0.0
    result = sweeper.run_sweep(_Store(), derive_interval_seconds=10 ** 9,
                              event_prune_interval_seconds=0)
    assert result["reclaimed"] == 3 and result["events_pruned"] == 0


# ── filename privacy (PRD §22) ───────────────────────────────────────────────

def test_the_default_policy_shows_names_to_the_runs_owner(isolated_store):
    assert isolated_store.remediation_filename_privacy("s-1") == "visible"


def test_the_policy_can_be_set_to_suppressed(isolated_store):
    isolated_store.set_setting(isolated_store.FILENAME_PRIVACY_SETTING, "suppressed")
    assert isolated_store.remediation_filename_privacy("s-1") == "suppressed"


def test_an_unreadable_policy_suppresses_rather_than_guessing_visible(isolated_store,
                                                                     monkeypatch):
    """The one unknown in this change that does NOT stay unknown, and the asymmetry is the
    reason: guessing `visible` discloses a name the deployment configured away and cannot be
    undone once a frame is sent; guessing `suppressed` costs a label on a card whose document the
    owner can still identify by its ref."""
    monkeypatch.setattr(isolated_store, "get_setting",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("settings away")))
    assert isolated_store.remediation_filename_privacy("s-1") == "suppressed"


def test_a_suppressed_projection_withholds_the_name_and_keeps_the_identity(monkeypatch,
                                                                           isolated_store):
    import core
    import routes.scans as scans
    monkeypatch.setattr(core, "store", isolated_store)
    event = {"seq": 4, "kind": "remediate.fix_applied", "document": "Patient 4021 MRI.pdf",
             "detail": {"fixes": 2, "file": "Patient 4021 MRI.pdf"}}

    shown = scans._project_event(dict(event), "s-priv", "visible")
    hidden = scans._project_event(dict(event), "s-priv", "suppressed")

    assert shown["document"] == "Patient 4021 MRI.pdf"
    assert hidden["document"] is None
    assert hidden["document_suppressed"] is True
    assert "Patient" not in repr(hidden)
    # The identity survives suppression, which is what keeps per-document grouping and ordering
    # working on a run whose names are withheld.
    assert hidden["document_ref"] == shown["document_ref"]
    assert hidden["document_ref"]


def test_a_document_ref_does_not_correlate_across_runs():
    """Salted with the scan id: a shared handle would let a viewer of one run detect activity on
    the same document in another they cannot see."""
    import remediation_run
    same = remediation_run.document_ref("scan-a", "A.pdf")
    other_run = remediation_run.document_ref("scan-b", "A.pdf")
    assert same and other_run and same != other_run
    assert remediation_run.document_ref("scan-a", None) is None


def test_the_projection_marks_material_events_for_the_client(monkeypatch, isolated_store):
    import core
    import routes.scans as scans
    monkeypatch.setattr(core, "store", isolated_store)
    material = scans._project_event({"kind": "remediate.delivered"}, "s", "visible")
    lease = scans._project_event({"kind": "scan.interrupted"}, "s", "visible")
    assert material["material"] is True
    assert lease["material"] is False


def test_the_shared_operations_view_never_selects_the_document_column(isolated_store):
    """Live Operations spans workspace users. The suppression there is structural — the name is
    simply not in the SELECT list — rather than an allow-list somebody extends later."""
    isolated_store.append_scan_event("s-shared", "remediate.fix_applied", document="Payroll.xlsx",
                                     detail={"fixes": 1})
    summaries = isolated_store.recent_remediation_event_summaries(["s-shared"])
    assert summaries["s-shared"]
    assert "Payroll" not in repr(summaries)


# ── the stream's close ───────────────────────────────────────────────────────

def _finished(in_flight=0, **snapshot):
    import routes.scans as scans
    return scans._stream_is_finished({"in_flight": in_flight, "snapshot": snapshot})


def test_terminal_document_work_does_not_close_the_stream_while_delivery_is_pending():
    """PRD §21's recorded gap. `in_flight == 0` is a statement about JOBS; the client's `onDone`
    drives the batch's finalization, so closing there finalizes over delivery that has not
    happened. `completing` is the run state whose reason code is literally
    `delivery_reconciliation_outstanding`."""
    assert _finished(state="completing", also=[], delivery={"pending": 2}) is False
    assert _finished(state="completed", also=[], delivery={"pending": 0}) is True


def test_a_pending_delivery_behind_a_more_severe_headline_still_holds_the_stream():
    """Precedence displays the most severe applicable state, so a run owing both a review
    decision and a delivery shows `needs_attention` and carries `completing` in `also`. Reading
    only `state` would close over the delivery."""
    assert _finished(state="needs_attention", also=["completing"],
                     delivery={"pending": 1}) is False


def test_a_run_waiting_on_a_human_closes_as_it_always_did():
    """The stream stays open for reconciliation the run performs ITSELF, not for a review decision
    that may be hours away — that would be a held connection dressed up as liveness. The client's
    fallback poll covers it, which is what it already does today."""
    assert _finished(state="needs_attention", also=[], delivery={"pending": 0}) is True


def test_work_still_in_flight_always_holds_the_stream_open():
    assert _finished(in_flight=2, state="completed", also=[], delivery={"pending": 0}) is False


def test_an_unknown_pending_count_is_not_treated_as_zero():
    """Unknown is never success. Closing on a missing count would tell the client delivery
    finished when nothing said so."""
    assert _finished(state="completed", also=[], delivery={}) is False
    assert _finished(state="completed", also=[]) is False


def test_a_missing_snapshot_degrades_to_the_shipped_behaviour():
    """The snapshot build is wrapped in a try/except so a snapshot failure cannot take the stream
    down. If it swallowed, this must fall back to what shipped — not assert completion."""
    import routes.scans as scans
    assert scans._stream_is_finished({"in_flight": 0}) is True
    assert scans._stream_is_finished({"in_flight": 3}) is False


def test_a_pending_delivery_really_does_produce_the_completing_state():
    """The bite check on the rule above. Every assertion in this section is written against a
    literal `completing`, so if the snapshot never actually reaches that state for a run whose
    documents are done and whose copies are undelivered, the whole section tests nothing."""
    import remediation_run
    snapshot = remediation_run.build_snapshot({
        "scan_id": "s", "run_id": "s",
        "jobs": [{"file": "A.pdf", "status": "done"}],
        "corrected_stored": 1, "corrected_delivered": 0, "corrected_documents": ["A.pdf"],
    })
    assert snapshot["state"] == "completing"
    assert snapshot["reason"] == "delivery_reconciliation_outstanding"
    assert snapshot["terminal"] is False


def test_the_close_rule_can_only_ever_extend_the_stream():
    """The bite check on the rollout risk. Every input on which the shipped rule closed
    (`in_flight == 0`) must still close, or a run that finishes today would hang tomorrow — and
    the client's `onDone` is what finalizes the batch, so a stream that never closes is a batch
    that never finalizes."""
    import remediation_run
    import routes.scans as scans
    counters = {k: 0 for k in remediation_run.DOCUMENT_OUTCOMES}
    counters["completed"] = 3
    for pending in (0, 2):
        snapshot = remediation_run.build_snapshot({
            "scan_id": "s", "run_id": "s",
            "jobs": [{"file": f"{i}.pdf", "status": "done"} for i in range(3)],
            "corrected_stored": 3, "corrected_delivered": 3 - pending,
            "corrected_documents": [f"{i}.pdf" for i in range(3)],
        })
        finished = scans._stream_is_finished({"in_flight": 0, "snapshot": snapshot})
        # Pending delivery is the ONLY case that newly holds it open.
        assert finished is (pending == 0), (pending, snapshot["state"])
