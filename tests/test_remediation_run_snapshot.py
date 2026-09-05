"""The reconciled remediation run snapshot — PRD "Remediation Real-Time Operations Panel" §7-§9.

The defect this closes is not a rendering bug. On one paint the Remediate panel could show an
"Applying fixes" headline, zero active documents, every document queued, corrected copies already
saved, and a source label naming a provider the run does not use. Every number was true of its own
subsystem; together they were not an account of anything.

So these tests are about the ACCOUNT, and the ones that matter most assert things the old shape
could not express: that the six document counters partition the scope exactly, that a run with no
active attempt cannot claim to be applying fixes, that a SharePoint run is never labelled
OneDrive, and that an unreconcilable snapshot says so rather than picking one subsystem's number.
"""
from __future__ import annotations
import datetime as _dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import remediation_run as rr  # noqa: E402

OWNER = "owner@example.com"
OTHER = "stranger@example.com"
NOW = _dt.datetime(2026, 9, 5, 12, 0, 0, tzinfo=_dt.timezone.utc)


def _iso(**delta) -> str:
    return (NOW + _dt.timedelta(**delta)).isoformat()


def _job(file: str, status: str, **kw) -> dict:
    job = {"file": file, "status": status, "attempts": 0, "created_at": _iso(minutes=-10),
           "updated_at": _iso(minutes=-1), "run_after": _iso(minutes=-10)}
    job.update(kw)
    return job


def _facts(jobs, **kw) -> dict:
    facts = {"scan_id": "scan-1", "run_id": "scan-1", "batch_id": "b1", "jobs": jobs,
             "source": "sharepoint", "scan_snapshot_id": "scan-1",
             "started_at": _iso(minutes=-10), "latest_progress_at": _iso(minutes=-1),
             "review_documents": [], "review_items": 0, "corrected_documents": [],
             "corrected_stored": 0, "corrected_delivered": 0, "verified_documents": [],
             "fixes_applied": 0, "fixes_verified": 0, "locations": []}
    facts.update(kw)
    return facts


def _snap(jobs, **kw) -> dict:
    return rr.build_snapshot(_facts(jobs, **kw), now=NOW)


# ── the partition ────────────────────────────────────────────────────────────

def test_the_six_counters_always_sum_to_the_documents_in_scope():
    """PRD §17.3. The property, over every job status the queue can produce, mixed together —
    not one case at a time, which is the arrangement that lets a missing branch hide."""
    jobs = [_job("a.docx", "done"), _job("b.docx", "running", lease_expires_at=_iso(minutes=5)),
            _job("c.docx", "queued"), _job("d.docx", "dead"),
            _job("e.docx", "cancelled"), _job("f.docx", "running", lease_expires_at=_iso(minutes=-5)),
            _job("g.docx", "queued", run_after=_iso(minutes=3)),
            _job("h.docx", "surprising-new-status"), _job("i.docx", "done")]
    snap = _snap(jobs, corrected_documents=["a.docx"], corrected_stored=1,
                 review_documents=["i.docx"], review_items=2)
    assert snap["total_documents"] == 9
    assert sum(snap["documents"][k] for k in rr.DOCUMENT_OUTCOMES) == 9
    assert snap["integrity"]["ok"], snap["integrity"]["violations"]


def test_every_job_status_lands_in_exactly_one_outcome():
    for status in ("queued", "running", "done", "dead", "cancelled", "", "wat"):
        outcome, reason = rr.classify_document(_job("x", status), now=NOW)
        assert outcome in rr.DOCUMENT_OUTCOMES, (status, outcome)
        assert reason


def test_a_finished_job_with_no_correction_and_no_review_is_skipped_not_completed():
    """`done` is the queue's word, not the run's outcome. A document the worker opened and found
    no eligible approved fix for is in scope and was not completed — `skipped` is the partition's
    slot for exactly that, and counting it as completed is how a run reports fixing documents it
    did not touch."""
    assert rr.classify_document(_job("x", "done"), now=NOW)[0] == "skipped"
    assert rr.classify_document(_job("x", "done"), now=NOW, has_correction=True)[0] == "completed"
    assert rr.classify_document(_job("x", "done"), now=NOW, review_pending=True)[0] == "review"


def test_an_expired_lease_is_waiting_rather_than_processing_or_failed():
    """The sweeper will hand it to another worker, so nobody is working on it right now and no
    attempt has been exhausted. Counting it as processing is what let 'Applying fixes' outlive
    the workers that were applying them."""
    outcome, reason = rr.classify_document(
        _job("x", "running", lease_expires_at=_iso(minutes=-30)), now=NOW)
    assert (outcome, reason) == ("waiting", "lease_expired")


