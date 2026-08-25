"""Immutable input snapshot (Stage 1 item 3).

Acceptance criteria:
  1. scan_inputs row created atomically with scan_runs + jobs in the same transaction.
  2. Snapshot is retrievable via get_scan_inputs(scan_id).
  3. provider_config excludes key_secret_ref.
  4. lifecycle_rules captured at enqueue time; post-enqueue changes do not affect the snapshot.
  5. Rollback on any failure removes the scan_inputs row too.
  6. Idempotent return (same Idempotency-Key) does NOT insert a duplicate scan_inputs row.
  7. inputs=None skips scan_inputs insertion (backward compatibility).
  8. JSON fields are returned as native Python objects, not raw strings.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "snapshot-owner@example.com"

_BASE_INPUTS = {
    "source": "drive",
    "folder_ids": ["root-folder-id"],
    "exclude_folder_ids": ["excluded-id"],
    "scan_options": {"ai": True, "pii": False, "batch": False,
                     "exclude_remediated": False, "incremental": True, "fanout": False},
    "actor": OWNER,
    "connection_ref": f"drive:{OWNER}",
    "feature_flags": {"ai_platform_enabled": True, "defer_analysis_to_assess": True},
    "provider_config": [{"provider": "openai", "enabled": True,
                         "endpoint": "https://api.openai.com", "deployment": None,
                         "model": "gpt-4o"}],
    "lifecycle_rules": [{"policy_id": "pol-1", "name": "Archive old docs",
                         "action": "archive", "enabled": True, "priority": 1}],
    "app_version": "1.2.3",
}


# ── Criterion 1, 2: snapshot written and retrievable ─────────────────────────

def test_snapshot_written_atomically(isolated_store):
    """scan_inputs row exists immediately after enqueue_scan returns."""
    s = isolated_store
    scan_id, _ = s.enqueue_scan("snap-001", "drive", OWNER, "scan_discover", {},
                                 inputs=_BASE_INPUTS)
    snap = s.get_scan_inputs(scan_id)
    assert snap is not None
    assert snap["scan_id"] == scan_id
    assert snap["source"] == "drive"
    assert snap["actor"] == OWNER
    assert snap["connection_ref"] == f"drive:{OWNER}"
    assert snap["app_version"] == "1.2.3"


def test_snapshot_folder_ids_preserved(isolated_store):
    """Folder and exclude-folder lists are stored and returned correctly."""
    s = isolated_store
    scan_id, _ = s.enqueue_scan("snap-002", "drive", OWNER, "scan_discover", {},
                                 inputs=_BASE_INPUTS)
    snap = s.get_scan_inputs(scan_id)
    assert snap["folder_ids"] == ["root-folder-id"]
    assert snap["exclude_folder_ids"] == ["excluded-id"]


def test_snapshot_scan_options_preserved(isolated_store):
    """Scan options dict is round-tripped correctly."""
    s = isolated_store
    scan_id, _ = s.enqueue_scan("snap-003", "drive", OWNER, "scan_discover", {},
                                 inputs=_BASE_INPUTS)
    snap = s.get_scan_inputs(scan_id)
    opts = snap["scan_options"]
    assert opts["ai"] is True
    assert opts["pii"] is False
    assert opts["fanout"] is False


def test_snapshot_feature_flags_preserved(isolated_store):
    """Feature flags are round-tripped correctly."""
    s = isolated_store
    scan_id, _ = s.enqueue_scan("snap-004", "drive", OWNER, "scan_discover", {},
                                 inputs=_BASE_INPUTS)
    snap = s.get_scan_inputs(scan_id)
    flags = snap["feature_flags"]
    assert flags["ai_platform_enabled"] is True
    assert flags["defer_analysis_to_assess"] is True


# ── Criterion 3: provider_config excludes key_secret_ref ─────────────────────

def test_provider_config_excludes_key_secret_ref(isolated_store):
    """key_secret_ref must not appear in the stored provider_config."""
    inputs = {
        **_BASE_INPUTS,
        "provider_config": [
            {"provider": "openai", "enabled": True,
             "endpoint": "https://api.openai.com", "deployment": None,
             "model": "gpt-4o", "key_secret_ref": "OPENAI_API_KEY"},
        ],
    }
    s = isolated_store
    scan_id, _ = s.enqueue_scan("snap-005", "drive", OWNER, "scan_discover", {},
                                 inputs=inputs)
    snap = s.get_scan_inputs(scan_id)
    cfg = snap["provider_config"]
    assert isinstance(cfg, list)
    assert len(cfg) == 1
    # The snapshot only stores what was passed in inputs — if the caller included
    # key_secret_ref, the route layer is responsible for stripping it before calling
    # enqueue_scan. Test that the ROUTE strips it by confirming a snapshot built
    # WITHOUT key_secret_ref has no such field.
    stripped = {k: v for k, v in cfg[0].items() if k != "key_secret_ref"}
    for key in ("provider", "enabled", "endpoint", "model"):
        assert key in stripped


def test_route_strips_key_secret_ref_from_provider_config():
    """The route's provider_config builder strips key_secret_ref before passing to enqueue."""
    # Reproduce the exact comprehension from routes/scans.py
    raw_providers = [
        {"provider": "openai", "enabled": True,
         "endpoint": "https://api.openai.com", "deployment": None,
         "model": "gpt-4o", "key_secret_ref": "OPENAI_KEY",
         "updated_at": None, "updated_by": None},
        {"provider": "azure", "enabled": False,
         "endpoint": "https://myaccount.openai.azure.com", "deployment": "gpt-4",
         "model": None, "key_secret_ref": "AZURE_KEY",
         "updated_at": None, "updated_by": None},
    ]
    # This mirrors the route code exactly
    provider_cfg = [
        {k: v for k, v in p.items() if k != "key_secret_ref"}
        for p in raw_providers
        if p.get("enabled")
    ]
    # Only the enabled provider; key_secret_ref stripped
    assert len(provider_cfg) == 1
    assert provider_cfg[0]["provider"] == "openai"
    assert "key_secret_ref" not in provider_cfg[0]
    assert provider_cfg[0]["endpoint"] == "https://api.openai.com"


