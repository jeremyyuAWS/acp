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

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

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


def test_recent_scans_includes_status(open_client):
    """A normally completed scan surfaces status='done' alongside its counts."""
    c, store = open_client
    _seed(store, "s1", "alice@example.com", "2026-08-20T10:00:00+00:00", 80)
    r = c.get("/admin/analytics/overview", params={"period": "all"})
    body = r.json()
    assert body["recent_scans"][0]["status"] == "done"


def test_recent_scans_status_distinguishes_cancelled_scan_from_a_real_zero(open_client):
    """A scan stopped before assessment ran must not read as a zero-finding result.

    `_seed` (via store.save_scan) always produces a finalized status='done' row — it can't
    represent a scan that never got that far. Build one the way cancel_scan actually leaves
    it: init_scan_run + add_inventory (discovery only, no file_records) + cancel_scan — the
    same state test_unfinalized_scan_aggregate.py exercises for the identical underlying bug
    (NULL counters silently reading as zero). The two scans below land with an identical
    certifiable=0, and only the `status` field tells them apart.
    """
    c, store = open_client
    store.init_scan_run("s-cancelled", "drive", 40, "2026-08-20T09:00:00+00:00", "default",
                         "h", owner="alice@example.com", status="running")
    store.add_inventory("s-cancelled", [
        {"file": f"doc-{i}.pdf", "doc_class": "pdf", "size_kb": 10} for i in range(40)
    ])
    assert store.cancel_scan("s-cancelled", owner="alice@example.com") is True
    _seed(store, "s-real-zero", "alice@example.com", "2026-08-21T10:00:00+00:00", None,
          files=5, certifiable=0)

    r = c.get("/admin/analytics/overview", params={"period": "all"})
    rows = {s["id"]: s for s in r.json()["recent_scans"]}

    assert rows["s-cancelled"]["status"] == "cancelled"
    assert rows["s-cancelled"]["certifiable"] == 0, "cancelled before assessment — nothing was assessed"

    assert rows["s-real-zero"]["status"] == "done"
    assert rows["s-real-zero"]["certifiable"] == 0, "assessed in full — genuinely nothing certifiable"


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

@pytest.mark.parametrize('path', ['/admin/analytics/scans/other-user', '/admin/analytics/export', '/admin/analytics/methodology'])
def test_new_admin_surfaces_deny_non_admin(gated_client, path):
    client, _ = gated_client
    assert client.get(path).status_code == 403


def test_attempts_include_active_other_user_and_nullable_results(open_client):
    client, store = open_client
    for sid, actor, status in [('running', 'alice@example.com', 'running'), ('failed', 'bob@example.com', 'failed'), ('superseded', 'bob@example.com', 'superseded')]:
        store.init_scan_run(sid, 'drive', 3, '2026-08-20T10:00:00+00:00', 'default', 'h', owner=actor, status=status)
    response = client.get('/admin/analytics/overview', params={'period': 'all'})
    data = response.json()
    assert data['attempts'] == 3
    assert data['active_users'] == 2
    assert data['unsuccessful_runs'] == 2
    assert data['by_status'] == {'running': 1, 'failed': 1, 'superseded': 1}
    assert all(r['certifiable'] is None for r in data['register']['rows'])
    assert data['successful_results']['certifiable_rate'] is None
    assert response.headers['cache-control'] == 'no-store'
    filtered = client.get('/admin/analytics/overview', params={'period': 'all', 'owner': 'bob@example.com', 'status': 'failed'}).json()
    assert [r['id'] for r in filtered['register']['rows']] == ['failed']


def test_register_pagination_search_export_and_detail_reconcile(open_client):
    import csv
    import io
    client, store = open_client
    for i in range(25):
        store.init_scan_run(f'run-{i:02}', 'drive', 2, f'2026-08-20T10:00:{i:02}+00:00', 'default', 'h', owner='alice@example.com', status='running')
    data = client.get('/admin/analytics/overview', params={'period': 'all', 'page': 2}).json()
    assert data['register']['total'] == 25
    assert len(data['register']['rows']) == 5
    exported = client.get('/admin/analytics/export', params={'period': 'all'})
    assert len(list(csv.DictReader(io.StringIO(exported.text)))) == 25
    assert exported.headers['x-export-rows'] == '25'
    search = client.get('/admin/analytics/overview', params={'period': 'all', 'search': 'run-24'}).json()
    assert search['register']['total'] == 1
    detail = client.get('/admin/analytics/scans/run-24').json()
    assert detail['scan']['files'] == 2
    assert detail['observations'] == []
    assert detail['scan']['certifiable'] is None
    assert client.get('/admin/analytics/scans/absent').status_code == 404
    assert client.get('/admin/analytics/methodology', params={'period': 'all'}).json()['scope'] == 'Platform · all users'


def test_custom_boundaries_timezone_and_previous_period():
    from datetime import datetime, timezone
    from analytics_overview import build
    rows = [{'id': 'before', 'started_at': '2026-03-08T07:59:59Z', 'status': 'failed'},
            {'id': 'start', 'started_at': '2026-03-08T08:00:00Z', 'status': 'running'},
            {'id': 'end', 'started_at': '2026-03-09T07:00:00Z', 'status': 'done'},
            {'id': 'unknown', 'started_at': None, 'status': 'failed'}]
    data = build(rows, period='custom', start='2026-03-08T00:00:00-08:00', end='2026-03-09T00:00:00-07:00', timezone_name='America/Los_Angeles', now=datetime(2026, 3, 10, tzinfo=timezone.utc))
    assert data['attempts'] == 1
    assert data['activity'][0]['date'] == '2026-03-08'
    assert data['comparison']['attempts'] == 1
    assert data['comparison']['start'] == '2026-03-07T09:00:00+00:00'
    assert data['reporting']['missing_started_at'] == 1
    assert data['reporting']['partial_data'] is True