def test_a_lease_that_has_only_just_expired_is_still_processing():
    """Between expiry and the sweeper's reclaim the document would otherwise flicker out of
    `processing` and back on the next poll. The grace is what stops the panel strobing."""
    assert rr.classify_document(
        _job("x", "running", lease_expires_at=_iso(seconds=-5)), now=NOW)[0] == "processing"


# ── run state ────────────────────────────────────────────────────────────────

def test_a_queued_run_with_no_active_attempt_cannot_display_applying_fixes():
    """PRD §17.2 — the headline defect, asserted directly. `running` is the only state whose
    phase rail can show `applying` as active, and only an active attempt can produce it."""
    snap = _snap([_job(f"{i}.docx", "queued") for i in range(5)])
    assert snap["state"] == "accepted"
    assert snap["documents"]["processing"] == 0
    applying = next(p for p in snap["phases"] if p["key"] == "applying")
    assert applying["status"] != "active"

    # ...and once workers went away mid-run, it is `waiting`, still never `running`.
    snap = _snap([_job("a.docx", "done"), _job("b.docx", "queued", attempts=1)],
                 corrected_documents=["a.docx"], corrected_stored=1)
    assert snap["state"] == "waiting"


def test_running_requires_an_active_attempt():
    snap = _snap([_job("a.docx", "running", lease_expires_at=_iso(minutes=5), attempts=1),
                  _job("b.docx", "queued")])
    assert snap["state"] == "running"
    assert snap["documents"]["processing"] == 1


def test_state_precedence_is_the_prd_order_and_not_whichever_fact_answered_last():
    counters = {"completed": 0, "processing": 2, "waiting": 1, "review": 1,
                "failed": 0, "skipped": 0}
    resolved = rr.derive_run_state(counters, total=4, claimed_any=True, progress_age_s=5)
    # Needs attention outranks running (PRD §7) — but the run still SAYS it is processing, in
    # `also`, so a live run's progress is not hidden behind the more severe headline.
    assert resolved["state"] == "needs_attention"
    assert "running" in resolved["also"]


def test_a_stall_is_only_claimable_once_something_was_claimed():
    """A queue nobody has picked up is `waiting` — 'no compatible processing slot is currently
    active' — and reporting that capacity fact as a fault is a different, wrong story."""
    jobs = [_job("a.docx", "queued")]
    never_claimed = _snap(jobs, latest_progress_at=_iso(hours=-3))
    assert never_claimed["state"] == "accepted"

    claimed = _snap([_job("a.docx", "queued", attempts=1)], latest_progress_at=_iso(hours=-3))
    assert claimed["state"] == "stalled"


def test_cancellation_overrides_every_processing_state():
    jobs = [_job("a.docx", "running", lease_expires_at=_iso(minutes=5))]
    assert _snap(jobs, cancel_requested=True)["state"] == "cancel_requested"
    assert _snap(jobs, cancelled=True)["state"] == "cancelled"


def test_a_run_with_exceptions_left_does_not_report_plain_completed():
    snap = _snap([_job("a.docx", "done"), _job("b.docx", "dead")],
                 corrected_documents=["a.docx"], corrected_stored=1, corrected_delivered=1)
    assert snap["state"] == "completed_with_exceptions"
    assert snap["terminal"] is True

    clean = _snap([_job("a.docx", "done")], corrected_documents=["a.docx"],
                  corrected_stored=1, corrected_delivered=1)
    assert clean["state"] == "completed"


def test_documents_terminal_but_a_corrected_copy_undelivered_is_completing_not_completed():
    """PRD §11's delivery-failure class: the fix and its verification stand, only the write to
    the destination is outstanding. Reporting that run as complete is what makes a lost corrected
    copy invisible."""
    snap = _snap([_job("a.docx", "done")], corrected_documents=["a.docx"],
                 corrected_stored=1, corrected_delivered=0)
    assert snap["state"] == "completing"
    assert snap["delivery"] == {"stored": 1, "delivered": 0, "pending": 1, "eligible": 1,
                                "latest_at": None}


def test_no_run_at_all_is_draft_rather_than_a_completed_run_of_zero_documents():
    assert _snap([])["state"] == "draft"


def test_paused_is_declared_but_never_derived():
    """ACP has no pause control for a remediation run (PRD §18's first open decision). A state
    nothing can produce must not be inferred from an idle queue — which is exactly the mistake
    the rest of this module exists to stop."""
    assert "paused" in rr.RUN_STATES
    assert "paused" not in rr.STATE_PRECEDENCE
    for jobs in ([], [_job("a.docx", "queued")], [_job("a.docx", "running")],
                 [_job("a.docx", "dead")]):
        assert _snap(jobs)["state"] != "paused"


