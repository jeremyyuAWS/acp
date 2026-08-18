"""Compliance-trend-over-time analytics (audit gap A2).

Every completed scan already persists avg_score + completed_at, so the estate's trajectory is latent
in the scan history. `analytics_trends.compliance_trend` turns that history into a chronological
series + a first-vs-latest summary, and `GET /analytics/compliance-trend` serves it owner-scoped.

The pure helper is tested exhaustively (it is the single authority on the trajectory math); the route
is tested through a TestClient so "the helper computes it and the endpoint never returns it" — the
same defect with a unit test in front of it — cannot pass.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import analytics_trends as at  # noqa: E402


def _s(sid, when, score, *, files=10, certifiable=8, source="drive"):
    """A list_scans-shaped row."""
    return {"id": sid, "completed_at": when, "source": source, "avg_score": score,
            "files": files, "certifiable": certifiable}


# ── the pure helper ────────────────────────────────────────────────────────────
def test_points_are_chronological_and_summary_reports_the_movement():
    # Given newest-first (as list_scans returns), the series comes back oldest→newest.
    r = at.compliance_trend([
        _s("s3", "2026-08-18T10:00:00Z", 88, files=100, certifiable=80),
        _s("s2", "2026-08-15T10:00:00Z", 72, files=100, certifiable=60),
        _s("s1", "2026-08-10T10:00:00Z", 70, files=50, certifiable=30),
    ])
    assert [p["scan_id"] for p in r["points"]] == ["s1", "s2", "s3"]
    assert "_at" not in r["points"][0]                       # the sort key is stripped
    assert r["points"][0]["certifiable_pct"] == 60.0 and r["points"][2]["certifiable_pct"] == 80.0
    s = r["summary"]
    assert (s["n"], s["scored"]) == (3, 3)
    assert (s["first"], s["latest"], s["delta"]) == (70, 88, 18)
    assert s["direction"] == "improving" and s["best"] == 88 and s["span_days"] == 8


def test_a_decline_reads_as_declining():
    r = at.compliance_trend([_s("b", "2026-01-02T00:00:00Z", 80), _s("a", "2026-01-01T00:00:00Z", 90)])
    assert r["summary"]["direction"] == "declining" and r["summary"]["delta"] == -10


def test_a_sub_half_point_move_is_flat_not_a_trend():
    r = at.compliance_trend([_s("a", "2026-01-01T00:00:00Z", 90.0), _s("b", "2026-01-02T00:00:00Z", 90.3)])
    assert r["summary"]["direction"] == "flat"


def test_one_scan_is_a_baseline_never_a_slope():
    r = at.compliance_trend([_s("a", "2026-01-01T00:00:00Z", 90)])
    assert r["summary"]["direction"] == "insufficient"
    assert r["summary"]["first"] == 90 and r["summary"]["latest"] == 90 and r["summary"]["delta"] is None


def test_empty_and_none_histories_are_well_formed():
    for r in (at.compliance_trend([]), at.compliance_trend(None)):
        assert r["points"] == [] and r["summary"]["n"] == 0
        assert r["summary"]["direction"] == "insufficient" and r["summary"]["delta"] is None


def test_a_cancelled_scan_keeps_its_point_but_leaves_the_score_series():
    # None avg_score (cancelled mid-run) must not read as a real 0 that tanks the trend; a row with
    # no timestamp cannot sit on the line at all and is dropped.
    r = at.compliance_trend([
        _s("a", "2026-01-01T00:00:00Z", 70, certifiable=5),
        _s("cancel", "2026-01-02T00:00:00Z", None, certifiable=None),
        _s("b", "2026-01-03T00:00:00Z", 78, certifiable=8),
        _s("notime", None, 50, files=1, certifiable=0),
    ])
    assert (r["summary"]["n"], r["summary"]["scored"]) == (3, 2)          # notime dropped, cancel kept
    assert r["summary"]["direction"] == "improving" and r["summary"]["delta"] == 8
    mid = next(p for p in r["points"] if p["scan_id"] == "cancel")
    assert mid["score"] is None and mid["certifiable_pct"] is None


def test_by_source_splits_a_rising_drive_from_a_declining_sharepoint():
    # The blended trend can hide a declining source behind a rising one — by_source is what stops
    # a multi-source estate from reading one number and missing that SharePoint is getting worse.
    r = at.compliance_trend([
        _s("d1", "2026-08-10T00:00:00Z", 60, source="drive"),
        _s("d2", "2026-08-18T00:00:00Z", 90, source="drive"),
        _s("p1", "2026-08-11T00:00:00Z", 95, source="sharepoint"),
        _s("p2", "2026-08-17T00:00:00Z", 80, source="sharepoint"),
    ])
    assert list(r["by_source"].keys()) == ["drive", "sharepoint"]        # first-seen (d1 is earliest)
    assert r["by_source"]["drive"]["direction"] == "improving" and r["by_source"]["drive"]["delta"] == 30
    assert r["by_source"]["sharepoint"]["direction"] == "declining" and r["by_source"]["sharepoint"]["delta"] == -15


def test_by_source_shares_the_summary_shape_with_the_overall_trend():
    r = at.compliance_trend([_s("a", "2026-01-01T00:00:00Z", 70), _s("b", "2026-01-05T00:00:00Z", 82)])
    assert set(r["by_source"]["drive"]) == set(r["summary"])             # identical shape, no divergence
    assert r["by_source"]["drive"] == r["summary"]                       # single source ⇒ equal to blend


def test_a_missing_source_buckets_under_unknown_never_dropped():
    r = at.compliance_trend([_s("x", "2026-01-01T00:00:00Z", 50, source=None),
                             _s("y", "2026-01-03T00:00:00Z", 55, source=None)])
    assert r["by_source"]["unknown"]["n"] == 2 and r["by_source"]["unknown"]["delta"] == 5


def test_by_source_is_empty_for_an_empty_history():
    assert at.compliance_trend([])["by_source"] == {}


# ── the route (owner-scoped, through the real app) ──────────────────────────────
@pytest.fixture()
def client(monkeypatch, isolated_store):
    """A TestClient with the access gate OFF, so the owner resolves to 'demo'."""
    import core
    from fastapi.testclient import TestClient
    from app import app
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", "", raising=False)
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


def test_endpoint_returns_the_owners_trajectory(client):
    c, store = client
    _seed(store, "d01", "demo", "2026-08-10T10:00:00+00:00", 70)
    _seed(store, "d02", "demo", "2026-08-14T10:00:00+00:00", 82)
    _seed(store, "d03", "demo", "2026-08-18T10:00:00+00:00", 91)
    body = c.get("/analytics/compliance-trend").json()
    assert [p["scan_id"] for p in body["points"]] == ["d01", "d02", "d03"]
    assert body["summary"]["first"] == 70 and body["summary"]["latest"] == 91
    assert body["summary"]["direction"] == "improving" and body["summary"]["delta"] == 21


def test_endpoint_is_owner_scoped(client):
    c, store = client
    _seed(store, "mine", "demo", "2026-08-18T10:00:00+00:00", 88)
    _seed(store, "theirs", "someone@else.com", "2026-08-18T10:00:00+00:00", 40)
    body = c.get("/analytics/compliance-trend").json()
    assert [p["scan_id"] for p in body["points"]] == ["mine"]       # never another user's estate


def test_source_filter_narrows_the_trend(client):
    c, store = client
    _seed(store, "drv", "demo", "2026-08-17T10:00:00+00:00", 60, source="drive")
    _seed(store, "sp", "demo", "2026-08-18T10:00:00+00:00", 95, source="sharepoint")
    body = c.get("/analytics/compliance-trend", params={"source": "sharepoint"}).json()
    assert [p["scan_id"] for p in body["points"]] == ["sp"]
    assert body["points"][0]["source"] == "sharepoint"
