"""A delivery-only retry re-sends a verified corrected copy, and CANNOT do anything else.

PRD "Remediation Real-Time Operations Panel" §11 splits the delivery failure out from every other
exception class for one reason: the corrected copy exists and passed verification, so the only
thing missing is a write to the provider. Re-running remediation to fix a failed SharePoint write
would re-open the source, re-apply fixes and re-verify — hours of work, a second set of counters,
and a fresh opportunity for the fix to land differently — to move some bytes ACP already has.

So this file is mostly about what the retry MUST NOT be able to do. Three of its guards are
structural rather than behavioural, and that is deliberate: a rule enforced by a reviewer noticing
is a rule that holds until somebody is in a hurry.

  * the delivery module's own imports are read, and a fixer appearing in them fails the suite;
  * the handler's source is read for the two store writers that would restamp a correction;
  * the idempotency key is the delivery table's PRIMARY KEY, so "one operation per duplicate
    request" is enforced by the database rather than by whichever request wins a read-then-write.

The refusals are the other half. Every one of them names a code AND a sentence, because the thing
this replaces is a greyed-out button with no explanation — and because "deliver it anyway" on an
artifact whose provenance ACP cannot state is how a stale document reaches a customer's library.
"""
from __future__ import annotations

import ast
import hashlib
import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

OWNER = "owner@example.com"
OTHER = "stranger@example.com"
SID = "run-1"
DOC = "policy.docx"
BYTES = b"corrected-bytes"
DIGEST = hashlib.sha256(BYTES).hexdigest()


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def store(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "delivery.db")
    return store_mod.Store()


def _seed(store, *, files=(DOC,), provider="sharepoint", delivered=False, digest=DIGEST,
          verified=True, owner=OWNER):
    """A finished run whose corrected copies were stored but never reached the provider."""
    store.init_scan_run(SID, provider, len(files), "2026-09-01T00:00:00Z", "rubric", "hash",
                        owner=owner)
    for name in files:
        store.save_file_result(SID, {
            "file": name, "engine": "office", "status": "pass", "score": 40, "compliant": 0,
            "skipped_rules": 0, "drive_file_id": f"id-{name}",
            "issues": [{"ruleId": "DOCX-ALT-001", "wcag": "1.1.1", "severity": "CRITICAL"}],
        }, "2026-09-01T00:00:00Z")
        store.add_inventory(SID, [{"file": name, "drive_id": "b!library", "path": "/Policies",
                                   "library_name": "Policies",
                                   "source_modified": "2026-08-30T00:00:00Z"}])
        job = store.enqueue_job("remediate_file",
                                {"scan_id": SID, "file": name, "source": provider},
                                scan_id=SID, batch_id="batch-1")
        store.claim_job("w1")
        store.complete_job(job, **_held(store, job))
        store.record_remediation(SID, name, drive_write_url="http://sp/1" if delivered else None,
                                 blob_url="http://blob/1", corrected_sha256=digest,
                                 corrected_bytes=len(BYTES))
        if verified:
            store.record_remediation_diffs(SID, name, [
                {"rule_id": "1.1.1", "before": "(no alt text)", "after": "A chart",
                 "note": "verified on re-scan"}])
    return store


def _held(store, job_id):
    from conftest import held
    return held(store, job_id)


def _records(store, *, cancelled=False):
    """The exception records the gate judges, composed exactly as the route composes them."""
    import remediation_exceptions as exceptions
    import remediation_run
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    run_facts = store.remediation_run_facts(SID)
    facts = store.remediation_exception_facts(SID)
    review = set(run_facts.get("review_documents") or ())
    corrected = set(run_facts.get("corrected_documents") or ())
    verified = set(run_facts.get("verified_documents") or ())
    outcomes = {j["file"]: remediation_run.classify_document(
        j, now=now, review_pending=j["file"] in review, has_correction=j["file"] in corrected,
        has_verified_fix=j["file"] in verified) for j in run_facts["jobs"]}
    return exceptions.compose_records(outcomes=outcomes, documents=facts["documents"],
                                      run_id=SID)


@pytest.fixture()
def gated_client(monkeypatch, store):
    import core
    from fastapi.testclient import TestClient
    from app import app
    monkeypatch.setattr(core, "store", store)
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


# ── a delivery failure costs the run no applied or verified fixes ─────────────