# ── units ────────────────────────────────────────────────────────────────────

def test_applied_verified_and_delivered_are_separately_labelled():
    """PRD §17.4. `remediation_status` served remediation_diff's row count as `fixes_applied` and
    its distinct-file count as `verified_documents` — one table under two names, neither of which
    was 'fixes applied'. Here the four are four keys and no key is a bare 'verified'."""
    snap = _snap([_job("a.docx", "done")], fixes_applied=12, fixes_verified=9,
                 verified_documents=["a.docx"], corrected_documents=["a.docx"],
                 corrected_stored=1, corrected_delivered=1)
    assert snap["fixes"]["applied"] == 12
    assert snap["fixes"]["verified"] == 9
    assert snap["fixes"]["verification_failures"] == 3
    assert snap["fixes"]["documents_verified"] == 1
    assert snap["delivery"]["delivered"] == 1
    assert "verified" not in snap  # never a bare, unit-less count at the top level


# ── source identity ──────────────────────────────────────────────────────────

def test_a_sharepoint_run_is_never_labelled_onedrive():
    """PRD §17.1. Every other surface in this repo labels the provider 'SharePoint / OneDrive'
    (store._SOURCE_LABEL and five frontend copies of it), which names two providers for a run
    that uses one. This panel names the one."""
    ident = rr.source_identity(scan_id="scan-1", provider="sharepoint",
                               locations=[{"site_name": "Legal", "library_name": "Contracts"}])
    assert ident["provider_label"] == "SharePoint"
    assert "OneDrive" not in (ident["breadcrumb"] or "")
    assert ident["breadcrumb"] == "SharePoint · Legal · Contracts"
    assert not any("OneDrive" in v for v in rr.PROVIDER_LABELS.values() if v != "OneDrive")


def test_an_unknown_provider_is_echoed_rather_than_mapped_to_a_plausible_neighbour():
    ident = rr.source_identity(scan_id="s", provider="box")
    assert ident["provider_label"] == "box"
    assert ident["breadcrumb"] == "box"


def test_many_sites_are_counted_rather_than_named_one_at_random():
    ident = rr.source_identity(scan_id="s", provider="sharepoint", locations=[
        {"site_name": "Legal", "library_name": "Contracts"},
        {"site_name": "Finance", "library_name": "Invoices"}])
    assert ident["breadcrumb"] == "SharePoint · 2 sites · 2 libraries"


# ── invariants ───────────────────────────────────────────────────────────────

def test_a_partition_that_does_not_sum_is_reported_not_repaired():
    snap = _snap([_job("a.docx", "done")], corrected_documents=["a.docx"], corrected_stored=1,
                 corrected_delivered=1)
    snap["documents"]["completed"] = 5          # a subsystem disagreeing with the scope
    violations = rr.check_invariants(snap)
    assert [v["invariant"] for v in violations] == ["document_partition"]
    assert violations[0]["metric"] == "documents"


def test_more_verified_fixes_than_applied_is_a_violation():
    snap = _snap([_job("a.docx", "done")], fixes_applied=2, fixes_verified=7,
                 corrected_documents=["a.docx"], corrected_stored=1, corrected_delivered=1)
    assert any(v["invariant"] == "verified_within_applied" for v in snap["integrity"]["violations"])
    assert snap["integrity"]["ok"] is False
    # The measured values SURVIVE the violation — the panel keeps showing last-confirmed numbers
    # and names the affected metric, rather than the server silently choosing one of them.
    assert snap["fixes"]["applied"] == 2 and snap["fixes"]["verified"] == 7
    assert snap["integrity"]["affected"] == ["fixes"]


def test_a_terminal_run_with_an_active_attempt_is_a_violation():
    snap = _snap([_job("a.docx", "done")], corrected_documents=["a.docx"], corrected_stored=1,
                 corrected_delivered=1)
    assert snap["state"] == "completed"
    snap["documents"]["processing"] = 1
    snap["documents"]["completed"] = 0
    assert any(v["invariant"] == "terminal_has_no_active_attempt"
               for v in rr.check_invariants(snap))


def test_a_source_naming_a_different_scan_snapshot_is_a_violation():
    snap = _snap([_job("a.docx", "queued")], scan_snapshot_id="some-other-scan")
    assert any(v["invariant"] == "source_matches_scan" for v in snap["integrity"]["violations"])


def test_a_healthy_snapshot_reports_no_violations():
    snap = _snap([_job("a.docx", "running", lease_expires_at=_iso(minutes=5), attempts=1),
                  _job("b.docx", "queued")])
    assert snap["integrity"] == {"ok": True, "violations": [], "affected": []}


