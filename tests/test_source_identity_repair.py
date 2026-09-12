import copy
import pytest
import source_identity_repair as repair


def snapshot(n=1):
    rows = [{'file':f'file-{i}.docx','source_name':f'Original {i}.docx',
             'drive_file_id':f'item-{i}','drive_id':None,'site_id':None,
             'source_modified':'2026-09-12T12:00:00Z','checksum':None} for i in range(n)]
    return {'run':{'source':'sharepoint','scope':{'kind':'sharepoint','site':None}},
            'job':{'id':'discovery','status':'done','payload':{'source':'sharepoint','folder':None,'folders':None}},
            'inventory':rows,'records':[dict(file=r['file'],drive_file_id=r['drive_file_id'],source_modified=r['source_modified'],checksum=None,remediated_at=None,status='analysed',score=80) for r in rows],
            'remediation':False}


class FakeStore:
    def __init__(self,n=1): self.saved=snapshot(n); self.writes=[]
    def source_identity_repair_snapshot(self,sid,owner): return copy.deepcopy(self.saved)
    def backfill_verified_default_drive(self,sid,owner,expected,drive):
        assert expected == self.saved
        self.writes.append((sid,owner,drive))
        return len(expected['inventory'])


def provider(store, mutate=None):
    calls=[]
    def post(batch):
        calls.append(batch)
        answers=[]
        for request in batch:
            if request['id']=='drive': body={'id':'real-drive','driveType':'business'}
            else:
                row=store.saved['inventory'][int(request['id'])]
                body={'id':row['drive_file_id'],'name':row['source_name'],
                      'parentReference':{'driveId':'real-drive'},
                      'lastModifiedDateTime':row['source_modified'],'file':{'hashes':{}}}
                if mutate: mutate(body)
            answers.append({'id':request['id'],'status':200,'body':body})
        return {'responses':answers}
    return post,calls


def test_147_sources_verified_in_eight_bounded_batches_before_one_write():
    store=FakeStore(147);post,calls=provider(store)
    assert repair.probe(store,'s','owner')['available']
    assert repair.repair(store,'s','owner','token',post=post)=={'status':'repaired','repaired_files':147}
    assert len(calls)==8 and all(len(c)<=20 for c in calls)
    assert all(r['method']=='GET' and r['url'].startswith('/me/drive') for c in calls for r in c)
    assert store.writes==[('s','owner','real-drive')]


@pytest.mark.parametrize('field,value,reason',[
    ('lastModifiedDateTime','2026-09-13T12:00:00Z','source_changed'),
    ('name','renamed.docx','source_identity_mismatch'),('id','wrong-item','source_identity_mismatch'),
    ('parentReference',{'driveId':'wrong-drive'},'source_identity_mismatch'),('file',None,'source_identity_mismatch')])
def test_changed_or_wrong_source_never_writes(field,value,reason):
    store=FakeStore();post,_=provider(store,lambda b:b.update({field:value}))
    with pytest.raises(repair.RepairBlocked,match=reason):repair.repair(store,'s','owner','token',post=post)
    assert not store.writes


def test_late_batch_failure_has_no_partial_repair():
    store=FakeStore(40);post,calls=provider(store)
    def failing(batch):
        answer=post(batch)
        if len(calls)==3:answer['responses'][0]['status']=404
        return answer
    with pytest.raises(repair.RepairBlocked,match='provider_metadata_unavailable'):
        repair.repair(store,'s','owner','token',post=failing)
    assert not store.writes


@pytest.mark.parametrize('change',[
    lambda s:s['job']['payload'].update(folder='chosen-folder'),
    lambda s:s['job'].update(status='dead'),
    lambda s:s.update(remediation=True),
    lambda s:s['records'][0].update(source_modified='2026-09-11T12:00:00Z'),
    lambda s:s['inventory'][0].update(source_name=None),
    lambda s:s['run']['scope'].update(site='selected-site'),
    lambda s:s.update(records=[]),
    lambda s:s['records'][0].update(status='error'),
    lambda s:s['records'][0].update(score=None)])
def test_ambiguous_or_admitted_selection_not_repairable(change):
    store=FakeStore();change(store.saved)
    assert not repair.probe(store,'s','owner')['available']
    with pytest.raises(repair.RepairBlocked):repair.repair(store,'s','owner','token',post=lambda _:pytest.fail('no Graph allowed'))
    assert not store.writes


def test_recognized_checksum_requires_exact_fresh_named_provider_hash():
    store=FakeStore();store.saved['inventory'][0]['checksum']='a'*64
    post,_=provider(store)
    with pytest.raises(repair.RepairBlocked,match='source_checksum_unverified'):repair.repair(store,'s','owner','token',post=post)
    assert not store.writes
    post,_=provider(store,lambda b:b['file']['hashes'].update(sha256Hash='a'*64))
    assert repair.repair(store,'s','owner','token',post=post)['repaired_files']==1