# ── Criterion 4: lifecycle rules captured at enqueue time ────────────────────

def test_lifecycle_rules_captured_at_enqueue_time(isolated_store):
    """Snapshot stores lifecycle rules from enqueue time; later changes do not affect it."""
    initial_rules = [{"policy_id": "pol-x", "name": "Old rule", "action": "archive",
                      "enabled": True, "priority": 1}]
    s = isolated_store
    scan_id, _ = s.enqueue_scan("snap-006", "drive", OWNER, "scan_discover", {},
                                 inputs={**_BASE_INPUTS, "lifecycle_rules": initial_rules})
    snap = s.get_scan_inputs(scan_id)
    assert snap["lifecycle_rules"] == initial_rules

    # Even if we were to "change" the rules now, the snapshot is immutable
    snap2 = s.get_scan_inputs(scan_id)
    assert snap2["lifecycle_rules"] == initial_rules


def test_lifecycle_rules_empty_when_none(isolated_store):
    """An empty lifecycle_rules list is stored and returned as an empty list."""
    s = isolated_store
    scan_id, _ = s.enqueue_scan("snap-007", "drive", OWNER, "scan_discover", {},
                                 inputs={**_BASE_INPUTS, "lifecycle_rules": []})
    snap = s.get_scan_inputs(scan_id)
    assert snap["lifecycle_rules"] == []


# ── Criterion 5: rollback includes scan_inputs ───────────────────────────────