# ── revision ─────────────────────────────────────────────────────────────────

def test_the_revision_advances_with_the_newest_durable_event_and_not_with_the_clock():
    early = _snap([_job("a.docx", "queued")], latest_progress_at=_iso(minutes=-5))
    late = _snap([_job("a.docx", "queued")], latest_progress_at=_iso(minutes=-1))
    assert late["revision"] > early["revision"]
    # Two reads of an unchanged run agree, whatever the wall clock did between them — which is
    # what makes a revision usable for gap detection rather than a timestamp in disguise.
    again = rr.build_snapshot(_facts([_job("a.docx", "queued")], latest_progress_at=_iso(minutes=-5)),
                              now=NOW + _dt.timedelta(seconds=30))
    assert again["revision"] == early["revision"]


# ── the route ────────────────────────────────────────────────────────────────

@pytest.fixture()
def gated_client(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: True)
    client = TestClient(app)

    def as_user(email):
        client.headers.update({"Authorization": f"Bearer {email}"})
        return client
    return as_user


def _scan_with_batch(store, scan_id: str, files: list[str], source: str = "sharepoint") -> str:
    store.enqueue_scan(scan_id, source, OWNER, "scan_discover", {})
    for file in files:
        store.enqueue_job("remediate_file", {"scan_id": scan_id, "file": file},
                          scan_id=scan_id, batch_id="batch-1")
    return scan_id


def test_a_stranger_cannot_read_someone_elses_run_snapshot(gated_client, isolated_store):
    sid = _scan_with_batch(isolated_store, "s-snap-1", ["a.docx"])
    assert gated_client(OTHER).get(f"/scans/{sid}/remediation/snapshot").status_code == 404
    assert gated_client(OWNER).get("/scans/nope/remediation/snapshot").status_code == 404


def test_the_owner_gets_a_reconciled_snapshot_of_their_own_run(gated_client, isolated_store):
    sid = _scan_with_batch(isolated_store, "s-snap-2", ["a.docx", "b.docx", "c.docx"])
    r = gated_client(OWNER).get(f"/scans/{sid}/remediation/snapshot")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    snap = r.json()
    assert snap["total_documents"] == 3
    assert sum(snap["documents"][k] for k in rr.DOCUMENT_OUTCOMES) == 3
    assert snap["state"] == "accepted"        # enqueued, nothing claimed
    assert snap["integrity"]["ok"], snap["integrity"]["violations"]
    assert snap["source"]["provider_label"] == "SharePoint"
    assert snap["revision"] is not None and snap["generated_at"]


def test_a_document_requeued_inside_one_batch_is_counted_once(gated_client, isolated_store):
    """The partition is asserted against the scope, so a document appearing twice in it would
    break the assertion — and a scope that double-counts is the same class of defect as the
    unscoped `failed: 294` that produced '-147 documents remediated'."""
    sid = _scan_with_batch(isolated_store, "s-snap-3", ["a.docx"])
    isolated_store.enqueue_job("remediate_file", {"scan_id": sid, "file": "a.docx"},
                               scan_id=sid, batch_id="batch-1")
    snap = gated_client(OWNER).get(f"/scans/{sid}/remediation/snapshot").json()
    assert snap["total_documents"] == 1
    assert sum(snap["documents"][k] for k in rr.DOCUMENT_OUTCOMES) == 1


def test_the_snapshot_scopes_to_the_latest_batch(gated_client, isolated_store):
    sid = _scan_with_batch(isolated_store, "s-snap-4", ["a.docx", "b.docx"])
    for file in ("a.docx",):
        isolated_store.enqueue_job("remediate_file", {"scan_id": sid, "file": file},
                                   scan_id=sid, batch_id="batch-2")
    snap = gated_client(OWNER).get(f"/scans/{sid}/remediation/snapshot").json()
    assert snap["batch_id"] == "batch-2"
    assert snap["total_documents"] == 1


def test_the_facts_method_reads_review_and_delivery_from_the_real_tables(isolated_store):
    sid = _scan_with_batch(isolated_store, "s-snap-5", ["a.docx"])
    isolated_store.queue_hitl_deferral(sid, "a.docx", "no faithful alt source", 2,
                                      rule_id="1.1.1", rule_name="Non-text Content")
    facts = isolated_store.remediation_run_facts(sid)
    assert facts["review_documents"] == ["a.docx"]
    assert facts["review_items"] == 1
    assert facts["source"] == "sharepoint"
    assert [j["file"] for j in facts["jobs"]] == ["a.docx"]
