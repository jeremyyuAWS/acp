from __future__ import annotations

from fastapi.testclient import TestClient


def _client(monkeypatch, isolated_store):
    import core
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    return TestClient(app)


def _ledger(store, sid="scan-drilldown"):
    with store._db.cursor() as cur:
        store._db.execute(cur,
            "INSERT INTO scan_runs(id,source,status,owner_email,workflow_id,workflow_revision) "
            "VALUES(%s,'sharepoint','done','demo',%s,1)", (sid, f"workflow-{sid}"))
        store._db.execute(cur,
            "INSERT INTO file_records(scan_id,file,drive_file_id,checksum) "
            "VALUES(%s,'policy.docx','item-1','sha-1')", (sid,))
        store._db.execute(cur,
            "INSERT INTO scan_rule_traces(scan_id,file,rule_id,rule_name,plain_name,level,"
            "fix_mode,outcome,finding_count) VALUES(%s,'policy.docx','1.1.1','Non-text',"
            "'Images need text','A','human','FAIL',2)", (sid,))
    execution = store.enqueue_stage_batch(
        sid, "remediate", "remediate_file", [{"scan_id": sid, "file": "policy.docx"}],
        snapshot_id=sid, request_fingerprint="drilldown")
    rows = store.seed_finding_dispositions(sid, execution["batch_id"], snapshot_id=sid)
    store.transition_finding_disposition(
        sid, execution["batch_id"], rows[0]["finding_id"], "resolved_verified",
        expected_revision=0, event_id="verified-1", fix_evidence_ids=["diff:1"],
        verified_at="2026-09-07T00:00:00Z")
    store.transition_finding_disposition(
        sid, execution["batch_id"], rows[1]["finding_id"], "awaiting_review",
        expected_revision=0, event_id="review-1", review_item_id="hitl-1")
    return sid, execution["batch_id"], rows


def test_drilldown_returns_only_the_requested_current_bucket(monkeypatch, isolated_store):
    sid, batch_id, rows = _ledger(isolated_store)
    response = _client(monkeypatch, isolated_store).get(
        f"/scans/{sid}/finding-dispositions?disposition=resolved_verified")
    assert response.status_code == 200
    body = response.json()
    assert body["batch_id"] == batch_id
    assert [item["finding_id"] for item in body["items"]] == [rows[0]["finding_id"]]
    assert body["items"][0]["fix_evidence_ids"] == ["diff:1"]


def test_drilldown_rejects_unknown_buckets(monkeypatch, isolated_store):
    sid, _batch_id, _rows = _ledger(isolated_store)
    response = _client(monkeypatch, isolated_store).get(
        f"/scans/{sid}/finding-dispositions?disposition=made_up")
    assert response.status_code == 400


def test_event_history_is_current_batch_and_finding_scoped(monkeypatch, isolated_store):
    sid, batch_id, rows = _ledger(isolated_store)
    response = _client(monkeypatch, isolated_store).get(
        f"/scans/{sid}/finding-dispositions/{rows[0]['finding_id']}/events")
    assert response.status_code == 200
    assert response.json() == {
        "scan_id": sid,
        "batch_id": batch_id,
        "finding_id": rows[0]["finding_id"],
        "events": [{
            "event_id": "verified-1", "from_disposition": None,
            "to_disposition": "resolved_verified", "from_revision": 0, "to_revision": 1,
            "review_item_id": None, "fix_evidence_ids": ["diff:1"],
            "verified_at": "2026-09-07T00:00:00Z",
            "created_at": response.json()["events"][0]["created_at"],
        }],
    }


def test_foreign_or_missing_scan_is_not_an_existence_oracle(monkeypatch, isolated_store):
    response = _client(monkeypatch, isolated_store).get(
        "/scans/not-owned/finding-dispositions")
    assert response.status_code == 404
    assert response.json()["detail"] == "scan not found"
