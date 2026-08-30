"""Durable job-queue tests (ADR 0004) — store methods + JobWorker.

Runs against a fresh SQLite database.
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
    tmp = Path(tempfile.mkdtemp()) / "jobs-test.db"
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", tmp)
    return store_mod.Store()


def test_enqueue_claim_complete(store):
    jid = store.enqueue_job("scan_file", {"file": "a.docx"}, scan_id="s1")
    assert store.get_job(jid)["status"] == "queued"

    job = store.claim_job("w1")
    assert job["id"] == jid
    assert job["status"] == "running"
    assert job["attempts"] == 1
    assert job["payload"] == {"file": "a.docx"}      # JSON round-trips to a dict

    # Queue is now empty — nothing else to claim.
    assert store.claim_job("w1") is None

    store.complete_job(jid)
    assert store.get_job(jid)["status"] == "done"


def test_priority_order(store):
    store.enqueue_job("t", {"n": 1}, priority=100)
    store.enqueue_job("t", {"n": 2}, priority=10)     # higher priority (lower number)
    first = store.claim_job("w1")
    assert first["payload"]["n"] == 2


def test_retry_then_dead_letter(store):
    jid = store.enqueue_job("t", {}, max_attempts=2)

    store.claim_job("w1")                              # attempt 1
    assert store.fail_job(jid, "boom", backoff_seconds=0) == "queued"
    assert store.get_job(jid)["status"] == "queued"
    assert store.get_job(jid)["last_error"] == "boom"

    store.claim_job("w1")                              # attempt 2 == max
    assert store.fail_job(jid, "boom again", backoff_seconds=0) == "dead"
    assert store.get_job(jid)["status"] == "dead"


def test_force_dead(store):
    jid = store.enqueue_job("t", {}, max_attempts=10)
    store.claim_job("w1")
    assert store.fail_job(jid, "fatal", force_dead=True) == "dead"
    assert store.get_job(jid)["status"] == "dead"


def test_backoff_gate_hides_job(store):
    jid = store.enqueue_job("t", {})
    store.claim_job("w1")
    store.fail_job(jid, "transient", backoff_seconds=3600)   # run_after in the future
    # Not eligible yet → claim returns nothing.
    assert store.claim_job("w1") is None


def test_reclaim_stuck(store):
    jid = store.enqueue_job("t", {})
    store.claim_job("w1")                              # now 'running'
    assert store.get_job(jid)["status"] == "running"
    # Lease 0 → the running job is immediately considered stuck.
    assert store.reclaim_stuck_jobs(lease_seconds=0) == 1
    assert store.get_job(jid)["status"] == "queued"


def test_job_stats(store):
    a = store.enqueue_job("t", {})
    store.enqueue_job("t", {})
    store.claim_job("w1")
    store.complete_job(a) if store.get_job(a)["status"] == "running" else None
    stats = store.job_stats()
    assert stats.get("queued", 0) + stats.get("done", 0) >= 1


def test_oldest_queued_job_is_none_on_an_empty_queue(store):
    assert store.oldest_queued_job() is None


def test_oldest_queued_job_returns_the_longest_waiting_one(store):
    first = store.enqueue_job("scan_discover", {})
    store.enqueue_job("scan_discover", {})            # a second, newer job
    oldest = store.oldest_queued_job()
    assert oldest["id"] == first


def test_oldest_queued_job_ignores_claimed_and_done_jobs(store):
    jid = store.enqueue_job("t", {})
    store.claim_job("w1")                              # now 'running', not 'queued'
    assert store.oldest_queued_job() is None
    store.complete_job(jid)
    assert store.oldest_queued_job() is None


def test_oldest_queued_job_ignores_a_job_still_in_backoff(store):
    """A job whose run_after hasn't arrived yet is not eligible for claim_job() either — it must
    not count as evidence the worker tier is stalled, the same run_after<=now() gate claim_job()
    itself uses."""
    jid = store.enqueue_job("t", {})
    store.claim_job("w1")
    store.fail_job(jid, "transient", backoff_seconds=3600)   # run_after far in the future
    assert store.oldest_queued_job() is None


def test_oldest_queued_job_can_be_scoped_to_an_owner(store):
    st = store
    st.save_scan({"_scan_id": "mine", "started_at": "2026-08-29T00:00:00+00:00",
                  "completed_at": "2026-08-29T00:01:00+00:00", "source": "drive",
                  "owner": "me@example.com", "rubric": {"name": "r", "hash": "h"},
                  "summary": {"files": 0, "certifiable": 0, "uncertain": 0, "error": 0, "avg_score": 0},
                  "files": []})
    st.save_scan({"_scan_id": "theirs", "started_at": "2026-08-29T00:00:00+00:00",
                  "completed_at": "2026-08-29T00:01:00+00:00", "source": "drive",
                  "owner": "someone-else@example.com", "rubric": {"name": "r", "hash": "h"},
                  "summary": {"files": 0, "certifiable": 0, "uncertain": 0, "error": 0, "avg_score": 0},
                  "files": []})
    st.enqueue_job("scan_discover", {}, scan_id="theirs")
    mine = st.enqueue_job("scan_discover", {}, scan_id="mine")

    # Global (owner=None, the shape GET /jobs actually calls) sees whichever queued first —
    # scoping is opt-in via the owner argument, not the route's default.
    assert st.oldest_queued_job(owner="me@example.com")["id"] == mine


def test_worker_runs_handler(store):
    import worker
    seen = []

    @worker.handler("greet")
    def _greet(payload, job):
        seen.append(payload["name"])

    jid = store.enqueue_job("greet", {"name": "ada"})
    w = worker.JobWorker(store, worker_id="w-test")
    assert w.run_once() is True                        # handled one
    assert seen == ["ada"]
    assert store.get_job(jid)["status"] == "done"
    assert w.run_once() is False                       # queue empty


def test_worker_retries_then_dead(store):
    import worker

    @worker.handler("always_fail")
    def _boom(payload, job):
        raise ValueError("nope")

    jid = store.enqueue_job("always_fail", {}, max_attempts=3)
    w = worker.JobWorker(store, worker_id="w-test")
    for _ in range(3):
        w.run_once()
        # Clear the backoff gate so the requeued job is eligible on the next claim.
        if store.get_job(jid)["status"] == "queued":
            with store._db.cursor() as cur:
                store._db.execute(cur, "UPDATE jobs SET run_after=%s WHERE id=%s",
                                  (store._now(), jid))
    assert store.get_job(jid)["status"] == "dead"


def test_worker_on_retry_fires_when_a_transient_failure_is_requeued(store):
    """The live progress signal for PRD Discover-card §16.8 (Retrying): a caller-supplied
    on_retry hook lets core.py announce "failed, waiting to retry" on the job's live poll/SSE
    state without worker.py importing core (see JobWorker's own docstring on why — it is
    deliberately infrastructure-only)."""
    import worker

    @worker.handler("flaky")
    def _flaky(payload, job):
        raise ValueError("transient boom")

    jid = store.enqueue_job("flaky", {}, max_attempts=5)
    calls = []
    w = worker.JobWorker(store, worker_id="w-test", on_retry=lambda jid_, patch: calls.append((jid_, patch)))
    assert w.run_once() is True
    assert store.get_job(jid)["status"] == "queued"           # requeued, not dead-lettered
    assert len(calls) == 1
    seen_jid, patch = calls[0]
    assert seen_jid == jid
    assert patch["phase"] == "retrying"
    assert patch["attempt"] == 1
    assert patch["max_attempts"] == 5
    assert "transient boom" in patch["last_error"]


def test_worker_on_retry_does_not_fire_on_dead_letter(store):
    """A job that exhausts its attempts (or fails fatally) is DONE, not retrying — firing
    on_retry here would tell the frontend a dead job is about to come back."""
    import worker

    @worker.handler("always_fail_retry_check")
    def _boom(payload, job):
        raise ValueError("nope")

    jid = store.enqueue_job("always_fail_retry_check", {}, max_attempts=1)
    calls = []
    w = worker.JobWorker(store, worker_id="w-test", on_retry=lambda jid_, patch: calls.append((jid_, patch)))
    w.run_once()
    assert store.get_job(jid)["status"] == "dead"
    assert calls == []


def test_worker_on_retry_does_not_fire_for_a_fatal_error(store):
    """FatalJobError always force-dead-letters immediately (no requeue) — same guard as above,
    covering the other dead-letter path (worker.py's separate except FatalJobError branch)."""
    import worker
    from worker import FatalJobError

    @worker.handler("fatal_kind")
    def _fatal(payload, job):
        raise FatalJobError("unrecoverable")

    jid = store.enqueue_job("fatal_kind", {}, max_attempts=5)
    calls = []
    w = worker.JobWorker(store, worker_id="w-test", on_retry=lambda jid_, patch: calls.append((jid_, patch)))
    w.run_once()
    assert store.get_job(jid)["status"] == "dead"
    assert calls == []


def test_worker_on_retry_does_not_fire_when_a_zombie_lost_the_completion_race(store):
    """The exact race test_job_completion_race.py documents: fail_job() returns "queued" even
    when a zombie worker's requeue write was suppressed because a second worker already
    completed the same job_id. on_retry must re-read the row's REAL status rather than trust
    that return value, or a finished job could flash "retrying" right after it finished.

    The handler itself performs the "concurrent" second-worker reclaim + completion before
    raising, so this exercises run_once()'s actual except-branch — not a re-implementation of
    its guard logic — for the same interleaving reclaim_stuck_jobs() makes possible: a second
    worker finishes the job while the first (zombie) worker's handler is still on the stack."""
    import worker

    @worker.handler("zombie_flavor")
    def _boom(payload, job):
        store.reclaim_stuck_jobs(lease_seconds=0)     # this job's lease "expires" immediately
        reclaimed = store.claim_job("w2")              # a second worker reclaims the SAME job
        assert reclaimed["id"] == job["id"]
        assert store.complete_job(job["id"]) is True   # ...and finishes it successfully
        raise ValueError("zombie's late failure")       # only now does the zombie's own call fail

    jid = store.enqueue_job("zombie_flavor", {}, max_attempts=5)
    calls = []
    w = worker.JobWorker(store, worker_id="w1",
                         on_retry=lambda jid_, patch: calls.append((jid_, patch)))
    assert w.run_once() is True
    assert store.get_job(jid)["status"] == "done"      # worker B's completion, untouched
    assert calls == []                                  # the zombie's late failure announced nothing


def test_worker_no_handler_dead_letters_eventually(store):
    import worker
    jid = store.enqueue_job("unknown_type", {}, max_attempts=1)
    w = worker.JobWorker(store, worker_id="w-test")
    w.run_once()
    assert store.get_job(jid)["status"] == "dead"


def test_scan_handler_runs_persists_finalizes(store, monkeypatch):
    """The async `scan` job in IMMEDIATE mode: run_scan → save_scan → finalize, token cleared.
    run_scan is stubbed so the test needs no engines. Metadata-only discovery is the default now
    (ADR 0020), so this pins the legacy immediate-analysis path with the documented override —
    the deferred (metadata-only) behaviour is covered in test_deferred_assess."""
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "0")
    import core, scanner, handlers  # noqa: F401 — registers the 'scan' handler
    import worker

    monkeypatch.setattr(core, "store", store)  # handler + finalize use core.store

    captured = {}

    def fake_run_scan(source, *, drive_token=None, sp_token=None, folder=None,
                      ai_enabled=True, scan_id=None, user=None, detect_pii=True,
                      exclude_remediated=False, inventory_out=None):
        captured["scan_id"] = scan_id
        captured["drive_token"] = drive_token
        captured["ai_enabled"] = ai_enabled
        captured["user"] = user
        return {"_scan_id": scan_id, "summary": {"files": 1, "certifiable": 1,
                "uncertain": 0, "error": 0, "avg_score": 100},
                "rubric": {"name": "r", "version": "1", "hash": "h"},
                "started_at": "t0", "completed_at": "t1", "source": source, "files": []}

    monkeypatch.setattr(handlers, "run_scan", fake_run_scan)
    monkeypatch.setattr(store, "get_ai_enabled", lambda: True)

    sid = "scan-async-1"
    core.register_scan_tokens(sid, drive="user-token-xyz")
    jid = store.enqueue_job("scan", {"source": "drive", "scan_id": sid, "ai": True}, scan_id=sid)

    w = worker.JobWorker(store, worker_id="w-test")
    assert w.run_once() is True
    assert store.get_job(jid)["status"] == "done"

    # The handler received the in-memory token (never from the job payload) ...
    assert captured["drive_token"] == "user-token-xyz"
    assert captured["scan_id"] == sid
    # ... persisted the scan ...
    assert store.get_scan(sid) is not None
    # ... and cleared the token afterwards.
    assert core.get_scan_tokens(sid) == {}


