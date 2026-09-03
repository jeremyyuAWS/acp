"""Unified Google and Microsoft onboarding keeps identity, access, and status honest."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


def _request(email="owner@hosp.org"):
    return SimpleNamespace(state=SimpleNamespace(user_email=email))


@pytest.fixture()
def people(monkeypatch, isolated_store):
    import core
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "OWNER_EMAIL", "owner@hosp.org")
    monkeypatch.setattr(core, "ADMIN_EMAILS", set())
    isolated_store.set_allowlist(["owner@hosp.org"])
    return isolated_store


def test_google_person_gets_access_and_durable_metadata(people, monkeypatch):
    import invites
    from routes.system import add_person, list_people
    monkeypatch.setattr(invites, "invite_configured", lambda: False)

    result = add_person({"email": "New.User@Example.com", "provider": "google", "role": "user"},
                        _request())

    assert "new.user@example.com" in people.get_allowlist()
    assert result["person"]["status"] == "access_ready"
    assert people.get_people()[0]["provider"] == "google"
    roster = list_people(_request())
    assert roster["can_manage"] is True
    assert {p["email"] for p in roster["people"]} == {"owner@hosp.org", "new.user@example.com"}


def test_microsoft_without_graph_configuration_explains_manual_setup(people, monkeypatch):
    import invites
    from routes.system import add_person
    monkeypatch.setattr(invites, "invite_configured", lambda: False)
    monkeypatch.setattr(invites, "send_guest_invite", lambda *_: pytest.fail("Graph must stay dark"))

    result = add_person({"email": "guest@example.com", "provider": "microsoft"}, _request())

    assert result["person"]["status"] == "setup_required"
    assert "guest@example.com" in people.get_allowlist()


def test_microsoft_invitation_records_pending_state(people, monkeypatch):
    import invites
    from routes.system import add_person
    monkeypatch.setattr(invites, "invite_configured", lambda: True)
    monkeypatch.setattr(invites, "send_guest_invite",
                        lambda *_: {"redemption_url": "https://redeem.example", "status": "PendingAcceptance"})

    result = add_person({"email": "guest@example.com", "provider": "microsoft", "role": "admin"},
                        _request())

    assert result["person"]["status"] == "invited"
    assert result["person"]["redemption_url"] == "https://redeem.example"
    assert people.get_admins() == ["guest@example.com"]


def test_suspend_and_restore_change_the_real_login_gate(people, monkeypatch):
    import invites
    from routes.system import add_person, update_person
    monkeypatch.setattr(invites, "invite_configured", lambda: False)
    add_person({"email": "user@example.com", "provider": "google"}, _request())

    update_person("user@example.com", {"status": "suspended"}, _request())
    assert "user@example.com" not in people.get_allowlist()
    assert people.get_people()[0]["status"] == "suspended"

    update_person("user@example.com", {"status": "access_ready"}, _request())
    assert "user@example.com" in people.get_allowlist()


def test_owner_is_protected_and_duplicate_access_is_rejected(people, monkeypatch):
    import invites
    from routes.system import add_person, delete_person
    monkeypatch.setattr(invites, "invite_configured", lambda: False)
    with pytest.raises(HTTPException) as owner:
        delete_person("owner@hosp.org", _request())
    assert owner.value.status_code == 409

    add_person({"email": "person@example.com", "provider": "google"}, _request())
    with pytest.raises(HTTPException) as duplicate:
        add_person({"email": "person@example.com", "provider": "google"}, _request())
    assert duplicate.value.status_code == 409


def test_non_owner_admin_can_view_but_cannot_manage(people, monkeypatch):
    import core, invites
    from routes.system import add_person, list_people
    monkeypatch.setattr(invites, "invite_configured", lambda: False)
    people.set_admins(["admin@hosp.org"])
    people.set_allowlist(["owner@hosp.org", "admin@hosp.org"])

    assert list_people(_request("admin@hosp.org"))["can_manage"] is False
    with pytest.raises(HTTPException) as blocked:
        add_person({"email": "x@y.com", "provider": "google"}, _request("admin@hosp.org"))
    assert blocked.value.status_code == 403
    assert core.is_admin("admin@hosp.org")
