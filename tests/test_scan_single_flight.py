"""Single-flight scans per owner: starting a new durable scan while one is already running for
the same user must cancel the old one first, not let both discover concurrently.

Found live 2026-08-26: nothing stopped a second "Re-scan all sources" click (or a stray duplicate
request) from enqueuing a second durable scan while the first was still running — both then
listed the same Drive concurrently, racing each other for DB connections and producing confusing
overlapping results (a tiny folder-scoped listing and a 15k-item whole-Drive listing logging
almost simultaneously for one account). "Re-scan" means "start fresh, superseding whatever's
running" — there is no UI for intentionally running two scans in parallel for one user.

REGRESSION found live 2026-08-26, same day: the guard originally reused cancel_scan(), which
stamps completed_at=now(). That made the superseded run sort as the estate's NEWEST scan in
list_scans() (ORDER BY completed_at DESC) — with files=0 since it barely started — hiding the
real completed scan behind it. Production's monitor caught this within minutes: "newest has 0
documents but a recent scan had 999". The guard now calls supersede_scan() instead, which uses a
distinct 'superseded' status that list_scans()/list_scans_admin()/list_scans_including_discovered()/
previous_run_for_source() all exclude — see test_scan_supersede_excluded_from_listings.py.
"""
from __future__ import annotations
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "jeremyyu.movate@gmail.com"
OTHER = "other@example.com"
_NOW = datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def gated_client(monkeypatch, isolated_store):
    """Same shape as test_cancel_queued_job.py's fixture."""
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: True)

    client = TestClient(app)

    def as_user(email):
        client.headers.update({"Authorization": f"Bearer {email}"})
        return client

    return as_user


def _start_queued(client_fn, owner, source="local"):
    r = client_fn(owner).post(f"/scans?source={source}&queue=true&fanout=true")
    assert r.status_code == 200, r.text
    return r.json()["scan_id"]


def _mark_running(store, scan_id, owner):
    """A freshly enqueued scan sits at status='queued' until a worker claims it — active_scan()
    only reports status='running'. Simulate the claim so the guard has something to find, the
    same way a real worker's init_scan_run call would."""
    store.init_scan_run(scan_id, "local", total=5, started_at=_NOW,
                        rubric_name="WCAG 2.1 AA", rubric_hash="abc123",
                        owner=owner, status="running")


def test_a_second_scan_cancels_the_first_for_the_same_owner(gated_client, isolated_store):
    s1 = _start_queued(gated_client, OWNER)
    _mark_running(isolated_store, s1, OWNER)
    assert isolated_store.get_scan(s1, owner=OWNER)["run"]["status"] == "running"

    s2 = _start_queued(gated_client, OWNER)

    assert s2 != s1
    assert isolated_store.get_scan(s1, owner=OWNER)["run"]["status"] == "superseded"
    # The new scan is untouched — it starts at 'queued' like any fresh enqueue.
    assert isolated_store.get_scan(s2, owner=OWNER)["run"]["status"] == "queued"


def test_a_second_scan_is_unaffected_when_the_first_is_not_yet_claimed(gated_client, isolated_store):
    """A scan still sitting at status='queued' (no worker has claimed it) is not what
    active_scan() reports as active — starting another one must not touch it or error."""
    s1 = _start_queued(gated_client, OWNER)
    assert isolated_store.get_scan(s1, owner=OWNER)["run"]["status"] == "queued"

    s2 = _start_queued(gated_client, OWNER)

    assert isolated_store.get_scan(s1, owner=OWNER)["run"]["status"] == "queued"
    assert isolated_store.get_scan(s2, owner=OWNER)["run"]["status"] == "queued"


def test_no_prior_scan_is_a_no_op(gated_client, isolated_store):
    """The common case — no active scan at all — must not raise or behave differently."""
    s1 = _start_queued(gated_client, OWNER)
    assert isolated_store.get_scan(s1, owner=OWNER)["run"]["status"] == "queued"


def test_a_different_owners_scan_is_never_cancelled(gated_client, isolated_store):
    """Per-user isolation: my new scan must never cancel someone else's running scan."""
    s1 = _start_queued(gated_client, OTHER)
    _mark_running(isolated_store, s1, OTHER)

    _start_queued(gated_client, OWNER)

    assert isolated_store.get_scan(s1, owner=OTHER)["run"]["status"] == "running"


def test_only_the_most_recent_prior_scan_is_cancelled(gated_client, isolated_store):
    """Two stale running scans for the same owner (e.g. left over from an earlier bug) — the
    guard cancels whichever active_scan() reports (the most recent), matching reconnect's own
    "most recent in-flight scan" semantics rather than trying to sweep every old row."""
    s1 = _start_queued(gated_client, OWNER)
    _mark_running(isolated_store, s1, OWNER)
    s2 = _start_queued(gated_client, OWNER)
    _mark_running(isolated_store, s2, OWNER)

    s3 = _start_queued(gated_client, OWNER)

    assert isolated_store.get_scan(s2, owner=OWNER)["run"]["status"] == "superseded"
    assert isolated_store.get_scan(s3, owner=OWNER)["run"]["status"] == "queued"
