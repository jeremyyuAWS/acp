"""A failed stage execution must be re-runnable; a finished one must not be re-run.

WHAT THIS FIXES. `enqueue_stage_batch` derives `batch_id` from
(scan_id, stage, snapshot_id, request_fingerprint), so re-submitting the same scan and scope lands
on the same id by construction — that is the point, and it is what stops an identical resubmission
creating a second batch. But the lookup that decided "this execution already exists" matched rows
of ANY status. A batch whose jobs had all died was therefore handed straight back with
`reused: True` and nothing queued, while the route answered `enqueued: <len(job_ids)>` — a retry
that reports success and does nothing.

That is the 2026-09-04 SharePoint incident's own shape: 147 jobs dead, an operator doing the
obvious thing, and no way to tell a re-run that worked from one that never happened. Demonstrated
against the method before the change: two dead jobs, resubmitted → `reused: True`,
`statuses: ['dead', 'dead']`, zero queued rows.

The two design points these pin, because neither follows from "exclude terminal statuses":

  * `done` stays reusable. It is terminal too, and re-running finished work would undo the
    idempotency the snapshot execution exists to provide.
  * Failed rows are RE-QUEUED IN PLACE, not skipped so new rows insert beside them. The batch_id
    is deterministic, so an insert would leave two generations under one id — and
    `remediation_status` scopes its counts to exactly that id, so a 147-document retry would
    report 294 documents. That is the number this whole thread began with.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

SID = "8b83e9e1ca5c"
SNAP = "snapshot-1"
FILES = ("policy.docx", "handbook.docx")


@pytest.fixture()
def store(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "stage-retry.db")
    return store_mod.Store()


def _payloads(token="tok-1"):
    return [{"scan_id": SID, "file": f, "source": "sharepoint", "drive_token": token}
            for f in FILES]


def _submit(store, *, token="tok-1", snapshot=SNAP, files=FILES):
    payloads = [p for p in _payloads(token) if p["file"] in files]
    fingerprint = '{"files": %s}' % sorted(files)
    return store.enqueue_stage_batch(SID, "remediate", "remediate_file", payloads,
                                     snapshot_id=snapshot, request_fingerprint=fingerprint)


def _set_status(store, job_ids, status):
    with store._db.cursor() as cur:
        for jid in job_ids:
            store._db.execute(cur, "UPDATE jobs SET status=%s WHERE id=%s", (status, jid))


def _rows(store):
    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT id,status,batch_id FROM jobs WHERE scan_id=%s", (SID,))
        return store._db.fetchall(cur)


def test_a_dead_execution_is_re_queued_rather_than_handed_back(store):
    first = _submit(store)
    _set_status(store, first["job_ids"], "dead")

    second = _submit(store)

    assert second["batch_id"] == first["batch_id"], "the same work keeps the same execution id"
    assert second["reused"] is False, (
        "a retry that revived dead work queued something — reporting it as a reuse is the lie "
        "that made the incident's re-submission invisible")
    assert second["requeued"] == len(FILES)
    assert second["statuses"] == ["queued"] * len(FILES)
    assert sorted(r["status"] for r in _rows(store)) == ["queued", "queued"]


def test_the_retry_does_not_double_the_batch(store):
    """One row per document, before and after. The count this protects is the one that started
    all of this: remediation_status scopes to batch_id, so a second generation under the same id
    would report 2N documents for an N-document batch."""
    first = _submit(store)
    _set_status(store, first["job_ids"], "dead")

    second = _submit(store)

    rows = _rows(store)
    assert len(rows) == len(FILES), f"the retry duplicated the batch: {rows}"
    assert set(second["job_ids"]) == {r["id"] for r in rows}
    status = store.remediation_status(SID)
    assert status["batch_documents"] == len(FILES)
    assert status["failed"] == 0, "the dead rows were revived, so nothing is failed any more"


def test_a_finished_execution_is_still_reused(store):
    """The idempotency the snapshot execution exists for. `done` is terminal too, and excluding
    every terminal status from the lookup would have re-run completed work."""
    first = _submit(store)
    _set_status(store, first["job_ids"], "done")

    second = _submit(store)

    assert second["reused"] is True
    assert second["requeued"] == 0
    assert second["statuses"] == ["done"] * len(FILES)
    assert sorted(r["status"] for r in _rows(store)) == ["done", "done"]


def test_in_flight_work_is_never_disturbed(store):
    first = _submit(store)
    _set_status(store, first["job_ids"], "running")

    second = _submit(store)

    assert second["reused"] is True and second["requeued"] == 0
    assert sorted(r["status"] for r in _rows(store)) == ["running", "running"]


def test_a_mixed_execution_revives_only_what_failed(store):
    first = _submit(store)
    _set_status(store, first["job_ids"][:1], "done")
    _set_status(store, first["job_ids"][1:], "dead")

    second = _submit(store)

    assert second["reused"] is False and second["requeued"] == 1
    assert sorted(second["statuses"]) == ["done", "queued"]
    assert sorted(r["status"] for r in _rows(store)) == ["done", "queued"]


def test_a_cancelled_execution_does_not_re_cancel_itself(store):
    """cancel_requested_at has to be cleared with the status, or the revived job is stopped again
    at the worker's first checkpoint and the retry reads as another silent failure."""
    first = _submit(store)
    with store._db.cursor() as cur:
        for jid in first["job_ids"]:
            store._db.execute(cur,
                "UPDATE jobs SET status='cancelled',cancel_requested_at=%s WHERE id=%s",
                ("2026-09-05T00:00:00Z", jid))

    second = _submit(store)

    assert second["reused"] is False
    with store._db.cursor() as cur:
        store._db.execute(cur,
            "SELECT cancel_requested_at FROM jobs WHERE scan_id=%s", (SID,))
        assert [r["cancel_requested_at"] for r in store._db.fetchall(cur)] == [None, None]


