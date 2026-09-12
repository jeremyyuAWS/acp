from review_item_kind import optional_inspection,serialize_review_item

def test_optional_record_serialization_does_not_fake_a_decision_or_verification():
    row={'id':'automatic','rule_id':'auto/verify','status':'pending','validated':False}
    result=serialize_review_item(row)
    assert optional_inspection(result)
    assert result['review_required'] is False and result['review_task_state']=='completed'
    assert result['status']=='pending' and result['validated'] is False
    assert 'inspection_only' not in row
    actual={'rule_id':'1.1.1','status':'pending'}
    assert serialize_review_item(actual)==actual and not optional_inspection(actual)


def test_persisted_optional_task_is_returned_for_browsing_without_review_gate(isolated_store, monkeypatch):
    from types import SimpleNamespace
    import core
    from routes.hitl import hitl_list
    monkeypatch.setattr(core, 'store', isolated_store)
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur, "INSERT INTO scan_runs(id,owner_email,source,status) VALUES(%s,%s,'local','done')", ('optional-scan','owner@example.com'))
    item = isolated_store.queue_hitl_deferral('optional-scan','auto.pdf','Automatic fix applied — verify the result',1,rule_id='auto/verify')
    request = SimpleNamespace(state=SimpleNamespace(user_email='owner@example.com'))
    first = hitl_list(request, scan_id='optional-scan')
    reread = hitl_list(request, scan_id='optional-scan')
    assert first == reread and len(first) == 1
    assert first[0]['id'] == item and first[0]['review_task_state'] == 'completed'
    assert first[0]['review_required'] is False
    assert isolated_store.get_hitl_item(item)['status'] == 'pending'
    assert not isolated_store.get_hitl_item(item).get('validated')
    assert hitl_list(SimpleNamespace(state=SimpleNamespace(user_email='other@example.com')),scan_id='optional-scan') == []
