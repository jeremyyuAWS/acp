import pytest
from release_artifacts import ReleaseArtifactError
from saved_copy_verification import verify_saved_copy, current_assessment


def test_missing_version_never_runs_detectors(monkeypatch):
    monkeypatch.setattr('saved_copy_verification.assess_candidate',lambda *a,**k:pytest.fail('must not run'))
    with pytest.raises(ReleaseArtifactError):verify_saved_copy(object(),'scan','owner','x.docx','',None)


def test_verification_only_checks_exact_candidate_without_delivery(monkeypatch):
    calls=[]
    monkeypatch.setattr('saved_copy_verification.assess_candidate',lambda *a,**k:calls.append((a,k)) or {'assessment_ok':True})
    assert verify_saved_copy('store','scan','owner','x.docx','sha','at')=={'assessment_ok':True}
    assert calls==[(('store','scan','x.docx','owner','sha','at'),{'allow_remaining_issues':True})]


def test_stale_timestamp_not_projected(monkeypatch):
    class Store:
        def get_file_records(self,*a,**k):
            assert k['owner']=='owner'
            return {'x.docx':{'corrected_sha256':'sha','remediated_at':'new'}}
    monkeypatch.setattr('saved_copy_verification.saved_assessment',lambda *a,**k:{'artifact_sha256':'sha','remediated_at':'old'})
    assert current_assessment(Store(),'scan','owner','x.docx') is None


def test_retry_route_rejects_wrong_owner(monkeypatch):
    from types import SimpleNamespace
    from routes import scans
    from fastapi import HTTPException
    class Store:
        def get_scan(self,sid,owner=None):return None
    monkeypatch.setattr(scans.core,'store',Store())
    request=SimpleNamespace(state=SimpleNamespace(user_email='other'),headers={})
    with pytest.raises(HTTPException) as error:
        scans.retry_saved_copy_verification('scan',scans.SavedCopyVerificationRequest(file='x.docx',corrected_sha256='sha',remediated_at='at'),request)
    assert error.value.status_code==404


def test_real_saved_bytes_rechecked_without_rewriting(candidate, monkeypatch):
    monkeypatch.setattr('verification_identity.evaluator_identity', lambda: 'test-evaluator')
    from test_release_candidate_assessment import SID,OWNER,FILE
    store,state,save=candidate
    digest,at=save(state['bytes']);before=state['bytes']
    evidence=verify_saved_copy(store,SID,OWNER,FILE,digest,at)
    assert evidence['artifact_sha256']==digest
    assert evidence['assessment_ok'] is True
    assert evidence['remaining_criteria']==['1.1.1']
    assert state['bytes']==before
    assert store.get_file_record(SID,FILE)['remediated_at']==at
    assert store.release_for_scan(SID,OWNER) is None
    assert current_assessment(store,SID,OWNER,FILE)==evidence
    with pytest.raises(ReleaseArtifactError):verify_saved_copy(store,SID,OWNER,FILE,'old',at)


from test_release_candidate_assessment import candidate


def test_reuse_checks_actual_bytes_and_pending_writes(candidate,monkeypatch):
    from test_release_candidate_assessment import SID,OWNER,FILE
    monkeypatch.setattr('verification_identity.evaluator_identity',lambda:'test-evaluator')
    store,state,save=candidate
    digest,at=save(state['bytes'])
    first=verify_saved_copy(store,SID,OWNER,FILE,digest,at)
    monkeypatch.setattr('proposals.verify_residual',lambda *a,**k:pytest.fail('unchanged successful check must not rerun'))
    assert verify_saved_copy(store,SID,OWNER,FILE,digest,at)['assessment_reused'] is True
    original=state['bytes'];state['bytes']=b'changed actual bytes'
    with pytest.raises(ReleaseArtifactError):verify_saved_copy(store,SID,OWNER,FILE,digest,at)
    state['bytes']=original
    monkeypatch.setattr(store,'count_unapplied_approved_values',lambda *a:1)
    with pytest.raises(ReleaseArtifactError) as error:verify_saved_copy(store,SID,OWNER,FILE,digest,at)
    assert error.value.category=='approved_changes_unapplied'


def test_failed_incomplete_or_changed_evaluator_and_scope_rerun(candidate,monkeypatch):
    from test_release_candidate_assessment import SID,OWNER,FILE
    monkeypatch.setattr('verification_identity.evaluator_identity',lambda:'test-evaluator')
    store,state,save=candidate;digest,at=save(state['bytes'])
    first=verify_saved_copy(store,SID,OWNER,FILE,digest,at)
    calls=[]
    monkeypatch.setattr('saved_copy_verification.assess_candidate',lambda *a,**k:calls.append(1) or {'reran':True})
    monkeypatch.setattr('verification_identity.evaluator_identity',lambda:'new-evaluator')
    assert verify_saved_copy(store,SID,OWNER,FILE,digest,at)=={'reran':True}
    monkeypatch.setattr('verification_identity.evaluator_identity',lambda:'test-evaluator')
    monkeypatch.setattr(store,'scope_for_file',lambda *a:{'1.3.1':['docx']})
    assert verify_saved_copy(store,SID,OWNER,FILE,digest,at)=={'reran':True}
    monkeypatch.setattr(store,'scope_for_file',lambda sid,file,scope:scope)
    for override in [{'assessment_ok':False},{'skipped_rules':2}]:
        monkeypatch.setattr('saved_copy_verification.current_assessment',lambda *a,**k:{**first,**override})
        assert verify_saved_copy(store,SID,OWNER,FILE,digest,at)=={'reran':True}
    assert len(calls)==4


from test_capability_enforcement import client


def test_http_saved_copy_verification_requires_run_capability_and_owned_scan(client,monkeypatch):
    import workspace_roles as wr
    from test_capability_enforcement import OWNER,REVIEWER,ANALYST
    tc,core,store=client
    monkeypatch.setenv(wr.FLAG,'1')
    monkeypatch.setattr(store,'get_scan',lambda sid,owner=None:{'files':[]} if owner==REVIEWER else None)
    calls=[]
    monkeypatch.setattr('saved_copy_verification.verify_saved_copy',lambda *args:calls.append(args) or {'assessment_ok':True})
    body={'file':'actual.docx','corrected_sha256':'a'*64,'remediated_at':'now'}
    path='/scans/owned-scan/verify-saved-copy'
    assert tc.post(path,json=body).status_code==401
    assert tc.post(path,json=body,headers={'Authorization':f'Bearer {ANALYST}'}).status_code==403
    assert tc.post(path,json=body,headers={'Authorization':f'Bearer {OWNER}'}).status_code==404
    result=tc.post(path,json=body,headers={'Authorization':f'Bearer {REVIEWER}'})
    assert result.status_code==200
    assert len(calls)==1 and calls[0][2]==REVIEWER
