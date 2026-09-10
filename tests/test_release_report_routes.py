"""Owner-scoped report downloads/retries and transactional automatic completion."""
from types import SimpleNamespace
import pytest
from fastapi import HTTPException, Response
from routes import scans
import release_report_delivery as delivery
import release_reports
from test_release_reports import setup as release_setup, OWNER as REPORT_OWNER
from test_automatic_release_service import prepared, flow, persistence, OWNER, SID, FILE, tick


def request(owner=REPORT_OWNER, headers=None):
    return SimpleNamespace(state=SimpleNamespace(user_email=owner), headers=headers or {})


@pytest.fixture
def report_bundle(isolated_store, monkeypatch):
    monkeypatch.setattr(scans.core, 'store', isolated_store)
    release = release_setup(isolated_store)
    return isolated_store, delivery.queue_release_reports(isolated_store, 'scan', REPORT_OWNER, release)


def test_status_download_headers_and_durable_payload(report_bundle):
    store, bundle = report_bundle
    response = Response()
    status = scans.get_release_reports('scan', request(), response)
    assert response.headers['cache-control'] == 'no-store'
    assert status['status'] == 'queued' and status['bundle_id'] == bundle['bundle_id']
    result = scans.download_release_report('scan', bundle['bundle_id'], 0, request())
    assert b'Remediation and publication summary' in result.body
    assert result.headers['content-disposition'].startswith("attachment; filename*=UTF-8''scan-summary-")
    assert result.headers['content-type'].startswith('text/html')
    assert result.headers['x-content-type-options'] == 'nosniff'
    assert result.headers['content-security-policy'] == "sandbox; default-src 'none'; style-src 'unsafe-inline'"
    assert result.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('owner,sid,status', [(None, 'scan', 401), ('other@example.com', 'scan', 404), (REPORT_OWNER, 'foreign', 404)])
def test_all_report_routes_require_owned_scan(report_bundle, owner, sid, status):
    _, bundle = report_bundle
    calls = [lambda: scans.get_release_reports(sid, request(owner), Response()),
             lambda: scans.download_release_report(sid, bundle['bundle_id'], 0, request(owner)),
             lambda: scans.retry_release_reports(sid, request(owner), Response())]
    for call in calls:
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == status


def test_foreign_bundle_and_invalid_asset_are_not_exposed(report_bundle):
    store, bundle = report_bundle
    store.init_scan_run('other-owned', 'sharepoint', 1, '2026-09-09', 'rubric', 'hash', owner=REPORT_OWNER, status='completed')
    for sid, bid, index in [('other-owned', bundle['bundle_id'], 0), ('scan', 'missing', 0), ('scan', bundle['bundle_id'], -1), ('scan', bundle['bundle_id'], 999)]:
        with pytest.raises(HTTPException) as exc:
            scans.download_release_report(sid, bid, index, request())
        assert exc.value.status_code == 404


def test_retry_registers_credentials_and_requeues_failed_bundle(report_bundle, monkeypatch):
    store, bundle = report_bundle
    calls = []
    monkeypatch.setattr(scans.core, 'register_scan_tokens', lambda sid, **kw: calls.append((sid, kw)))
    with store._db.cursor() as cur:
        store._db.execute(cur, "UPDATE release_report_bundles SET status='failed',error='temporary failure' WHERE id=%s", (bundle['bundle_id'],))
    response = Response()
    state = scans.retry_release_reports('scan', request(headers={'x-sp-token': 'test-token'}), response)
    assert state['status'] == 'queued' and state['error'] is None
    assert calls == [('scan', {'drive': None, 'sp': 'test-token', 'require_shared': True})]
    assert response.headers['cache-control'] == 'no-store'
    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT COUNT(*) AS n FROM jobs WHERE type='publish_release_reports'")
        assert store._db.fetchone(cur)['n'] == 2


def test_retry_maps_missing_and_conflict_errors(report_bundle, monkeypatch):
    monkeypatch.setattr(scans.core, 'register_scan_tokens', lambda *a, **kw: None)
    for error, status in [(KeyError('gone'), 404), (ValueError('Destination unavailable'), 409)]:
        def fail(*a, **kw):
            raise error
        monkeypatch.setattr(delivery, 'retry_release_reports', fail)
        with pytest.raises(HTTPException) as exc:
            scans.retry_release_reports('scan', request(), Response())
        assert exc.value.status_code == status


def test_route_capabilities():
    from workspace_capability_map import ROUTE_CAPABILITIES
    assert ROUTE_CAPABILITIES[('GET', '/scans/{sid}/release/reports')] == {'release.view'}
    assert ROUTE_CAPABILITIES[('GET', '/scans/{sid}/release/reports/{bundle_id}/{asset_index}')] == {'release.view'}
    assert ROUTE_CAPABILITIES[('POST', '/scans/{sid}/release/reports/retry')] == {'release.publish'}


def report_authorization(prepared):
    destination = flow.preview(prepared.store, SID, OWNER, [FILE])['destination']
    prepared.mode = 'receipt'
    return flow.authorize(prepared.store, SID, OWNER, prepared.run, [FILE], destination, 'reports-request', include_reports=True)


def test_automatic_completion_freezes_and_queues_reports(prepared, monkeypatch):
    row = report_authorization(prepared)
    calls = []
    def build(store, sid, owner, release_id):
        calls.append((sid, owner, release_id))
        assert persistence.get(store, row['id'], OWNER)['status'] != 'completed'
        return [{'name': 'scan-summary.html', 'content': b'<html>Frozen</html>', 'content_type': 'text/html'}]
    monkeypatch.setattr(release_reports, 'build_release_reports', build)
    result = tick(prepared, row)
    assert result['status'] == 'completed'
    assert len(calls) == 1
    assert delivery.get_latest_release_reports(prepared.store, SID, OWNER)['status'] == 'queued'
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur, "SELECT COUNT(*) AS n FROM jobs WHERE type='publish_release_reports'")
        assert prepared.store._db.fetchone(cur)['n'] == 1


def test_report_queue_failure_rolls_back_automatic_completion(prepared, monkeypatch):
    row = report_authorization(prepared)
    original_enqueue = prepared.store.enqueue_job
    def fail_report(kind, *a, **kw):
        if kind == 'publish_release_reports':
            raise RuntimeError('report queue unavailable')
        return original_enqueue(kind, *a, **kw)
    monkeypatch.setattr(prepared.store, 'enqueue_job', fail_report)
    with pytest.raises(RuntimeError, match='report queue unavailable'):
        tick(prepared, row)
    assert persistence.get(prepared.store, row['id'], OWNER)['status'] != 'completed'
    assert delivery.get_latest_release_reports(prepared.store, SID, OWNER)['status'] == 'not_started'
    # The successful document receipt stays durable; retrying finishes reports, not republishing.
    assert prepared.store.release_for_scan(SID, OWNER)['published'] == 1
    monkeypatch.setattr(prepared.store, 'enqueue_job', original_enqueue)
    result = tick(prepared, persistence.get(prepared.store, row['id'], OWNER))
    assert result['status'] == 'completed'
    assert len(prepared.calls) == 1