def test_a_delivery_failure_does_not_reduce_the_applied_or_verified_counts(store):
    """The premise of the whole class. The corrected copy exists and the fixes are verified; only
    the provider write is missing, and the counters must say so."""
    import remediation_run
    _seed(store)
    snapshot = remediation_run.build_snapshot(store.remediation_run_facts(SID))
    assert snapshot["fixes"]["verified"] == 1
    assert snapshot["fixes"]["verification_failures"] == 0
    assert snapshot["delivery"] == {**snapshot["delivery"], "stored": 1, "delivered": 0,
                                    "pending": 1}
    assert snapshot["documents"]["completed"] == 1, (
        "a document whose corrected copy was stored and verified is completed — the provider "
        "write is a separate fact, counted in `delivery`")

    groups = {g["key"]: g for g in
              __import__("remediation_exceptions").build_exception_groups(_records(store))}
    assert set(groups) == {"delivery_failure"}
    assert groups["delivery_failure"]["documents"] == 1


def test_a_delivered_document_raises_no_exception_at_all(store):
    import remediation_exceptions as exceptions
    _seed(store, delivered=True)
    assert exceptions.build_exception_groups(_records(store)) == []


# ── the retry cannot reach a fixer or a verifier ──────────────────────────────

FIXERS = ("remediate_office", "remediate_pdf", "remediate", "apply_alt", "apply_field_name",
          "apply_link_text", "apply_text_values", "apply_xlsx_labels", "assessment", "scanner_run")


def _imported_modules(path: Path) -> set[str]:
    """Every module name this file imports, at module level or inside a function."""
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_the_delivery_module_cannot_import_a_fixer_or_a_verifier():
    """Structural, because the alternative is trusting that nobody adds one in a hurry.

    A delivery-only retry that could reach a fixer could change `applied` and `verified` — the two
    numbers a delivery failure must leave alone — and it would do so on a path a user reaches by
    pressing a button labelled "Retry delivery only"."""
    imported = _imported_modules(ACP / "api/remediation_delivery.py")
    assert not (imported & set(FIXERS)), (
        f"api/remediation_delivery.py imports {sorted(imported & set(FIXERS))}. A delivery-only "
        f"retry must not be able to re-apply a fix or re-run verification.")


def test_the_delivery_worker_records_only_the_delivery_url():
    """`record_remediation` moves four columns including `remediated_at`; calling it from the
    delivery path would restamp a week-old correction with today's time, making the artifact look
    newer than the verification that passed it. `record_delivery_url` moves one."""
    source = (ACP / "api/handlers.py").read_text()
    start = source.index('def _deliver_corrected_copy(')
    body = source[start:]
    assert "record_delivery_url" in body
    assert "record_remediation(" not in body.split("def _audit_detail")[0], (
        "the delivery worker calls record_remediation, which would restamp remediated_at")


def test_a_delivery_retry_runs_no_fixer_and_writes_no_fix_rows(store, monkeypatch):
    """Behavioural companion to the two structural guards: run the worker for real against a
    stubbed provider and prove the run's fix rows are untouched."""
    import core
    import handlers
    import remediation_delivery as delivery
    monkeypatch.setattr(core, "store", store)
    _seed(store, provider="drive")
    before = store.remediation_run_facts(SID)

    record = _records(store)[0]
    import remediation_exceptions as exceptions
    decision = exceptions.delivery_retry_decision(record)
    assert decision["eligible"], decision

    store.claim_delivery(SID, DOC, idempotency_key=decision["idempotency_key"],
                         destination_provider="drive",
                         destination_key=decision["destination"]["key"],
                         artifact_digest=DIGEST, actor=OWNER)
    monkeypatch.setattr("blob.download_remediated", lambda owner, sid, f: BYTES)
    monkeypatch.setattr(delivery, "perform_delivery",
                        lambda **kw: "https://drive.example/corrected")
    handlers._deliver_corrected_copy(
        {"scan_id": SID, "file": DOC, "owner": OWNER, "actor": OWNER,
         "idempotency_key": decision["idempotency_key"], "artifact_digest": DIGEST,
         "destination": decision["destination"], "provider": "drive"},
        {"id": "job-x", "attempts": 1})

    after = store.remediation_run_facts(SID)
    assert (after["fixes_applied"], after["fixes_verified"]) == \
           (before["fixes_applied"], before["fixes_verified"]), \
        "a delivery-only retry changed the run's fix counts"
    assert after["corrected_delivered"] == 1
    assert after["latest_delivery_at"] == before["latest_delivery_at"], (
        "the delivery restamped remediated_at — a correction must not appear to have been "
        "produced at the moment it was re-sent")