def test_remediate_file_handler(store, monkeypatch):
    """remediate_file: fetch → remediate_html → write back → record + audit.
    The Drive client is stubbed; remediation is real (lxml)."""
    import core, handlers  # noqa: F401 — registers the handler
    import worker

    monkeypatch.setattr(core, "store", store)
    monkeypatch.setattr(store, "get_ai_enabled", lambda: True)

    written = {}

    class _FakeFiles:
        def get_media(self, fileId):
            class _Exec:
                def execute(_self):
                    return b"<html><head></head><body><h1>Doc</h1></body></html>"
            return _Exec()

        def list(self, **k):
            q = k.get("q", "")
            # Folder search → the Remediated folder; file-existence search → none
            # (so the upsert writes a fresh copy via create()).
            files = [{"id": "remediated-folder"}] if "Remediated" in q else []
            class _Exec:
                def execute(_self):
                    return {"files": files}
            return _Exec()

        def create(self, body=None, media_body=None, fields=None):
            class _Exec:
                def execute(_self):
                    written["body"] = body
                    written["uploaded"] = media_body is not None
                    return {"id": "new-file", "webViewLink": "https://drive/remediated/x"}
            return _Exec()

        def update(self, fileId=None, media_body=None, fields=None):
            class _Exec:
                def execute(_self):
                    written["updated"] = fileId
                    written["uploaded"] = media_body is not None
                    return {"id": fileId, "webViewLink": "https://drive/remediated/x"}
            return _Exec()

    class _FakeSvc:
        def files(self):
            return _FakeFiles()

    monkeypatch.setattr(handlers, "_drive_client", lambda token: _FakeSvc())

    sid = "scan-rem-1"
    core.register_scan_tokens(sid, drive="tok")
    jid = store.enqueue_job("remediate_file",
                            {"scan_id": sid, "file": "page.html", "drive_file_id": "orig-id"},
                            scan_id=sid)
    # the scan must exist for record_remediation's UPDATE to target a row
    with store._db.cursor() as cur:
        store._db.execute(cur, "INSERT INTO scan_runs(id,completed_at) VALUES(%s,%s)", (sid, "t"))
        store._db.execute(cur,
            "INSERT INTO file_records(scan_id,file,engine,status,score,compliant,skipped_rules,drive_file_id) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)", (sid, "page.html", "python/html", "issues", 70, 0, 0, "orig-id"))

    w = worker.JobWorker(store, worker_id="w-test")
    assert w.run_once() is True
    assert store.get_job(jid)["status"] == "done"
    assert written["uploaded"] is True
    assert written["body"]["name"] == "page.html"
    # the remediated file was recorded with the Drive write-back url
    decisions = store.list_decisions(scan_id=sid)
    assert any(d["action"] == "remediate.applied" for d in decisions)


