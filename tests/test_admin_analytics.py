"""Admin analytics overview endpoint tests.

Verifies that:
- Non-admin callers get 403 (backend enforcement, not just a hidden tab)
- Admin callers get the aggregated KPI payload
- Period filters correctly narrow the result set
- Source filter narrows to a single connector
- by_source breakdown is present and keyed by connector name
- recent_scans list is capped at 20 and includes owner_email
- store.list_scans_admin() includes owner_email unlike list_scans()
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

# Stub heavy optional deps that aren't installed in the test env so that
# importing routes (which pull in report.py → reportlab, handlers.py → lxml) works.
# `report` is imported at module level by routes/scans.py; stub it directly so the
# whole reportlab import chain is skipped, regardless of import order.
for _m in (
    "reportlab", "reportlab.lib", "reportlab.lib.pagesizes", "reportlab.lib.styles",
    "reportlab.lib.units", "reportlab.lib.colors", "reportlab.platypus",
    "reportlab.graphics", "reportlab.graphics.charts",
    "reportlab.graphics.charts.barcharts", "reportlab.pdfgen",
    "lxml", "lxml.html",
    "report",
    "remediate", "handlers",
):
    sys.modules.setdefault(_m, MagicMock())

import pytest


# ── store.list_scans_admin() ────────────────────────────────────────────────────
def test_list_scans_admin_includes_owner_email(isolated_store):
    """list_scans_admin includes owner_email; list_scans does not."""
    store = isolated_store
    store.save_scan({
        "_scan_id": "s1", "started_at": "2026-08-01T00:00:00+00:00",
        "completed_at": "2026-08-02T00:00:00+00:00",
        "source": "drive", "owner": "alice@example.com",
        "rubric": {"name": "wcag-aa", "hash": "h"},
        "summary": {"files": 5, "certifiable": 4, "uncertain": 0, "error": 0, "avg_score": 88.0},
        "files": [{"file": f"f{i}.pdf", "engine": "pdf", "status": "certifiable",
                   "score": 88.0, "compliant": 1, "skipped_rules": 0, "issues": []} for i in range(5)],
    })
    rows = store.list_scans_admin()
    assert rows, "expected at least one row"
    assert "owner_email" in rows[0], "owner_email must be present in list_scans_admin rows"
    assert rows[0]["owner_email"] == "alice@example.com"

    # Regular list_scans should NOT expose owner_email
    regular = store.list_scans(owner=None)
    assert "owner_email" not in regular[0]


def test_list_scans_admin_returns_all_users(isolated_store):
    """list_scans_admin returns completed scans from every user, not just one."""
    store = isolated_store
    for owner, sid in [("alice@example.com", "a1"), ("bob@example.com", "b1")]:
        store.save_scan({
            "_scan_id": sid, "started_at": "2026-08-01T00:00:00+00:00",
            "completed_at": "2026-08-02T00:00:00+00:00",
            "source": "drive", "owner": owner,
            "rubric": {"name": "wcag-aa", "hash": "h"},
            "summary": {"files": 2, "certifiable": 1, "uncertain": 0, "error": 0, "avg_score": 70.0},
            "files": [{"file": "f.pdf", "engine": "pdf", "status": "certifiable",
                       "score": 70.0, "compliant": 1, "skipped_rules": 0, "issues": []}],
        })
    rows = store.list_scans_admin()
    assert len(rows) == 2
    owners = {r["owner_email"] for r in rows}
    assert owners == {"alice@example.com", "bob@example.com"}


# ── endpoint tests ───────────────────────────────────────────────────────────────
@pytest.fixture()
def open_client(monkeypatch, isolated_store):
    """TestClient with admin auth DISABLED (OWNER_EMAIL='') — tests data correctness.

    _require_admin is a no-op when OWNER_EMAIL is empty (dev/demo mode), so any caller
    reaches the endpoint. This lets data-shape tests focus on the response body without
    standing up auth plumbing.
    """
    import core
    from fastapi.testclient import TestClient
    from app import app
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", "", raising=False)
    return TestClient(app), isolated_store


@pytest.fixture()
def gated_client(monkeypatch, isolated_store):
    """TestClient with admin auth ON: OWNER_EMAIL set, _require_admin enforces.

    Callers without a recognised admin identity in request.state.user_email get 403.
    No user_email is set by default in test requests, so the default caller is a stranger.
    """
    import core
    from fastapi.testclient import TestClient
    from app import app
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", "admin@example.com", raising=False)
    monkeypatch.setattr(core, "is_admin", lambda e: e == "admin@example.com", raising=False)
    return TestClient(app), isolated_store


def _seed(store, sid, owner, when, score, *, source="drive", files=10, certifiable=8):
    store.save_scan({
        "_scan_id": sid, "started_at": "2026-08-01T00:00:00+00:00", "completed_at": when,
        "source": source, "owner": owner, "rubric": {"name": "wcag-aa", "hash": "h"},
        "summary": {"files": files, "certifiable": certifiable, "uncertain": 0, "error": 0,
                    "avg_score": score},
        "files": [{"file": f"d{i}.pdf", "engine": "pdf", "status": "certifiable", "score": score,
                   "compliant": 1, "skipped_rules": 0, "issues": []} for i in range(files)],
    })


def test_non_admin_gets_403(gated_client):
    """Backend enforces the admin gate — a caller with no recognised identity gets 403."""
    c, _ = gated_client
    # request.state.user_email is not set → "" → core.is_admin("") == False → 403
    r = c.get("/admin/analytics/overview")
    assert r.status_code == 403


def test_endpoint_returns_200_and_kpi_payload(open_client):
    c, store = open_client
    _seed(store, "s1", "alice@example.com", "2026-08-20T10:00:00+00:00", 80, files=10, certifiable=8)
    _seed(store, "s2", "bob@example.com",   "2026-08-21T10:00:00+00:00", 90, files=20, certifiable=18)
    r = c.get("/admin/analytics/overview", params={"period": "all"})
    assert r.status_code == 200
    body = r.json()
    assert body["scans"] == 2
    assert body["docs"] == 30
    assert body["certifiable"] == 26
    assert body["certifiable_rate"] == round(26 / 30 * 100, 1)
    assert body["avg_score"] == round((80 + 90) / 2, 1)


def test_by_source_breakdown(open_client):
    c, store = open_client
    _seed(store, "drv", "alice@example.com", "2026-08-20T10:00:00+00:00", 80,
          source="drive", files=10, certifiable=8)
    _seed(store, "sp",  "bob@example.com",   "2026-08-21T10:00:00+00:00", 90,
          source="sharepoint", files=20, certifiable=18)
    r = c.get("/admin/analytics/overview", params={"period": "all"})
    body = r.json()
    assert "drive" in body["by_source"]
    assert "sharepoint" in body["by_source"]
    assert body["by_source"]["drive"]["scans"] == 1
    assert body["by_source"]["drive"]["docs"] == 10
    assert body["by_source"]["sharepoint"]["docs"] == 20


def test_source_filter(open_client):
    c, store = open_client
    _seed(store, "drv", "alice@example.com", "2026-08-20T10:00:00+00:00", 80, source="drive")
    _seed(store, "sp",  "bob@example.com",   "2026-08-21T10:00:00+00:00", 90, source="sharepoint")
    r = c.get("/admin/analytics/overview", params={"period": "all", "source": "drive"})
    body = r.json()
    assert body["scans"] == 1
    assert "sharepoint" not in body["by_source"]


def test_period_filter_excludes_old_scans(open_client):
    c, store = open_client
    _seed(store, "old", "alice@example.com", "2025-01-01T10:00:00+00:00", 60)
    _seed(store, "new", "alice@example.com", "2026-08-20T10:00:00+00:00", 90)
    r = c.get("/admin/analytics/overview", params={"period": "30d"})
    body = r.json()
    assert body["scans"] == 1
    assert any(s["id"] == "new" for s in body["recent_scans"])
    assert not any(s["id"] == "old" for s in body["recent_scans"])


def test_recent_scans_includes_owner_email(open_client):
    c, store = open_client
    _seed(store, "s1", "alice@example.com", "2026-08-20T10:00:00+00:00", 80)
    r = c.get("/admin/analytics/overview", params={"period": "all"})
    body = r.json()
    assert body["recent_scans"][0]["owner_email"] == "alice@example.com"


def test_trend_is_present_and_correct(open_client):
    c, store = open_client
    _seed(store, "a", "alice@example.com", "2026-08-15T10:00:00+00:00", 70)
    _seed(store, "b", "alice@example.com", "2026-08-20T10:00:00+00:00", 85)
    r = c.get("/admin/analytics/overview", params={"period": "all"})
    body = r.json()
    assert "trend" in body
    assert "summary" in body["trend"]
    assert body["trend"]["summary"]["direction"] == "improving"


def test_empty_period_returns_zero_kpis(open_client):
    c, store = open_client
    _seed(store, "old", "alice@example.com", "2025-01-01T10:00:00+00:00", 70)
    r = c.get("/admin/analytics/overview", params={"period": "today"})
    body = r.json()
    assert body["scans"] == 0
    assert body["docs"] == 0
    assert body["certifiable_rate"] is None
    assert body["avg_score"] is None
