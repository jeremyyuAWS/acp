"""Selected SCs constrain cached evidence, proposal work and residual verification."""
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'api'))
import store as store_mod
import handlers
import proposals
from assessment_selection import selection

NARROW = {'1.1.1': frozenset({'docx'})}
WIDE = {**NARROW, '1.3.1': frozenset({'docx'})}

@pytest.mark.parametrize('prior,current,expected', [(NARROW,WIDE,False),(WIDE,NARROW,True),(NARROW,None,False),(None,NARROW,True),(NARROW,NARROW,True)])
def test_reuse_requires_measured_scope(prior,current,expected):
    st = SimpleNamespace(get_scan_scope=lambda sid: prior if sid == 'old' else current,
                         scope_for_file=lambda sid,name,scope: scope)
    assert store_mod.Store._analysis_covers_scope(st,'old','a.docx','new','a.docx') is expected


def test_same_scan_different_folder_selection_is_not_duplicate():
    st = SimpleNamespace(get_scan_scope=lambda sid: WIDE,
                         scope_for_file=lambda sid,name,scope: NARROW if name == 'a.docx' else WIDE)
    assert not store_mod.Store._analysis_covers_scope(st,'same','a.docx','same','b.docx')


def test_remediation_respects_file_scope_and_fails_closed(monkeypatch):
    st = SimpleNamespace(get_scan_scope=lambda sid: WIDE,
                         scope_for_file=lambda sid,name,scope: NARROW)
    monkeypatch.setattr(handlers.core,'store',st)
    allows = handlers._remediation_scope('a.docx','scan')
    assert allows('1.1.1') and not allows('1.3.1')
    st.get_scan_scope = lambda sid: (_ for _ in ()).throw(RuntimeError('unavailable'))
    with pytest.raises(RuntimeError):
        handlers._remediation_scope('a.docx','scan')


def test_unselected_proposers_do_not_read_file_or_call_ai():
    with selection({'1.1.1'}):
        assert proposals.propose_section_headings(Path('/absent.docx'),'.docx') == []
        assert proposals.propose_images_of_text(Path('/absent.docx'),'.docx') == []
        assert proposals.propose_sensory_rewrite('click the red button') == []


def test_verification_carries_original_scan_scope(monkeypatch):
    import scanner
    seen=[]
    def assess(path,filename,**kw):
        seen.append(kw)
        return {'status':'analysed','issues':[]},None
    monkeypatch.setattr(scanner,'analyse_and_assess',assess)
    assert proposals.verify_residual(b'fixture','a.docx',scan_id='selected-scan').ok
    assert seen == [{'detect_pii':False,'scan_id':'selected-scan'}]


def test_store_rejects_prior_analysis_with_unmeasured_criteria(monkeypatch,tmp_path):
    monkeypatch.setattr(store_mod,'_SQLITE_PATH',tmp_path/'scope.db')
    st=store_mod.Store()
    for sid,scope in [('old',NARROW),('new',WIDE)]:
        st.init_scan_run(sid,'drive',1,'2026-09-11T00:00:00Z','rubric','hash',owner='owner',
                         scope={'scan_scope':{k:list(v) for k,v in scope.items()}})
    st.save_file_result('old',{'file':'a.docx','engine':'office','status':'analysed',
        'score':100,'compliant':True,'skipped_rules':0,'issues':[],
        'drive_file_id':'drive-id','checksum':'same-bytes'},'2026-09-11T00:01:00Z')
    st.finalize_scan_run('old','2026-09-11T00:01:00Z')
    assert st.find_prior_analysis('owner','drive-id','same-bytes','hash') is not None
    assert st.find_prior_analysis('owner','drive-id','same-bytes','hash',
                                  scan_id='new',filename='a.docx') is None


def test_multicriterion_link_proposer_only_generates_selected_sc(monkeypatch):
    monkeypatch.setattr(proposals,'extract_office_links',lambda *a:[('Details','https://a.test'),('Details','https://b.test')])
    monkeypatch.setattr(proposals,'derive_link_text',lambda *a:{'text':'destination','rationale':'from URL'})
    with selection({'2.4.9'}):
        out=proposals.propose_link_texts(Path('a.docx'),'.docx')
    assert len(out)==2 and all(p['sc']=='2.4.9' for p in out)


def test_image_text_proposer_does_not_run_unselected_strict_check(monkeypatch):
    import ocr
    monkeypatch.setattr(ocr,'is_available',lambda:True)
    monkeypatch.setattr(ocr,'_embedded_images',lambda *a:[object()])
    thresholds=[]
    monkeypatch.setattr(ocr,'_ocr_words',lambda image,floor: thresholds.append(floor) or 100)
    monkeypatch.setattr(ocr,'ocr_text',lambda image:'Words in image')
    monkeypatch.setattr(proposals,'thumb_b64',lambda image:None)
    with selection({'1.4.5'}):
        out=proposals.propose_images_of_text(Path('a.docx'),'.docx')
    assert thresholds == [ocr._MIN_PIXELS]
    assert out[0]['sc']=='1.4.5'


def test_ai_activity_reports_only_recorded_same_scan_evidence(monkeypatch,tmp_path):
    monkeypatch.setattr(store_mod,'_SQLITE_PATH',tmp_path/'activity.db')
    st=store_mod.Store()
    for sid,ok,reason in [('scan',True,None),('scan',False,'circuit_open'),('another',True,None)]:
        st.record_ai_call(surface='vision',provider='ollama',model='llava',zone='cloud',
                          latency_ms=0,ok=ok,reason=reason,scan_id=sid)
    activity=st.scan_ai_activity('scan')
    assert activity['records']==2 and activity['succeeded']==1
    assert activity['reasons']==[{'reason':'circuit_open','records':1}]
    assert activity['groups'][0]['provider']=='ollama'
