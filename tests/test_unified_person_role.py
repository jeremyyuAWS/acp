"""One explicit owner decision updates both authorization fields or neither."""
import pytest
from fastapi import HTTPException
from test_workspace_roles_admin import env, OWNER, MANAGER, NOBODY, _req
import workspace_rbac as rbac


def person(store, email=NOBODY):
    return next(p for p in store.get_people() if p['email'] == email)


def test_owner_atomic_promotion_demotion_and_undo(env):
    adm, core, store = env
    promoted = adm.assign_person_role(NOBODY, {'role_id': rbac.PLATFORM_ADMIN, 'platform_role': 'admin'}, _req(OWNER))
    assert promoted['person']['role'] == 'admin'
    assert promoted['person']['workspace_role_id'] == rbac.PLATFORM_ADMIN
    assert NOBODY in store.get_admins()
    adm.assign_person_role(NOBODY, {'role_id': 'role-manager', 'platform_role': 'user'}, _req(OWNER))
    assert person(store)['role'] == 'user' and NOBODY not in store.get_admins()
    restored = adm.assign_person_role(NOBODY, {'role_id': rbac.PLATFORM_ADMIN, 'platform_role': 'admin'}, _req(OWNER))
    assert restored['person']['workspace_role_id'] == rbac.PLATFORM_ADMIN
    assert restored['person']['role'] == 'admin'
    assert NOBODY in store.get_admins()


def test_workspace_only_manager_changes_keep_existing_platform_grant(env):
    adm, core, store = env
    store.upsert_person({'email': NOBODY, 'role': 'admin'})
    store.set_admins([NOBODY])
    adm.assign_person_role(NOBODY, {'role_id': 'role-manager'}, _req(MANAGER))
    assert person(store)['role'] == 'admin' and NOBODY in store.get_admins()
    assert person(store)['workspace_role_id'] == 'role-manager'


@pytest.mark.parametrize('platform_role', ['admin', 'user'])
def test_platform_grant_fields_are_owner_only_even_for_role_managers(env, platform_role):
    adm, core, store = env
    before = person(store)
    with pytest.raises(HTTPException) as failure:
        adm.assign_person_role(NOBODY, {'role_id': 'role-manager', 'platform_role': platform_role}, _req(MANAGER))
    assert failure.value.status_code == 403
    assert person(store) == before and NOBODY not in store.get_admins()


def test_owner_self_protection(env):
    adm, core, store = env
    before = person(store, OWNER)
    with pytest.raises(HTTPException) as failure:
        adm.assign_person_role(OWNER, {'role_id': '', 'platform_role': 'user'}, _req(OWNER))
    assert failure.value.status_code == 409
    assert person(store, OWNER) == before


def test_custom_role_called_platform_admin_does_not_grant_platform_administration(env):
    adm, core, store = env
    store.delete_workspace_role(tenant_id=OWNER, role_id=rbac.PLATFORM_ADMIN)
    store.upsert_workspace_role(tenant_id=OWNER, role_id=rbac.PLATFORM_ADMIN, name='Platform Admin',
                               permissions={'overview': 'view'}, expected_version=None)
    adm.assign_person_role(NOBODY, {'role_id': rbac.PLATFORM_ADMIN, 'platform_role': 'user'}, _req(OWNER))
    assert person(store)['workspace_role_id'] == rbac.PLATFORM_ADMIN
    assert person(store)['role'] == 'user' and NOBODY not in store.get_admins()


@pytest.mark.parametrize('point', ['admins', 'person', 'audit'])
def test_unified_save_rolls_back_workspace_and_platform_fields_on_failure(env, monkeypatch, point):
    adm, core, store = env
    before = person(store)
    admins = store.get_admins()
    def fail(*args):
        raise RuntimeError('write failed')
    if point == 'admins':
        monkeypatch.setattr(store, 'set_admins', fail)
    elif point == 'person':
        original = store.upsert_person
        monkeypatch.setattr(store, 'upsert_person', lambda row: fail() if 'role' in row else original(row))
    else:
        original = store.log_decision
        monkeypatch.setattr(store, 'log_decision', lambda actor, action, **kw: fail() if action == 'settings.person.platform_role' else original(actor, action, **kw))
    with pytest.raises(RuntimeError, match='write failed'):
        adm.assign_person_role(NOBODY, {'role_id': rbac.PLATFORM_ADMIN, 'platform_role': 'admin'}, _req(OWNER))
    assert person(store) == before
    assert store.get_admins() == admins


def test_no_role_demotes_only_explicit_owner_decision(env):
    adm, core, store = env
    adm.assign_person_role(NOBODY, {'role_id': rbac.PLATFORM_ADMIN, 'platform_role': 'admin'}, _req(OWNER))
    adm.assign_person_role(NOBODY, {'role_id': '', 'platform_role': 'user'}, _req(OWNER))
    assert person(store)['workspace_role_id'] is None
    assert person(store)['role'] == 'user' and NOBODY not in store.get_admins()


def test_deployment_admin_workspace_changes_preserve_configured_platform_authority(env, monkeypatch):
    adm, core, store = env
    monkeypatch.setattr(core, 'ADMIN_EMAILS', {NOBODY})
    before = person(store)
    with pytest.raises(HTTPException) as failure:
        adm.assign_person_role(NOBODY, {'role_id': 'role-manager', 'platform_role': 'user'}, _req(OWNER))
    assert failure.value.status_code == 409 and person(store) == before
    adm.assign_person_role(NOBODY, {'role_id': 'role-manager'}, _req(OWNER))
    assert person(store)['workspace_role_id'] == 'role-manager'
    from routes.system import _people_payload
    projected = next(p for p in _people_payload()['people'] if p['email'] == NOBODY)
    assert projected['platform_role_admin'] is True and projected['platform_role_locked'] is True
