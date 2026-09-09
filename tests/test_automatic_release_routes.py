"""Authorization API and actual publish queue use isolated storage/provider fakes."""
from types import SimpleNamespace
import json
import pytest
from fastapi import Response, HTTPException
from test_automatic_release_service import prepared, authorize, OWNER, SID, FILE, DIGEST
from routes.scans import publish_files as real_publish
from routes.automatic_release import status, authorize as authorize_route, stop, AuthorizationRequest
import automatic_release as flow
import automatic_release_store as persistence


def request(owner=OWNER):
    return SimpleNamespace(state=SimpleNamespace(user_email=owner),headers={'x-sp-token':'fixture-only'})


def test_api_read_post_restore_stop_exact_owner_contract(prepared,monkeypatch):
    import routes.automatic_release as route
    monkeypatch.setattr(route,'credentials',lambda *a:None)
    monkeypatch.setattr(route,'_preflight_release_destination',lambda *a:{'ready':True})
    response=Response()
    initial=status(SID,request(),response,[FILE])
    assert initial['authorization'] is None and initial['available']
    assert response.headers['cache-control']=='no-store'
    body=AuthorizationRequest(run_id=prepared.run,files=[FILE],destination=initial['destination'],request_id='route-request')
    row=authorize_route(SID,body,request(),Response())
    assert row['run_id']==prepared.run and row['files']==[FILE] and row['status']=='active'
    assert row['progress']==dict(published=0,pending=1,blocked=0,failed=0)
    assert row['destination_label'].startswith('SharePoint / ')
    changed_selection=status(SID,request(),Response(),['other.pptx'])
    assert changed_selection['authorization']['id']==row['id']
    stopped=stop(SID,row['id'],request(),Response())
    assert stopped['status']=='stopped'
    assert authorize_route(SID,body,request(),Response())['status']=='stopped'
    with pytest.raises(HTTPException):stop(SID,row['id'],request('other'),Response())
    with pytest.raises(HTTPException):stop('other-scan',row['id'],request(),Response())


def test_actual_publish_queue_forwards_exact_automatic_authority(prepared,monkeypatch):
    import core
    from routes import scans
    monkeypatch.setattr(scans,'_preflight_release_destination',lambda *a:{'ready':True})
    monkeypatch.setattr(core,'register_scan_tokens',lambda *a,**kw:None)
    row=authorize(prepared)
    flow.publish_admission(prepared.store,row['id'],OWNER,SID,FILE,DIGEST)
    body=dict(files=[FILE],automatic_release_id=row['id'],destination=row['intent']['destination'],
              expected_destination=row['intent']['destination'],release_folder_name=row['intent']['release_folder_name'],expected_artifacts={FILE:DIGEST})
    result=real_publish(SID,request(),body)
    assert result['queued']==1
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur,"SELECT payload FROM jobs WHERE batch_id=%s AND type='publish_file'",(result['batch_id'],))
        jobs=[json.loads(r['payload']) for r in prepared.store._db.fetchall(cur)]
    assert len(jobs)==1 and jobs[0]['automatic_release_id']==row['id']
    assert jobs[0]['artifact_digest']=='sha256:'+DIGEST
    assert 'token' not in json.dumps(jobs)
    persistence.stop(prepared.store,row['id'],OWNER)
    import handlers
    monkeypatch.setattr(handlers,'_publish_file_guarded',lambda *a:pytest.fail('stopped automatic delivery reached provider path'))
    from worker import FatalJobError
    with pytest.raises(FatalJobError):handlers._publish_file(jobs[0],{})
    with pytest.raises(HTTPException):real_publish(SID,request(),body)


def test_publish_route_rejects_forged_scope_or_unadmitted_artifact(prepared):
    row=authorize(prepared)
    body=dict(files=[FILE],automatic_release_id=row['id'],destination=row['intent']['destination'],
              release_folder_name=row['intent']['release_folder_name'],expected_artifacts={FILE:DIGEST})
    with pytest.raises(HTTPException):real_publish(SID,request(),body)
    flow.publish_admission(prepared.store,row['id'],OWNER,SID,FILE,DIGEST)
    for changed in ({'files':['outside.pptx']},{'expected_artifacts':{FILE:'b'*64}},{'automatic_release_id':'forged'}):
        with pytest.raises(HTTPException):real_publish(SID,request(),{**body,**changed})


def test_automatic_release_capabilities_do_not_grant_review_authority():
    from workspace_capability_map import ROUTE_CAPABILITIES
    assert ROUTE_CAPABILITIES[('GET','/scans/{sid}/release/automatic')] == {'release.view'}
    for path in ('/scans/{sid}/release/automatic','/scans/{sid}/release/automatic/{authorization_id}/stop'):
        assert ROUTE_CAPABILITIES[('POST',path)] == {'release.publish'}
