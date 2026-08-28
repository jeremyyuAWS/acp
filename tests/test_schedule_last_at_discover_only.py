"""/schedule's `last_at` — the third call site carrying the list_scans() Discover-only blind
spot, found live 2026-08-28 while chasing why a just-run scan showed 0 files on the Discover
Results tab. list_scans() filters to `completed_at IS NOT NULL`, which an ADR 0020 Discover-only
run never sets (only `discovered_at`, via set_scan_status) — the same gap
list_scans_including_discovered() fixed for api/routes/assess.py on 2026-08-21 and
list_finished_scans() fixed for /monitor/estate today (#907). This route had it too:
`scans[0]["completed_at"]` read None off a genuinely-newest Discover-only row and reported
`last_at: null` for an estate whose background sweep was running and succeeding every interval —
the schedule page read as "never run" while the sweep log said otherwise.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


@pytest.fixture()
def client(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient

    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    return TestClient(app), isolated_store


def test_last_at_sees_a_discover_only_sweep(client):
    """The regression, stated directly: a scan that only ever reached 'discovered' must still
    move last_at, not read as if the estate has never been refreshed."""
    c, store = client
    store.init_scan_run("s1", "drive", 12, "2026-08-28T09:00:00+00:00", "wcag-aa", "h",
                        owner="owner@example.com", status="running", scope={"kind": "drive"})
    store.set_scan_files("s1", 12)
    store.set_scan_status("s1", "discovered")

    body = c.get("/schedule").json()
    assert body["last_at"] is not None


def test_last_at_prefers_completed_over_discovered_when_both_exist(client):
    c, store = client
    store.init_scan_run("s_old", "drive", 5, "2026-08-18T09:00:00+00:00", "wcag-aa", "h",
                        owner="owner@example.com", status="running", scope={"kind": "drive"})
    with store._db.cursor() as cur:
        store._db.execute(cur,
            "UPDATE scan_runs SET status='discovered', discovered_at=%s WHERE id=%s",
            ("2026-08-18T09:05:00+00:00", "s_old"))

    store.init_scan_run("s_new", "drive", 9, "2026-08-21T09:00:00+00:00", "wcag-aa", "h",
                        owner="owner@example.com", status="running", scope={"kind": "drive"})
    with store._db.cursor() as cur:
        store._db.execute(cur,
            "UPDATE scan_runs SET completed_at=%s, status='done' WHERE id=%s",
            ("2026-08-21T10:00:00+00:00", "s_new"))

    body = c.get("/schedule").json()
    assert body["last_at"] == "2026-08-21T10:00:00+00:00"


def test_last_at_is_still_none_with_no_scans_at_all(client):
    c, _store = client
    assert c.get("/schedule").json()["last_at"] is None