def test_remediate_file_non_html_deferred(store, monkeypatch):
    import core, handlers  # noqa: F401
    import worker
    monkeypatch.setattr(core, "store", store)
    sid = "scan-rem-2"
    # HTML, PDF, and Office (docx/pptx/xlsx) are all remediated server-side now
    # (ADR 0005). An unsupported type (e.g. .rtf) still defers to human review.
    jid = store.enqueue_job("remediate_file",
                            {"scan_id": sid, "file": "report.rtf", "drive_file_id": "p"},
                            scan_id=sid)
    w = worker.JobWorker(store, worker_id="w-test")
    assert w.run_once() is True
    assert store.get_job(jid)["status"] == "done"   # completes, but defers
    assert any(d["action"] == "remediate.deferred"
               for d in store.list_decisions(scan_id=sid))


# ── dead_letter_breakdown: incident-shaped aggregation ───────────────────────────────

def _dead_job(store, *, scan_id, error, jtype="scan_file", attempts=1,
              created_at="2026-08-30T00:00:00+00:00", updated_at="2026-08-30T00:00:00+00:00",
              max_attempts=5):
    """Seed a single dead-lettered job row with fully-controlled attempts/timestamps.

    Goes straight to a 'dead' row via direct UPDATE rather than driving fail_job through
    real retries — the timing tests need created_at/updated_at values the store's own
    _now() can't produce deterministically, and the aggregation tests need attempts values
    independent of how many times this particular row actually failed."""
    jid = store.enqueue_job(jtype, {}, scan_id=scan_id, max_attempts=max_attempts)
    with store._db.cursor() as cur:
        store._db.execute(cur,
            "UPDATE jobs SET status='dead', last_error=%s, attempts=%s, "
            "created_at=%s, updated_at=%s WHERE id=%s",
            (error, attempts, created_at, updated_at, jid))
    return jid


