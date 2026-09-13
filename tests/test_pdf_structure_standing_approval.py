"""Production PDF tag drafts require human approval; maps never tag a PDF."""
from hashlib import sha256
from pathlib import Path
import io

import pikepdf
import pytest
import blob
from ai_run_policy import run_context
from ai_standing_approval import approve_file, eligible_item
from release_continuation import eligibility, PDF_STRUCTURE_MANUAL, PDF_STRUCTURE_REVIEW
from automatic_review_queue import HUMAN_REASONS
import test_ai_standing_approval as standing
from test_pdf_structure_repairs import fixture
from pdf_structure_repairs import apply_pdf_structure_repairs, collect_structure_targets
from remediate_pdf import remediate_pdf


@pytest.mark.parametrize('rule,kind',[('1.3.1','pdf-table-header-scope'),('2.4.6','pdf-tag-heading')])
def test_actual_native_producer_requires_human_approval_then_writes_saved_tags(isolated_store,monkeypatch,tmp_path,rule,kind):
    source=tmp_path/'tagged.pdf';source.write_bytes(fixture())
    proposals=[]
    saved,_,_=remediate_pdf(source,ai_enabled=False,proposals=proposals)
    data=Path(saved).read_bytes() if saved else source.read_bytes()
    drafts=[p for p in proposals if p.get('kind')==kind]
    assert drafts and all(not p.get('model') and not p.get('model_call_id') for p in drafts)
    store=isolated_store
    monkeypatch.setattr(standing,'FILE','tagged.pdf')
    monkeypatch.setattr(standing,'DIGEST',sha256(data).hexdigest())
    monkeypatch.setattr(blob,'download_remediated',lambda *args:data)
    job=standing.seed(store,monkeypatch)
    with run_context(store,job['payload'],job) as ctx:
        item=store.enqueue_proposals(standing.SID,standing.FILE,rule,drafts)
        row=store.get_hitl_item(item)
        assert eligibility(row,standing.FILE) is None  # real writer, explicit human consent only
        with pytest.raises(ValueError,match='deterministic draft'):
            eligible_item(store,standing.OWNER,standing.SID,ctx.run_id,row)
        approve_file(store,ctx)
    assert store.get_hitl_item(item)['status']=='pending'
    assert not standing.apply_jobs(store)
    assert PDF_STRUCTURE_REVIEW in HUMAN_REASONS
    # The existing human-decision path produces concrete values for the normal writer.
    row=store.get_hitl_item(item)
    updated,replay=store.complete_hitl_decision(item,'approved','Reviewed existing tags',None,
        detail='Explicit human review',resolution=None,approved_values=[p['proposed_value'] for p in drafts],actor=standing.OWNER,
        request_id='human-native-tags',expected_version=row['decision_version'],
        expected_proposal_snapshot_ids=row['proposal_snapshot_ids'],
        expected_source_revision=store.remediation_source_revision(standing.SID))
    assert updated and not replay
    values=store.approved_pdf_structure_values(standing.SID,standing.FILE,rule)
    candidate,edits,unresolved=apply_pdf_structure_repairs(data,values)
    assert candidate!=data and len(edits)==len(drafts) and not unresolved
    with pikepdf.open(io.BytesIO(candidate)) as pdf:
        tags=collect_structure_targets(pdf)
        if rule=='2.4.6':
            assert any(r['text']=='Introduction' and r['role']=='/H1' for r in tags)
        else:
            table=pdf.Root['/StructTreeRoot']['/K'][0]['/K'][2]
            assert str(table['/K'][0]['/K'][0]['/A']['/Scope'])=='/Column'
    if rule=='2.4.6':
        from office_structure import pdf_headings_labels_check
        source.write_bytes(data);assert pdf_headings_labels_check(source)
        source.write_bytes(candidate);assert pdf_headings_labels_check(source)==[]
    assert not store.get_hitl_item(item)['applied'] and not store.get_hitl_item(item)['validated']


@pytest.mark.parametrize('rule',['1.3.1','2.4.6'])
def test_map_only_is_specific_human_work_and_cannot_enter_writer(rule):
    row={'status':'pending','rule_id':rule,'proposals':[{'locator':'page:1','kind':'pdf-structure',
        'proposed_value':'Heading 1: Introduction','explain_only':True}],
        'proposal_snapshot_ids':['snapshot'],'finding_count':1,'decision_version':0}
    assert eligibility(row,'untagged.pdf')==PDF_STRUCTURE_MANUAL
    assert PDF_STRUCTURE_MANUAL in HUMAN_REASONS
    if rule=='1.3.1':
        assert eligibility(row,'manual.docx')=='Manual work or no supported proposal writer'


def test_word_structure_is_already_written_automatically_without_ai_approval(tmp_path):
    from test_docx_structural_dispatch import fixture as word_fixture, scan
    from remediate_office import remediate_office
    source=tmp_path/'word.docx';word_fixture(source)
    assert {i['detail'] for i in scan(source)} >= {'No H1 heading found','Table has no header row'}
    changes=[]
    saved,_,_=remediate_office(source,ai_enabled=False,diffs=changes,in_scope=lambda sc:sc=='1.3.1')
    assert saved and scan(Path(saved))==[]
    assert len([change for change in changes if change['rule_id']=='1.3.1'])==2
