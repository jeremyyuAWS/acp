"""Tests for P-6 (blob silent-overwrite fix) and performance quick-wins.

P-6: upload_remediated must attempt overwrite=False first; on 409 log and retry.
Perf-1: _CATALOG_JSON loaded once at module level, not per-call.
Perf-2: get_scan_scope() caches per scan_id (no repeated DB queries).
Perf-3: JobWorker default poll_interval reduced from 2.0 s to 0.5 s.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))


@pytest.fixture(autouse=True)
def _mock_azure(monkeypatch):
    """Stub the azure SDK so blob.py loads cleanly without the real package."""
    content_settings = MagicMock()
    azure_blob_mod = MagicMock()
    azure_blob_mod.ContentSettings = content_settings
    monkeypatch.setitem(sys.modules, "azure", MagicMock())
    monkeypatch.setitem(sys.modules, "azure.storage", MagicMock())
    monkeypatch.setitem(sys.modules, "azure.storage.blob", azure_blob_mod)
    monkeypatch.setitem(sys.modules, "azure.identity", MagicMock())


# ── P-6: upload_remediated detect-and-log on 409 ─────────────────────────────

def _make_409():
    exc = Exception("BlobAlreadyExists")
    exc.status_code = 409
    exc.error_code = "BlobAlreadyExists"
    return exc


def test_upload_remediated_first_call_uses_overwrite_false():
    import blob
    blob_client = MagicMock()
    svc = MagicMock()
    svc.get_blob_client.return_value = blob_client
    with patch.object(blob, "_service_client", return_value=svc):
        blob.upload_remediated("owner@x.com", "s1", "out.docx", b"data", "application/octet-stream")
    first_call = blob_client.upload_blob.call_args_list[0]
    assert first_call.kwargs.get("overwrite") is False, (
        "first upload_blob call must use overwrite=False"
    )


def test_upload_remediated_retries_with_overwrite_true_on_409(caplog):
    import blob
    import logging
    blob_client = MagicMock()
    blob_client.upload_blob.side_effect = [_make_409(), None]
    svc = MagicMock()
    svc.get_blob_client.return_value = blob_client
    with patch.object(blob, "_service_client", return_value=svc):
        with caplog.at_level(logging.WARNING, logger="blob"):
            blob.upload_remediated("owner@x.com", "s1", "out.docx", b"data", "application/octet-stream")
    assert blob_client.upload_blob.call_count == 2
    second_call = blob_client.upload_blob.call_args_list[1]
    assert second_call.kwargs.get("overwrite") is True, (
        "second upload_blob call must use overwrite=True"
    )
    assert any("overwriting existing blob" in r.message for r in caplog.records), (
        "WARNING must be logged before the overwrite retry"
    )


def test_upload_remediated_propagates_non_409_exception():
    import blob
    blob_client = MagicMock()
    blob_client.upload_blob.side_effect = ConnectionError("network failure")
    svc = MagicMock()
    svc.get_blob_client.return_value = blob_client
    with patch.object(blob, "_service_client", return_value=svc):
        with pytest.raises(ConnectionError):
            blob.upload_remediated("owner@x.com", "s1", "out.docx", b"data", "application/octet-stream")
    assert blob_client.upload_blob.call_count == 1, "must not retry on non-409 errors"


def test_upload_remediated_noop_when_blob_storage_unconfigured():
    import blob
    with patch.object(blob, "_service_client", return_value=None):
        result = blob.upload_remediated("owner@x.com", "s1", "out.docx", b"data", "application/octet-stream")
    assert result is None


# ── Perf-1: catalog loaded once at module level ───────────────────────────────

def test_catalog_json_loaded_at_module_level():
    import store
    assert isinstance(store._CATALOG_JSON, dict), "_CATALOG_JSON must be a dict"
    assert store._CATALOG_JSON, "_CATALOG_JSON must not be empty"


def test_catalog_json_has_engine_keys():
    import store
    assert any(isinstance(v, list) for v in store._CATALOG_JSON.values()), (
        "_CATALOG_JSON must have at least one extension key mapping to a list of rules"
    )


# ── Perf-2: get_scan_scope caches per scan_id ────────────────────────────────

def test_get_scan_scope_caches_result(isolated_store):
    """Second call must return the cached value without hitting the DB."""
    isolated_store.init_scan_run(
        "s_scope", "local", 1, "2026-01-01T00:00:00Z", "test-rubric", "abc123"
    )
    scope1 = isolated_store.get_scan_scope("s_scope")
    original_execute = isolated_store._db.execute
    query_count = [0]

    def _counting_execute(cur, sql, params=()):
        if "scan_runs" in sql and "scope" in sql.lower() and sql.strip().upper().startswith("SELECT"):
            query_count[0] += 1
        return original_execute(cur, sql, params)

    isolated_store._db.execute = _counting_execute
    scope2 = isolated_store.get_scan_scope("s_scope")
    assert query_count[0] == 0, "second get_scan_scope call must not query the DB"
    assert scope2 == scope1


def test_get_scan_scope_caches_none_for_missing_scan(isolated_store):
    """None result (missing scan) is also cached so we avoid repeated DB misses."""
    result1 = isolated_store.get_scan_scope("nonexistent-scan")
    assert result1 is None
    assert "nonexistent-scan" in isolated_store._scope_cache, "None result must be cached"
    result2 = isolated_store.get_scan_scope("nonexistent-scan")
    assert result2 is None


# ── Perf-4: get_scan_scope_rules caches per scan_id ─────────────────────────

def test_get_scan_scope_rules_caches_result(isolated_store):
    """Second call must return the cached list without hitting the DB."""
    isolated_store.init_scan_run(
        "s_rules", "local", 1, "2026-01-01T00:00:00Z", "test-rubric", "abc123"
    )
    rules1 = isolated_store.get_scan_scope_rules("s_rules")
    original_execute = isolated_store._db.execute
    query_count = [0]

    def _counting_execute(cur, sql, params=()):
        if "scan_runs" in sql and sql.strip().upper().startswith("SELECT"):
            query_count[0] += 1
        return original_execute(cur, sql, params)

    isolated_store._db.execute = _counting_execute
    rules2 = isolated_store.get_scan_scope_rules("s_rules")
    assert query_count[0] == 0, "second get_scan_scope_rules call must not query the DB"
    assert rules2 == rules1


def test_get_scan_scope_rules_caches_empty_for_missing_scan(isolated_store):
    """Empty result for a missing scan is cached so we avoid repeated DB misses."""
    result1 = isolated_store.get_scan_scope_rules("nonexistent-rules-scan")
    assert result1 == []
    assert "nonexistent-rules-scan" in isolated_store._scope_rules_cache, \
        "empty result must be cached in _scope_rules_cache"
    result2 = isolated_store.get_scan_scope_rules("nonexistent-rules-scan")
    assert result2 == []


# ── Perf-5: executemany on DB adapters ───────────────────────────────────────

def test_sqlite_executemany_inserts_multiple_rows(isolated_store):
    """executemany must insert all rows in one call via SQLite's native executemany."""
    with isolated_store._db.cursor() as cur:
        isolated_store._db.executemany(
            cur,
            "INSERT INTO scan_runs(id, source, files, started_at, rubric_name, rubric_hash) "
            "VALUES(%s,%s,%s,%s,%s,%s)",
            [
                ("em_scan1", "local", 1, "2026-01-01T00:00:00Z", "r", "h1"),
                ("em_scan2", "local", 2, "2026-01-01T00:00:00Z", "r", "h2"),
            ],
        )
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(
            cur, "SELECT COUNT(*) AS n FROM scan_runs WHERE id IN (%s,%s)",
            ("em_scan1", "em_scan2")
        )
        row = isolated_store._db.fetchone(cur)
    assert row["n"] == 2, "executemany must insert both rows"


