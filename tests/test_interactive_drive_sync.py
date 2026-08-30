"""PRD Phase 3, interactive scans — core._interactive_drive_sync_plan.

Brings the delta-sync mechanism built for the scheduled sweep (core._drive_sync_plan, #933/#951)
to a user-initiated Drive scan: reconstruct the estate from a stored per-user cursor + Drive's
Changes API instead of always walking the whole Drive. Three things make this genuinely
different from the sweep, not just a copy of it, and all three are pinned here:

  1. NO SKIP. The sweep's "nothing changed" means "do nothing" — nobody is watching a background
     sweep. An interactive scan is watched: the caller who clicked "scan" is owed a completed
     scan every time, so "nothing changed" here still returns a drive_delta (an empty one), never
     a signal to do nothing.
  2. PER-OWNER CURSOR. The sweep is one service-account identity with one shared cursor; an
     interactive scan can be any signed-in user, so two different users' Drive accounts must
     never share or clobber each other's delta position.
  3. REUSES THE CALLER'S OWN Drive SERVICE. Unlike the sweep (which has nothing built yet and
     builds its own ADC service), an interactive caller already built one from its own request's
     token before ever reaching this gate — building a second one here would be wasted work (and,
     in a caller that asserts _drive_service was called exactly once, a real regression, caught
     live while building this: see git history for why _drive_delta_check takes a `build_svc`
     callable rather than a token).
  4. THE PRIOR-SCAN BASELINE IS ALSO VERIFIED PER GOOGLE ACCOUNT
     (core._drive_prior_inventory_for_account), not just looked up by owner. A Drive token is a
     per-request browser OAuth credential, not a server-bound "connected account" — nothing
     stops the same signed-in ACP user presenting a DIFFERENT Google identity (a different
     account in the browser's Drive picker) from one interactive scan to the next.
     Reconstructing one account's estate from another's inventory would silently show the wrong
     documents, mirroring _sp_prior_inventory_for_drive's identical concern for SharePoint.

Hermetic: no real Drive access. scanner._drive_service/drive_account_id/drive_start_page_token/
drive_changes_since are monkeypatched, and a minimal store double stands in for
get_sync_cursor/save_sync_cursor/latest_scan_inventory_items.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

SVC_ALICE = object()
SVC_BOB = object()


@pytest.fixture()
def core_mod(monkeypatch):
    import core
    import scanner

    class _Store:
        def __init__(self):
            self.sync_cursors: dict = {}       # cursor_key -> {"page_token": ...}
            self.prior_inventory: dict = {}     # owner -> inventory rows, or absent = None

        def get_sync_cursor(self, cursor_key):
            return dict(self.sync_cursors[cursor_key]) if cursor_key in self.sync_cursors else None

        def save_sync_cursor(self, cursor_key, owner_email, page_token):
            self.sync_cursors[cursor_key] = {"cursor_key": cursor_key,
                                             "owner_email": owner_email,
                                             "page_token": page_token}

        def latest_scan_inventory_items(self, owner, source):
            return self.prior_inventory.get(owner)

    store = _Store()
    monkeypatch.setattr(core, "get_store", lambda: store)

    # Spy on scanner._drive_service — the scheduled sweep still calls it (ADC); an interactive
    # plan must NOT, since it is handed an already-built svc directly.
    calls = {"drive_service_calls": [], "changes_calls": []}

    def _fake_drive_service(token=None):
        calls["drive_service_calls"].append(token)
        return object()

    def _fake_drive_changes_since(svc, page_token):
        calls["changes_calls"].append(svc)
        return [], set(), "next-token"

    monkeypatch.setattr(scanner, "_drive_service", _fake_drive_service)
    monkeypatch.setattr(scanner, "drive_start_page_token", lambda svc: "seed-token")
    monkeypatch.setattr(scanner, "drive_changes_since", _fake_drive_changes_since)
    # Default: no account identity in play. PRIOR_ROW carries no drive_account_id either, so
    # existing tests below (none of which care about account matching) see a trivial match —
    # see test_a_prior_scan_by_a_different_google_account_never_gets_used_as_the_baseline etc.
    # for tests that override this.
    monkeypatch.setattr(scanner, "drive_account_id", lambda svc: None)
    return core, store, calls


PRIOR_ROW = {"file": "unchanged.pdf", "drive_file_id": "F0", "mime": "application/pdf",
            "size_kb": 1, "checksum": "x", "created_at": None, "source_modified": None,
            "owner": None, "parent_folder": None}


def test_first_ever_interactive_scan_has_nothing_to_reconstruct_and_seeds_a_cursor(core_mod):
    core, store, calls = core_mod
    result = core._interactive_drive_sync_plan("alice@x.com", SVC_ALICE)
    assert result is None, "no cursor yet — nothing to reconstruct from, fall back to a full listing"
    assert store.sync_cursors["drive:alice@x.com"]["page_token"] == "seed-token"
    assert calls["drive_service_calls"] == [], (
        "an interactive plan must reuse the caller's svc, never build its own")


def test_no_changes_still_returns_a_delta_never_a_skip(core_mod, monkeypatch):
    import scanner
    core, store, calls = core_mod
    store.sync_cursors["drive:alice@x.com"] = {"page_token": "tok-1"}
    store.prior_inventory["alice@x.com"] = [PRIOR_ROW]
    monkeypatch.setattr(scanner, "drive_changes_since", lambda svc, tok: ([], set(), "tok-2"))

    result = core._interactive_drive_sync_plan("alice@x.com", SVC_ALICE)
    assert result is not None, "an interactive scan must never be told to do nothing"
    assert result["changed"] == [] and result["removed_ids"] == set()
    assert [f["id"] for f in result["prior_files"]] == ["F0"]
    assert store.sync_cursors["drive:alice@x.com"]["page_token"] == "tok-2"


def test_real_changes_are_reconstructed(core_mod, monkeypatch):
    import scanner
    core, store, calls = core_mod
    store.sync_cursors["drive:alice@x.com"] = {"page_token": "tok-1"}
    store.prior_inventory["alice@x.com"] = [PRIOR_ROW]
    changed_file = {"id": "F1", "name": "changed.pdf", "mimeType": "application/pdf"}
    monkeypatch.setattr(scanner, "drive_changes_since",
                        lambda svc, tok: ([changed_file], {"F2"}, "tok-2"))

    result = core._interactive_drive_sync_plan("alice@x.com", SVC_ALICE)
    assert result["changed"] == [changed_file]
    assert result["removed_ids"] == {"F2"}


def test_a_cursor_with_no_prior_scan_falls_back_to_a_full_listing(core_mod, monkeypatch):
    import scanner
    core, store, calls = core_mod
    store.sync_cursors["drive:alice@x.com"] = {"page_token": "tok-1"}
    # No entry in store.prior_inventory for alice — every prior interactive scan since the
    # cursor was seeded failed before saving, or this is the account's first-ever whole-Drive
    # scan under this cursor.
    monkeypatch.setattr(scanner, "drive_changes_since", lambda svc, tok: ([], set(), "tok-2"))

    result = core._interactive_drive_sync_plan("alice@x.com", SVC_ALICE)
    assert result is None


def test_a_failed_change_check_falls_back_to_a_full_listing(core_mod, monkeypatch):
    import scanner
    core, store, calls = core_mod
    store.sync_cursors["drive:alice@x.com"] = {"page_token": "tok-1"}
    store.prior_inventory["alice@x.com"] = [PRIOR_ROW]

    def _boom(svc, tok):
        raise RuntimeError("HttpError 404 — expired page token")
    monkeypatch.setattr(scanner, "drive_changes_since", _boom)

    result = core._interactive_drive_sync_plan("alice@x.com", SVC_ALICE)
    assert result is None


class _FakePanic(BaseException):
    """Stands in for pyo3_runtime.PanicException — a broken native cryptography/_cffi_backend
    build surfaces as a BaseException subclass, deliberately NOT an Exception subclass, so
    `except Exception` would let it propagate uncaught. core._drive_delta_check's docstring
    justifies its wider `except BaseException` specifically for this case; this test is what
    makes that justification checked rather than asserted in a comment nobody re-verifies."""


def test_a_baseexception_from_the_change_check_still_falls_back_safely(core_mod, monkeypatch):
    import scanner
    core, store, calls = core_mod
    store.sync_cursors["drive:alice@x.com"] = {"page_token": "tok-1"}
    store.prior_inventory["alice@x.com"] = [PRIOR_ROW]

    def _panic(svc, tok):
        raise _FakePanic("Python API version mismatch")
    monkeypatch.setattr(scanner, "drive_changes_since", _panic)

    result = core._interactive_drive_sync_plan("alice@x.com", SVC_ALICE)
    assert result is None, (
        "a BaseException (not just Exception) from the change check must still degrade to a "
        "full listing, not propagate and crash the scan — plain `except Exception` would not "
        "catch this")


def test_two_different_users_never_share_or_clobber_each_others_cursor(core_mod, monkeypatch):
    import scanner
    core, store, calls = core_mod
    store.prior_inventory["alice@x.com"] = [PRIOR_ROW]
    store.prior_inventory["bob@y.com"] = [PRIOR_ROW]

    # Alice's first-ever check seeds HER cursor only.
    core._interactive_drive_sync_plan("alice@x.com", SVC_ALICE)
    assert "drive:alice@x.com" in store.sync_cursors
    assert "drive:bob@y.com" not in store.sync_cursors

    # Bob's first-ever check must ALSO see "no cursor yet" — Alice's seed must not leak to him.
    result = core._interactive_drive_sync_plan("bob@y.com", SVC_BOB)
    assert result is None, "bob has no cursor of his own yet — Alice's must not answer for him"

    # Both cursors now exist, independently. A real change-check now distinguishes them by svc.
    monkeypatch.setattr(scanner, "drive_changes_since",
                        lambda svc, tok: ([{"id": "ONLY_ALICES", "name": "a.pdf"}], set(), "a-2")
                        if svc is SVC_ALICE else ([], set(), "b-2"))
    alice_result = core._interactive_drive_sync_plan("alice@x.com", SVC_ALICE)
    assert alice_result["changed"] == [{"id": "ONLY_ALICES", "name": "a.pdf"}]
    # Bob's own cursor is untouched by Alice's check just now.
    assert store.sync_cursors["drive:bob@y.com"]["page_token"] == "seed-token"


def test_the_scheduled_sweeps_own_cursor_is_a_completely_separate_key(core_mod):
    """Sanity check on the shared _drive_delta_check helper: the sweep's fixed "drive" key and
    an interactive user's "drive:{owner}" key can never collide, however the owner is named."""
    core, store, calls = core_mod
    # A scheduled-sweep-style call (core._drive_sync_plan) uses cursor_key "drive" verbatim and
    # builds its OWN ADC service — never namespaced per owner, unlike the interactive plan.
    core._drive_sync_plan(None)
    assert "drive" in store.sync_cursors
    assert calls["drive_service_calls"] == [None], "the sweep must build its own ADC service"

    core._interactive_drive_sync_plan("alice@x.com", SVC_ALICE)
    assert "drive:alice@x.com" in store.sync_cursors
    assert set(store.sync_cursors) == {"drive", "drive:alice@x.com"}
    # The interactive call must still never have built its own service.
    assert calls["drive_service_calls"] == [None]