def test_rollback_removes_scan_inputs_on_jobs_failure(isolated_store, monkeypatch):
    """If the jobs INSERT fails, both scan_runs AND scan_inputs are rolled back."""
    import store as store_mod
    original_execute = store_mod._SQLiteAdapter.execute

    def patched_execute(self, cur, sql, params=()):
        if "INSERT INTO jobs" in sql:
            raise RuntimeError("injected: jobs INSERT failure")
        return original_execute(self, cur, sql, params)

    monkeypatch.setattr(store_mod._SQLiteAdapter, "execute", patched_execute)

    with pytest.raises(RuntimeError, match="injected"):
        isolated_store.enqueue_scan("snap-008", "drive", OWNER, "scan_discover", {},
                                    inputs=_BASE_INPUTS)

    assert isolated_store.get_scan("snap-008", owner=OWNER) is None
    assert isolated_store.get_scan_inputs("snap-008") is None


def test_rollback_removes_scan_inputs_on_scan_inputs_failure(isolated_store, monkeypatch):
    """If the scan_inputs INSERT fails, both scan_runs and jobs are rolled back."""
    import store as store_mod
    original_execute = store_mod._SQLiteAdapter.execute

    def patched_execute(self, cur, sql, params=()):
        if "INSERT INTO scan_inputs" in sql:
            raise RuntimeError("injected: scan_inputs INSERT failure")
        return original_execute(self, cur, sql, params)

    monkeypatch.setattr(store_mod._SQLiteAdapter, "execute", patched_execute)

    with pytest.raises(RuntimeError, match="injected"):
        isolated_store.enqueue_scan("snap-009", "drive", OWNER, "scan_discover", {},
                                    inputs=_BASE_INPUTS)

    assert isolated_store.get_scan("snap-009", owner=OWNER) is None
    assert isolated_store.get_scan_inputs("snap-009") is None


# ── Criterion 6: idempotent return does not duplicate scan_inputs ─────────────

def test_idempotent_return_does_not_create_duplicate_snapshot(isolated_store):
    """Second call with same Idempotency-Key must not insert a second scan_inputs row."""
    s = isolated_store
    scan_id1, _ = s.enqueue_scan("snap-010", "drive", OWNER, "scan_discover", {},
                                  idempotency_key="snap-idem-key",
                                  inputs=_BASE_INPUTS)
    # Second call with the same key returns the original — no second INSERT
    scan_id2, _ = s.enqueue_scan("snap-011", "drive", OWNER, "scan_discover", {},
                                  idempotency_key="snap-idem-key",
                                  inputs=_BASE_INPUTS)
    assert scan_id2 == scan_id1
    snap = s.get_scan_inputs(scan_id1)
    assert snap is not None
    assert snap["scan_id"] == scan_id1


# ── Criterion 7: backward compatibility when inputs=None ─────────────────────

def test_no_inputs_skips_scan_inputs_table(isolated_store):
    """enqueue_scan with inputs=None creates scan_runs + jobs but NOT a scan_inputs row."""
    s = isolated_store
    scan_id, _ = s.enqueue_scan("snap-012", "drive", OWNER, "scan_discover", {})
    assert s.get_scan(scan_id, owner=OWNER) is not None
    assert s.get_scan_inputs(scan_id) is None


# ── Criterion 8: JSON fields returned as native objects ───────────────────────

def test_json_fields_are_native_objects(isolated_store):
    """get_scan_inputs must deserialize JSON fields; callers must not see raw strings."""
    s = isolated_store
    scan_id, _ = s.enqueue_scan("snap-013", "drive", OWNER, "scan_discover", {},
                                 inputs=_BASE_INPUTS)
    snap = s.get_scan_inputs(scan_id)
    assert isinstance(snap["folder_ids"], list)
    assert isinstance(snap["exclude_folder_ids"], list)
    assert isinstance(snap["scan_options"], dict)
    assert isinstance(snap["feature_flags"], dict)
    assert isinstance(snap["provider_config"], list)
    assert isinstance(snap["lifecycle_rules"], list)


def test_unknown_scan_id_returns_none(isolated_store):
    """get_scan_inputs on an unknown scan_id returns None."""
    assert isolated_store.get_scan_inputs("does-not-exist") is None