def test_dead_letter_breakdown_shape_is_additive(store):
    """type/error/n keep their existing meaning and are joined by the new fields —
    other readers of top_errors[0].error (e.g. QueuePanel's deadReason) must not break."""
    _dead_job(store, scan_id="s1", error="boom", attempts=2)
    out = store.dead_letter_breakdown()
    row = out["top_errors"][0]
    assert row["type"] == "scan_file"
    assert row["error"] == "boom"
    assert row["n"] == 1
    assert set(row) == {"type", "error", "n", "affected_runs", "total_attempts",
                        "first_seen", "last_seen"}


def test_affected_runs_counts_distinct_scans_not_job_rows(store):
    """A scan whose per-file jobs dead-letter under the SAME reason contributes ONE to
    affected_runs but MANY to n — e.g. a scan's fan-out into several scan_file jobs where
    three files all hit the same drive error (grouping is by type+error, so this stays
    within a single group only when the type is held constant). A second scan hitting the
    same reason adds one more run."""
    _dead_job(store, scan_id="scan-a", error="drive quota exceeded", jtype="scan_file")
    _dead_job(store, scan_id="scan-a", error="drive quota exceeded", jtype="scan_file")
    _dead_job(store, scan_id="scan-a", error="drive quota exceeded", jtype="scan_file")
    _dead_job(store, scan_id="scan-b", error="drive quota exceeded", jtype="scan_file")

    out = store.dead_letter_breakdown()
    row = next(r for r in out["top_errors"] if r["error"] == "drive quota exceeded")
    assert row["n"] == 4                 # four dead job rows
    assert row["affected_runs"] == 2     # but only two distinct scans


