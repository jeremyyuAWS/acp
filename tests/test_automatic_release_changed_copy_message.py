"""A dead delivery of older bytes must not ask users to reconnect."""
import pytest
from test_automatic_release_service import prepared, authorize, tick, SID, FILE, DIGEST


@pytest.mark.parametrize('provider', ['sharepoint', 'drive'])
def test_dead_delivery_of_changed_copy_identifies_new_plan_requirement(prepared, provider):
    row = authorize(prepared)
    admitted = tick(prepared, row)
    if provider == 'drive':
        # The coordinator's decision is provider-independent; no provider is called.
        admitted['intent']['destination']['provider'] = provider
        with prepared.store._db.cursor() as cur:
            import json
            prepared.store._db.execute(cur, 'UPDATE automatic_release_authorizations SET intent=%s WHERE id=%s',
                                      (json.dumps(admitted['intent']), admitted['id']))
    with prepared.store._db.cursor() as cur:
        prepared.store._db.execute(cur, "UPDATE jobs SET status='dead' WHERE type='publish_file' AND scan_id=%s", (SID,))
        prepared.store._db.execute(cur, 'UPDATE file_records SET corrected_sha256=%s WHERE scan_id=%s', ('b' * 64, SID))
    blocked = tick(prepared, admitted)
    entry = blocked['progress']['files'][FILE]
    assert entry['state'] == 'blocked'
    assert entry['failure_category'] == 'admitted_copy_changed'
    assert 'new release plan' in entry['message'].lower()
    assert 'reconnect' not in entry['message'].lower()
    assert entry['artifact_digest'] == DIGEST
    assert not entry.get('requires_reconnect')
    assert len(prepared.calls) == 1
    import automatic_release as flow
    assert not flow.public(blocked, prepared.store)['can_resume']
