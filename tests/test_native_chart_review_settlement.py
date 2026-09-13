"""Original drafts settle only after exact saved-chart writing and actual recheck."""
from hashlib import sha256
import io
import zipfile
import pytest
from ai_run_policy import run_context
from proposals import Verification
import chart_data
import proposals
from native_chart_review_settlement import settle
from test_chart_data import _native_chart_pptx
from chart_fixtures import rezip

OWNER='chart-owner@example.com'; SID='chart-settle'; FILE='chart.pptx'

def setup_case(store,tmp_path):
    original=_native_chart_pptx(['A','B','C'],[10,30,20])
    with zipfile.ZipFile(io.BytesIO(original)) as z: entries={n:z.read(n) for n in z.namelist()}
    edits=chart_data.chart_descr_edits(entries,'.pptx')
    corrected=rezip({**entries,**{n:v[0] for n,v in edits.items()}})
    with store._db.cursor() as cur:
        store._db.execute(cur,"INSERT INTO scan_runs(id,owner_email,status,source) VALUES(%s,%s,'done','local')",(SID,OWNER))
        store._db.execute(cur,"INSERT INTO file_records(scan_id,file,corrected_sha256,remediated_at) VALUES(%s,%s,%s,'2026-09-13')",(SID,FILE,sha256(corrected).hexdigest()))
    batch=store.enqueue_stage_batch(SID,'remediate','remediate_file',[{'scan_id':SID,'file':FILE,'owner':OWNER,'source':'local','remediation_impact_policy':{'rule_based':2,'ai':1,'ai_budget_usd':'1.00'}}],snapshot_id=store.remediation_source_revision(SID),request_fingerprint='charts')
    job=store.get_job(batch['job_ids'][0])
    path=tmp_path/FILE;path.write_bytes(original)
    with run_context(store,job['payload'],job):
        item=store.enqueue_proposals(SID,FILE,'1.1.1',proposals.propose_chart_datasheet(path,'.pptx'))
    return job,item,original,corrected


def test_exact_chart_row_closes_only_after_actual_corrected_file_recheck(isolated_store,tmp_path):
    s=isolated_store;job,item,original,corrected=setup_case(s,tmp_path)
    assert s.get_hitl_item(item)['status']=='pending'
    assert settle(s,job,SID,FILE,original,corrected,Verification(False,set(),'unavailable')) == []
    assert settle(s,job,SID,FILE,original,corrected,Verification(True,{'1.1.1'})) == []
    assert settle(s,job,SID,FILE,original,corrected,Verification(True,set())) == [item]
    row=s.get_hitl_item(item)
    assert row['status']=='approved' and row['applied'] and row['validated']
    assert 'B at 30' in row['proposals'][0]['approved_value']
    assert 'model_call_id' not in row['proposals'][0]
    assert row['approved_proposal_snapshot_ids'] == row['proposal_snapshot_ids']
    assert row['approved_value_sha256']
    assert settle(s,job,SID,FILE,original,corrected,Verification(True,set())) == []


@pytest.mark.parametrize('mutation',['mixed','partial_count','changed_proposal','changed_snapshot','changed_hash','cancel','source','reviewed'])
def test_stale_or_mixed_chart_row_never_silently_disappears(isolated_store,tmp_path,mutation):
    s=isolated_store;job,item,original,corrected=setup_case(s,tmp_path)
    with s._db.cursor() as cur:
        if mutation=='mixed':s._db.execute(cur,"UPDATE hitl_queue SET finding_count=2 WHERE id=%s",(item,))
        if mutation=='partial_count':s._db.execute(cur,"UPDATE hitl_queue SET finding_count=3 WHERE id=%s",(item,))
        if mutation=='changed_proposal':s._db.execute(cur,"UPDATE hitl_queue SET proposals='[]',decision_version=decision_version+1 WHERE id=%s",(item,))
        if mutation=='changed_snapshot':s._db.execute(cur,"UPDATE hitl_queue SET proposal_snapshot_ids='[]' WHERE id=%s",(item,))
        if mutation=='changed_hash':s._db.execute(cur,"UPDATE file_records SET corrected_sha256='changed' WHERE scan_id=%s",(SID,))
        if mutation=='cancel':s._db.execute(cur,"UPDATE stage_executions SET cancel_requested_at='2026-09-13' WHERE execution_id=%s",(job['batch_id'],))
        if mutation=='source':s._db.execute(cur,"UPDATE scan_runs SET scope='changed' WHERE id=%s",(SID,))
        if mutation=='reviewed':s._db.execute(cur,"UPDATE hitl_queue SET status='rejected',decision_version=decision_version+1 WHERE id=%s",(item,))
    assert settle(s,job,SID,FILE,original,corrected,Verification(True,set())) == []
    assert s.get_hitl_item(item)['status'] == ('rejected' if mutation=='reviewed' else 'pending')


