"""A credential-cache outage is retryable, never proof that provider sign-in expired."""
import pytest
import core
import worker


class RedisRead:
    def __init__(self, value=None, failures=0):
        self.value, self.failures, self.calls = value, failures, 0

    def get(self, key):
        self.calls += 1
        if self.calls <= self.failures:
            raise ConnectionError('shared cache temporarily unavailable')
        return self.value


def configure(monkeypatch, client, local=None):
    monkeypatch.setattr(core, 'REDIS_URL', 'redis://synthetic')
    monkeypatch.setattr(core, 'SCAN_TOKENS', local or {})
    monkeypatch.setattr(core, '_get_redis', lambda: client)
    monkeypatch.setattr(core, '_reset_token_redis', lambda: None)
    monkeypatch.setattr(core._time, 'sleep', lambda _: None)
    monkeypatch.setattr(core, 'swallowed', lambda *a: None)


def test_unavailable_shared_reads_raise_retryable_error_without_inventing_auth_expiry(monkeypatch):
    client=RedisRead(failures=99);configure(monkeypatch,client)
    with pytest.raises(core.SharedTokenStoreUnavailable) as raised:
        core.get_scan_tokens('authorized-scan')
    assert client.calls==2
    assert worker.classify_job_error(raised.value)==worker.TRANSIENT
    assert worker.job_retry_policy(worker.TRANSIENT,1)[0] is False


def test_second_read_recovery_returns_actual_shared_tokens(monkeypatch):
    client=RedisRead('{"sp":"shared-token"}',failures=1);configure(monkeypatch,client)
    assert core.get_scan_tokens('authorized-scan')=={'sp':'shared-token'}
    assert client.calls==2


def test_second_read_successfully_missing_is_not_a_store_outage(monkeypatch):
    client=RedisRead(failures=1);configure(monkeypatch,client)
    assert core.get_scan_tokens('expired-scan')=={}
    assert client.calls==2


@pytest.mark.parametrize('value',[None,'{}'])
def test_successful_missing_credential_read_preserves_real_reconnect_result(monkeypatch,value):
    client=RedisRead(value);configure(monkeypatch,client)
    assert core.get_scan_tokens('expired-scan')=={}
    assert client.calls==1
    assert worker.classify_job_error(worker.FatalJobError('SharePoint session expired — reconnect and retry'))==worker.AUTH


def test_usable_local_compatibility_tokens_survive_shared_outage(monkeypatch):
    client=RedisRead(failures=99);configure(monkeypatch,client,{'scan':{'drive':'local-token'}})
    assert core.get_scan_tokens('scan')=={'drive':'local-token'}
    assert client.calls==2


@pytest.mark.parametrize('max_attempts,expected_status',[(3,'queued'),(1,'dead')])
def test_real_worker_retries_cache_outage_with_existing_attempt_cap(isolated_store,monkeypatch,max_attempts,expected_status):
    client=RedisRead(failures=99);configure(monkeypatch,client)
    provider_calls=[]
    def publish_probe(payload,job):
        token=core.get_scan_tokens('authorized-scan').get('sp')
        if not token:
            raise worker.FatalJobError('SharePoint session expired — reconnect and retry')
        provider_calls.append(token)
    monkeypatch.setitem(worker.HANDLERS,'credential_read_probe',publish_probe)
    job_id=isolated_store.enqueue_job('credential_read_probe',{},max_attempts=max_attempts)
    assert worker.JobWorker(isolated_store,worker_id='token-recovery-test').run_once()
    job=isolated_store.get_job(job_id)
    assert job['status']==expected_status and job['attempts']==1
    assert job['error_class']==worker.TRANSIENT
    assert not provider_calls
    if expected_status=='queued':
        client.failures=0;client.value='{"sp":"shared-token"}'
        with isolated_store._db.cursor() as cur:
            isolated_store._db.execute(cur,"UPDATE jobs SET run_after='2000-01-01T00:00:00+00:00' WHERE id=%s",(job_id,))
        assert worker.JobWorker(isolated_store,worker_id='token-recovery-test').run_once()
        assert isolated_store.get_job(job_id)['status']=='done'
        assert provider_calls==['shared-token']


def test_real_worker_still_stops_for_successful_missing_shared_credentials(isolated_store,monkeypatch):
    configure(monkeypatch,RedisRead())
    def missing_session(payload,job):
        assert core.get_scan_tokens('expired-scan')=={}
        raise worker.FatalJobError('SharePoint session expired — reconnect and retry')
    monkeypatch.setitem(worker.HANDLERS,'missing_credential_probe',missing_session)
    job_id=isolated_store.enqueue_job('missing_credential_probe',{},max_attempts=3)
    assert worker.JobWorker(isolated_store,worker_id='missing-token-test').run_once()
    assert isolated_store.get_job(job_id)['status']=='dead'


@pytest.mark.parametrize('source',['drive','sharepoint'])
def test_real_publish_handler_outage_never_records_expired_session_or_requests_reconnect(isolated_store,monkeypatch,source):
    import handlers
    import automatic_release
    import automatic_release_store
    import publish
    store=isolated_store
    owner,sid,file='owner@example.test','token-outage','report.docx'
    with store._db.cursor() as cur:
        store._db.execute(cur,"INSERT INTO scan_runs(id,owner_email,status,source) VALUES(%s,%s,'done',%s)",(sid,owner,source))
        store._db.execute(cur,"INSERT INTO file_records(scan_id,file,compliant,corrected_sha256,remediated_at) VALUES(%s,%s,1,%s,'2026-09-13')",(sid,file,'1'*64))
    release=store.ensure_release_execution(sid,owner,source,1)
    monkeypatch.setattr(core,'store',store)
    configure(monkeypatch,RedisRead(failures=99))
    effects=[]
    monkeypatch.setattr(handlers,'_release_failure',lambda *a,**k:effects.append('expired-session'))
    monkeypatch.setattr(automatic_release_store,'update_file',lambda *a,**k:effects.append('reconnect'))
    monkeypatch.setattr(handlers,'_drive_client',lambda *a,**k:effects.append('drive-client'))
    monkeypatch.setattr(publish,'archive_copy_publish_sharepoint',lambda *a,**k:effects.append('sharepoint-upload'))
    monkeypatch.setattr(publish,'archive_copy_publish',lambda *a,**k:effects.append('drive-upload'))
    monkeypatch.setattr(publish,'ensure_sharepoint_release_folder',lambda *a,**k:effects.append('sharepoint-folder'))
    # Admission belongs to separate frozen-artifact tests. Here an admitted callback
    # reaches the real publish entry point and real owned scan/release/ready-file reads.
    monkeypatch.setattr(automatic_release,'publish_job',lambda s,p,j,callback:callback(p,j))
    payload={'scan_id':sid,'file':file,'owner':owner,'release_id':release['id'],'automatic_release_id':'admitted'}
    with pytest.raises(core.SharedTokenStoreUnavailable):
        handlers._publish_file(payload,{'scan_id':sid})
    assert effects==[]
    assert store.get_release_document(release['id'],file,owner) is None
