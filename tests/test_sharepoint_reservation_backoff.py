"""A live or uncertain Graph upload must not exhaust retries before its lease ends."""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from test_sharepoint_release_worker import FakeStore, DIGEST, FILE, OWNER, SID


@pytest.mark.parametrize('scenario', ['busy', 'response_lost'])
def test_real_publish_worker_waits_for_sharepoint_reservation(isolated_store, monkeypatch, scenario):
    import core
    import handlers
    import publish
    import release_candidate_assessment
    import worker

    store = FakeStore()
    start = datetime.now(timezone.utc)
    store.reserve_side_effect = lambda **kwargs: {
        'effect_id': 'effect-1', 'status': 'reserved', 'acquired': scenario == 'response_lost',
        'reclaimed': False, 'reused': False, 'reservation_token': 'reservation-1',
        'lease_expires_at': (start + timedelta(seconds=240)).isoformat(),
    }
    calls = []

    def upload(*args, **kwargs):
        calls.append('upload')
        assert scenario == 'response_lost', 'a busy reservation must never upload'
        response = httpx.Response(503, request=httpx.Request('PUT', 'https://graph.test/copy'))
        raise httpx.HTTPStatusError('temporary Graph response failure', request=response.request,
                                    response=response)

    monkeypatch.setattr(core, 'store', store)
    monkeypatch.setattr(core, 'get_scan_tokens', lambda sid: {'sp': 'fixture-token'})
    monkeypatch.setattr(publish._blob, 'download_remediated', lambda *args: b'corrected fixture')
    monkeypatch.setattr(publish, 'ensure_sharepoint_release_folder',
                        lambda *args: {'id': 'root-1', 'name': 'release', 'url': 'https://graph.test/root'})
    monkeypatch.setattr(publish, 'archive_copy_publish_sharepoint', upload)
    # This fixture isolates reservation timing; actual corrected-document reassessment
    # is exercised by the managed caption and release candidate suites.
    monkeypatch.setattr(release_candidate_assessment, 'assess_candidate',
                        lambda *args, **kwargs: {'artifact_sha256': DIGEST})
    jid = isolated_store.enqueue_job('publish_file',
        {'scan_id': SID, 'release_id': 'release-1', 'file': FILE, 'owner': OWNER},
        batch_id='execution-1')
    runner = worker.JobWorker(isolated_store, job_types=['publish_file'])
    assert runner.run_once()
    job = isolated_store.get_job(jid)
    assert job['status'] == 'queued' and job['attempts'] == 1
    assert (datetime.fromisoformat(job['run_after']) - start).total_seconds() >= 240
    assert not runner.run_once(), 'the queue must not retry while the upload lease is held'
    assert calls == (['upload'] if scenario == 'response_lost' else [])
    assert store.published is None and not store.documents
