"""Real durable intent, incremental job and exact provider receipt presentation."""
import pytest
import automatic_release_store
import progress_evidence
from test_remediation_waterfall_view import seed


def setup(store, scope=147):
    run = seed(store)
    files = [f'file-{n}.pdf' for n in range(scope)]
    release = store.ensure_release_execution('scan', 'owner', 'local', scope,
        preferred_folder_name='Authorized batch')
    authorization = automatic_release_store.create(store, 'owner', 'scan', run, 'batch',
        {'files': {file: {'checksum': 'frozen-source'} for file in files},
         'release_parent_id': None, 'release_folder_name': release['folder_name']})
    entries = {file: {'state': 'waiting'} for file in files}
    for file in files[:9]:
        digest = 'sha256:' + 'a' * 64
        entries[file] = {'state': 'published', 'artifact_digest': digest}
        store.record_release_document(release['id'], 'owner',
            {'file': file, 'status': 'published', 'artifact_digest': digest})
    automatic_release_store.save(store, authorization, status='waiting', progress={'files': entries})
    execution = store.enqueue_stage_batch('scan', 'release', 'publish_file',
        [{'owner': 'owner', 'scan_id': 'scan', 'file': files[-1], 'automatic_release_id': authorization['id']}],
        snapshot_id='corrected', request_fingerprint='incremental')['batch_id']
    return execution, authorization, release, files


def test_incremental_request_retains_its_ledger_and_shows_only_approved_cumulative_scope(isolated_store):
    store = isolated_store
    execution, authorization, _, _ = setup(store)
    snapshot = store.stage_execution_snapshot(execution, owner='owner')
    assert snapshot['domain_reconciliation']['total'] == 1
    batch = progress_evidence.read(store, execution, owner='owner')['release_batch_progress']
    assert batch == {'available': True, 'authorization_id': authorization['id'], 'run_id': authorization['run_id'],
                     'total': 147, 'delivered': 9, 'remaining': 138, 'status': 'waiting', 'revision': 1}
    assert progress_evidence.read(store, execution, owner='intruder')['file_processing']['available'] is False


@pytest.mark.parametrize('mutation', ['digest', 'destination', 'progress_only', 'unrelated_authorization', 'replaced_run'])
def test_unconfirmed_receipts_or_unrelated_identity_never_inflate_delivered_scope(isolated_store, mutation):
    store = isolated_store
    execution, authorization, release, files = setup(store, scope=12)
    with store._db.cursor() as cur:
        if mutation == 'digest':
            store._db.execute(cur, "UPDATE release_documents SET artifact_digest='sha256:wrong' WHERE release_id=%s", (release['id'],))
        elif mutation == 'destination':
            store._db.execute(cur, "UPDATE release_executions SET folder_name='Other destination' WHERE id=%s", (release['id'],))
        elif mutation == 'progress_only':
            store._db.execute(cur, 'DELETE FROM release_documents WHERE release_id=%s', (release['id'],))
        elif mutation == 'unrelated_authorization':
            store._db.execute(cur, "UPDATE automatic_release_authorizations SET owner_email='other' WHERE id=%s", (authorization['id'],))
        else:
            store._db.execute(cur, 'UPDATE stage_executions SET is_current=0 WHERE execution_id=%s', (authorization['run_id'],))
    batch = progress_evidence.read(store, execution, owner='owner')['release_batch_progress']
    if mutation in {'unrelated_authorization', 'replaced_run'}:
        assert batch == {'available': False}
    else:
        assert batch['total'] == 12 and batch['delivered'] == 0 and batch['remaining'] == 12
