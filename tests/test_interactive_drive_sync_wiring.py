"""Wiring: handlers._scan_discover threads core._interactive_drive_sync_plan's result into
scanner._list's drive_delta= for the right requests, and only those.

core._interactive_drive_sync_plan itself (the gate's own decision logic — no skip, per-owner
cursor) is unit-tested in tests/test_interactive_drive_sync.py; this file is about the CALLER —
which real scan requests are even eligible to reach it. Hermetic: scanner._list and
core._interactive_drive_sync_plan are both replaced with spies, so no real Drive access and no
dependence on the gate's own internals.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "alice@x.com"
_SENTINEL_DELTA = {"prior_files": [], "changed": [], "removed_ids": set()}


def _wire(monkeypatch, st, *, plan_result=_SENTINEL_DELTA):
    import core
    import handlers
    import scanner

    monkeypatch.setattr(core, "store", st)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")
    monkeypatch.setattr(scanner, "_drive_service", lambda tok: object())
    monkeypatch.setattr(scanner, "_scope_for_listing", lambda user=None: None)
    # Not under test here: _fake_list below returns no items, which would otherwise trip
    # _scan_discover's "0 files — is the source actually reachable?" guard against a dummy svc
    # that has none of the real Drive client's methods.
    monkeypatch.setattr(handlers, "_roots_reachable", lambda *a, **kw: (True, None))

    list_calls: list[dict] = []

    def _fake_list(*a, **kw):
        list_calls.append(kw)
        # A non-empty result — an empty one triggers _scan_discover's unrelated "suspicious
        # zero" retry-once-after-5s path, which calls _list a SECOND time with no drive_delta
        # kwarg at all, polluting list_calls[-1] with a call this test isn't about.
        return [{"name": "a.pdf", "id": "F1", "source_mime": "application/pdf", "size_kb": 1,
                "checksum": "c1", "created_at": None, "source_modified": None,
                "owner": None, "parent_folder": None}]

    monkeypatch.setattr(scanner, "_list", _fake_list)

    plan_calls: list[tuple] = []

    def _fake_plan(owner, svc):
        plan_calls.append((owner, svc))
        return plan_result

    monkeypatch.setattr(core, "_interactive_drive_sync_plan", _fake_plan)
    return list_calls, plan_calls


def _discover(scan_id, **payload_over):
    import handlers
    payload = {"scan_id": scan_id, "source": "drive", "user": OWNER,
              "drive_token": "alice-token", "ai": False}
    payload.update(payload_over)
    handlers._scan_discover(payload, {"scan_id": scan_id})


def test_a_whole_drive_scan_consults_the_gate_and_threads_its_result_into_list(
        isolated_store, monkeypatch):
    list_calls, plan_calls = _wire(monkeypatch, isolated_store)
    _discover("s-whole-1")
    assert len(plan_calls) == 1 and plan_calls[0][0] == OWNER
    assert list_calls[-1]["drive_delta"] is _SENTINEL_DELTA


def test_a_folder_scoped_scan_never_consults_the_gate(isolated_store, monkeypatch):
    list_calls, plan_calls = _wire(monkeypatch, isolated_store)
    _discover("s-folder-1", folder="1abc")
    assert plan_calls == [], "Drive's Changes API has no folder filter — must not gate a scoped scan"
    assert list_calls[-1]["drive_delta"] is None


def test_a_multi_folder_scan_never_consults_the_gate(isolated_store, monkeypatch):
    list_calls, plan_calls = _wire(monkeypatch, isolated_store)
    _discover("s-folders-1", folders=["1abc", "2def"])
    assert plan_calls == []
    assert list_calls[-1]["drive_delta"] is None


def test_a_non_drive_source_never_consults_the_gate(isolated_store, monkeypatch):
    list_calls, plan_calls = _wire(monkeypatch, isolated_store)
    handlers_payload = {"scan_id": "s-local-1", "source": "local", "user": OWNER, "ai": False}
    import handlers
    handlers._scan_discover(handlers_payload, {"scan_id": "s-local-1"})
    assert plan_calls == []


def test_incremental_false_opts_out_of_the_gate(isolated_store, monkeypatch):
    list_calls, plan_calls = _wire(monkeypatch, isolated_store)
    _discover("s-noinc-1", incremental=False)
    assert plan_calls == [], "incremental=false must also opt out of discovery-level delta sync"
    assert list_calls[-1]["drive_delta"] is None


def test_the_gates_own_none_falls_through_to_a_full_listing(isolated_store, monkeypatch):
    """When the gate itself has nothing to reconstruct from (its own tested behavior in
    test_interactive_drive_sync.py), the caller must still just proceed — no special handling,
    drive_delta stays None and _list does its normal full walk."""
    list_calls, plan_calls = _wire(monkeypatch, isolated_store, plan_result=None)
    _discover("s-none-1")
    assert len(plan_calls) == 1 and plan_calls[0][0] == OWNER
    assert list_calls[-1]["drive_delta"] is None
