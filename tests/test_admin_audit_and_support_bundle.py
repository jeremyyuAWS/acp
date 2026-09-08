"""`GET /admin/audit-events` and `GET /admin/support-bundle` — PRD §13, §15, §20.6.

THE TWO SURFACES A PORTABLE ACCEPTANCE RUN CANNOT ANSWER WITHOUT. Both were absent for four
reference-cluster runs, and their scenario reported `unknown` every time — never a pass, which is
the point of the suite having four states, but also a question nobody could answer on any target.

§20.6 IS AN ABSOLUTE: "Secrets never appear in configuration output or support bundles." The tests
below treat that as something to CHECK. The important one puts a real-looking credential in the
environment, in a variable the bundle's own composition never reads, and asserts the route refuses
rather than returning — because the failure mode worth defending against is not the field somebody
remembered, it is the one somebody adds next week.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

ADMIN = "admin@example.test"
USER = "user@example.test"


@pytest.fixture()
def client(monkeypatch, isolated_store):
    """A TestClient with a configured owner, so `_require_admin` actually gates.

    An ungated client would make every 403 assertion below vacuous — `_require_admin` is a no-op
    when no owner is configured (local dev without auth), which is exactly the shape of test that
    passes while enforcing nothing.
    """
    import core
    from fastapi.testclient import TestClient

    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", ADMIN, raising=False)
    return TestClient(app), isolated_store


def as_admin(monkeypatch):
    """Make `core.is_admin` say yes.

    NOT A WAY AROUND THE GATE. `request.state.user_email` is stamped only on the GIS branch of the
    access middleware, which needs a real Google client id, so a TestClient cannot present an
    identity at all. What is under test here is the ENFORCEMENT WIRING — that each route calls
    `_require_admin`, and that its answer decides the response — and flipping `is_admin` exercises
    exactly that in both directions. `test_*_require_admin` is the other half.
    """
    import core
    monkeypatch.setattr(core, "is_admin", lambda e: True)


# ── the audit trail ───────────────────────────────────────────────────────────

def test_a_deployment_is_recorded_once_per_release_not_once_per_process(isolated_store):
    """Every replica runs startup and a crash-looping pod runs it repeatedly. Recording per
    process would turn one incident into thousands of rows and bury the deployments among them."""
    store = isolated_store
    assert store.record_deployment_audit(version="1.2.3", commit="abc", platform="kubernetes",
                                         profile="standard") is True
    assert store.record_deployment_audit(version="1.2.3", commit="abc", platform="kubernetes",
                                         profile="standard") is False
    assert store.record_deployment_audit(version="1.2.4", commit="def", platform="kubernetes",
                                         profile="standard") is True
    types = [e["type"] for e in store.list_audit_events()]
    assert types.count("deployment.started") == 2


def test_a_fresh_installation_that_changed_nothing_still_has_an_audit_trail(isolated_store):
    """"No events" must mean "audit logging is broken", not "nothing has happened yet" — the one
    ambiguity an auditor cannot afford (PRD §15, §20.12)."""
    store = isolated_store
    store.record_deployment_audit(version="1.0.0", commit="c", platform="kubernetes",
                                  profile="standard")
    events = store.list_audit_events()
    assert events and events[0]["type"] == "deployment.started"


def test_the_deployment_row_carries_no_environment_or_credential(isolated_store):
    store = isolated_store
    store.record_deployment_audit(version="1.0.0", commit="c0ffee", platform="kubernetes",
                                  profile="regulated")
    detail = store.list_audit_events()[0]["detail"]
    assert "1.0.0" in detail and "kubernetes" in detail
    assert "://" not in detail, f"a connection-string-shaped value reached an audit row: {detail}"


def test_a_per_document_decision_is_not_an_audit_event(isolated_store):
    """`decision_log` holds both. A per-document row carries `file` — a customer's document name —
    and PRD §13 keeps those out of exported diagnostics."""
    store = isolated_store
    store.log_decision("someone@example.test", "hitl.accepted", scan_id="s1",
                       file="Q3 Board Minutes.docx", detail="accepted alt text")
    events = store.list_audit_events()
    assert events == [], f"a document-scoped decision was exported as an audit event: {events}"


def test_the_allow_list_is_a_prefix_list_and_an_unnamed_action_is_not_exported(isolated_store):
    """A blocklist exports document names the day somebody adds an action nobody excluded. This
    asserts the opposite default: unnamed means not exported."""
    store = isolated_store
    store.log_decision("admin", "settings.ai_enabled", detail="ai_enabled set to False")
    store.log_decision("admin", "something.brand_new", detail="whatever this is")
    types = [e["type"] for e in store.list_audit_events()]
    assert "settings.ai_enabled" in types
    assert "something.brand_new" not in types


def test_a_platform_action_that_is_document_scoped_is_dropped_rather_than_stripped(isolated_store):
    """Defence in depth: the prefix says platform, the row says document. Either the action is
    mis-named or the call site is wrong, and neither is a row to export."""
    store = isolated_store
    store.log_decision("admin", "settings.something", file="Payroll.xlsx", detail="x")
    assert store.list_audit_events() == []


def test_audit_events_require_admin_not_merely_a_signed_in_user(client, monkeypatch):
    """An audit log names who changed what and when. Any allow-listed user could otherwise read
    the platform's entire administrative history; a hidden tab is not enforcement."""
    c, store = client
    monkeypatch.setattr("core.is_admin", lambda e: False)
    assert c.get("/admin/audit-events").status_code == 403


