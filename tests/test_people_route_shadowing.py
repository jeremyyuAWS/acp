"""The workspace-role endpoint must actually be REACHABLE over HTTP.

THE BUG THIS EXISTS FOR. `system.py` registered `PUT /admin/people/{email:path}` and
`workspace_roles_admin.py` registered `PUT /admin/people/{email:path}/role`. The `:path`
converter matches `.*` — slashes included — and `routes/__init__.py` includes `system` first
and `workspace_roles_admin` last, so the SHORTER route won every match:

    PUT /admin/people/alice@hosp.org/role   ->  update_person(email="alice@hosp.org/role")

`update_person` then looked that address up, did not find it, and answered
`404 person not found`. That is the red line an administrator saw on the People screen, on the
row whose dropdown they had just used — the original bug report. `assign_person_role` was
unreachable and had never once served a request.

WHY NOTHING CAUGHT IT, which is the part worth keeping. Every test for the shadowed endpoint
calls the Python function directly:

    adm.assign_person_role(REVIEWER, {"role_id": rbac.ANALYST}, request=_req(OWNER))

That exercises the handler and proves it correct — which it was, the whole time — while saying
nothing about whether a request can reach it. A guard tested only through its own function is a
guard nobody proved the callers reach. So these tests go over HTTP on purpose, and the assertion
that matters is not "assignment succeeds" but "the request lands in the handler we think it
does".
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ACP / "api"))

import workspace_rbac as rbac        # noqa: E402
import workspace_roles as wr         # noqa: E402

OWNER = "owner@hosp.org"
ALICE = "alice@hosp.org"


@pytest.fixture
def client(monkeypatch):
    """The real app and the real router stack — the thing under test is the routing table."""
    import core
    import store as store_mod

    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "acp-test.db")
    st = store_mod.Store()
    monkeypatch.setattr(core, "store", st, raising=False)
    monkeypatch.setattr(core, "get_store", lambda: st, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "ALLOWED_DOMAINS", [], raising=False)
    monkeypatch.setattr(core, "ADMIN_EMAILS", set(), raising=False)
    monkeypatch.setattr(core, "OPEN_ACCESS", True, raising=False)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda t: (t or "").strip().lower() or None,
                        raising=False)
    st.set_allowlist([OWNER, ALICE])
    st.upsert_person({"email": ALICE, "provider": "google", "status": "access_ready",
                      "role": "user"})
    wr.seed_builtin_roles(st, tenant_id=wr.tenant_id_for(OWNER))

    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app), core, st


def as_owner(tc, method, path, **kw):
    return tc.request(method, path, headers={"Authorization": f"Bearer {OWNER}"}, **kw)


# ── the routing table itself ──────────────────────────────────────────────────

def test_the_role_endpoint_is_reachable_and_assigns(client):
    """THE REGRESSION. Before the fix this was 404 'person not found' for every address."""
    tc, _core, st = client
    r = as_owner(tc, "PUT", f"/admin/people/{ALICE}/role", json={"role_id": rbac.VIEWER})
    assert r.status_code == 200, r.text
    stored = next(p for p in st.get_people() if p["email"] == ALICE)
    assert stored.get(wr.ROLE_FIELD) == rbac.VIEWER


def test_the_request_lands_in_assign_person_role_not_update_person(client):
    """THE DISCRIMINATING ASSERTION, and it is why an invalid address is used rather than a valid
    one. The two candidate handlers refuse a slash-free non-address differently:

        assign_person_role  -> 400 'a valid email is required'   (its own validation)
        update_person       -> 404 'person not found'            (email became "noatsign/role")

    So the status code alone names which one ran. Asserting only that a valid assignment
    succeeds would go green again the moment somebody restored `:path`, as long as
    `update_person` happened to find the row.
    """
    tc, _core, _st = client
    r = as_owner(tc, "PUT", "/admin/people/noatsign/role", json={"role_id": rbac.VIEWER})
    assert r.status_code == 400, r.text
    assert "valid email" in r.json()["detail"]


def test_update_person_still_serves_its_own_path(client):
    """The control. Narrowing the converter must not break the route it belongs to — a fix that
    unshadows one endpoint by breaking another is not a fix."""
    tc, _core, st = client
    r = as_owner(tc, "PUT", f"/admin/people/{ALICE}", json={"role": "admin",
                                                            "status": "access_ready"})
    assert r.status_code == 200, r.text
    assert next(p for p in st.get_people() if p["email"] == ALICE)["role"] == "admin"


def test_role_impact_is_reachable_too(client):
    """It always was — `system.py` registers no GET under a person, so nothing shadowed it. That
    asymmetry is what made the bug so confusing from the UI: the dialog's preview filled in
    correctly from this endpoint, and then the write it was previewing answered 'person not
    found' about the same address a moment later."""
    tc, _core, _st = client
    r = as_owner(tc, "GET", f"/admin/people/{ALICE}/role-impact?role_id={rbac.VIEWER}")
    assert r.status_code == 200, r.text
    assert r.json()["email"] == ALICE


# ── the general rule, so the next sub-route is not swallowed silently ─────────

def test_no_people_route_uses_a_greedy_path_converter(client):
    """THE RULE RATHER THAN THE INSTANCE.

    `{email:path}` under `/admin/people` is unsafe by construction: it matches slashes, so it
    swallows every current and future sub-route of a person. An address in a path segment never
    contains a literal slash — the SPA sends it through encodeURIComponent — so the default
    `[^/]+` converter is both correct and safe here.

    This is deliberately a rule about the route table and not about the one endpoint that broke:
    the next `/admin/people/{email}/<something>` would fail exactly the same way, and it would
    again report itself as "that person does not exist".

    ENUMERATED THROUGH `core.enumerate_api_routes`, NOT BY WALKING `app.routes`, and the first
    draft of this test got that wrong in the way its docstring warns about. On this FastAPI,
    everything added via `include_router()` becomes an opaque `_IncludedRouter` that exposes
    neither `.path` nor `.routes` — so a hand-rolled walk found 4 paths (the OpenAPI and docs
    routes), none of them under /admin/people, and this assertion compared [] to [] and passed.
    It stayed green through the bite check that turned the two tests above red, which is how it
    was caught: a check that cannot fail is indistinguishable from a check that passed.
    """
    import core
    from app import app

    greedy = sorted({r.path for r in core.enumerate_api_routes(app)
                     if r.path.startswith("/admin/people") and ":path" in r.path})
    assert greedy == [], f"greedy converters under /admin/people shadow sub-routes: {greedy}"


def test_the_enumerator_actually_sees_the_people_routes(client):
    """The control for the rule above, and it exists because that rule already passed vacuously
    once. Without it, `enumerate_api_routes` returning nothing at all would read as "no greedy
    converters" — the same false green, one layer down."""
    import core
    from app import app

    people = {r.path for r in core.enumerate_api_routes(app)
              if r.path.startswith("/admin/people")}
    assert "/admin/people" in people
    assert "/admin/people/{email}" in people
    assert "/admin/people/{email}/role" in people, sorted(people)
    assert "/admin/people/{email}/role-impact" in people, sorted(people)
