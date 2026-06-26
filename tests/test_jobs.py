"""Durable job-queue tests (ADR 0004) — store methods + JobWorker.

Runs against a fresh SQLite database. The schema's Postgres-only
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migration statements are filtered out
for SQLite (their columns already exist in the CREATE TABLE for a fresh DB).
"""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


@pytest.fixture()
def store():
    import store as store_mod
    tmp = Path(tempfile.mkdtemp()) / "jobs-test.db"
    store_mod._SQLITE_PATH = tmp
    store_mod._SCHEMA[:] = [s for s in store_mod._SCHEMA
                            if not s.strip().upper().startswith("ALTER TABLE")]
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


def test_worker_no_handler_dead_letters_eventually(store):
    import worker
    jid = store.enqueue_job("unknown_type", {}, max_attempts=1)
    w = worker.JobWorker(store, worker_id="w-test")
    w.run_once()
    assert store.get_job(jid)["status"] == "dead"


def test_scan_handler_runs_persists_finalizes(store, monkeypatch):
    """The async `scan` job: run_scan → save_scan → finalize, with the token cleared.
    run_scan is stubbed so the test needs no engines."""
    import core, scanner, handlers  # noqa: F401 — registers the 'scan' handler
    import worker

    core.store = store  # handler + finalize use core.store

    captured = {}

    def fake_run_scan(source, *, drive_token=None, sp_token=None, folder=None,
                      ai_enabled=True, scan_id=None, user=None, detect_pii=True):
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

    core.store = store
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
    core.store = store
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