def test_total_attempts_sums_across_the_group(store):
    """total_attempts is the SUM of each job's own attempts (claim_job increments the same
    row on every retry — see fail_job/claim_job), not just a per-job or per-row count."""
    _dead_job(store, scan_id="s1", error="timeout", attempts=1)
    _dead_job(store, scan_id="s2", error="timeout", attempts=5)
    _dead_job(store, scan_id="s3", error="timeout", attempts=3)

    out = store.dead_letter_breakdown()
    row = next(r for r in out["top_errors"] if r["error"] == "timeout")
    assert row["n"] == 3
    assert row["total_attempts"] == 9


def test_first_seen_and_last_seen_are_the_true_min_and_max(store):
    """first_seen/last_seen must reflect the earliest created_at and latest updated_at
    across the WHOLE group, not whichever row SQLite happens to return first or last —
    seed them out of both creation order and alphabetical order to catch that."""
    _dead_job(store, scan_id="s1", error="flaky", jtype="scan_file",
              created_at="2026-08-30T09:00:00+00:00", updated_at="2026-08-30T09:05:00+00:00")
    _dead_job(store, scan_id="s2", error="flaky", jtype="scan_file",
              created_at="2026-08-30T06:00:00+00:00",   # earliest created_at
              updated_at="2026-08-30T09:50:00+00:00")   # latest updated_at
    _dead_job(store, scan_id="s3", error="flaky", jtype="scan_file",
              created_at="2026-08-30T08:00:00+00:00", updated_at="2026-08-30T07:00:00+00:00")

    out = store.dead_letter_breakdown()
    row = next(r for r in out["top_errors"] if r["error"] == "flaky")
    assert row["first_seen"] == "2026-08-30T06:00:00+00:00"
    assert row["last_seen"] == "2026-08-30T09:50:00+00:00"


