"""POST /admin/workspace-roles/bootstrap — the one call site the §15 migration has.

WHY THIS FILE EXISTS AT ALL. A migration nothing calls is not a migration; it is a module with
tests. This repo has the receipts on that shape — `tests/test_orphaned_detectors.py` records three
detectors declared and never invoked, reading as capability for months — so the seeding path gets
an endpoint and the endpoint gets a test, rather than waiting for slice 3's admin UI to be the
first thing that ever runs it.

THREE PROPERTIES, and each is a way this endpoint could be wrong while looking right:

  * OWNER-ONLY. Seeding roles and assigning them is the root-of-trust action, so it sits with
    _require_owner alongside "who is an admin" rather than with _require_admin — which, under the
    default OPEN_ACCESS, is everybody.
  * DRY BY DEFAULT. The §15 rollout opens with an Observe step whose entire purpose is reading the
    plan before it means anything. A preview you have to remember to ask for is one somebody skips.
  * IT SAYS WHETHER THE ROWS DO ANYTHING. Nothing enforces them until
    ACP_WORKSPACE_RBAC_ENABLED is on, and an administrator who writes roles and believes they took
    effect has been misled by a successful-looking response.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

ACP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ACP / "api"))

import workspace_rbac as rbac        # noqa: E402
import workspace_roles as wr         # noqa: E402

OWNER = "owner@hosp.org"


def _req(email):
    return SimpleNamespace(state=SimpleNamespace(user_email=email))


@pytest.fixture
def env(monkeypatch):
    """A REAL Store on its own temp SQLite file, not a double.

    The double in tests/test_admin_management.py is right for that file — it exercises the admin
    union, which is settings-backed. This endpoint writes to two tables that were added with this
    feature, and a double would happily accept writes against DDL that does not exist.
    """
    import core
    import store as store_mod
    import routes.system as s

    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "acp-test.db")
    st = store_mod.Store()
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "store", st, raising=False)
    monkeypatch.setattr(core, "get_store", lambda: st, raising=False)
    st.upsert_person({"email": OWNER, "provider": "google", "role": "admin"})
    st.upsert_person({"email": "deva@hosp.org", "provider": "google", "role": "admin"})
    st.upsert_person({"email": "nurse@hosp.org", "provider": "microsoft", "role": "user"})
    return s, core, st


def test_only_the_owner_may_run_it(env):
    """An admin is not enough. Under OPEN_ACCESS every signed-in user is an admin, so gating this
    on _require_admin would mean anyone who can log in may seed and assign roles — which is the
    same mistake api/acr_authz.py exists to document, made in the module that defines roles."""
    s, _core, _st = env
    for who in ("deva@hosp.org", "nurse@hosp.org", "", None):
        with pytest.raises(HTTPException) as exc:
            s.bootstrap_workspace_roles(request=_req(who), body={"apply": True})
        assert exc.value.status_code == 403


def test_it_previews_by_default_and_writes_nothing(env):
    s, _core, st = env
    out = s.bootstrap_workspace_roles(request=_req(OWNER))
    assert out["dry_run"] is True
    assert {a["email"] for a in out["assignments"]} == {OWNER, "deva@hosp.org", "nurse@hosp.org"}
    assert all(a["applied"] is False for a in out["assignments"])
    assert st.list_workspace_roles(tenant_id=OWNER) == [], "a preview created roles"
    assert wr.role_id_for_email(st, "nurse@hosp.org") is None, "a preview assigned a role"


def test_an_explicit_apply_seeds_and_assigns(env):
    s, _core, st = env
    out = s.bootstrap_workspace_roles(request=_req(OWNER), body={"apply": True})
    assert out["dry_run"] is False
    assert set(out["roles_created"]) == set(rbac.BUILTIN_ROLES)
    assert wr.role_id_for_email(st, OWNER) == rbac.OWNER
    assert wr.role_id_for_email(st, "deva@hosp.org") == rbac.PLATFORM_ADMIN
    assert wr.role_id_for_email(st, "nurse@hosp.org") == rbac.COMPLIANCE_MANAGER


@pytest.mark.parametrize("body", [None, {}, {"apply": False}, {"apply": "yes"}, {"apply": "true"},
                                  {"apply": "false"}, {"apply": 1}, {"apply": 0},
                                  {"Apply": True}, {"applied": True}])
def test_anything_short_of_a_json_true_is_a_preview(env, body):
    """The string cases are the point, and `{"apply": "false"}` is the one that made this test
    change the code. Under a bare `bool(body.get("apply"))` every non-empty string applies — so a
    client that serialises booleans as strings would migrate a live deployment by sending the
    request that most clearly says do not. `{"apply": 1}` is here for the same reason from the
    other direction: 1 is not `true`, and guessing that it meant to be is how the strict check
    erodes back into a truthiness check."""
    s, _core, st = env
    out = s.bootstrap_workspace_roles(request=_req(OWNER), body=body)
    assert out["dry_run"] is True, f"{body!r} was treated as an instruction to write"
    assert st.list_workspace_roles(tenant_id=OWNER) == []
    assert all(a["applied"] is False for a in out["assignments"])


def test_running_it_twice_is_safe(env):
    """The endpoint is reachable from a UI button; somebody will press it twice. The second run
    must create nothing and reassign nobody."""
    s, _core, st = env
    s.bootstrap_workspace_roles(request=_req(OWNER), body={"apply": True})
    wr.assign_role(st, email="nurse@hosp.org", role_id=rbac.VIEWER, actor=OWNER)

    second = s.bootstrap_workspace_roles(request=_req(OWNER), body={"apply": True})
    assert second["roles_created"] == []
    assert wr.role_id_for_email(st, "nurse@hosp.org") == rbac.VIEWER, \
        "the second run undid a deliberate tightening"


def test_the_response_says_whether_the_rows_actually_do_anything(env, monkeypatch):
    """Seeding succeeds whether or not enforcement is on, so 'it worked' is not the interesting
    part of the answer — `enabled` is. Without it an administrator reads a successful migration as
    a live one."""
    s, _core, _st = env
    monkeypatch.delenv(wr.FLAG, raising=False)
    assert s.bootstrap_workspace_roles(request=_req(OWNER))["enabled"] is False
    monkeypatch.setenv(wr.FLAG, "1")
    assert s.bootstrap_workspace_roles(request=_req(OWNER))["enabled"] is True


def test_applying_is_recorded_in_the_audit_trail(env):
    """PRD §12 wants role.created / role.assigned in ACP's audit history. The per-person rows come
    from assign_role; this asserts the migration itself is attributable to the owner who ran it."""
    s, _core, st = env
    s.bootstrap_workspace_roles(request=_req(OWNER), body={"apply": True})
    actions = [d for d in st.list_decisions() if d["action"] in ("role.migration", "role.assigned")]
    assert any(d["action"] == "role.migration" and d["actor"] == OWNER for d in actions)
    assigned = {d["detail"].split(" ·")[0] for d in actions if d["action"] == "role.assigned"}
    assert assigned == {OWNER, "deva@hosp.org", "nurse@hosp.org"}


def test_a_preview_leaves_no_audit_trail_either(env):
    """A preview that logged as if it had migrated would put a false event in the record an
    auditor reads — worse than no event, because it looks like evidence."""
    s, _core, st = env
    s.bootstrap_workspace_roles(request=_req(OWNER))
    assert [d for d in st.list_decisions() if d["action"].startswith("role.")] == []