def test_no_token_does_not_query_graph_or_mutate():
    store=FakeStore()
    with pytest.raises(repair.RepairBlocked,match='microsoft_connection_required'):repair.repair(store,'s','owner',None)
    assert not store.writes


def seed_real(store):
    saved=snapshot()
    with store._db.cursor() as c:
        store._db.execute(c,"INSERT INTO scan_runs(id,source,owner_email,scope,status) VALUES(%s,%s,%s,%s,%s)",('s','sharepoint','owner','{"kind":"sharepoint","site":null}','done'))
        store._db.execute(c,"INSERT INTO jobs(id,type,status,payload,scan_id,created_at) VALUES(%s,%s,%s,%s,%s,%s)",('discovery','scan_discover','done','{"source":"sharepoint","folder":null,"folders":null}','s','2026-09-12'))
        store._db.execute(c,"INSERT INTO file_records(scan_id,file,drive_file_id,source_modified,status,score) VALUES(%s,%s,%s,%s,%s,%s)",('s','file-0.docx','item-0','2026-09-12T12:00:00Z','analysed',80))
    store.add_inventory('s',saved['inventory'])


def test_real_store_atomic_repair_preserves_assessment_and_scope(isolated_store):
    seed_real(isolated_store)
    before=isolated_store.source_identity_repair_snapshot('s','owner')
    assert repair.probe(isolated_store,'s','owner')['available']
    fake=FakeStore();post,_=provider(fake)
    assert repair.repair(isolated_store,'s','owner','token',post=post)['repaired_files']==1
    after=isolated_store.source_identity_repair_snapshot('s','owner')
    assert after['inventory'][0]['drive_id']=='real-drive'
    assert after['records']==before['records'] and after['run']==before['run'] and after['job']==before['job']
    assert repair.repair(isolated_store,'s','owner','token',post=post)['status']=='already_current'


def test_real_store_source_context_race_rolls_back(isolated_store):
    seed_real(isolated_store)
    expected=isolated_store.source_identity_repair_snapshot('s','owner')
    with isolated_store._db.cursor() as c:
        isolated_store._db.execute(c,"UPDATE scan_inventory SET source_modified=%s WHERE scan_id=%s",('2026-09-13T00:00:00Z','s'))
    with pytest.raises(ValueError,match='source_context_changed'):
        isolated_store.backfill_verified_default_drive('s','owner',expected,'real-drive')
    assert isolated_store.list_inventory('s')[0]['drive_id'] is None


@pytest.mark.parametrize('expected,hashes',[
    ('a'*64,{'sha1Hash':'a'*64}),
    ('opaque-checksum',{'quickXorHash':'opaque-checksum'}),
    ('AAAAAAAAAAAAAAAAAAAAAAAAAAA=',{'quickXorHash':'aaaaaaaaaaaaaaaaaaaaaaaaaaa='})])
def test_unknown_wrong_algorithm_and_quickxor_case_never_accepted(expected,hashes):
    with pytest.raises(repair.RepairBlocked,match='source_checksum_unverified'):
        repair._checksum(expected,hashes)


def test_known_hex_case_and_exact_quickxor_accepted():
    repair._checksum('A'*40,{'sha1Hash':'a'*40})
    repair._checksum('AAAAAAAAAAAAAAAAAAAAAAAAAAA=',{'quickXorHash':'AAAAAAAAAAAAAAAAAAAAAAAAAAA='})


def test_route_requires_owner_and_registers_fresh_connected_token(isolated_store,monkeypatch):
    from types import SimpleNamespace
    from fastapi import Response,HTTPException
    import core
    import routes.automatic_release as route
    seed_real(isolated_store)
    monkeypatch.setattr(core,'store',isolated_store)
    calls=[]
    monkeypatch.setattr(route,'credentials',lambda sid,request:calls.append(('credentials',sid)))
    monkeypatch.setattr(core,'get_scan_tokens',lambda sid:{'sp':'fresh-provider-token'})
    def run(store,sid,owner,token):
        assert calls == [('credentials','s')]
        assert owner=='owner' and token=='fresh-provider-token'
        return {'status':'repaired','repaired_files':1}
    monkeypatch.setattr(repair,'repair',run)
    request=SimpleNamespace(state=SimpleNamespace(user_email='owner'),headers={})
    response=Response()
    assert route.repair_source_identity('s',request,response)['repaired_files']==1
    assert response.headers['cache-control']=='no-store'
    request.state.user_email='different-owner'
    with pytest.raises(HTTPException) as exc:route.repair_source_identity('s',request,Response())
    assert exc.value.status_code==404 and len(calls)==1


