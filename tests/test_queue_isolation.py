"""Owner-email isolation and concurrent-queue invariants (ADR 0008, R11).

Verifies the store-layer properties that make multi-user Postgres concurrency
safe — the exact 3-users-scanning-their-own-Drives pilot scenario, exercised at
the unit level without a live staging estate.

Live stress-testing against a real endpoint is a separate step:
    python scripts/load_test_concurrency.py --url <staging-url> --users 3
"""
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))


def _insert_scan(store, scan_id: str, owner_email: str) -> None:
    """Insert a minimal completed scan_runs row, bypassing save_scan's full report."""
    with store._db.cursor() as cur:
        store._db.execute(
            cur,
            "INSERT INTO scan_runs(id,started_at,completed_at,source,rubric_name,rubric_hash,"
            "files,certifiable,uncertain,error,avg_score,status,files_done,owner_email) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (scan_id, "2026-01-01T00:00:00", "2026-01-01T00:01:00", "local",
             "test-rubric", "abc123", 0, 0, 0, 0, None, "done", 0, owner_email),
        )


# ── list_scans isolation ──────────────────────────────────────────────────────

def test_list_scans_returns_only_owner_scans(isolated_store):
    """User A's scans must not appear in User B's list_scans() result."""
    _insert_scan(isolated_store, "scan-a1", "alice@example.com")
    _insert_scan(isolated_store, "scan-a2", "alice@example.com")
    _insert_scan(isolated_store, "scan-b1", "bob@example.com")

    alice_ids = {s["id"] for s in isolated_store.list_scans("alice@example.com")}
    bob_ids = {s["id"] for s in isolated_store.list_scans("bob@example.com")}

    assert alice_ids == {"scan-a1", "scan-a2"}
    assert bob_ids == {"scan-b1"}
    assert alice_ids.isdisjoint(bob_ids), "isolation breach: a scan appeared in both users' lists"


def test_list_scans_no_owner_returns_all(isolated_store):
    """list_scans(owner=None) is the admin view — all completed scans, no owner filter."""
    _insert_scan(isolated_store, "scan-a", "alice@example.com")
    _insert_scan(isolated_store, "scan-b", "bob@example.com")

    all_ids = {s["id"] for s in isolated_store.list_scans(None)}
    assert {"scan-a", "scan-b"}.issubset(all_ids)


# ── get_scan isolation ────────────────────────────────────────────────────────

def test_get_scan_returns_none_for_wrong_owner(isolated_store):
    """A user must not be able to read another user's scan by guessing its ID."""
    _insert_scan(isolated_store, "scan-secret", "alice@example.com")

    assert isolated_store.get_scan("scan-secret", "alice@example.com") is not None
    assert isolated_store.get_scan("scan-secret", "bob@example.com") is None


# ── delete_scan isolation ─────────────────────────────────────────────────────

def test_delete_scan_wrong_owner_returns_none_and_leaves_row(isolated_store):
    """delete_scan by a non-owner must return None and leave the row intact."""
    _insert_scan(isolated_store, "scan-owned", "alice@example.com")

    result = isolated_store.delete_scan("scan-owned", "bob@example.com")
    assert result is None

    # Row must still be accessible to its real owner.
    assert isolated_store.get_scan("scan-owned", "alice@example.com") is not None


# ── reset_user_data isolation ─────────────────────────────────────────────────

def test_reset_user_data_clears_only_that_user(isolated_store):
    """reset_user_data(email) deletes only rows owned by email, leaving others intact."""
    _insert_scan(isolated_store, "scan-a", "alice@example.com")
    _insert_scan(isolated_store, "scan-b", "bob@example.com")

    isolated_store.reset_user_data("alice@example.com")

    assert isolated_store.list_scans("alice@example.com") == []
    assert len(isolated_store.list_scans("bob@example.com")) == 1


# ── concurrent enqueue ────────────────────────────────────────────────────────

def test_concurrent_enqueue_all_jobs_land_with_unique_ids(isolated_store):
    """N threads enqueueing jobs concurrently must produce N distinct job IDs — no losses,
    no duplicates.

    Unit-level proxy for the multi-user Postgres concurrency scenario (R11). The live
    staging run (scripts/load_test_concurrency.py) exercises the same invariant over real
    network round-trips and a real Postgres WAL.
    """
    n_users = 3
    n_scans_per_user = 4  # 12 concurrent jobs total

    def enqueue_for_user(user_index: int) -> list[str]:
        return [
            isolated_store.enqueue_job(
                "scan",
                payload={"user": f"user{user_index}@example.com", "source": "local"},
                scan_id=f"s-u{user_index}-{uuid.uuid4().hex[:8]}",
            )
            for _ in range(n_scans_per_user)
        ]

    with ThreadPoolExecutor(max_workers=n_users) as pool:
        per_user = list(pool.map(enqueue_for_user, range(n_users)))

    all_ids = [jid for ids in per_user for jid in ids]
    assert len(all_ids) == n_users * n_scans_per_user, "jobs were lost under concurrent enqueue"
    assert len(set(all_ids)) == len(all_ids), "duplicate job IDs under concurrent enqueue"