def test_owner_scoping_excludes_another_tenants_incident_fields(store):
    """purge/breakdown scoping (owner=) must exclude another tenant's dead jobs from EVERY
    new field, not just n — error text can name a file, and affected_runs/total_attempts/
    first_seen/last_seen are all derived from the same potentially-leaking rows."""
    st = store
    st.save_scan({"_scan_id": "mine", "started_at": "2026-08-29T00:00:00+00:00",
                  "completed_at": "2026-08-29T00:01:00+00:00", "source": "drive",
                  "owner": "me@example.com", "rubric": {"name": "r", "hash": "h"},
                  "summary": {"files": 0, "certifiable": 0, "uncertain": 0, "error": 0, "avg_score": 0},
                  "files": []})
    st.save_scan({"_scan_id": "theirs", "started_at": "2026-08-29T00:00:00+00:00",
                  "completed_at": "2026-08-29T00:01:00+00:00", "source": "drive",
                  "owner": "someone-else@example.com", "rubric": {"name": "r", "hash": "h"},
                  "summary": {"files": 0, "certifiable": 0, "uncertain": 0, "error": 0, "avg_score": 0},
                  "files": []})
    # Same error text on both tenants' scans so the two groups would MERGE into one row
    # if the owner scope were missing from the new aggregates.
    _dead_job(st, scan_id="mine", error="shared reason", attempts=2,
              created_at="2026-08-30T01:00:00+00:00", updated_at="2026-08-30T01:00:00+00:00")
    _dead_job(st, scan_id="theirs", error="shared reason", attempts=9,
              created_at="2026-08-30T02:00:00+00:00", updated_at="2026-08-30T23:00:00+00:00")
    _dead_job(st, scan_id="theirs", error="shared reason", attempts=9,
              created_at="2026-08-30T02:00:00+00:00", updated_at="2026-08-30T23:00:00+00:00")

    mine_only = st.dead_letter_breakdown(owner="me@example.com")
    row = next(r for r in mine_only["top_errors"] if r["error"] == "shared reason")
    assert row["n"] == 1
    assert row["affected_runs"] == 1
    assert row["total_attempts"] == 2                       # not 2 + 9 + 9
    assert row["first_seen"] == "2026-08-30T01:00:00+00:00"  # not "theirs" earlier/later stamps
    assert row["last_seen"] == "2026-08-30T01:00:00+00:00"

    # Unscoped (owner=None — the shape GET /jobs actually calls when unset) sees both
    # tenants combined, which is what proves the scoped result above was really filtering
    # and not just coincidentally matching.
    everyone = st.dead_letter_breakdown()
    row_all = next(r for r in everyone["top_errors"] if r["error"] == "shared reason")
    assert row_all["n"] == 3
    assert row_all["affected_runs"] == 2
    assert row_all["total_attempts"] == 20
