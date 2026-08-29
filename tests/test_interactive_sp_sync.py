"""PRD Phase 3, interactive scans — core._interactive_sp_sync_plan.

Brings the delta-sync mechanism built for the scheduled sweep (core._sp_sync_plan, #961/#963/
#979) to a user-initiated SharePoint scan, mirroring core._interactive_drive_sync_plan (#978).
Three things make this genuinely different from BOTH the sweep and the Drive interactive plan:

  1. NO SKIP, same as Drive's interactive plan — an interactive user is owed a completed scan
     every time, so "nothing changed" still returns an sp_delta (an empty one), never a signal
     to do nothing.
  2. PER (USER, DRIVE) CURSOR, not just per-user. Drive's interactive plan only needed
     f"drive:{owner}" because a user has exactly one Drive, always the same. A SharePoint user
     can interactively scan a DIFFERENT library — or their own OneDrive — from one scan to the
     next, so the cursor is keyed f"sharepoint:{owner}:{drive_id}".
  3. THE PRIOR-SCAN BASELINE IS ALSO VERIFIED PER DRIVE (_sp_prior_inventory_for_drive), not just
     looked up by owner. store.latest_scan_inventory_items has no drive-scoped query of its
     own — it returns whatever the most recent 'sharepoint'-source scan for this owner covered,
     which could be a DIFFERENT library than the one being checked now. Reconstructing library
     B from library A's inventory would silently show the wrong estate, so this is a real
     correctness gap Drive's interactive plan never had (one account, one drive) and even the
     scheduled sweep never actually exercises (always the same configured drive) — caught here
     specifically because an interactive user's SharePoint target can vary.

Hermetic: no real Graph access. scanner.sp_delta_since is monkeypatched, and a minimal store
double stands in for get_sync_cursor/save_sync_cursor/latest_scan_inventory_items.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

DRIVE_A = "drv-a"
DRIVE_B = "drv-b"


def _row(item_id, name, *, drive_id=DRIVE_A, checksum="x"):
    return {"file": name, "drive_file_id": item_id, "mime": "application/pdf", "size_kb": 1,
           "checksum": checksum, "created_at": None, "source_modified": None, "owner": None,
           "parent_folder": None, "drive_id": drive_id}


@pytest.fixture()
def core_mod(monkeypatch):
    import core
    import scanner

    class _Store:
        def __init__(self):
            self.sync_cursors: dict = {}        # cursor_key -> {"page_token": ...}
            self.prior_inventory: dict = {}      # owner -> list[row] (with drive_id), or absent

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
    monkeypatch.setattr(scanner, "sp_delta_since", lambda token, drive_id, link: ([], set(), "next-link"))
    return core, store


def test_first_ever_interactive_scan_has_nothing_to_reconstruct_and_seeds_a_cursor(core_mod):
    core, store = core_mod
    result = core._interactive_sp_sync_plan("alice@x.com", "alice-token", DRIVE_A)
    assert result is None, "no cursor yet — nothing to reconstruct from, fall back to a full listing"
    assert store.sync_cursors[f"sharepoint:alice@x.com:{DRIVE_A}"]["page_token"] == "next-link"


def test_no_changes_still_returns_a_delta_never_a_skip(core_mod, monkeypatch):
    import scanner
    core, store = core_mod
    store.sync_cursors[f"sharepoint:alice@x.com:{DRIVE_A}"] = {"page_token": "tok-1"}
    store.prior_inventory["alice@x.com"] = [_row("F0", "unchanged.pdf")]
    monkeypatch.setattr(scanner, "sp_delta_since", lambda token, drive_id, link: ([], set(), "tok-2"))

    result = core._interactive_sp_sync_plan("alice@x.com", "alice-token", DRIVE_A)
    assert result is not None, "an interactive scan must never be told to do nothing"
    assert result["changed"] == [] and result["removed_ids"] == set()
    assert [f["id"] for f in result["prior_files"]] == ["F0"]
    assert store.sync_cursors[f"sharepoint:alice@x.com:{DRIVE_A}"]["page_token"] == "tok-2"


def test_real_changes_are_reconstructed(core_mod, monkeypatch):
    import scanner
    core, store = core_mod
    store.sync_cursors[f"sharepoint:alice@x.com:{DRIVE_A}"] = {"page_token": "tok-1"}
    store.prior_inventory["alice@x.com"] = [_row("F0", "unchanged.pdf")]
    changed_file = {"id": "F1", "name": "changed.pdf", "parentReference": {"driveId": DRIVE_A}}
    monkeypatch.setattr(scanner, "sp_delta_since",
                        lambda token, drive_id, link: ([changed_file], {(DRIVE_A, "F9")}, "tok-2"))

    result = core._interactive_sp_sync_plan("alice@x.com", "alice-token", DRIVE_A)
    assert result["changed"] == [changed_file]
    assert result["removed_ids"] == {(DRIVE_A, "F9")}


def test_a_cursor_with_no_prior_scan_at_all_falls_back_to_a_full_listing(core_mod, monkeypatch):
    import scanner
    core, store = core_mod
    store.sync_cursors[f"sharepoint:alice@x.com:{DRIVE_A}"] = {"page_token": "tok-1"}
    # No entry in store.prior_inventory for alice at all.
    monkeypatch.setattr(scanner, "sp_delta_since", lambda token, drive_id, link: ([], set(), "tok-2"))
    result = core._interactive_sp_sync_plan("alice@x.com", "alice-token", DRIVE_A)
    assert result is None


def test_a_prior_scan_of_a_different_drive_never_gets_used_as_the_baseline(core_mod, monkeypatch):
    """The real correctness gap this feature has that Drive's own interactive plan never did:
    the most recent completed SharePoint scan for this owner might be a DIFFERENT library. Using
    it anyway would silently reconstruct the wrong estate."""
    import scanner
    core, store = core_mod
    store.sync_cursors[f"sharepoint:alice@x.com:{DRIVE_A}"] = {"page_token": "tok-1"}
    # Alice's most recent completed scan was of DRIVE_B, not the DRIVE_A we're checking now.
    store.prior_inventory["alice@x.com"] = [_row("F0", "from-library-b.pdf", drive_id=DRIVE_B)]
    monkeypatch.setattr(scanner, "sp_delta_since",
                        lambda token, drive_id, link: ([{"id": "F1"}], set(), "tok-2"))
    result = core._interactive_sp_sync_plan("alice@x.com", "alice-token", DRIVE_A)
    assert result is None, "a different library's inventory must never be used as this drive's baseline"


def test_a_partial_drive_mismatch_also_refuses_the_whole_baseline(core_mod, monkeypatch):
    """Even if only SOME rows belong to a different drive (a corrupt/legacy record), the whole
    baseline is untrustworthy — never a partial reconstruction."""
    import scanner
    core, store = core_mod
    store.sync_cursors[f"sharepoint:alice@x.com:{DRIVE_A}"] = {"page_token": "tok-1"}
    store.prior_inventory["alice@x.com"] = [_row("F0", "ok.pdf", drive_id=DRIVE_A),
                                            _row("F1", "wrong-drive.pdf", drive_id=DRIVE_B)]
    monkeypatch.setattr(scanner, "sp_delta_since",
                        lambda token, drive_id, link: ([{"id": "F2"}], set(), "tok-2"))
    result = core._interactive_sp_sync_plan("alice@x.com", "alice-token", DRIVE_A)
    assert result is None


def test_onedrive_drive_id_none_is_its_own_valid_baseline(core_mod, monkeypatch):
    """A bare OneDrive scan uses drive_id=None — this must be treated as a real, matchable
    identity (the signed-in user's own drive), not as 'missing' or a wildcard."""
    import scanner
    core, store = core_mod
    store.sync_cursors["sharepoint:alice@x.com:None"] = {"page_token": "tok-1"}
    store.prior_inventory["alice@x.com"] = [_row("F0", "my-onedrive-file.pdf", drive_id=None)]
    monkeypatch.setattr(scanner, "sp_delta_since", lambda token, drive_id, link: ([], set(), "tok-2"))
    result = core._interactive_sp_sync_plan("alice@x.com", "alice-token", None)
    assert result is not None
    assert [f["id"] for f in result["prior_files"]] == ["F0"]


def test_a_failed_change_check_falls_back_to_a_full_listing(core_mod, monkeypatch):
    import scanner
    core, store = core_mod
    store.sync_cursors[f"sharepoint:alice@x.com:{DRIVE_A}"] = {"page_token": "tok-1"}
    store.prior_inventory["alice@x.com"] = [_row("F0", "unchanged.pdf")]

    def _boom(token, drive_id, link):
        raise RuntimeError("http 410")
    monkeypatch.setattr(scanner, "sp_delta_since", _boom)
    result = core._interactive_sp_sync_plan("alice@x.com", "alice-token", DRIVE_A)
    assert result is None


def test_two_different_drives_for_the_same_user_never_share_a_cursor(core_mod, monkeypatch):
    import scanner
    core, store = core_mod
    store.prior_inventory["alice@x.com"] = [_row("F0", "a.pdf", drive_id=DRIVE_A)]

    core._interactive_sp_sync_plan("alice@x.com", "tok", DRIVE_A)
    assert f"sharepoint:alice@x.com:{DRIVE_A}" in store.sync_cursors
    assert f"sharepoint:alice@x.com:{DRIVE_B}" not in store.sync_cursors

    result = core._interactive_sp_sync_plan("alice@x.com", "tok", DRIVE_B)
    assert result is None, "drive B has no cursor of its own yet — drive A's must not answer for it"


def test_two_different_users_never_share_a_cursor(core_mod, monkeypatch):
    import scanner
    core, store = core_mod
    store.prior_inventory["alice@x.com"] = [_row("F0", "a.pdf")]
    store.prior_inventory["bob@y.com"] = [_row("F0", "b.pdf")]

    core._interactive_sp_sync_plan("alice@x.com", "alice-tok", DRIVE_A)
    assert f"sharepoint:alice@x.com:{DRIVE_A}" in store.sync_cursors
    assert f"sharepoint:bob@y.com:{DRIVE_A}" not in store.sync_cursors


def test_the_scheduled_sweeps_own_cursor_is_a_completely_separate_key(core_mod, monkeypatch):
    import scanner
    import sp_sync
    core, store = core_mod
    monkeypatch.setattr(sp_sync, "sync_drive_id", lambda: DRIVE_A)
    core._sp_sync_plan(None, "app-token")
    assert "sharepoint" in store.sync_cursors

    core._interactive_sp_sync_plan("alice@x.com", "alice-tok", DRIVE_A)
    assert f"sharepoint:alice@x.com:{DRIVE_A}" in store.sync_cursors
    assert set(store.sync_cursors) == {"sharepoint", f"sharepoint:alice@x.com:{DRIVE_A}"}