def test_concurrent_review_version_change_wins_over_deterministic_settlement(isolated_store,tmp_path,monkeypatch):
    s=isolated_store;job,item,original,corrected=setup_case(s,tmp_path)
    execute=s._db.execute
    changed=False
    def concurrent(cur,sql,params=()):
        nonlocal changed
        if sql.startswith("UPDATE hitl_queue SET status='approved'") and not changed:
            changed=True
            execute(cur,"UPDATE hitl_queue SET decision_version=decision_version+1 WHERE id=%s",(item,))
        return execute(cur,sql,params)
    monkeypatch.setattr(s._db,'execute',concurrent)
    assert settle(s,job,SID,FILE,original,corrected,Verification(True,set())) == []
    assert changed and s.get_hitl_item(item)['status']=='pending'


def test_actual_mixed_chart_image_proposals_keep_the_full_review_count(isolated_store,tmp_path):
    s=isolated_store;job,item,original,corrected=setup_case(s,tmp_path)
    native=s.get_hitl_item(item)['proposals'][0]
    with run_context(s,job['payload'],job):
        s.enqueue_proposals(SID,FILE,'1.1.1',[native,{'locator':'image 1','proposed_value':'Image awaiting grounding','before':'No alt','source':'AI draft'}],finding_count=2)
    assert settle(s,job,SID,FILE,original,corrected,Verification(True,set())) == []
    assert s.get_hitl_item(item)['finding_count']==2
    assert s.get_hitl_item(item)['status']=='pending'


def test_changed_referenced_cells_cannot_settle_against_identical_chart_xml(tmp_path):
    import openpyxl, re
    from openpyxl.chart import LineChart, Reference
    wb=openpyxl.Workbook(); ws=wb.active
    ws.append(['Category','Value']); ws.append(['A',10]); ws.append(['B',20]); ws.append(['C',30])
    chart=LineChart(); chart.add_data(Reference(ws,min_col=2,min_row=1,max_row=4),titles_from_data=True)
    chart.set_categories(Reference(ws,min_col=1,min_row=2,max_row=4));ws.add_chart(chart,'D2')
    path=tmp_path/'cells.xlsx';wb.save(path);original=path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(original)) as z: old={n:z.read(n) for n in z.namelist()}
    changed=dict(old)
    changed['xl/worksheets/sheet1.xml']=changed['xl/worksheets/sheet1.xml'].replace(b'<v>20</v>',b'<v>999</v>')
    assert changed['xl/worksheets/sheet1.xml'] != old['xl/worksheets/sheet1.xml']
    edits=chart_data.chart_descr_edits(changed,'.xlsx')
    current={**changed,**{n:value[0] for n,value in edits.items()}}
    chart_part=next(n for n in old if chart_data._CHART_PART.match(n))
    assert old[chart_part] == current[chart_part]
    assert chart_data.has_exact_chart_data_alt(current,'.xlsx',chart_part)
    assert '999' in chart_data.exact_numeric_chart_description(chart_data.parse_chart_part(current[chart_part],current,chart_part))
    # Refuse before any database writes despite a currently exact caption on the
    # changed data; that is not the repair for the originally assessed dataset.
    assert settle(object(),{'id':'job'},SID,'cells.xlsx',original,rezip(current),Verification(True,set())) == []
