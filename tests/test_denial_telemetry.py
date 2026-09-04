"""Denials reach the audit log — once per kind per window, not once per request.

WHAT WOULD GO WRONG WITHOUT THE COALESCING, and why it needs its own tests rather than being
obvious from reading the code:

  * The SPA POLLS. Scan status, job progress, the activity snapshot. A user whose role was
    narrowed mid-session keeps those polls running until the navigation catches up, so one
    narrowing produces a denial every few seconds per open tab.
  * decision_log IS APPEND-ONLY by design (api/store.py). Ten thousand copies of one fact do not
    just cost storage — they bury the role changes and publish approvals the log exists for.
  * A 403 SHOULD NOT COST A WRITE. An authenticated user hammering an endpoint they lack would
    otherwise turn each refusal into an INSERT: a denial-of-service with a valid session.

The tests below check both halves of the answer. Suppressing repeats is only correct if the row
that does get written says how many it stood for — "Jane was refused once" and "Jane was refused
four hundred times" are different situations, and the first reads as a misclick.

THE FAILURE MODE THIS FILE IS SHAPED AGAINST is a telemetry feature that quietly records nothing.
Every test that asserts suppression is paired with one that asserts something WAS recorded,
because "no rows" passes a suppression test perfectly.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ACP / "api"))

import workspace_denials as denials    # noqa: E402
import workspace_rbac as rbac          # noqa: E402
import workspace_roles as wr           # noqa: E402

OWNER = "owner@hosp.org"
ANALYST = "analyst@hosp.org"


@pytest.fixture(autouse=True)
def _clean_window():
    """The window is process-global. A test that does not clear it is one whose result depends on
    which tests ran before it."""
    denials.reset()
    yield
    denials.reset()


# ── the coalescing itself ─────────────────────────────────────────────────────

def test_the_first_denial_of_a_kind_is_recorded():
    record, suppressed = denials.should_record(ANALYST, {"operations.view"})
    assert record is True
    assert suppressed == 0


def test_repeats_inside_the_window_are_suppressed():
    denials.should_record(ANALYST, {"operations.view"})
    for _ in range(50):
        record, _ = denials.should_record(ANALYST, {"operations.view"})
        assert record is False


def test_the_next_recorded_row_says_how_many_it_stood_for():
    """Suppression without a count would understate a persistent problem as a one-off."""
    denials.should_record(ANALYST, {"operations.view"}, now=1000.0)
    for _ in range(17):
        denials.should_record(ANALYST, {"operations.view"}, now=1001.0)
    record, suppressed = denials.should_record(ANALYST, {"operations.view"},
                                               now=1000.0 + denials.WINDOW_SECONDS + 1)
    assert record is True
    assert suppressed == 17


def test_a_different_person_is_a_different_kind():
    denials.should_record(ANALYST, {"operations.view"})
    record, _ = denials.should_record("someone-else@hosp.org", {"operations.view"})
    assert record is True, "one user's denials must not mask another's"


def test_a_different_requirement_is_a_different_kind():
    denials.should_record(ANALYST, {"operations.view"})
    record, _ = denials.should_record(ANALYST, {"release.publish"})
    assert record is True


def test_two_paths_needing_the_same_capability_are_the_SAME_kind():
    """Keyed on the requirement, not the URL. `/scans/a/status` and `/scans/b/status` are one
    refusal to the operator reading it, and keying on the path would defeat the coalescing for
    every per-object route — which is most of them."""
    denials.should_record(ANALYST, {"assess.view", "discover.view"})
    record, _ = denials.should_record(ANALYST, {"discover.view", "assess.view"})
    assert record is False, "requirement order changed the key"


def test_the_window_does_not_grow_without_bound():
    """A hostile or broken client varying its identity must not grow this map forever."""
    for i in range(denials.MAX_TRACKED + 500):
        denials.should_record(f"user{i}@hosp.org", {"operations.view"})
    assert len(denials._seen) <= denials.MAX_TRACKED


# ── the row an operator reads ─────────────────────────────────────────────────

def test_the_detail_names_the_route_pattern_not_the_customers_id():
    """The concrete scan id is the customer's data; the pattern is the permission, and it is the
    permission this row is about. It also keeps rows for one refusal identical, which is what
    makes them countable."""
    text = denials.detail(ANALYST, {"operations.view"}, role="Analyst", method="GET",
                          path="/scans/{sid}/status", suppressed=0)
    assert "/scans/{sid}/status" in text
    assert "Analyst" in text and ANALYST in text
    assert "operations.view" in text


def test_the_detail_says_when_a_user_has_no_role_at_all():
    text = denials.detail("nobody@hosp.org", {"remediate.run"}, role=None, method="POST",
                          path="/scans/{sid}/remediate", suppressed=0)
    assert "no workspace role" in text


def test_the_detail_reports_the_suppressed_count_when_there_is_one():
    text = denials.detail(ANALYST, {"operations.view"}, role="Analyst", method="GET",
                          path="/admin/activity", suppressed=42)
    assert "+42 more" in text


# ── end to end, through the real refusal ──────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    import core
    import store as store_mod

    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "acp-test.db")
    st = store_mod.Store()
    monkeypatch.setattr(core, "store", st, raising=False)
    monkeypatch.setattr(core, "get_store", lambda: st, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "OPEN_ACCESS", True, raising=False)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda t: (t or "").strip().lower() or None,
                        raising=False)
    monkeypatch.setattr(core, "email_allowed", lambda e: bool(e), raising=False)
    monkeypatch.setenv(wr.FLAG, "1")

    for email in (OWNER, ANALYST):
        st.upsert_person({"email": email, "role": "user", "status": "access_ready"})
    wr.seed_builtin_roles(st, tenant_id=OWNER)
    wr.assign_role(st, email=ANALYST, role_id=rbac.ANALYST, actor=OWNER)

    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app), st


def _denials(store):
    return [d for d in store.list_decisions() if d["action"] == "role.access_denied"]


def test_a_refused_request_writes_one_audit_row(client):
    tc, st = client
    r = tc.get("/admin/activity", headers={"Authorization": f"Bearer {ANALYST}"})
    assert r.status_code == 403
    rows = _denials(st)
    assert len(rows) == 1
    assert rows[0]["actor"] == ANALYST
    assert "operations.view" in rows[0]["detail"]


def test_a_polling_client_does_not_fill_the_audit_log(client):
    """The scenario this exists for: an SPA that keeps polling after a role narrows."""
    tc, st = client
    for _ in range(40):
        assert tc.get("/admin/activity",
                      headers={"Authorization": f"Bearer {ANALYST}"}).status_code == 403
    assert len(_denials(st)) == 1, "40 refusals wrote more than one audit row"


def test_an_allowed_request_writes_nothing(client):
    """The other direction, and the one that makes the tests above mean something: a telemetry
    feature that recorded nothing at all would pass every suppression assertion."""
    tc, st = client
    assert tc.get("/hitl/queue", headers={"Authorization": f"Bearer {ANALYST}"}).status_code != 403
    assert _denials(st) == []


def test_the_refusal_survives_a_failing_audit_write(client, monkeypatch):
    """The write is best-effort BECAUSE the refusal is already decided. An exception escaping the
    recorder would turn a correct 403 into a 500 — which reads to the client as "the server
    broke" rather than "you may not do this", and makes the gate itself the outage."""
    tc, st = client

    def boom(*a, **k):
        raise RuntimeError("audit log unavailable")

    monkeypatch.setattr(st, "log_decision", boom, raising=False)
    r = tc.get("/admin/activity", headers={"Authorization": f"Bearer {ANALYST}"})
    assert r.status_code == 403
    assert r.json()["capability_denied"] is True


def test_denials_are_not_recorded_when_enforcement_is_off(client, monkeypatch):
    """Nothing is refused with the flag off, so there is nothing to record — and a row would be a
    false positive in the record an operator reads during the observe step of the rollout."""
    tc, st = client
    monkeypatch.delenv(wr.FLAG, raising=False)
    tc.get("/admin/activity", headers={"Authorization": f"Bearer {ANALYST}"})
    assert _denials(st) == []
