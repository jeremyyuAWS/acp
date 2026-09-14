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
