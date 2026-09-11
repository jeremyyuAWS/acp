"""Expanded tabs remain independent of per-report ACR authority and global settings."""
import pytest
from fastapi import HTTPException
from starlette.requests import Request
import core
import workspace_rbac as rbac
import workspace_roles as wr
import workspace_capability_map as capmap
from routes.scans import set_assessment_scope

OWNER = "owner@test.invalid"


def test_expanded_tab_backfill_is_explicit_idempotent_and_preserves_choices(isolated_store):
    st = isolated_store
    st.upsert_workspace_role(tenant_id=OWNER, role_id="old", name="Old",
                            permissions={"assess": "operate", "acr": "hidden"})
    assert wr.backfill_existing_main_tabs(st, tenant_id=OWNER, actor="maintenance") == ["old"]
    row = st.get_workspace_role(tenant_id=OWNER, role_id="old")
    assert {p["capability"]: p["access_level"] for p in row["permissions"]} == {
        "assess": "operate", "acr": "hidden", "graph": "operate"}
    assert wr.backfill_existing_main_tabs(st, tenant_id=OWNER, actor="maintenance") == []
    assert st.get_workspace_role(tenant_id=OWNER, role_id="old")["version"] == row["version"]
    # New roles never acquire implicit access after maintenance has finished.
    assert "acr.view" not in rbac.capabilities_for({"assess": "operate"})


@pytest.mark.parametrize("tab", ["graph", "acr"])
@pytest.mark.parametrize("level", ["hidden", "view", "operate"])
def test_new_tab_levels(tab, level):
    caps = rbac.capabilities_for({tab: level})
    assert (f"{tab}.view" in caps) == (level != "hidden")
    assert (f"{tab}.operate" in caps) == (level == "operate")


def test_graph_only_role_reads_scan_data_but_cannot_start_assessment():
    caps = rbac.capabilities_for({"graph": "view"})
    assert capmap.allows("GET", "/scans/{sid}", caps)
    assert not capmap.allows("POST", "/scans/{sid}/assess", caps)
    assert not capmap.allows("POST", "/scans/{sid}/comments", caps)


@pytest.fixture
def scan_scope_store(isolated_store, monkeypatch):
    st = isolated_store
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setattr("routes.scans._owner", lambda request: OWNER)
    st.init_scan_run("mine", "drive", 0, "2026-09-11", "WCAG", "hash",
                     owner=OWNER, status="discovered", scope={"other_fact": 8})
    st.init_scan_run("other", "drive", 0, "2026-09-11", "WCAG", "hash",
                     owner="other@test.invalid", status="discovered")
    return st


def request():
    return Request({"type": "http", "method": "PUT", "path": "/", "headers": []})


def test_assessment_operator_saves_exact_scope_without_settings_permission(scan_scope_store):
    st = scan_scope_store
    st.set_setting("scan_scope", '{"1.1.1":["pdf"]}')
    caps = rbac.capabilities_for({"assess": "operate"})
    assert capmap.allows("PUT", "/scans/{sid}/assessment-scope", caps)
    assert not capmap.allows("PUT", "/settings", caps)
    assert st.get_scan_scope("mine") is None  # previously cached absence
    result = set_assessment_scope("mine", {"scan_scope": {"1.3.1": ["pdf", "docx"]}}, request())
    assert result["scan_scope"] == {"1.3.1": ["docx", "pdf"]}
    assert st.get_scan_scope("mine") == {"1.3.1": frozenset({"pdf", "docx"})}
    assert st.get_setting("scan_scope") == '{"1.1.1":["pdf"]}'
    assert st.get_scan("mine", owner=OWNER)["run"]["scope"]["other_fact"] == 8
    assert not capmap.allows("PUT", "/scans/{sid}/assessment-scope",
                            rbac.capabilities_for({"assess": "view"}))


@pytest.mark.parametrize("body", [{"scan_scope": {}}, {"scan_scope": "invalid"},
                                 {"scan_scope": {"1.1.1": ["pdf"]}, "ai_base_url": "bad"}])
def test_scope_rejects_invalid_or_unrelated_settings(scan_scope_store, body):
    with pytest.raises(HTTPException) as exc:
        set_assessment_scope("mine", body, request())
    assert exc.value.status_code == 422
    assert scan_scope_store.get_scan_scope("mine") is None


def test_scope_cannot_touch_other_users_scan(scan_scope_store):
    with pytest.raises(HTTPException) as exc:
        set_assessment_scope("other", {"scan_scope": {"1.1.1": ["pdf"]}}, request())
    assert exc.value.status_code == 404


