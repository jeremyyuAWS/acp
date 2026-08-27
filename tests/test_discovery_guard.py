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


class TestSuspiciousZeroBaseline:
    """The baseline the suspicious-zero guard compares against, across a retry.

    The guard (handlers._scan_discover) fails a scan whose listing returned 0 when a prior scan of
    the same source found files, and releases the discovery slot so the run can be retried. The
    retry is exactly where the choice of baseline decides whether the guard still works — see
    Store.last_nonempty_run_for_source.
    """

    def _run(self, store, scan_id, at, *, files=0, status="discovered",
             source="drive", user="owner@example.com"):
        store.init_scan_run(scan_id, source, 0, at, "rb", "hash", owner=user, status=status)
        if files:
            store.add_inventory(scan_id, [{"file": f"f{i}.pdf"} for i in range(files)])

    def test_skips_the_failed_zero_run_a_retry_would_otherwise_land_on(self, store):
        # A: real inventory. B: the zero this guard already failed. C: the retry it invited.
        self._run(store, "A", "2026-01-01T00:00:00", files=3)
        self._run(store, "B", "2026-01-02T00:00:00", files=0, status="failed")
        self._run(store, "C", "2026-01-03T00:00:00", files=0, status="running")

        # What the guard used to ask, and why it went quiet on the retry: B IS the prior run, and
        # it carries no inventory, so "did this source have files last time?" answered no.
        assert store.previous_run_for_source("C", owner="owner@example.com") == "B"
        assert store.count_inventory("B") == 0

        # What it asks now.
        base = store.last_nonempty_run_for_source("C", owner="owner@example.com")
        assert base == "A", "retry must compare against the last run that found files"
        assert store.count_inventory(base) == 3

    def test_idempotent_across_many_failed_retries(self, store):
        self._run(store, "A", "2026-01-01T00:00:00", files=3)
        for i in range(5):
            self._run(store, f"F{i}", f"2026-01-1{i}T00:00:00", files=0, status="failed")
        self._run(store, "LAST", "2026-01-20T00:00:00", files=0, status="running")
        assert store.last_nonempty_run_for_source("LAST", owner="owner@example.com") == "A"

    def test_none_for_a_genuinely_new_source(self, store):
        # No prior run at all: a first scan returning 0 is not suspicious, it is just empty. The
        # guard must stay silent here or every new connector's first scan fails.
        self._run(store, "ONLY", "2026-01-01T00:00:00", files=0, status="running")
        assert store.last_nonempty_run_for_source("ONLY", owner="owner@example.com") is None

    def test_a_genuinely_empty_source_is_not_a_first_scan(self, store):
        """Why _scan_discover keeps BOTH lookups instead of swapping one for the other.

        The suspicious-zero block answers two questions off what looks like one fact. "Has this
        source ever been scanned?" gates the first-scan retry (#858) — any prior run answers it.
        "Did it ever prove it had files?" is the guard baseline — only a run with inventory does.

        A genuinely empty source is where they diverge: it HAS prior runs, and none has inventory.
        Answering the retry gate with the non-empty lookup would call it a first scan forever and
        re-list it after a 5s sleep on every scan, for as long as the source stays empty.
        """
        self._run(store, "EMPTY1", "2026-01-01T00:00:00", files=0)
        self._run(store, "EMPTY2", "2026-01-02T00:00:00", files=0)
        self._run(store, "NOW", "2026-01-03T00:00:00", files=0, status="running")
        owner = "owner@example.com"
        # Not a first scan — the retry gate must see a prior run and stay quiet.
        assert store.previous_run_for_source("NOW", owner=owner) == "EMPTY2"
        # And no baseline to refuse against — the guard must stay quiet too.
        assert store.last_nonempty_run_for_source("NOW", owner=owner) is None

    def test_does_not_cross_sources(self, store):
        self._run(store, "D", "2026-01-01T00:00:00", files=3, source="drive")
        self._run(store, "S", "2026-01-02T00:00:00", files=0, source="sharepoint")
        assert store.last_nonempty_run_for_source("S", owner="owner@example.com") is None

    def test_does_not_cross_owners(self, store):
        self._run(store, "MINE", "2026-01-01T00:00:00", files=3, user="alice@a.com")
        self._run(store, "THEIRS", "2026-01-02T00:00:00", files=0, user="bob@a.com")
        assert store.last_nonempty_run_for_source("THEIRS", owner="bob@a.com") is None

    def test_ignores_superseded_even_when_it_has_inventory(self, store):
        # Same exclusion previous_run_for_source makes: a superseded run barely started before
        # this one replaced it, so its inventory is not evidence about the estate.
        self._run(store, "A", "2026-01-01T00:00:00", files=3)
        self._run(store, "SUP", "2026-01-02T00:00:00", files=9, status="superseded")
        self._run(store, "C", "2026-01-03T00:00:00", files=0, status="running")
        assert store.last_nonempty_run_for_source("C", owner="owner@example.com") == "A"

    def _run_with_file_records(self, store, scan_id, at, *, files=0,
                                source="drive", user="owner@example.com"):
        """Simulate a pre-ADR-0020 scan: rows in file_records, NOT scan_inventory."""
        store.init_scan_run(scan_id, source, 0, at, "rb", "hash", owner=user, status="completed")
        if files:
            with store._db.cursor() as cur:
                for i in range(files):
                    store._db.execute(cur,
                        "INSERT INTO file_records(scan_id,file,engine,status,score,compliant,"
                        "skipped_rules,drive_file_id,acp_stamped,checksum,size_kb,pages,sheets,"
                        "source_modified) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (scan_id, f"file{i}.pdf", "pdfminer", "pass", 1.0, 1,
                         "[]", None, None, None, None, None, None, None))

    def test_pre_adr0020_file_records_baseline_is_found(self, store):
        """Pre-ADR-0020 scans stored files in file_records, not scan_inventory.

        last_nonempty_run_for_source must find them so the suspicious-zero guard
        does not go silent when the only prior successful scan predates the inventory table.
        """
        self._run_with_file_records(store, "OLD", "2026-01-01T00:00:00", files=5)
        self._run(store, "NOW", "2026-01-03T00:00:00", files=0, status="running")

        base = store.last_nonempty_run_for_source("NOW", owner="owner@example.com")
        assert base == "OLD", (
            "guard baseline must reach pre-ADR-0020 scans whose files are in file_records"
        )
        # count_inventory must also return the file_records count so the guard message is accurate.
        assert store.count_inventory("OLD") == 5

    def test_count_inventory_falls_back_to_file_records(self, store):
        """count_inventory returns file_records count when scan_inventory is empty."""
        self._run_with_file_records(store, "OLD", "2026-01-01T00:00:00", files=7)
        assert store.count_inventory("OLD") == 7
