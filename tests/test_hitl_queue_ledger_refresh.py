"""Existing review cards refresh proposals/counts without nesting independent writes.

Runs on isolated SQLite by default and the disposable PostgreSQL integration database
when DATABASE_URL is configured. Includes a real current finding ledger, unlike card-only
fixtures which never exercised the disposition write.
"""
import uuid
import pytest


@pytest.mark.parametrize('refresh', ['proposal', 'deferral'])
def test_existing_card_refresh_commits_before_ledger_projection(isolated_store, refresh):
    st = isolated_store
    sid = 'ledger-refresh-' + uuid.uuid4().hex
    with st._db.cursor() as cur:
        st._db.execute(cur,
            "INSERT INTO scan_runs(id,source,status,workflow_id,workflow_revision) "
            "VALUES(%s,'local','done',%s,1)", (sid, sid))
        st._db.execute(cur,
            "INSERT INTO file_records(scan_id,file,checksum) VALUES(%s,'a.docx','one')", (sid,))
        st._db.execute(cur,
            "INSERT INTO scan_rule_traces(scan_id,file,rule_id,rule_name,plain_name,level,"
            "fix_mode,outcome,finding_count) VALUES(%s,'a.docx','1.1.1','Alt','Alt',"
            "'A','human','FAIL',3)", (sid,))
    execution = st.enqueue_stage_batch(sid, 'remediate', 'remediate_file',
        [{'scan_id': sid, 'file': 'a.docx'}], snapshot_id=sid, request_fingerprint=sid)
    st.seed_finding_dispositions(sid, execution['batch_id'])
    item = st.queue_hitl_review_for_file(sid, 'a.docx',
        [{'rule_id': '1.1.1', 'finding_count': 1}])[0]
    if refresh == 'proposal':
        assert st.enqueue_proposals(sid, 'a.docx', '1.1.1',
            [{'locator': 'image', 'proposed_value': 'A chart'}], finding_count=3) == item['id']
    else:
        assert st.queue_hitl_deferral(sid, 'a.docx', 'Vision unavailable', 3) is None
    assert st.get_hitl_item(item['id'])['finding_count'] == 3
    with st._db.cursor() as cur:
        st._db.execute(cur, 'SELECT disposition,review_item_id FROM finding_disposition '
            'WHERE scan_id=%s AND batch_id=%s', (sid, execution['batch_id']))
        rows = st._db.fetchall(cur)
    assert len(rows) == 3
    assert all(row['disposition'] == 'awaiting_review' and row['review_item_id'] == item['id']
               for row in rows)
