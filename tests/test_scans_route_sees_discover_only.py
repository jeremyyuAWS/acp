"""GET /scans — the actual root cause of a live "0 documents" report on 2026-08-28.

This is the route the SPA's own App.jsx calls on every load (listScans() in frontend/src/api.js)
to build scanList and pick a default scan (pickDefaultScan() in frontend/src/defaultScan.js).
It used list_scans(), which filters to `completed_at IS NOT NULL` — a filter an ADR 0020
Discover-only run never satisfies (only `discovered_at` is set). Once Discover-only became the
default scan behaviour, a user whose most recent scans were all Discover-only got an EMPTY
scanList back from this route: pickDefaultScan([]) returns null, App.jsx never calls setScan(),
and `run` stays undefined for the rest of the session. Every tab reads that as "nothing has ever
been scanned" — Discover shows 0 documents with no scope line and never even requests the
inventory (scanId was undefined, not just empty), and Assess (gated on the same missing `run`)
reads the same way.

This is the SAME blind spot already fixed for /monitor/estate (#907, via list_finished_scans())
and /schedule's last_at (#908) — this is the call site those two were downstream SYMPTOMS of,
not the root cause itself. list_scans_including_discovered() is deliberately not used here
either: it would let a scan still mid-listing (no files yet) outrank a real finished one as "the
newest" and get auto-selected, which is the identical dishonest-zero shape from the other
direction.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

OWNER = "demo"


def _seed_discover_only_scan(store, sid: str, owner: str, files: int,
                             started_at: str = "2026-08-28T21:00:00+00:00",
                             discovered_at: str | None = None) -> None:
    store.init_scan_run(sid, "drive", files, started_at, "wcag-aa", "h", owner=owner,
                        status="running", scope={"kind": "drive"})
    store.set_scan_files(sid, files)
    if discovered_at is None:
        # set_scan_status stamps the REAL current wall-clock time — fine when only presence
        # matters, wrong for a test asserting a specific ordering (see the explicit-timestamp
        # branch below, used wherever this scan must sort relative to another with a known date).
        store.set_scan_status(sid, "discovered")
    else:
        with store._db.cursor() as cur:
            store._db.execute(cur, "UPDATE scan_runs SET status='discovered', discovered_at=%s WHERE id=%s",
                              (discovered_at, sid))


def _seed_assessed_scan(store, sid: str, owner: str, files: int, completed_at: str) -> None:
    store.save_scan({
        "_scan_id": sid,
        "started_at": "2026-07-29T21:00:00+00:00",
        "completed_at": completed_at,
        "source": "drive",
        "owner": owner,
        "rubric": {"name": "wcag-aa", "hash": "h"},
        "summary": {"files": files, "certifiable": files, "uncertain": 0, "error": 0,
                    "avg_score": 90},
        "files": [{"file": f"doc{i}.pdf", "engine": "pdf", "status": "certifiable",
                   "score": 90, "compliant": 1, "skipped_rules": 0, "issues": []}
                  for i in range(files)],
    })


@pytest.fixture()
def client(monkeypatch, isolated_store):
    """An ungated TestClient (local-dev shape: no access code, no GIS) — same pattern as
    test_scan_not_found_detail.py. _owner() resolves to 'demo' here."""
    import core
    from fastapi.testclient import TestClient

    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    return TestClient(app), isolated_store


def test_a_discover_only_scan_is_no_longer_invisible_to_the_apps_own_scan_list(client):
    """The regression, stated directly: the exact call the SPA makes on every page load must see
    a Discover-only run, or the app auto-selects nothing and every tab reads as never-scanned."""
    c, store = client
    _seed_discover_only_scan(store, "s1", OWNER, files=32)

    res = c.get("/scans")
    assert res.status_code == 200
    ids = [s["id"] for s in res.json()]
    assert ids == ["s1"], "list_scans() would have returned [] here — the live bug"


def test_pickdefaultscan_would_have_returned_null_on_the_old_response(client):
    """Not a frontend test — a pin on the SHAPE of the old bug, so a future change to the route
    cannot quietly reintroduce it without a backend test noticing. The old route (list_scans)
    returns [] for an all-Discover-only estate; [] is exactly what frontend/src/defaultScan.js's
    pickDefaultScan() treats as 'no scan available'."""
    c, store = client
    _seed_discover_only_scan(store, "s1", OWNER, files=32)

    old_shape = store.list_scans(owner=OWNER)
    assert old_shape == [], "confirms the route WOULD have been broken without the fix"

    new_shape = c.get("/scans").json()
    assert len(new_shape) == 1


def test_both_discover_only_and_assessed_scans_appear_newest_first(client):
    c, store = client
    _seed_discover_only_scan(store, "s_old", OWNER, files=5,
                             started_at="2026-08-18T09:00:00+00:00",
                             discovered_at="2026-08-18T09:05:00+00:00")
    _seed_assessed_scan(store, "s_new", OWNER, files=9, completed_at="2026-08-21T10:00:00+00:00")

    ids = [s["id"] for s in c.get("/scans").json()]
    assert ids == ["s_new", "s_old"]


def test_a_scan_still_mid_listing_does_not_appear(client):
    """Distinct from list_scans_including_discovered(): a scan that has not reached a real
    terminal state yet must not show up as a candidate default — that is the OTHER direction of
    the same dishonest-zero bug, reintroduced if this route were widened instead of narrowed."""
    c, store = client
    store.init_scan_run("s_running", "drive", 0, "2026-08-28T23:59:00+00:00", "wcag-aa", "h",
                        owner=OWNER, status="running", scope={"kind": "drive"})

    ids = [s["id"] for s in c.get("/scans").json()]
    assert ids == []
