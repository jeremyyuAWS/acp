"""Later unrelated edits and presence scans cannot discharge semantic review."""
import json
from hashlib import sha256

from unverified_changes import pending_records, record_verification
from proposals import Verification


def seed(store):
    with store._db.cursor() as cur:
        store._db.execute(cur,"INSERT INTO scan_runs(id,status) VALUES('scan','done')")
        store._db.execute(cur,"INSERT INTO file_records(scan_id,file,corrected_sha256) VALUES('scan','file.docx',%s)",(sha256(b'later').hexdigest(),))
        store._db.execute(cur,"INSERT INTO ai_validation_outcomes(id,scan_id,file,rule_id,outcome,source_revision,actual_source_sha256,artifact_sha256) VALUES('later-write','scan','file.docx','2.4.2','verified_cleared','revision',%s,%s)",('ai-artifact',sha256(b'later').hexdigest()))
    store.log_decision('system','apply.saved_unverified',scan_id='scan',file='file.docx',rule_id='1.1.1',
        detail=json.dumps({'artifact_sha256':'ai-artifact','source_sha256':'original',
          'requires_semantic_review':True,'assessment_revision':'revision','item_ids':['image'],
          'changes':[{'locator':'word/document.xml#Picture 1','after':'A green square'}]}))


def test_later_other_criterion_write_preserves_semantic_pending(isolated_store):
    store=isolated_store;seed(store)
    rows=pending_records(store,'scan','file.docx')
    assert len(rows)==1
    assert rows[0]['applied_artifact_sha256']=='ai-artifact'
    assert rows[0]['artifact_sha256']==sha256(b'later').hexdigest()
    assert record_verification(store,'scan','file.docx',b'later',Verification(True,set()))==0
    assert len(pending_records(store,'scan','file.docx'))==1


def test_new_assessment_revision_alone_is_not_semantic_verification(isolated_store):
    store=isolated_store;seed(store)
    with store._db.cursor() as cur:
        store._db.execute(cur,"UPDATE ai_validation_outcomes SET source_revision='later-assessment' WHERE id='later-write'")
    assert len(pending_records(store,'scan','file.docx'))==1


def test_disconnected_artifact_does_not_inherit_old_obligation(isolated_store):
    store=isolated_store;seed(store)
    with store._db.cursor() as cur:
        store._db.execute(cur,"UPDATE file_records SET corrected_sha256='unrelated-source' WHERE scan_id='scan'")
    assert pending_records(store,'scan','file.docx')==[]


import pytest


@pytest.mark.parametrize('action,time,expected', [('approve','2999-01-01',0),('standing_approve','2999-01-01',1),('approve','2000-01-01',1)])
def test_only_later_exact_human_verified_receipt_clears(isolated_store,action,time,expected):
    store=isolated_store;seed(store)
    with store._db.cursor() as cur:
        store._db.execute(cur,"INSERT INTO hitl_events(id,scan_id,file,rule_id,item_id,action,approved_value_sha256,proposal_snapshot_ids) VALUES('human','scan','file.docx','1.1.1','image',%s,'value','[\"proposal\"]')",(action,))
        store._db.execute(cur,"INSERT INTO ai_validation_outcomes(id,scan_id,file,rule_id,item_id,outcome,artifact_sha256,approval_event_id,proposal_snapshot_id,actual_approved_value_sha256,created_at) VALUES('confirmation','scan','file.docx','1.1.1','image','verified_cleared',%s,'human','proposal','value',%s)",(sha256(b'later').hexdigest(),time))
    assert len(pending_records(store,'scan','file.docx'))==expected
