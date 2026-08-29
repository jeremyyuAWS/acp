"""Wiring: handlers._scan_discover threads core._interactive_sp_sync_plan's result into
scanner._list's sp_delta= for the right requests, and only those — the SharePoint mirror of
test_interactive_drive_sync_wiring.py.

core._interactive_sp_sync_plan itself (the gate's own decision logic — no skip, per-(user,drive)
cursor, the drive-mismatch baseline check) is unit-tested in tests/test_interactive_sp_sync.py;
scanner._sp_whole_library_target's own eligibility rules are unit-tested in
tests/test_sp_whole_library_target.py. This file is about the CALLER wiring the two together —
which real scan requests are even eligible to reach the gate. Hermetic: scanner._list and
core._interactive_sp_sync_plan are both replaced with spies, so no real Graph access.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "alice@x.com"
DRIVE = "drv-1"
_SENTINEL_DELTA = {"prior_files": [], "changed": [], "removed_ids": set()}


def _wire(monkeypatch, st, *, plan_result=_SENTINEL_DELTA):
    import core
    import handlers
    import scanner

    monkeypatch.setattr(core, "store", st)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")
    monkeypatch.setattr(scanner, "_scope_for_listing", lambda user=None: None)
    # Not under test here: _fake_list below returns no items, which would otherwise trip
    # _scan_discover's "0 files — is the source actually reachable?" guard.
    monkeypatch.setattr(handlers, "_roots_reachable", lambda *a, **kw: (True, None))

    list_calls: list[dict] = []

    def _fake_list(*a, **kw):
        list_calls.append(kw)
        return [{"name": "a.pdf", "id": "F1", "sp": True, "source_mime": "application/pdf",
                "size_kb": 1, "checksum": "c1", "created_at": None, "source_modified": None,
                "owner": None, "parent_folder": None}]

    monkeypatch.setattr(scanner, "_list", _fake_list)

    plan_calls: list[tuple] = []

    def _fake_plan(owner, token, drive_id):
        plan_calls.append((owner, token, drive_id))
        return plan_result

    monkeypatch.setattr(core, "_interactive_sp_sync_plan", _fake_plan)
    return list_calls, plan_calls


def _discover(scan_id, **payload_over):
    import handlers
    payload = {"scan_id": scan_id, "source": "sharepoint", "user": OWNER,
              "sp_token": "alice-sp-token", "ai": False}
    payload.update(payload_over)
    handlers._scan_discover(payload, {"scan_id": scan_id})


def test_a_bare_onedrive_scan_consults_the_gate_and_threads_its_result_into_list(
        isolated_store, monkeypatch):
    list_calls, plan_calls = _wire(monkeypatch, isolated_store)
    _discover("s-onedrive-1")
    assert plan_calls == [(OWNER, "alice-sp-token", None)]
    assert list_calls[-1]["sp_delta"] is _SENTINEL_DELTA


def test_a_whole_library_scan_consults_the_gate_with_its_drive_id(isolated_store, monkeypatch):
    list_calls, plan_calls = _wire(monkeypatch, isolated_store)
    _discover("s-library-1", folder=f"{DRIVE}/root")
    assert plan_calls == [(OWNER, "alice-sp-token", DRIVE)]
    assert list_calls[-1]["sp_delta"] is _SENTINEL_DELTA


def test_a_site_scoped_scan_never_consults_the_gate(isolated_store, monkeypatch):
    """A bare site id walks every library on the site — no single drive to scope a delta to."""
    list_calls, plan_calls = _wire(monkeypatch, isolated_store)
    _discover("s-site-1", folder="contoso.sharepoint.com,g1,g2")
    assert plan_calls == []
    assert list_calls[-1]["sp_delta"] is None


def test_a_sub_folder_scan_never_consults_the_gate(isolated_store, monkeypatch):
    list_calls, plan_calls = _wire(monkeypatch, isolated_store)
    _discover("s-folder-1", folder=f"{DRIVE}/item123")
    assert plan_calls == []
    assert list_calls[-1]["sp_delta"] is None


def test_a_multi_location_scan_never_consults_the_gate(isolated_store, monkeypatch):
    list_calls, plan_calls = _wire(monkeypatch, isolated_store)
    _discover("s-multi-1", folders=[f"{DRIVE}/root", "drv-2/root"])
    assert plan_calls == []
    assert list_calls[-1]["sp_delta"] is None


def test_a_non_sharepoint_source_never_consults_the_sharepoint_gate(isolated_store, monkeypatch):
    list_calls, plan_calls = _wire(monkeypatch, isolated_store)
    handlers_payload = {"scan_id": "s-local-1", "source": "local", "user": OWNER, "ai": False}
    import handlers
    handlers._scan_discover(handlers_payload, {"scan_id": "s-local-1"})
    assert plan_calls == []


def test_incremental_false_still_reaches_the_gate(isolated_store, monkeypatch):
    """incremental=false is the UI's actual default (App.jsx's ADR 0011 reuse toggle, off since
    2026-08-19 — a real scan request never sends true). Discovery-level delta sync has no
    ADR-0011-style invisible-skip risk (every reconstructed file still gets a fresh analysis, and
    the baseline itself is drive-scoped and verified — core._sp_prior_inventory_for_drive), so it
    must not be gated on that flag — a prior version tied the two together and made this feature
    unreachable from the shipped app."""
    list_calls, plan_calls = _wire(monkeypatch, isolated_store)
    _discover("s-noinc-1", incremental=False)
    assert plan_calls == [(OWNER, "alice-sp-token", None)]
    assert list_calls[-1]["sp_delta"] is _SENTINEL_DELTA


def test_no_sp_token_never_consults_the_gate(isolated_store, monkeypatch):
    """The dedicated sync app's token is never substituted for an interactive user's own —
    without a real per-request token there is nothing this gate can authenticate with."""
    list_calls, plan_calls = _wire(monkeypatch, isolated_store)
    _discover("s-notoken-1", sp_token=None)
    assert plan_calls == []


def test_the_gates_own_none_falls_through_to_a_full_listing(isolated_store, monkeypatch):
    list_calls, plan_calls = _wire(monkeypatch, isolated_store, plan_result=None)
    _discover("s-none-1")
    assert plan_calls == [(OWNER, "alice-sp-token", None)]
    assert list_calls[-1]["sp_delta"] is None