# ── one operation per duplicate request ───────────────────────────────────────

def test_the_idempotency_key_is_free_of_time_and_nonce():
    """Two requests a second apart must compute the SAME key, or nothing downstream can collapse
    them. Keyed on the artifact digest so a genuinely new corrected copy is a new operation."""
    import remediation_exceptions as exceptions
    a = exceptions.delivery_idempotency_key(SID, DOC, "sharepoint:drive/b!x/folder/Remediated",
                                            DIGEST)
    b = exceptions.delivery_idempotency_key(SID, DOC, "sharepoint:drive/b!x/folder/Remediated",
                                            DIGEST)
    assert a == b
    other = exceptions.delivery_idempotency_key(
        SID, DOC, "sharepoint:drive/b!x/folder/Remediated", "0" * 64)
    assert other != a, "a different artifact must be a different operation"


def test_a_duplicate_claim_returns_the_first_operation_rather_than_a_second(store):
    _seed(store)
    key = "k" * 64
    first = store.claim_delivery(SID, DOC, idempotency_key=key, destination_provider="sharepoint",
                                destination_key="sharepoint:drive/b!library/folder/Remediated",
                                artifact_digest=DIGEST, actor=OWNER)
    second = store.claim_delivery(SID, DOC, idempotency_key=key, destination_provider="sharepoint",
                                  destination_key="sharepoint:drive/b!library/folder/Remediated",
                                  artifact_digest=DIGEST, actor=OWNER)
    assert first["claimed"] is True and second["claimed"] is False
    assert second["status"] == "in_flight"
    assert len(store.list_deliveries(SID)) == 1


def test_two_identical_retry_requests_enqueue_one_delivery_job(gated_client, store):
    """The user-visible property, end to end: pressing the button twice delivers once."""
    _seed(store)
    client = gated_client(OWNER)
    first = client.post(f"/scans/{SID}/remediation/exceptions/retry-delivery",
                        json={"files": [DOC]}).json()
    second = client.post(f"/scans/{SID}/remediation/exceptions/retry-delivery",
                         json={"files": [DOC]}).json()
    assert first["started"] == 1 and first["complete_success"] is True
    assert second["started"] == 0 and second["duplicate"] == 1
    assert first["results"][0]["idempotency_key"] == second["results"][0]["idempotency_key"]
    assert len(store.list_deliveries(SID)) == 1


# ── stale and missing artifacts are refused, with a reason ────────────────────

@pytest.mark.parametrize("mutate,code", [
    (lambda r: r.update({"artifact_digest": None}), "artifact_provenance_unknown"),
    (lambda r: r.update({"artifact_observed_digest": "0" * 64}), "artifact_stale"),
    (lambda r: r.update({"source_modified": "2099-01-01T00:00:00Z"}), "artifact_stale"),
    (lambda r: r.update({"artifact_stored_at": None}), "artifact_missing"),
    (lambda r: r.update({"fixes_verified": 0}), "artifact_not_verified"),
    (lambda r: r.update({"delivered_url": "http://sp/already"}), "already_delivered"),
    (lambda r: r.update({"provider": "blob"}), "provider_unsupported"),
    (lambda r: r.update({"destination_drive_id": None}), "destination_unknown"),
])
def test_an_undeliverable_artifact_is_refused_with_a_named_reason(store, mutate, code):
    import remediation_exceptions as exceptions
    _seed(store)
    record = _records(store)[0]
    mutate(record)
    decision = exceptions.delivery_retry_decision(record)
    assert decision["eligible"] is False
    assert decision["code"] == code, decision
    assert decision["message"] and decision["message"] != code, (
        "every refusal owes the user a sentence, not just a code")


def test_the_worker_re_checks_the_digest_against_the_bytes(store, monkeypatch):
    """The gate ran against a row; between then and the write the object can be replaced by a
    re-run of the document. Checking once would make the guarantee true of the row and merely
    likely of the bytes."""
    import remediation_delivery as delivery
    with pytest.raises(delivery.DeliveryRefused) as refused:
        delivery.load_artifact(owner=OWNER, scan_id=SID, file=DOC, expected_digest=DIGEST,
                               download=lambda *a: b"something-else")
    assert refused.value.code == "artifact_stale"

    with pytest.raises(delivery.DeliveryRefused) as missing:
        delivery.load_artifact(owner=OWNER, scan_id=SID, file=DOC, expected_digest=DIGEST,
                               download=lambda *a: None)
    assert missing.value.code == "artifact_missing"


