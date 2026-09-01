import json


def test_immutable_evidence_summary_and_file_detail(isolated_store, monkeypatch):
    import core
    import handlers

    st = isolated_store
    monkeypatch.setattr(core, "store", st)
    with st._db.cursor() as cur:
        st._db.execute(cur, "INSERT INTO scan_runs(id,owner_email,status,source) VALUES(%s,%s,%s,%s)",
                       ("scan-1", "owner@x.com", "discovered", "drive"))
    st.add_inventory("scan-1", [
        {"file": "old.docx", "path": "/Archive/old.docx", "doc_class": "text-document",
         "source_modified": "2019-01-01T00:00:00+00:00", "owner": "owner@x.com"},
        {"file": "missing.docx", "path": "/Archive/missing.docx", "doc_class": "text-document",
         "source_modified": None, "owner": "owner@x.com"},
    ])
    st.create_disposition_policy(
        "retention", name="Retention", match=json.dumps([
            {"field": "modified_at", "op": "before", "value": "2020-01-01T00:00:00+00:00"}
        ]), action="archive", action_config="{}", requires_approval=True, enabled=True,
        owner_email="owner@x.com")

    result = handlers._evaluate_discover_lifecycle_rules("scan-1", "drive", "owner@x.com")
    assert result["lifecycle_archive"] == 1
    assert st.get_lifecycle_status("scan-1", "missing.docx")["lifecycle_status"] == "Unevaluable"

    summary = st.lifecycle_summary("scan-1", "owner@x.com")
    assert summary["total"] == summary["reconciled_total"] == 2
    assert summary["counts"]["archive_candidate"] == 1
    assert summary["counts"]["unevaluable"] == 1
    assert summary["recommendations_only"] is True

    ledger = st.list_lifecycle_rule_results("scan-1", "owner@x.com")
    assert ledger[0]["evaluated"] == 2
    assert ledger[0]["matched"] == 1
    assert ledger[0]["unevaluable"] == 1

    detail = st.lifecycle_file_detail("scan-1", "old.docx", "owner@x.com")
    assert detail["evaluations"][0]["policy_version"] == 1
    condition = detail["evaluations"][0]["evidence"]["conditions"][0]
    assert condition["observed_value"] == "2019-01-01T00:00:00+00:00"
    assert condition["value"] == "2020-01-01T00:00:00+00:00"

    handlers._evaluate_discover_lifecycle_rules("scan-1", "drive", "owner@x.com")
    assert len(st.lifecycle_file_detail("scan-1", "old.docx", "owner@x.com")["evaluations"]) == 1


def test_equal_priority_destructive_rules_fail_closed():
    import disposition
    archive = {"policy_id": "a", "name": "Archive", "action": "archive", "priority": 1}
    delete = {"policy_id": "d", "name": "Delete", "action": "delete", "priority": 1}
    chosen, status, reason = disposition.resolve_candidate([archive, delete], "owner@x.com")
    assert chosen is None
    assert status == "Conflict — review required"
    assert "neither action was selected" in reason


def test_lifecycle_routes_are_owner_scoped_and_return_one_snapshot(isolated_store, monkeypatch):
    import core
    from app import app
    from fastapi.testclient import TestClient

    st = isolated_store
    with st._db.cursor() as cur:
        st._db.execute(cur, "INSERT INTO scan_runs(id,owner_email,status,source) VALUES(%s,%s,%s,%s)",
                       ("scan-route", "owner@x.com", "discovered", "drive"))
    st.add_inventory("scan-route", [{"file": "a.docx", "doc_class": "text-document"}])
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda token: token or None)
    monkeypatch.setattr(core, "email_allowed", lambda email: True)
    client = TestClient(app)

    mine = client.get("/scans/scan-route/lifecycle/summary",
                      headers={"Authorization": "Bearer owner@x.com"})
    assert mine.status_code == 200
    assert mine.json()["total"] == mine.json()["reconciled_total"] == 1

    foreign = client.get("/scans/scan-route/lifecycle/summary",
                         headers={"Authorization": "Bearer other@x.com"})
    assert foreign.status_code == 404
