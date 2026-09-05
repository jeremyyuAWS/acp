"""Suspending somebody actually stops them signing in.

THE HOLE. `core.email_allowed` is the authentication perimeter — the one gate every request
passes — and it did not consult suspension at all. Suspension appeared to work anyway, for a
reason that had nothing to do with it being read: `PUT /admin/people` drops a suspended person
from the ALLOWLIST, so an allow-listed person was refused because their GRANT had been deleted.

A DOMAIN-admitted person has no allowlist entry to delete. `ACP_ALLOWED_DOMAINS` admits them by
rule, so the owner clicked Suspend, the People screen said suspended, and the address kept
signing in exactly as before. Measured on a real store before the fix:

    newcomer@hosp.org          status='suspended'  email_allowed=True     <- the hole
    contractor@elsewhere.test  status='suspended'  email_allowed=False    <- the allowlist, not
                                                                            the suspension

WHY THE RBAC LAYER DID NOT COVER IT, which is the part that makes this ship-blocking rather than
theoretical. `workspace_roles` checks suspension correctly — but only from the `navigation` rung
upward. Below it (`off` and `observe`, and `off` is the default this product ships in)
`access_for_email` returns `legacy_access()` for everyone, because not-yet-enforcing means
"preserve current access". Measured across the ladder, for a suspended person:

    off         tabs=10  caps=22        <- suspension not consulted on this path at all
    observe     tabs=10  caps=22
    navigation  tabs= 0  caps= 0
    enforce     tabs= 0  caps= 0

So until the rollout is climbed, the perimeter is the ONLY place a suspension can take effect.
That is why the fix lives in `email_allowed` rather than beside the other suspension checks.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ACP / "api"))

OWNER = "owner@hosp.org"
DOMAIN_USER = "newcomer@hosp.org"        # admitted by the DOMAIN rule alone — on no list
LISTED = "contractor@elsewhere.test"     # admitted by the allowlist, outside the domain
ENV_ADMIN = "deployer@elsewhere.test"    # ACP_ADMIN_EMAILS — permanent, not removable from the UI
OUTSIDER = "stranger@elsewhere.test"


# No `importlib.reload` in this file, for the reason recorded at the top of test_jit_roster.py:
# it leaves two live copies of a module in the suite and breaks unrelated tests in full-suite
# ordering only. Monkeypatching the attribute is enough — core reads these at call time.
@pytest.fixture
def env(monkeypatch):
    """A workspace with a domain rule, an owner, an env admin, and a fresh store."""
    import core
    import store as store_mod

    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "acp-test.db")
    st = store_mod.Store()
    monkeypatch.setattr(core, "store", st, raising=False)
    monkeypatch.setattr(core, "get_store", lambda: st, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "ALLOWED_DOMAINS", ["hosp.org"], raising=False)
    monkeypatch.setattr(core, "ALLOWED_EMAILS", set(), raising=False)
    monkeypatch.setattr(core, "ADMIN_EMAILS", {ENV_ADMIN}, raising=False)
    st.set_allowlist([OWNER, LISTED])
    core.forget_rostered()
    return core, st


def suspend(st, email):
    """Suspend exactly as `PUT /admin/people` does: drop the allowlist grant, set the status."""
    st.set_allowlist([e for e in st.get_allowlist() if e != email])
    st.upsert_person({"email": email, "role": "user", "status": "suspended"})


def active(st, email):
    st.upsert_person({"email": email, "role": "user", "status": "access_ready"})


# ── the hole itself ───────────────────────────────────────────────────────────

def test_a_suspended_domain_admitted_person_is_refused(env):
    """THE BUG. No allowlist entry to delete, so before the fix the domain rule admitted them."""
    core, st = env
    assert core.email_allowed(DOMAIN_USER), "premise: the domain admits them while active"
    suspend(st, DOMAIN_USER)
    assert core.email_allowed(DOMAIN_USER) is False


def test_an_unsuspended_domain_person_is_still_admitted(env):
    """THE CONTROL. Without it, "suspended people are refused" is satisfiable by refusing
    everybody at the domain, which would be a far worse bug than the one being fixed."""
    core, st = env
    active(st, DOMAIN_USER)
    assert core.email_allowed(DOMAIN_USER) is True
    assert core.email_allowed("colleague@hosp.org") is True, "no record at all: still admitted"


def test_a_suspended_allow_listed_person_stays_refused(env):
    """Already true before the fix — but for the wrong reason (the allowlist removal), so it has
    to keep passing for the right one now that suspension is actually read."""
    core, st = env
    assert core.email_allowed(LISTED)
    suspend(st, LISTED)
    assert core.email_allowed(LISTED) is False


def test_suspension_is_read_not_inferred_from_the_allowlist(env):
    """THE DISTINCTION THE OLD CODE COULD NOT MAKE, pinned so a future refactor cannot quietly
    go back to inferring it. Someone re-added to the allowlist while their record still says
    suspended must stay out: the two sources disagree and the withdrawal wins."""
    core, st = env
    suspend(st, LISTED)
    st.set_allowlist(list(st.get_allowlist()) + [LISTED])   # the grant is back
    assert LISTED in st.get_allowlist()
    assert core.email_allowed(LISTED) is False, "the stored withdrawal has to beat the grant"


def test_an_outsider_is_refused_with_or_without_a_record(env):
    core, _st = env
    assert core.email_allowed(OUTSIDER) is False


# ── who is exempt, and who deliberately is not ────────────────────────────────

def test_the_owner_is_exempt_even_with_a_suspended_record(env):
    """ANTI-LOCKOUT. `update_person` refuses to modify OWNER_EMAIL (409), so this state is not
    reachable through the product — the test forces it anyway, because the ordering is what makes
    that a guarantee rather than a coincidence, and an owner locked out is the one failure with
    no recovery path."""
    core, st = env
    st.upsert_person({"email": OWNER, "role": "owner", "status": "suspended"})
    assert core.email_allowed(OWNER) is True


def test_a_suspended_env_admin_is_refused(env):
    """THE DELIBERATE CHANGE, from "admins are always admitted".

    ACP_ADMIN_EMAILS cannot be edited from the UI, so before the fix suspending one of them was
    the same silent no-op as suspending a domain user. Safe to change because suspension is only
    ever written by `PUT /admin/people`, which is owner-gated: it is always a deliberate act by
    the one identity that can also undo it. `update_person` already strips a suspended person
    from the MANAGED admin list, so leaving the env list admitted made the two halves of "admin"
    disagree about the same click.
    """
    core, st = env
    assert core.email_allowed(ENV_ADMIN) is True
    suspend(st, ENV_ADMIN)
    assert core.email_allowed(ENV_ADMIN) is False


def test_unsuspending_restores_access_on_the_very_next_call(env):
    """NO MEMO, deliberately. The just-in-time roster next door caches "have we seen them", a
    fact that only moves one way. Suspension moves both ways and has to be obeyed now — a cache
    here would mean Reinstate needed a redeploy, which is this same bug wearing a performance
    optimisation as a disguise."""
    core, st = env
    suspend(st, DOMAIN_USER)
    assert core.email_allowed(DOMAIN_USER) is False
    active(st, DOMAIN_USER)
    assert core.email_allowed(DOMAIN_USER) is True


# ── the two failure policies, which point opposite ways on purpose ────────────

def test_the_perimeter_fails_open_when_the_store_cannot_be_read(env, monkeypatch):
    """A suspension check can only ever REMOVE access, so refusing on a failed read protects
    nothing and turns one unreadable settings row into a workspace-wide outage for people who
    were never suspended."""
    core, st = env

    def boom():
        raise RuntimeError("people_records unreadable")

    monkeypatch.setattr(st, "get_people", boom)
    assert core.is_suspended(DOMAIN_USER) is False
    assert core.email_allowed(DOMAIN_USER) is True


def test_the_capability_lookup_raises_when_the_store_cannot_be_read(env, monkeypatch):
    """The other half of the same decision. PRD §14: "Failure to load permissions must fail closed
    for sensitive operations." An unreadable store there means we cannot establish what somebody
    may do, and the three capability callers keep that raising policy."""
    core, st = env

    def boom():
        raise RuntimeError("people_records unreadable")

    monkeypatch.setattr(st, "get_people", boom)
    with pytest.raises(RuntimeError):
        core.suspended_in_store(DOMAIN_USER)


def test_an_empty_address_is_not_suspended(env):
    core, _st = env
    assert core.suspended_in_store("") is False
    assert core.suspended_in_store(None) is False
    assert core.is_suspended(None) is False


def test_the_lookup_is_case_and_whitespace_insensitive(env):
    core, st = env
    suspend(st, DOMAIN_USER)
    assert core.suspended_in_store("  NewComer@Hosp.org  ") is True


# ── one definition, not four ──────────────────────────────────────────────────

def test_every_suspension_reader_answers_from_the_same_definition(env):
    """Three modules carried a byte-identical copy of this lookup — app._capability_gate_suspended,
    routes.system._is_suspended and routes.workspace_roles_admin._suspended — which is three
    chances for the next person to change one of them. They now delegate. Asserted rather than
    assumed, because the whole bug being fixed here is one reader disagreeing with another."""
    import app
    import routes.system as system_routes
    import routes.workspace_roles_admin as roles_admin

    core, st = env
    suspend(st, DOMAIN_USER)
    active(st, LISTED)

    for who, expected in ((DOMAIN_USER, True), (LISTED, False), (OUTSIDER, False)):
        assert core.suspended_in_store(who) is expected
        assert app._capability_gate_suspended(who) is expected
        assert system_routes._is_suspended(who) is expected
        assert roles_admin._suspended(who) is expected


# ── what it costs, per request ────────────────────────────────────────────────

def test_the_gate_reads_the_people_records_once_per_call(env, monkeypatch):
    """STATED RATHER THAN ASSUMED. This runs on every authenticated request, so a second read
    slipping in here is a real regression even though nothing would fail. One read is the price
    of suspension being obeyed live; the allowlist read beside it was already being paid."""
    core, st = env
    calls = []
    real = st.get_people
    monkeypatch.setattr(st, "get_people", lambda: (calls.append(1), real())[1])

    core.email_allowed(DOMAIN_USER)
    assert len(calls) == 1, calls

    calls.clear()
    core.email_allowed(OWNER)
    assert calls == [], "the owner short-circuits before any store read"
