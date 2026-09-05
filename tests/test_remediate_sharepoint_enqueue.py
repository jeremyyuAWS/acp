"""What a SharePoint remediation batch is allowed to carry, and what it must not.

The 2026-09-04 outage (scan 8b83e9e1ca5c) was a worker-side routing bug — a SharePoint job read
its bytes through the Drive client — but the enqueue side made the same assumption from the other
end: it registered and attached a Drive token to every job whatever the scan's source. A job that
carries a Drive token is a job something can be tempted to spend one on.

So: a SharePoint submission carries no Drive token, and every submission carries a batch id, which
is what stops a re-run's failures from being counted against the run in front of the user (see
test_remediation_status_batch.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture
def client(monkeypatch, isolated_store):
    import core
    monkeypatch.setattr(core, "store", isolated_store)
    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app)


def _save(store, sid, source, files=("a.docx", "b.pptx"), drive_ids=False):
    store.save_scan({
        "_scan_id": sid, "started_at": "2026-09-04T00:00:00Z",
        "completed_at": "2026-09-04T00:01:00Z", "source": source, "owner": "demo",
        "rubric": {"name": "wcag-aa", "hash": "h"},
        "summary": {"files": len(files), "certifiable": 0, "uncertain": len(files),
                    "error": 0, "avg_score": 50},
        "files": [{"file": f, "engine": "office", "status": "uncertain", "score": 50,
                   "compliant": 0, "skipped_rules": 0,
                   "drive_file_id": f"drive-{f}" if drive_ids else None,
                   "issues": [{"ruleId": "DOC_TITLE", "wcag": "2.4.2", "severity": "SERIOUS"}]}
                  for f in files],
    })


def test_a_sharepoint_batch_carries_no_drive_token(client, isolated_store):
    _save(isolated_store, "sp-1", "sharepoint")

    r = client.post("/scans/sp-1/remediate", json={},
                    headers={"x-drive-token": "a-drive-token-for-a-different-provider"})
    assert r.status_code == 200 and r.json()["enqueued"] == 2

    for jid in r.json()["job_ids"]:
        payload = isolated_store.get_job(jid)["payload"]
        assert payload["source"] == "sharepoint"
        assert not payload.get("drive_token"), (
            "a SharePoint job must not carry a Drive token — the worker has no use for one and "
            "the missing-token failure is what took the 147-document batch down")


def test_equivalent_submission_reuses_the_snapshot_execution(client, isolated_store):
    _save(isolated_store, "sp-2", "sharepoint")

    first = client.post("/scans/sp-2/remediate", json={}).json()
    second = client.post("/scans/sp-2/remediate", json={}).json()

    assert first["batch_id"] and second["batch_id"] == first["batch_id"]
    assert first["snapshot_id"] == second["snapshot_id"]
    assert first["reused"] is False and second["reused"] is True
    assert set(first["job_ids"]) == set(second["job_ids"])
    assert {isolated_store.get_job(j)["payload"]["snapshot_id"]
            for j in second["job_ids"]} == {second["snapshot_id"]}

    status = isolated_store.remediation_status("sp-2")
    assert status["batch_id"] == second["batch_id"]
    assert status["queued"] == status["batch_documents"] == len(second["job_ids"])


def test_completed_submission_is_reused_for_the_same_snapshot(client, isolated_store):
    _save(isolated_store, "sp-complete", "sharepoint")
    first = client.post("/scans/sp-complete/remediate", json={}).json()
    with isolated_store._db.cursor() as cur:
        for jid in first["job_ids"]:
            isolated_store._db.execute(cur, "UPDATE jobs SET status='done' WHERE id=%s", (jid,))
    second = client.post("/scans/sp-complete/remediate", json={}).json()
    assert second["reused"] is True
    assert set(second["job_ids"]) == set(first["job_ids"])


def test_a_different_exact_scope_creates_a_distinct_execution(client, isolated_store):
    _save(isolated_store, "sp-scope", "sharepoint")
    first = client.post("/scans/sp-scope/remediate", json={"scope": ["a.docx"]}).json()
    second = client.post("/scans/sp-scope/remediate", json={"scope": ["b.pptx"]}).json()
    assert second["reused"] is False
    assert second["batch_id"] != first["batch_id"]


def test_a_drive_batch_still_carries_its_token(client, isolated_store):
    """The narrowing must not cost Drive anything: its worker still downloads, and still needs
    the durable payload token that survives a replica restart."""
    _save(isolated_store, "dr-1", "drive", drive_ids=True)

    r = client.post("/scans/dr-1/remediate", json={}, headers={"x-drive-token": "tok"})
    assert r.status_code == 200
    payloads = [isolated_store.get_job(j)["payload"] for j in r.json()["job_ids"]]
    assert payloads and all(p["drive_token"] == "tok" for p in payloads)
