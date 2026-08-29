"""GET /workspace/bootstrap (workspace-bootstrap redesign, Phase 1 step 1).

Covers:
  1. pick_default_scan — ported from frontend/src/defaultScan.js's pickDefaultScan,
     pinned against the same cases frontend/src/defaultScan.test.js does, so the two
     implementations cannot quietly drift apart.
  2. The route: identity/permissions, the picked scan's id/status/revision, its cached
     Overview snapshot, the scan-picker list, and the active-job summary — all in one
     response, tenant-isolated.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

from routes.workspace import pick_default_scan


def _s(id, files=None, published_at=None):
    return {"id": id, "files": files, "published_at": published_at}


# ── pick_default_scan — parity with defaultScan.test.js ───────────────────

def test_skips_a_collapsed_newest_scan_and_falls_back_to_the_most_recent_full_size_one():
    scans = [_s("new", 5), _s("real", 22), _s("older", 20)]
    assert pick_default_scan(scans)["id"] == "real"


def test_skips_consecutive_collapsed_scans_not_just_the_first():
    scans = [_s("a", 1), _s("b", 2), _s("full", 30), _s("c", 28)]
    assert pick_default_scan(scans)["id"] == "full"


def test_keeps_the_newest_when_it_is_full_size():
    scans = [_s("new", 24), _s("old", 22)]
    assert pick_default_scan(scans)["id"] == "new"


def test_never_hides_a_legitimately_small_estate():
    scans = [_s("new", 3), _s("old", 4), _s("older", 2)]
    assert pick_default_scan(scans)["id"] == "new"


def test_uses_exactly_the_monitor_threshold():
    assert pick_default_scan([_s("n", 11), _s("big", 22)])["id"] == "n"     # 11 == 0.5*22 -> kept
    assert pick_default_scan([_s("n", 10), _s("big", 22)])["id"] == "big"   # 10 < 11 -> skipped


def test_only_considers_the_recent_window():
    recent = [_s(f"r{i}", 20) for i in range(10)]
    scans = recent + [_s("ancient", 500)]
    assert pick_default_scan(scans)["id"] == "r0"


def test_degrades_safely_on_empty_or_missing_counts():
    assert pick_default_scan([]) is None
    assert pick_default_scan(None) is None
    assert pick_default_scan([_s("a")])["id"] == "a"


def test_prefers_a_published_scan_over_an_unpublished_one_of_similar_size():
    scans = [_s("new-unpub", 20), _s("old-pub", 22, "2026-08-01T00:00:00Z")]
    assert pick_default_scan(scans)["id"] == "old-pub"


def test_still_applies_collapse_check_before_published_preference():
    scans = [_s("small-pub", 5, "2026-08-01T00:00:00Z"), _s("big-unpub", 22)]
    assert pick_default_scan(scans)["id"] == "big-unpub"


# ── GET /workspace/bootstrap ────────────────────────────────────────────────

@pytest.fixture()
def app_client(isolated_store, monkeypatch):
    from fastapi.testclient import TestClient
    import core as core_mod
    monkeypatch.setattr(core_mod, "store", isolated_store)
    import app as app_mod
    return TestClient(app_mod.app, raise_server_exceptions=True)


def _seed_scan(s, scan_id, owner, *, completed_at="2026-08-01T00:00:00", files=10):
    with s._db.cursor() as cur:
        s._db.execute(cur,
            "INSERT INTO scan_runs (id, owner_email, source, rubric_hash, completed_at, "
            "files, certifiable, uncertain, error, avg_score, status) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (scan_id, owner, "drive", "rh1", completed_at, files, files, 0, 0, 90, "done"))


def test_bootstrap_with_no_scans_yet(app_client):
    resp = app_client.get("/workspace/bootstrap")
    assert resp.status_code == 200
    body = resp.json()
    assert body["scan_id"] is None
    assert body["scan_status"] is None
    assert body["revision"] is None
    assert body["overview"] is None
    assert body["scans"] == []
    assert body["active_job"] == {}
    assert body["me"]["email"] == "demo"


def test_bootstrap_returns_the_picked_scans_identity_status_and_overview(app_client, isolated_store):
    _seed_scan(isolated_store, "s1", "demo", files=10)
    resp = app_client.get("/workspace/bootstrap")
    assert resp.status_code == 200
    body = resp.json()
    assert body["scan_id"] == "s1"
    assert body["scan_status"] == "done"
    assert body["revision"] == 0
    assert body["overview"]["scan_id"] == "s1"
    assert body["overview"]["cached"] is False                # first read — computed, not a hit
    assert [s["id"] for s in body["scans"]] == ["s1"]


def test_bootstrap_picks_the_same_scan_pick_default_scan_would():
    """Not a route test — a direct check that pick_default_scan (what the route calls)
    agrees with the frontend algorithm on a case with a collapsed newest scan, so the
    route-level test above isn't the only place this logic is exercised."""
    scans = [_s("new", 5), _s("real", 22), _s("older", 20)]
    assert pick_default_scan(scans)["id"] == "real"


def test_bootstrap_reflects_active_job(app_client, isolated_store):
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "INSERT INTO scan_runs (id, owner_email, status, started_at) VALUES (%s,%s,%s,%s)",
            ("s-running", "demo", "running", "2026-08-29T00:00:00"))
        isolated_store._db.execute(cur,
            "INSERT INTO jobs (id, scan_id, type, status, payload) VALUES (%s,%s,%s,%s,%s)",
            ("j1", "s-running", "scan_file", "queued", "{}"))
    resp = app_client.get("/workspace/bootstrap")
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_job"].get("id") == "s-running"


def test_bootstrap_is_tenant_isolated(app_client, isolated_store):
    _seed_scan(isolated_store, "s-alice", "alice@example.com", files=10)
    # The test client's default identity is "demo" (no auth header) — alice's scan must
    # not surface in "demo"'s bootstrap response.
    resp = app_client.get("/workspace/bootstrap")
    body = resp.json()
    assert body["scan_id"] is None
    assert body["scans"] == []
