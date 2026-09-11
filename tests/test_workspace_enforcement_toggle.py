"""The Roles toggle changes durable shared authorization, not a process environment."""
import pytest
import core
import workspace_roles as wr
import workspace_rollout as rollout
from fastapi.testclient import TestClient
from app import app

OWNER = "owner@toggle.test"
MANAGER = "manager@toggle.test"
VIEWER = "viewer@toggle.test"

# Initialize the shared lazy store before fixture-specific paths are installed.
# Otherwise monkeypatch's first getattr creates its restore target on this fixture DB.
core.get_store()


@pytest.fixture
def toggle_client(isolated_store, monkeypatch):
    st = isolated_store
    monkeypatch.setattr(core, "store", st)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER)
    monkeypatch.setattr(core, "ACCESS_CODE", "")
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test")
    monkeypatch.setattr(core, "E2E_KEY", None)
    monkeypatch.setattr(core, "OPEN_ACCESS", True)
    monkeypatch.setattr(core, "verify_gis_token", lambda token: token)
    monkeypatch.setattr(core, "email_allowed", lambda email: email in (OWNER, MANAGER, VIEWER))
    monkeypatch.setenv(rollout.MODE_VAR, "off")
    wr.seed_builtin_roles(st, tenant_id=OWNER, actor=OWNER)
    for email, role in ((MANAGER, "platform-admin"), (VIEWER, "viewer")):
        st.upsert_person({"email": email, "workspace_role_id": role, "status": "access_ready"})
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {MANAGER}"})
    return client, st


def test_toggle_enables_and_disables_shared_persisted_mode_and_audits(toggle_client, monkeypatch):
    client, st = toggle_client
    response = client.put("/admin/workspace-roles/enforcement",
                          json={"enabled": True, "expected_mode": "off"})
    assert response.status_code == 200, response.text
    assert response.json()["rollout"]["enforcing"] is True
    assert st.get_setting(rollout.SETTING_KEY) == "enforce"
    from store import Store
    second_process_store = Store()
    monkeypatch.setattr(core, "store", second_process_store)
    assert rollout.mode() == "enforce"  # independent reader, unchanged process env=off
    response = client.put("/admin/workspace-roles/enforcement",
                          json={"enabled": False, "expected_mode": "enforce"})
    assert response.status_code == 200, response.text
    monkeypatch.setattr(core, "store", st)
    assert rollout.mode() == "off"
    audit = [r for r in st.list_decisions() if r["action"] == "roles.enforcement_changed"]
    assert len(audit) == 2
    assert all(r["actor"] == MANAGER for r in audit)


def test_viewer_cannot_disable_or_enable_even_when_roles_are_off(toggle_client):
    client, st = toggle_client
    client.headers.update({"Authorization": f"Bearer {VIEWER}"})
    for enabled in (False, True):
        response = client.put("/admin/workspace-roles/enforcement",
                              json={"enabled": enabled, "expected_mode": "off"})
        assert response.status_code == 403, response.text
    assert st.get_setting(rollout.SETTING_KEY) is None


def test_readiness_blocker_prevents_enabling(toggle_client):
    client, st = toggle_client
    st.delete_workspace_role(tenant_id=OWNER, role_id="platform-user")
    response = client.put("/admin/workspace-roles/enforcement",
                          json={"enabled": True, "expected_mode": "off"})
    assert response.status_code == 409, response.text
    assert st.get_setting(rollout.SETTING_KEY) is None


def test_stale_toggle_rejected_and_existing_owner_can_recover(toggle_client):
    client, st = toggle_client
    st.set_setting(rollout.SETTING_KEY, "enforce")
    response = client.put("/admin/workspace-roles/enforcement",
                          json={"enabled": False, "expected_mode": "off"})
    assert response.status_code == 409
    client.headers.update({"Authorization": f"Bearer {OWNER}"})
    response = client.put("/admin/workspace-roles/enforcement",
                          json={"enabled": False, "expected_mode": "enforce"})
    assert response.status_code == 200, response.text


def test_mode_read_errors_never_fall_back_to_off(toggle_client, monkeypatch):
    _, st = toggle_client
    def unavailable(*args, **kwargs):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(st, "get_setting", unavailable)
    with pytest.raises(RuntimeError, match="database unavailable"):
        rollout.mode()


def test_invalid_persisted_mode_fails_closed(toggle_client):
    _, st = toggle_client
    st.set_setting(rollout.SETTING_KEY, "typo")
    with pytest.raises(RuntimeError, match="invalid"):
        rollout.mode()


def test_roles_list_exposes_strict_toggle_permission_even_while_off(toggle_client):
    client, _ = toggle_client
    assert client.get("/admin/roles").json()["can_manage_enforcement"] is True
    client.headers.update({"Authorization": f"Bearer {VIEWER}"})
    response = client.get("/admin/roles")
    assert response.status_code == 200
    assert response.json()["can_manage_enforcement"] is False


def test_explicit_saved_off_overrides_deployment_enforce(toggle_client, monkeypatch):
    _, st = toggle_client
    monkeypatch.setenv(rollout.MODE_VAR, "enforce")
    st.set_setting(rollout.SETTING_KEY, "off")
    assert rollout.mode() == "off"