def test_a_prior_scan_by_a_different_google_account_never_gets_used_as_the_baseline(
        core_mod, monkeypatch):
    """The Drive mirror of SharePoint's drive-mismatch guard
    (test_interactive_sp_sync.py::test_a_prior_scan_of_a_different_drive_never_gets_used_as_the_baseline)
    — a Drive token is a per-request browser credential, so the same signed-in ACP user can sign
    into a DIFFERENT Google account in the browser's Drive picker from one scan to the next."""
    import scanner
    core, store, calls = core_mod
    store.sync_cursors["drive:alice@x.com"] = {"page_token": "tok-1"}
    store.prior_inventory["alice@x.com"] = [
        {**PRIOR_ROW, "drive_account_id": "alice.other@gmail.com"}]
    monkeypatch.setattr(scanner, "drive_changes_since",
                        lambda svc, tok: ([{"id": "F1"}], set(), "tok-2"))
    monkeypatch.setattr(scanner, "drive_account_id", lambda svc: "alice.work@gmail.com")

    result = core._interactive_drive_sync_plan("alice@x.com", SVC_ALICE)
    assert result is None, (
        "a different Google account's inventory must never be used as this account's baseline")


def test_a_partial_account_mismatch_also_refuses_the_whole_baseline(core_mod, monkeypatch):
    """Even if only SOME rows carry a different account (a corrupt/legacy record), the whole
    baseline is untrustworthy — never a partial reconstruction."""
    import scanner
    core, store, calls = core_mod
    store.sync_cursors["drive:alice@x.com"] = {"page_token": "tok-1"}
    store.prior_inventory["alice@x.com"] = [
        {**PRIOR_ROW, "drive_account_id": "alice.work@gmail.com"},
        {**PRIOR_ROW, "file": "other.pdf", "drive_file_id": "F9",
         "drive_account_id": "someone.else@gmail.com"}]
    monkeypatch.setattr(scanner, "drive_changes_since",
                        lambda svc, tok: ([{"id": "F1"}], set(), "tok-2"))
    monkeypatch.setattr(scanner, "drive_account_id", lambda svc: "alice.work@gmail.com")

    result = core._interactive_drive_sync_plan("alice@x.com", SVC_ALICE)
    assert result is None