def test_a_refused_delivery_closes_its_claim(store, monkeypatch):
    """A row left `in_flight` refuses every future retry of that artifact with `retry_in_flight`
    and nothing would ever clear it — the failure mode of a gate that only ever opens."""
    import core, handlers
    monkeypatch.setattr(core, "store", store)
    _seed(store)
    key = "z" * 64
    store.claim_delivery(SID, DOC, idempotency_key=key, destination_provider="sharepoint",
                         destination_key="sharepoint:drive/b!library/folder/Remediated",
                         artifact_digest=DIGEST, actor=OWNER)
    monkeypatch.setattr("blob.download_remediated", lambda owner, sid, f: b"stale-bytes")
    handlers._deliver_corrected_copy(
        {"scan_id": SID, "file": DOC, "owner": OWNER, "actor": OWNER, "idempotency_key": key,
         "artifact_digest": DIGEST, "destination": {"provider": "sharepoint"},
         "provider": "sharepoint"}, {"id": "job-y", "attempts": 1})
    row = store.list_deliveries(SID)[0]
    assert row["status"] == "refused" and row["error"] == "artifact_stale"


# ── ownership and permission ──────────────────────────────────────────────────

def test_another_users_run_is_not_retryable_and_does_not_confirm_it_exists(gated_client, store):
    _seed(store)
    stranger = gated_client(OTHER)
    for path in ("exceptions", "exceptions/retry-delivery", "exceptions/retry-documents",
                 "cancel", "pause", "resume"):
        method = stranger.get if path == "exceptions" else stranger.post
        assert method(f"/scans/{SID}/remediation/{path}").status_code == 404, path
    assert store.list_deliveries(SID) == []


def test_every_retry_and_control_route_requires_the_run_capability():
    """Enforcement is one middleware over one table (api/workspace_capability_map.py), so the
    thing to assert is the mapping — a route missing from it is unprotected and looks exactly
    like one deliberately left open."""
    import workspace_capability_map as capmap
    for path in ("/scans/{sid}/remediation/exceptions/retry-delivery",
                 "/scans/{sid}/remediation/exceptions/retry-documents",
                 "/scans/{sid}/remediation/cancel", "/scans/{sid}/remediation/pause",
                 "/scans/{sid}/remediation/resume"):
        assert capmap.ROUTE_CAPABILITIES[("POST", path)] == frozenset({"remediate.run"}), path
    assert capmap.ROUTE_CAPABILITIES[("GET", "/scans/{sid}/remediation/exceptions")] == \
        capmap.ROUTE_CAPABILITIES[("GET", "/scans/{sid}/remediation/snapshot")], (
        "the exception view carries strictly more than the snapshot it details, so it must not "
        "be readable where the snapshot is not")


def test_a_reviewer_capability_alone_does_not_grant_delivery():
    """Approving alt text and writing a document into a customer's SharePoint library are
    different rights, and PRD §5's grant model says a tab must not confer the second."""
    import workspace_capability_map as capmap
    caps = capmap.ROUTE_CAPABILITIES[
        ("POST", "/scans/{sid}/remediation/exceptions/retry-delivery")]
    assert "remediate.review" not in caps


# ── group actions ─────────────────────────────────────────────────────────────

def test_a_group_action_touches_only_the_documents_it_was_given(gated_client, store):
    _seed(store, files=("a.docx", "b.docx", "c.docx"))
    client = gated_client(OWNER)
    out = client.post(f"/scans/{SID}/remediation/exceptions/retry-delivery",
                      json={"files": ["a.docx"]}).json()
    assert out["requested"] == 1 and out["started"] == 1
    assert [row["file"] for row in store.list_deliveries(SID)] == ["a.docx"]


def test_an_empty_selection_acts_on_nothing(gated_client, store):
    """`[]` is "the user deselected everything", and reading it as "all" is the worst available
    interpretation of an empty selection."""
    _seed(store, files=("a.docx", "b.docx"))
    out = gated_client(OWNER).post(f"/scans/{SID}/remediation/exceptions/retry-delivery",
                                   json={"files": []}).json()
    assert out == {**out, "requested": 0, "started": 0, "summary": "Nothing to do"}
    assert store.list_deliveries(SID) == []