def test_scope_cannot_change_an_active_scan(scan_scope_store, monkeypatch):
    monkeypatch.setattr(scan_scope_store, "active_workflows", lambda owner: [{"scan_id": "mine"}])
    with pytest.raises(HTTPException) as exc:
        set_assessment_scope("mine", {"scan_scope": {"1.1.1": ["pdf"]}}, request())
    assert exc.value.status_code == 409


def test_scope_changes_visible_across_store_processes(scan_scope_store):
    from store import Store
    other_process = Store()
    assert other_process.get_scan_scope("mine") is None
    set_assessment_scope("mine", {"scan_scope": {"1.1.1": ["docx"]}}, request())
    assert other_process.get_scan_scope("mine", refresh=True) == {"1.1.1": frozenset({"docx"})}


def test_scope_read_returns_exact_selection_and_not_other_settings(scan_scope_store):
    from routes.scans import get_assessment_scope
    st = scan_scope_store
    st.set_setting("scan_scope", '{"1.1.1":["pdf"]}')
    st.set_setting("ai_api_key", "not-for-this-endpoint")
    assert get_assessment_scope("mine", request()) == {
        "scan_id": "mine", "scan_scope": '{"1.1.1":["pdf"]}'}
    set_assessment_scope("mine", {"scan_scope": {"1.3.1": ["docx"]}}, request())
    assert get_assessment_scope("mine", request())["scan_scope"] == {"1.3.1": ["docx"]}
    with pytest.raises(HTTPException) as exc:
        get_assessment_scope("other", request())
    assert exc.value.status_code == 404


def test_acr_workspace_operate_does_not_confer_report_approval(isolated_store, monkeypatch):
    from fastapi.testclient import TestClient
    from app import app
    user = "custom@test.invalid"
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "")
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test")
    monkeypatch.setattr(core, "E2E_KEY", None)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER)
    monkeypatch.setattr(core, "OPEN_ACCESS", True)
    monkeypatch.setattr(core, "verify_gis_token", lambda token: token)
    monkeypatch.setattr(core, "email_allowed", lambda email: email in (OWNER, user))
    monkeypatch.setenv("ACP_WORKSPACE_RBAC_MODE", "enforce")
    isolated_store.upsert_workspace_role(tenant_id=OWNER, role_id="custom", name="Custom",
                                         permissions={"acr": "operate"})
    isolated_store.upsert_person({"email": user, "workspace_role_id": "custom", "status": "access_ready"})
    client = TestClient(app)
    report = client.post("/acr", headers={"Authorization": f"Bearer {OWNER}"},
                         json={"product_version": "1"} )
    assert report.status_code == 200, report.text
    report_id = report.json()["report_id"]
    response = client.post(f"/acr/{report_id}/criteria/1.1.1/approve",
                           headers={"Authorization": f"Bearer {user}"})
    assert response.status_code == 403, response.text
    assert "approver" in response.text.lower()
    isolated_store.upsert_workspace_role(tenant_id=OWNER, role_id="custom", name="Custom",
                                         permissions={"acr": "hidden"})
    response = client.get("/acr", headers={"Authorization": f"Bearer {user}"})
    assert response.status_code == 403, response.text


@pytest.mark.parametrize("tab", ["assess", "remediate"])
@pytest.mark.parametrize("provider", ["drive", "sp"])
def test_stage_operator_can_refresh_only_own_credentials(scan_scope_store, monkeypatch, tab, provider):
    import routes.scans as scans
    caps = rbac.capabilities_for({tab: "operate"})
    assert capmap.allows("POST", f"/scans/{{sid}}/{provider}-token", caps)
    assert not capmap.allows("DELETE", "/scans/{sid}/tokens", caps)
    assert not capmap.allows("DELETE", "/scans/{sid}", caps)
    assert not capmap.allows("POST", f"/scans/{{sid}}/{provider}-token",
                            rbac.capabilities_for({tab: "view"}))
    writes = []
    monkeypatch.setattr(scans, "_register_scan_tokens", lambda *args, **kwargs: writes.append((args, kwargs)))
    req = Request({"type": "http", "method": "POST", "path": "/",
                   "headers": [(f"x-{provider}-token".encode(), b"fixture-token")]})
    handler = scans.refresh_scan_drive_token if provider == "drive" else scans.refresh_scan_sp_token
    assert handler("mine", req)["refreshed"] is True
    with pytest.raises(HTTPException) as exc:
        handler("other", req)
    assert exc.value.status_code == 404
    assert len(writes) == 1