def test_matching_account_id_uses_the_prior_scan_as_baseline(core_mod, monkeypatch):
    import scanner
    core, store, calls = core_mod
    store.sync_cursors["drive:alice@x.com"] = {"page_token": "tok-1"}
    store.prior_inventory["alice@x.com"] = [
        {**PRIOR_ROW, "drive_account_id": "alice.work@gmail.com"}]
    monkeypatch.setattr(scanner, "drive_changes_since", lambda svc, tok: ([], set(), "tok-2"))
    monkeypatch.setattr(scanner, "drive_account_id", lambda svc: "alice.work@gmail.com")

    result = core._interactive_drive_sync_plan("alice@x.com", SVC_ALICE)
    assert result is not None
    assert [f["id"] for f in result["prior_files"]] == ["F0"]


def test_an_unverifiable_current_identity_against_a_known_prior_one_is_a_mismatch(
        core_mod, monkeypatch):
    """scanner.drive_account_id's own best-effort failure mode returns None on any error — that
    must not be silently trusted against a prior scan whose account WAS recorded, or an
    identity check that can fail open is no check at all."""
    import scanner
    core, store, calls = core_mod
    store.sync_cursors["drive:alice@x.com"] = {"page_token": "tok-1"}
    store.prior_inventory["alice@x.com"] = [
        {**PRIOR_ROW, "drive_account_id": "alice.work@gmail.com"}]
    monkeypatch.setattr(scanner, "drive_changes_since",
                        lambda svc, tok: ([{"id": "F1"}], set(), "tok-2"))
    monkeypatch.setattr(scanner, "drive_account_id", lambda svc: None)

    result = core._interactive_drive_sync_plan("alice@x.com", SVC_ALICE)
    assert result is None
