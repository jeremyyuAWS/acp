from test_finding_disposition_ledger import _assessment, _batch


def test_same_document_verified_in_two_scans_has_distinct_ledger_events(isolated_store):
    store=isolated_store
    first=_assessment(store,'first-scan')
    second=_assessment(store,'fresh-rerun')
    # Real detector locations remain stable for the same source across scans.
    with store._db.cursor() as cur:
        for sid in [first,second]:
            for index in range(3):
                store._db.execute(cur,"INSERT INTO issue_records(scan_id,file,rule_id,wcag,severity,detail,location) VALUES(%s,'a.docx','missing-alt','SC_1_1_1','SERIOUS','Missing alt',%s)",(sid,f'word/document.xml#drawing{index}'))
    first_batch=_batch(store,first)
    store.seed_finding_dispositions(first,first_batch,snapshot_id=first)
    second_batch=_batch(store,second)
    store.seed_finding_dispositions(second,second_batch,snapshot_id=second)
    a=store.list_finding_dispositions(first,first_batch)
    b=store.list_finding_dispositions(second,second_batch)
    assert {row['finding_id'] for row in a if row['rule_id']=='1.1.1'} == {row['finding_id'] for row in b if row['rule_id']=='1.1.1'}
    evidence=[{'rule_id':'1.1.1','before':'missing caption','after':'authored meaningful caption','note':'verified'}]
    store.record_remediation_diffs(first,'a.docx',evidence)
    store.record_remediation_diffs(second,'a.docx',evidence)
    for sid,batch in [(first,first_batch),(second,second_batch)]:
        rows=[row for row in store.list_finding_dispositions(sid,batch) if row['rule_id']=='1.1.1']
        assert {row['disposition'] for row in rows} == {'resolved_verified'}
        assert all(len(store.finding_disposition_events(sid,batch,row['finding_id'])) == 1 for row in rows)


def test_same_scan_new_batch_is_independent_and_exact_group_replay_is_noop(isolated_store):
    store=isolated_store;sid=_assessment(store)
    for batch in ['original-batch','new-batch']:
        store.seed_finding_dispositions(sid,batch,snapshot_id='same-assessed-version')
        moved=store.set_finding_group_disposition(sid,'a.docx','1.1.1','resolved_verified',
            event_key='verified:a.docx:1.1.1',batch_id=batch,
            fix_evidence_ids=['diff:exact-saved-version'],verified_at='2026-09-13T23:00:00Z')
        assert moved == 3
        replay=store.set_finding_group_disposition(sid,'a.docx','1.1.1','resolved_verified',
            event_key='verified:a.docx:1.1.1',batch_id=batch,
            fix_evidence_ids=['diff:exact-saved-version'],verified_at='2026-09-13T23:00:00Z')
        assert replay == 0
        rows=[row for row in store.list_finding_dispositions(sid,batch) if row['rule_id']=='1.1.1']
        assert {row['revision'] for row in rows} == {1}
        assert all(len(store.finding_disposition_events(sid,batch,row['finding_id'])) == 1 for row in rows)
