"""_scan_discover must not flip the durable scan status to "discovered" until everything a
reader might act on that signal for is already durably written: the per-file inventory
(scan_inventory rows) and the lifecycle-rule evaluation.

Found live 2026-08-28: the status flip used to happen right after listing, before
core.store.add_inventory() ever ran. Two independent readers key off exactly this status:

  1. The frontend's poll loop clears `busy` the instant status != "running" and renders
     DiscoverCompleteSummary — so a scan looked "Discovery complete" with 0 files while the
     inventory table was still empty, self-correcting once the save actually finished.
  2. POST /scans/{sid}/assess's deferred_pending check requires status == "discovered" AND
     count_inventory(sid) > 0 AND assess_params:{sid} is set. A client hitting /assess in the
     old window fell through to the wrong (immediate-model) branch instead of the deferred one.

These tests spy on the store calls that used to race the status flip and assert the flip has
not happened by the time they run — proving the new ordering, not just the end state (which
every existing test in this area already asserted and would pass either way).
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_status_is_not_discovered_until_inventory_is_saved(isolated_store, monkeypatch):
    import core
    import handlers
    import scanner
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

    items = [{"name": "a.docx", "id": "d1", "mime": _DOCX}]
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)

    scan_id = "sd-race-inventory"
    seen_status_at_save = []
    real_add_inventory = isolated_store.add_inventory

    def _spy_add_inventory(sid, inv):
        row = isolated_store.get_scan(sid, owner=None)
        seen_status_at_save.append((row or {}).get("run", {}).get("status"))
        return real_add_inventory(sid, inv)

    monkeypatch.setattr(isolated_store, "add_inventory", _spy_add_inventory)

    handlers._scan_discover(
        {"scan_id": scan_id, "source": "local", "user": None},
        {"scan_id": scan_id, "id": "j-race-inventory"},
    )

    assert seen_status_at_save, "add_inventory was never called — test setup is wrong"
    assert seen_status_at_save[0] != "discovered", (
        "status was already 'discovered' while the inventory was still being written — "
        f"a reader in this exact window would see a 'complete' scan with 0 rows: {seen_status_at_save}"
    )
    final = isolated_store.get_scan(scan_id, owner=None)
    assert final["run"]["status"] == "discovered"
    assert isolated_store.count_inventory(scan_id) > 0


def test_status_is_not_discovered_until_lifecycle_rules_have_run(isolated_store, monkeypatch):
    import core
    import handlers
    import scanner
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

    items = [{"name": "a.docx", "id": "d1", "mime": _DOCX}]
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)

    scan_id = "sd-race-lifecycle"
    seen_status_during_lifecycle = []
    real_eval = handlers._evaluate_discover_lifecycle_rules

    def _spy_eval(sid, *a, **k):
        row = isolated_store.get_scan(sid, owner=None)
        seen_status_during_lifecycle.append((row or {}).get("run", {}).get("status"))
        return real_eval(sid, *a, **k)

    monkeypatch.setattr(handlers, "_evaluate_discover_lifecycle_rules", _spy_eval)

    handlers._scan_discover(
        {"scan_id": scan_id, "source": "local", "user": None},
        {"scan_id": scan_id, "id": "j-race-lifecycle"},
    )

    assert seen_status_during_lifecycle, "_evaluate_discover_lifecycle_rules was never called"
    assert seen_status_during_lifecycle[0] != "discovered", (
        "status was already 'discovered' before lifecycle rules evaluated: "
        f"{seen_status_during_lifecycle}"
    )
    assert isolated_store.get_scan(scan_id, owner=None)["run"]["status"] == "discovered"


def test_assess_params_is_already_set_when_status_becomes_discovered(isolated_store, monkeypatch):
    """The three-way deferred_pending check in POST /scans/{sid}/assess (status=='discovered' AND
    count_inventory>0 AND assess_params:{sid} is set) must never observe status='discovered' with
    assess_params still unset — that combination is exactly what sent a real request down the
    wrong (immediate-model) branch. Spy on set_scan_status itself: by the moment it writes
    'discovered', assess_params must already be in the store."""
    import core
    import handlers
    import scanner
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

    items = [{"name": "a.docx", "id": "d1", "mime": _DOCX}]
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: items)

    scan_id = "sd-race-assess-params"
    seen_assess_params_at_flip = []
    real_set_scan_status = isolated_store.set_scan_status

    def _spy_set_scan_status(sid, status):
        if status == "discovered":
            seen_assess_params_at_flip.append(
                isolated_store.get_setting(f"assess_params:{sid}"))
        return real_set_scan_status(sid, status)

    monkeypatch.setattr(isolated_store, "set_scan_status", _spy_set_scan_status)

    handlers._scan_discover(
        {"scan_id": scan_id, "source": "local", "user": None},
        {"scan_id": scan_id, "id": "j-race-assess-params"},
    )

    assert seen_assess_params_at_flip, "set_scan_status('discovered') was never called"
    assert seen_assess_params_at_flip[0] is not None, (
        "assess_params:{sid} was NOT yet set at the moment status flipped to 'discovered' — "
        "a client calling POST /scans/{sid}/assess in this exact window would fail the "
        "deferred_pending check and fall through to the wrong (immediate-model) branch"
    )
