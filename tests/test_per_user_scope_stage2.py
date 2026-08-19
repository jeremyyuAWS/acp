"""Per-user scan-scope override — stage 2, the resolution wiring (ADR 0035).

Stage 1 shipped the store primitive (`set/get/clear/resolve_setting`); this pins stage 2: the
widen-only union in `assessment_policy.active_scope(store, user=...)`, which is the map a scan freezes
into `scan_runs.scope` and therefore what scoring counts over. The invariant that matters for a
hospital is that a per-user override can only WIDEN — a user may assess more than the owner mandated,
never less — so an override can never silently hide a finding the owner required.

All tested against a fake store (no DB): `active_scope` reads exactly `get_setting` (owner/global) and
`get_user_setting` (the user's override), both of which the fake implements to the real signatures.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import assessment_policy as ap  # noqa: E402


class FakeStore:
    """Minimal store: an owner/global `scan_scope` and a per-user override map, matching the two
    methods `active_scope` calls. `get_user_setting` returns None when the user has no override —
    the signal, distinct from an empty-string override that means 'no restriction'."""
    def __init__(self, global_scope="", user_scopes=None):
        self._global = global_scope
        self._users = user_scopes or {}

    def get_setting(self, key, default=None):
        return self._global if key == ap.SCOPE_SETTING else default

    def get_user_setting(self, user, key):
        if key != ap.SCOPE_SETTING:
            return None
        return self._users.get(user)


@pytest.fixture(autouse=True)
def _no_module_override(monkeypatch):
    # `_scope_override` is a module-global test/per-call hook that would shadow the store; keep it off
    # so these tests exercise the store-backed owner resolution.
    monkeypatch.setattr(ap, "_scope_override", None)


OWNER = '{"1.4.3": ["docx"]}'


def test_no_user_is_exactly_the_owner_default():
    store = FakeStore(global_scope=OWNER)
    assert ap.active_scope(store) == {"1.4.3": frozenset({"docx"})}
    assert ap.active_scope(store, user=None) == {"1.4.3": frozenset({"docx"})}


def test_user_without_an_override_gets_the_owner_default():
    store = FakeStore(global_scope=OWNER, user_scopes={})
    assert ap.active_scope(store, user="nobody@h.org") == {"1.4.3": frozenset({"docx"})}


def test_override_widens_formats_on_a_shared_criterion():
    store = FakeStore(global_scope=OWNER, user_scopes={"a@h.org": '{"1.4.3": ["docx","pdf"]}'})
    assert ap.active_scope(store, user="a@h.org") == {"1.4.3": frozenset({"docx", "pdf"})}


def test_override_adds_a_criterion_without_dropping_the_owner_one():
    store = FakeStore(global_scope=OWNER, user_scopes={"a@h.org": '{"1.1.1": ["docx"]}'})
    got = ap.active_scope(store, user="a@h.org")
    assert got == {"1.4.3": frozenset({"docx"}), "1.1.1": frozenset({"docx"})}  # owner 1.4.3 kept


def test_override_can_never_narrow_below_the_owner_mandate():
    # THE invariant: owner mandates docx+pdf; a user override naming only docx must NOT drop pdf.
    store = FakeStore(global_scope='{"1.4.3": ["docx","pdf"]}',
                      user_scopes={"a@h.org": '{"1.4.3": ["docx"]}'})
    assert ap.active_scope(store, user="a@h.org") == {"1.4.3": frozenset({"docx", "pdf"})}


def test_empty_override_is_opting_into_no_restriction():
    # An empty override ("") is a real value — the user opting into 'assess everything' — which widens.
    store = FakeStore(global_scope=OWNER, user_scopes={"a@h.org": ""})
    assert ap.active_scope(store, user="a@h.org") is None


def test_override_cannot_narrow_below_an_unrestricted_owner():
    # Owner has no restriction (everything). A user override naming a subset cannot narrow below that.
    store = FakeStore(global_scope="", user_scopes={"a@h.org": '{"1.4.3": ["docx"]}'})
    assert ap.active_scope(store, user="a@h.org") is None


def test_malformed_override_is_ignored_never_widens_or_narrows():
    # A typo must neither explode the scan to the whole estate nor narrow it — it falls back to owner.
    store = FakeStore(global_scope=OWNER, user_scopes={"a@h.org": "not-a-known-preset"})
    assert ap.active_scope(store, user="a@h.org") == {"1.4.3": frozenset({"docx"})}


def test_one_store_isolates_users_from_each_other_and_from_the_global():
    # The fixture the ADR asks for: a user override changes ONLY that user's scope. One store, three
    # distinct answers — A widened, B untouched, the global (user=None) unchanged.
    store = FakeStore(global_scope=OWNER, user_scopes={
        "a@h.org": '{"1.4.3": ["docx","pdf"]}',   # A widens to pdf too
        # b@h.org has no override
    })
    assert ap.active_scope(store, user="a@h.org") == {"1.4.3": frozenset({"docx", "pdf"})}
    assert ap.active_scope(store, user="b@h.org") == {"1.4.3": frozenset({"docx"})}   # owner default
    assert ap.active_scope(store, user=None) == {"1.4.3": frozenset({"docx"})}        # global untouched


def test_widen_union_helper_none_means_everything():
    # Directly: 'everything' (None) unioned with anything is still everything.
    assert ap._widen_union(None, {"1.4.3": frozenset({"docx"})}) is None
    assert ap._widen_union({"1.4.3": frozenset({"docx"})}, None) is None
    assert ap._widen_union({"1.1.1": frozenset({"docx"})}, {"1.1.1": frozenset({"pdf"})}) == {
        "1.1.1": frozenset({"docx", "pdf"})}


def test_store_read_failure_falls_back_to_owner_not_raise():
    class Boom(FakeStore):
        def get_user_setting(self, user, key):
            raise RuntimeError("db down")
    store = Boom(global_scope=OWNER)
    # A hot-path store failure on the per-user read must not crash the scan; owner default stands.
    assert ap.active_scope(store, user="a@h.org") == {"1.4.3": frozenset({"docx"})}