def test_a_name_the_run_does_not_contain_is_dropped_rather_than_fatal(gated_client, store):
    _seed(store, files=("a.docx",))
    out = gated_client(OWNER).post(f"/scans/{SID}/remediation/exceptions/retry-delivery",
                                   json={"files": ["a.docx", "ghost.docx"]}).json()
    assert out["requested"] == 1 and out["started"] == 1


def test_a_partial_group_failure_never_reports_total_success(store):
    """The reporting property, tested on the summariser itself so every caller inherits it."""
    import remediation_exceptions as exceptions
    out = exceptions.summarize_outcomes([
        {"file": "a", "outcome": "started"}, {"file": "b", "outcome": "started"},
        {"file": "c", "outcome": "refused", "code": "artifact_stale"},
        {"file": "d", "outcome": "failed", "code": "enqueue_failed"},
    ])
    assert out["complete_success"] is False
    assert out["started"] == 2 and out["refused"] == 1 and out["failed"] == 1
    assert "2 delivery operations started" in out["summary"]
    assert "1 refused" in out["summary"] and "1 could not be started" in out["summary"]
    assert [row["file"] for row in out["results"]] == ["a", "b", "c", "d"]


def test_a_mixed_group_reports_each_document(gated_client, store):
    _seed(store, files=("good.docx", "stale.docx"))
    # One document's source moved on after its correction was produced.
    with store._db.cursor() as cur:
        store._db.execute(cur, "UPDATE scan_inventory SET source_modified=%s "
                               "WHERE scan_id=%s AND file=%s",
                          ("2099-01-01T00:00:00Z", SID, "stale.docx"))
    out = gated_client(OWNER).post(f"/scans/{SID}/remediation/exceptions/retry-delivery",
                                   json={"files": ["good.docx", "stale.docx"]}).json()
    assert out["complete_success"] is False
    by_file = {row["file"]: row for row in out["results"]}
    assert by_file["good.docx"]["outcome"] == "started"
    assert by_file["stale.docx"]["outcome"] == "refused"
    assert by_file["stale.docx"]["code"] == "artifact_stale"
    assert "changed after this corrected copy was produced" in by_file["stale.docx"]["message"]


# ── audit ─────────────────────────────────────────────────────────────────────

def test_an_audited_action_names_actor_run_document_destination_and_outcome(gated_client, store):
    _seed(store)
    gated_client(OWNER).post(f"/scans/{SID}/remediation/exceptions/retry-delivery",
                             json={"files": [DOC]})
    rows = [d for d in store.list_decisions(scan_id=SID)
            if d["action"] == "remediate.delivery_retry_requested"]
    assert rows, "a delivery retry left no audit row"
    detail = rows[0]["detail"]
    assert rows[0]["actor"] == OWNER
    for expected in (SID, DOC, "retry_delivery", "requested", "sharepoint"):
        assert expected in detail, expected


def test_an_audit_payload_carries_no_credential_and_no_document_content():
    """A whitelist, for the reason store._issue_provenance is one: the destination dict is built
    elsewhere and free to grow, and a payload that copies what it is handed is how a signed URL
    reaches a log."""
    import remediation_exceptions as exceptions
    payload = exceptions.audit_payload(
        actor=OWNER, run_id=SID, file=DOC, action="retry_delivery", outcome="delivered",
        destination={"provider": "sharepoint", "key": "sharepoint:drive/b!x/folder/Remediated",
                     "signed_url": "https://x?sig=SECRET", "access_token": "SECRET",
                     "extracted_text": "the patient's name is ..."},
        idempotency_key="k" * 64)
    assert set(payload) <= set(exceptions._AUDIT_FIELDS)
    blob = repr(payload)
    for leaked in ("SECRET", "sig=", "patient"):
        assert leaked not in blob, leaked


def test_the_lifecycle_event_for_an_action_omits_the_actor_from_the_shared_log(gated_client,
                                                                              store):
    """The actor belongs in the audit row, which is owner-scoped by construction. The scan event
    is replayed to every authorised viewer of the run, and naming who pressed the button there
    would put one user's identity on another's screen for no operational gain."""
    _seed(store)
    gated_client(OWNER).post(f"/scans/{SID}/remediation/exceptions/retry-delivery",
                             json={"files": [DOC]})
    events = [e for e in store.list_scan_events(SID)
              if e["kind"] == "remediate.delivery_retry_requested"]
    assert events, "no lifecycle event for the retry"
    assert "actor" not in (events[0]["detail"] or {})
    assert (events[0]["detail"] or {}).get("file") == DOC