@pytest.mark.parametrize('params', [{'period': 'custom'}, {'period': 'custom', 'start': '2026-08-02', 'end': '2026-08-01'}, {'timezone': 'made/up'}])
def test_invalid_reporting_intervals(open_client, params):
    client, _ = open_client
    assert client.get('/admin/analytics/overview', params=params).status_code == 422


def test_results_use_completion_basis_and_do_not_count_failed_attempts():
    from datetime import datetime, timezone
    from analytics_overview import build
    rows = [{'id': 'completed', 'started_at': '2026-08-01T00:00:00Z', 'completed_at': '2026-08-20T12:00:00Z', 'status': 'done', 'source': 'drive', 'files': 10, 'certifiable': 4, 'avg_score': 80},
            {'id': 'failed', 'started_at': '2026-08-20T11:00:00Z', 'completed_at': '2026-08-20T12:00:00Z', 'status': 'failed', 'files': 10, 'certifiable': 10}]
    data = build(rows, period='custom', start='2026-08-20T00:00:00Z', end='2026-08-21T00:00:00Z', now=datetime(2026, 8, 22, tzinfo=timezone.utc))
    assert data['attempts'] == 1
    assert data['successful_results']['scans'] == 1
    assert data['successful_results']['certifiable_rate'] == 40
    assert data['results_by_source']['drive']['docs'] == 10
    assert [r['id'] for r in data['results_register']['rows']] == ['completed']
    assert 'not ingestion freshness' in data['reporting']['data_through_note']


def test_export_preserves_unknowns_and_escapes_spreadsheet_formulas(open_client):
    import csv
    import io
    client, store = open_client
    store.init_scan_run('formula', 'drive', 2, '2026-08-20T10:00:00Z', 'default', 'h', owner='=danger()', status='running')
    response = client.get('/admin/analytics/export', params={'period': 'all'})
    row = next(csv.DictReader(io.StringIO(response.text)))
    assert row['owner_email'] == "'=danger()"
    assert row['certifiable'] == ''
    assert response.headers['cache-control'] == 'no-store'


def test_all_time_undated_rows_remain_inspectable_and_bad_metrics_unavailable():
    from analytics_overview import build
    rows = [{'id': 'undated', 'started_at': 'invalid', 'status': 'running', 'files': -1, 'avg_score': float('nan')},
            {'id': 'done', 'started_at': '2026-08-01T00:00:00Z', 'completed_at': '2026-08-02T00:00:00Z', 'status': 'done', 'files': 2, 'certifiable': 3}]
    result = build(rows, period='all')
    assert result['attempts'] == 2
    assert result['reporting']['undated_activity'] == 1
    assert sum(r['attempts'] for r in result['activity']) == 1
    undated = next(r for r in result['register']['rows'] if r['id'] == 'undated')
    assert undated['files'] is None
    assert undated['avg_score'] is None
    assert result['successful_results']['missing_results'] == 1
    assert result['successful_results']['certifiable_rate'] is None


def test_completion_register_is_server_paged():
    from analytics_overview import build
    rows = [{'id': str(i), 'started_at': '2026-08-01T00:00:00Z', 'completed_at': '2026-08-02T00:00:00Z', 'status': 'done'} for i in range(25)]
    result = build(rows, period='all', page=2, page_size=20)
    assert result['results_register']['total'] == 25
    assert len(result['results_register']['rows']) == 5
    assert result['results_register']['page'] == 2
    assert len(result['result_trend']) == 25
    assert 'owner_email' not in result['result_trend'][0]


def test_export_basis_matches_attempt_or_completion_register(open_client):
    import csv
    import io
    client, store = open_client
    _seed(store, 'completed-in-range', 'alice@example.com', '2026-08-20T12:00:00Z', 80)
    store.init_scan_run('attempt-in-range', 'drive', 2, '2026-08-20T12:00:00Z', 'default', 'h', owner='bob@example.com', status='running')
    params = {'period': 'custom', 'start': '2026-08-20T00:00:00Z', 'end': '2026-08-21T00:00:00Z'}
    attempts = client.get('/admin/analytics/export', params={**params, 'basis': 'attempts'})
    results = client.get('/admin/analytics/export', params={**params, 'basis': 'results'})
    assert [r['id'] for r in csv.DictReader(io.StringIO(attempts.text))] == ['attempt-in-range']
    assert [r['id'] for r in csv.DictReader(io.StringIO(results.text))] == ['completed-in-range']
    assert results.headers['x-export-basis'] == 'results'
    report = client.get('/admin/analytics/methodology', params={**params, 'basis': 'results'}).json()
    assert report['export_basis'] == 'results'
    assert report['time_basis'] == 'completed_at (successful results)'
    assert 'independently' in report['snapshot_note']
    assert client.get('/admin/analytics/export', params={'basis': 'invalid'}).status_code == 422


def test_outcome_group_drilldowns_reconcile_kpis():
    from analytics_overview import build
    rows = [{'id': state, 'started_at': '2026-08-20T12:00:00Z', 'status': state} for state in ['done', 'completed', 'failed', 'error', 'cancelled', 'interrupted', 'superseded', 'running', 'discovered']]
    overview = build(rows, period='all')
    successes = build(rows, period='all', status='__successful__')
    failures = build(rows, period='all', status='__unsuccessful__')
    assert successes['register']['total'] == overview['successful_runs'] == 2
    assert failures['register']['total'] == overview['unsuccessful_runs'] == 5
    assert '__successful__' in overview['filter_options']['statuses']