def test_real_store_nonnull_identity_never_overwritten(isolated_store):
    seed_real(isolated_store)
    expected=isolated_store.source_identity_repair_snapshot('s','owner')
    with isolated_store._db.cursor() as c:
        isolated_store._db.execute(c,"UPDATE scan_inventory SET drive_id=%s WHERE scan_id=%s",('already-resolved','s'))
    with pytest.raises(ValueError,match='source_context_changed'):
        isolated_store.backfill_verified_default_drive('s','owner',expected,'new-drive')
    assert isolated_store.list_inventory('s')[0]['drive_id']=='already-resolved'


@pytest.mark.parametrize('reason,code',[('source_changed',409),('microsoft_connection_required',401)])
def test_route_structured_blocked_status_is_safe(isolated_store,monkeypatch,reason,code):
    from types import SimpleNamespace
    from fastapi import Response,HTTPException
    import core
    import routes.automatic_release as route
    seed_real(isolated_store)
    monkeypatch.setattr(core,'store',isolated_store)
    monkeypatch.setattr(route,'credentials',lambda *a:None)
    monkeypatch.setattr(core,'get_scan_tokens',lambda sid:{'sp':'fresh-token'})
    def blocked(*a):raise repair.RepairBlocked(reason)
    monkeypatch.setattr(repair,'repair',blocked)
    request=SimpleNamespace(state=SimpleNamespace(user_email='owner'),headers={})
    with pytest.raises(HTTPException) as exc:route.repair_source_identity('s',request,Response())
    assert exc.value.status_code==code
    assert exc.value.detail=={'code':'source_identity_repair_blocked','reason':reason}


def test_overall_provider_deadline_refuses_late_batch_and_no_write(monkeypatch):
    store=FakeStore(40);post,calls=provider(store)
    now=[0.0]
    monkeypatch.setattr(repair,'monotonic',lambda:now[0])
    def slow(batch):
        answer=post(batch)
        now[0]+=31
        return answer
    with pytest.raises(repair.RepairBlocked,match='provider_metadata_timeout'):
        repair.repair(store,'s','owner','token',post=slow)
    assert len(calls)==2 and not store.writes


def test_real_transport_receives_only_remaining_overall_budget(monkeypatch):
    store=FakeStore(20);post,calls=provider(store)
    now=[0.0];timeouts=[]
    monkeypatch.setattr(repair,'monotonic',lambda:now[0])
    class Response:
        status_code=200
        def __init__(self,data):self.data=data
        def json(self):return self.data
    def transport(url,**kwargs):
        timeouts.append(kwargs['timeout'])
        data=post(kwargs['json']['requests'])
        now[0]+=45 if len(timeouts)==1 else 1
        return Response(data)
    monkeypatch.setattr(repair.httpx,'post',transport)
    assert repair.repair(store,'s','owner','token')['repaired_files']==20
    assert timeouts==[30,15]


def test_pg_repair_takes_admission_lock_before_owner_row_and_snapshot(isolated_store,monkeypatch):
    seed_real(isolated_store)
    expected=isolated_store.source_identity_repair_snapshot('s','owner')
    emitted=[]
    execute=isolated_store._db.execute
    def capture(cur,sql,args=()):
        emitted.append((sql,args))
        if 'pg_advisory_xact_lock' in sql:return
        return execute(cur,sql,args)
    monkeypatch.setattr(isolated_store._db,'supports_skip_locked',True)
    monkeypatch.setattr(isolated_store._db,'execute',capture)
    isolated_store.backfill_verified_default_drive('s','owner',expected,'real-drive')
    assert 'pg_advisory_xact_lock(hashtextextended(%s,0))' in emitted[0][0]
    assert emitted[0][1]==('stage:s:remediate',)
    assert emitted[1][0].startswith('UPDATE scan_runs')
    assert next(i for i,(sql,_) in enumerate(emitted) if sql.startswith('UPDATE scan_inventory'))>1


@pytest.mark.parametrize('value',['bad-parent',[],17])
def test_malformed_parent_reference_structured_refusal_no_write(value):
    store=FakeStore();post,_=provider(store,lambda b:b.update(parentReference=value))
    with pytest.raises(repair.RepairBlocked,match='source_identity_mismatch'):
        repair.repair(store,'s','owner','token',post=post)
    assert not store.writes


def test_malformed_hash_shape_structured_refusal_no_write():
    store=FakeStore();post,_=provider(store,lambda b:b['file'].update(hashes='malformed'))
    with pytest.raises(repair.RepairBlocked,match='ambiguous_metadata'):
        repair.repair(store,'s','owner','token',post=post)
    assert not store.writes


@pytest.mark.parametrize('bad',['bad-answer',{'id':'drive','status':200,'body':'bad-body'}])
def test_malformed_provider_answer_structured_refusal_no_write(bad):
    store=FakeStore()
    with pytest.raises(repair.RepairBlocked,match='ambiguous_metadata'):
        repair.repair(store,'s','owner','token',post=lambda batch:{'responses':[bad,{'id':'0','status':200,'body':{}}]})
    assert not store.writes