def test_the_revived_job_carries_the_CURRENT_payload(store):
    """A retry exists to carry what changed since the failure. The incident's jobs died for want
    of a Drive token; reviving them with the stale payload would fail them the same way."""
    first = _submit(store, token="expired-token")
    _set_status(store, first["job_ids"], "dead")

    second = _submit(store, token="fresh-token")

    payloads = [store.get_job(j)["payload"] for j in second["job_ids"]]
    assert {p["drive_token"] for p in payloads} == {"fresh-token"}
    assert {p["snapshot_id"] for p in payloads} == {SNAP}
    assert {p["stage_execution_id"] for p in payloads} == {second["batch_id"]}


def test_a_dead_execution_under_a_new_snapshot_is_a_new_execution(store):
    """Unchanged by this: a different snapshot is different work and gets its own id. Pinned so
    the re-queue path cannot be mistaken for the only way a failed batch re-runs."""
    first = _submit(store)
    _set_status(store, first["job_ids"], "dead")

    second = _submit(store, snapshot="snapshot-2")

    assert second["batch_id"] != first["batch_id"]
    assert second["reused"] is False and second.get("requeued", 0) == 0
    assert len(_rows(store)) == 2 * len(FILES)


def test_the_route_says_whether_a_retry_actually_queued_anything(monkeypatch, isolated_store):
    """`enqueued` counts the execution's documents whether or not this call queued them, so it
    cannot answer the only question a re-submitting operator has. `requeued` can."""
    import core
    monkeypatch.setattr(core, "store", isolated_store)
    from fastapi.testclient import TestClient
    from app import app
    client = TestClient(app)

    isolated_store.save_scan({
        "_scan_id": SID, "started_at": "2026-09-04T00:00:00Z",
        "completed_at": "2026-09-04T00:01:00Z", "source": "sharepoint", "owner": "demo",
        "rubric": {"name": "wcag-aa", "hash": "h"},
        "summary": {"files": 1, "certifiable": 0, "uncertain": 1, "error": 0, "avg_score": 50},
        "files": [{"file": "policy.docx", "engine": "office", "status": "uncertain", "score": 50,
                   "compliant": 0, "skipped_rules": 0,
                   "issues": [{"ruleId": "DOC_TITLE", "wcag": "2.4.2", "severity": "SERIOUS"}]}],
    })

    first = client.post(f"/scans/{SID}/remediate", json={}).json()
    assert first["reused"] is False and first["requeued"] == 0

    _set_status(isolated_store, first["job_ids"], "dead")
    retry = client.post(f"/scans/{SID}/remediate", json={}).json()
    assert retry["requeued"] == 1, "a retry that revived a dead document must say so"
    assert retry["reused"] is False

    done = client.post(f"/scans/{SID}/remediate", json={}).json()
    assert done["reused"] is True and done["requeued"] == 0, (
        "and one that matched live work must not claim to have queued any")