def test_audit_events_answer_the_shape_the_acceptance_suite_reads(client, monkeypatch):
    c, store = client
    as_admin(monkeypatch)
    store.record_deployment_audit(version="2026.9.8", commit="abc", platform="kubernetes",
                                  profile="standard")
    r = c.get("/admin/audit-events?limit=50")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["events"], body
    assert {"type", "at", "actor", "detail"} <= set(body["events"][0])
    assert "file" not in body["events"][0]


# ── the support bundle ────────────────────────────────────────────────────────

def test_the_support_bundle_requires_admin(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr("core.is_admin", lambda e: False)
    assert c.get("/admin/support-bundle").status_code == 403


def test_the_support_bundle_declares_itself_redacted_and_names_the_build(client, monkeypatch):
    c, _ = client
    as_admin(monkeypatch)
    body = c.get("/admin/support-bundle").json()
    assert body["redacted"] is True
    assert "release" in body and "dependencies" in body


def test_the_bundle_refuses_rather_than_returning_when_a_credential_reaches_it(
        client, monkeypatch):
    """THE TEST THAT MATTERS. A credential is planted in the environment AND forced into a bundle
    section, standing in for the field somebody adds next week. The route must refuse — a bundle
    that leaks is worse than no bundle, and an error a developer fixes is better than a quiet
    redaction that hides the bug."""
    c, _ = client
    as_admin(monkeypatch)
    monkeypatch.setenv("ACP_DB_PASSWORD", "hunter2-super-secret-value")
    monkeypatch.setattr("routes.system.pdf_engine_status",
                        lambda: {"available": "hunter2-super-secret-value"})
    r = c.get("/admin/support-bundle")
    assert r.status_code == 500, (
        f"the bundle returned {r.status_code} with a credential inside it; §20.6 says secrets "
        f"never appear in a support bundle")
    detail = r.json()["detail"]
    assert detail["code"] == "support_bundle_would_leak"
    assert "dependencies" in detail["sections"]
    # The offending VALUE is never named — that would put it in the error this route exists to
    # keep it out of.
    assert "hunter2-super-secret-value" not in r.text


def test_a_short_environment_value_does_not_redact_the_whole_bundle(client, monkeypatch):
    """Under six characters a "secret" is more likely to be ordinary prose — "true", "1", "acp" —
    and grepping for it would refuse every bundle forever."""
    c, _ = client
    as_admin(monkeypatch)
    monkeypatch.setenv("ACP_API_TOKEN", "true")
    assert c.get("/admin/support-bundle").status_code == 200


def test_the_bundle_never_serialises_the_environment(client, monkeypatch):
    """An allow-list of readings, not a dump with things removed: a filtered environment ships the
    variable somebody adds tomorrow."""
    c, _ = client
    as_admin(monkeypatch)
    monkeypatch.setenv("ACP_HARMLESS_MARKER", "marker-value-not-a-secret")
    text = c.get("/admin/support-bundle").text
    assert "ACP_HARMLESS_MARKER" not in text
    assert "marker-value-not-a-secret" not in text


def test_the_bundle_carries_no_document_names_or_user_identities(client, monkeypatch):
    c, store = client
    as_admin(monkeypatch)
    store.log_decision("someone@example.test", "hitl.accepted", scan_id="s1",
                       file="Q3 Board Minutes.docx", detail="accepted")
    text = c.get("/admin/support-bundle").text
    assert "Q3 Board Minutes.docx" not in text
    assert "someone@example.test" not in text