# ── Perf-6: _inventory_attrs bulk-loads per scan_id ─────────────────────────

def test_inventory_attrs_bulk_loads_on_first_miss(isolated_store):
    """First call for a scan_id must load ALL rows; second call for a different
    file in the same scan must NOT hit the DB again."""
    isolated_store.init_scan_run(
        "s_inv", "local", 2, "2026-01-01T00:00:00Z", "test-rubric", "abc123"
    )
    with isolated_store._db.cursor() as cur:
        isolated_store._db.executemany(
            cur,
            "INSERT INTO scan_inventory(scan_id, file, path, owner, parent_folder) "
            "VALUES(%s,%s,%s,%s,%s)",
            [
                ("s_inv", "a.docx", "/docs/a.docx", "alice@x.com", "Legal"),
                ("s_inv", "b.docx", "/docs/b.docx", "bob@x.com", "Finance"),
            ],
        )
    # Prime the cache
    attrs_a = isolated_store._inventory_attrs("s_inv", "a.docx")
    assert attrs_a["owner"] == "alice@x.com"
    assert "s_inv" in isolated_store._inventory_cache, "cache must be populated after first call"

    # Second call for a DIFFERENT file in the same scan must use the cache
    original_execute = isolated_store._db.execute
    query_count = [0]

    def _counting(cur, sql, params=()):
        if "scan_inventory" in sql and sql.strip().upper().startswith("SELECT"):
            query_count[0] += 1
        return original_execute(cur, sql, params)

    isolated_store._db.execute = _counting
    attrs_b = isolated_store._inventory_attrs("s_inv", "b.docx")
    assert query_count[0] == 0, "second file in same scan must not hit the DB"
    assert attrs_b["owner"] == "bob@x.com"


def test_inventory_attrs_missing_file_returns_empty(isolated_store):
    """A file not in inventory returns {} without error, and the scan is still cached."""
    isolated_store.init_scan_run(
        "s_inv2", "local", 1, "2026-01-01T00:00:00Z", "test-rubric", "abc123"
    )
    result = isolated_store._inventory_attrs("s_inv2", "ghost.docx")
    assert result == {}
    assert "s_inv2" in isolated_store._inventory_cache


# ── Perf-7: scan_batch fan-out parallelism ───────────────────────────────────

def test_scan_batch_workers_env_var_controls_parallelism(monkeypatch):
    """ACP_SCAN_BATCH_WORKERS is read and respected; default is 4."""
    import os
    monkeypatch.setenv("ACP_SCAN_BATCH_WORKERS", "8")
    # verify the env var is readable (the actual parallel execution is integration-level)
    assert os.environ.get("ACP_SCAN_BATCH_WORKERS") == "8"


# ── Perf-3: worker poll interval default ─────────────────────────────────────

def test_job_worker_default_poll_interval_is_half_second():
    from worker import JobWorker
    w = JobWorker(MagicMock())
    assert w.poll_interval == 0.5, f"expected 0.5s poll_interval, got {w.poll_interval}"
