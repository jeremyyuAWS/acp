"""Tests for active_discovery_guard and published_at snapshot stamp (resilience Phase 1)."""
import datetime
import sys
import tempfile
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture()
def store(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "guard_test.db")
    return store_mod.Store()


def _now():
    return datetime.datetime.utcnow().isoformat()


def _make_scan(store, scan_id, source="drive", user="owner@example.com"):
    store.init_scan_run(scan_id, source, 0, _now(), "rb", "hash", owner=user, status="running")


class TestActiveDiscoveryGuard:
    def test_first_claim_succeeds(self, store):
        holder = store.acquire_discovery_guard("user@a.com", "drive", "scan-1")
        assert holder is None

    def test_second_claim_blocked(self, store):
        store.acquire_discovery_guard("user@a.com", "drive", "scan-1")
        holder = store.acquire_discovery_guard("user@a.com", "drive", "scan-2")
        assert holder == "scan-1"

    def test_different_source_independent(self, store):
        store.acquire_discovery_guard("user@a.com", "drive", "scan-1")
        holder = store.acquire_discovery_guard("user@a.com", "sharepoint", "scan-3")
        assert holder is None

    def test_different_user_independent(self, store):
        store.acquire_discovery_guard("alice@a.com", "drive", "scan-1")
        holder = store.acquire_discovery_guard("bob@a.com", "drive", "scan-2")
        assert holder is None

    def test_release_allows_next_claim(self, store):
        store.acquire_discovery_guard("user@a.com", "drive", "scan-1")
        released = store.release_discovery_guard("scan-1")
        assert released

        holder = store.acquire_discovery_guard("user@a.com", "drive", "scan-2")
        assert holder is None

    def test_release_idempotent(self, store):
        store.acquire_discovery_guard("user@a.com", "drive", "scan-1")
        store.release_discovery_guard("scan-1")
        # Second release is a no-op, not an error
        store.release_discovery_guard("scan-1")

    def test_same_scan_idempotent_claim(self, store):
        store.acquire_discovery_guard("user@a.com", "drive", "scan-1")
        # Re-claiming the same scan_id returns None (not a conflict)
        holder = store.acquire_discovery_guard("user@a.com", "drive", "scan-1")
        assert holder is None


class TestMarkPublished:
    def test_stamps_published_at(self, store):
        _make_scan(store, "scan-x")
        ts = store.mark_published("scan-x")
        assert ts is not None

    def test_set_once(self, store):
        _make_scan(store, "scan-x")
        ts1 = store.mark_published("scan-x")
        ts2 = store.mark_published("scan-x", at="2099-01-01T00:00:00")
        assert ts1 == ts2

    def test_missing_scan_returns_none(self, store):
        result = store.mark_published("no-such-scan")
        assert result is None

    def test_independent_scans(self, store):
        _make_scan(store, "scan-a")
        _make_scan(store, "scan-b")
        store.mark_published("scan-a")
        assert store.mark_published("scan-b") is not None
