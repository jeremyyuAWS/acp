"""Separate run-scoped release permission; never approves or edits a document."""
from datetime import datetime, timedelta, timezone
import json
import re

import automatic_release_store as persistence
from release_continuation import record_identity, require_grants, request_for
from release_artifacts import ReleaseArtifactError, artifact_tag, require_current_record, require_current_source

ACTIVE = {'active', 'waiting', 'blocked'}
MAX_FILES = 500
MAX_DISPATCH_PER_TICK = 1


class DeliveryAlreadyAdmitted(ValueError):
    pass


def current_run(store, sid, owner):
    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT * FROM stage_executions WHERE scan_id=%s AND owner_email=%s AND stage='remediate' AND is_current=1 ORDER BY created_at DESC LIMIT 1", (sid, owner))
        return store._db.fetchone(cur)


def run_files(store, run):
    with store._db.cursor() as cur:
        store._db.execute(cur, 'SELECT w.input_id,j.status FROM stage_work_items w JOIN jobs j ON j.id=w.job_id WHERE w.execution_id=%s', (run,))
        return {r['input_id']: r['status'] for r in store._db.fetchall(cur)}


def selection(store, sid, owner, files, run_id=None):
    from assessment_policy import selected_documents
    scan = store.get_scan(sid, owner=owner)
    if not scan:
        raise ValueError('Scan not found')
    run = current_run(store, sid, owner)
    if not run or (run_id is not None and run['execution_id'] != run_id):
        raise ValueError('Start Remediate before enabling automatic release for its accepted run.')
    if run.get('cancel_requested_at') or run['state'] in {'cancelled', 'failed', 'superseded', 'interrupted'}:
        raise ValueError('This remediation run is stopped or failed.')
    if run['input_snapshot_id'] != store.remediation_source_revision(sid):
        raise ValueError('The assessed source changed. Start a new remediation run.')
    if (not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES
            or any(not isinstance(f, str) or not f or len(f) > 4096 for f in files)
            or len(set(files)) != len(files)):
        raise ValueError('Choose between 1 and 500 distinct files.')
    selected = selected_documents(store.get_decisions(sid, owner=owner))
    if set(files) - run_files(store, run['execution_id']).keys() or (selected is not None and set(files) - selected):
        raise ValueError('Files must belong to this accepted run and current document selection.')
    source = (scan.get('run') or {}).get('source')
    if source not in {'drive', 'sharepoint'}:
        raise ValueError('Automatic release requires a connected Google Drive or SharePoint destination.')
    records = store.get_file_records(sid, owner=owner)
    for file in files:
        record = records.get(file) or {}
        if not record.get('drive_file_id') or not record.get('source_modified') or (source == 'sharepoint' and not record.get('drive_id')):
            raise ValueError('Tracked source identity and assessment freshness are required for every selected file.')
    require_grants(store, owner, review=False)
    return run, source, records


def destination_for(store, sid, owner, source, records, files, supplied=None):
    from routes.scans import _release_destination
    existing = store.release_for_scan(sid, owner)
    if existing and existing.get('parent_folder_id'):
        selected = dict(provider=source, folder_id=existing['parent_folder_id'],
                        folder_name=existing.get('parent_folder_name') or 'Existing release destination')
    elif source == 'sharepoint':
        drives = {records[f]['drive_id'] for f in files}
        if len(drives) != 1:
            raise ValueError('Choose one explicit release destination for files from different libraries.')
        selected = dict(provider=source, folder_id=next(iter(drives)) + '/root', folder_name='Source library root')
    else:
        selected = dict(provider=source, folder_id='root', folder_name='Google Drive root')
    if supplied is not None:
        supplied = _release_destination(source, supplied)
        if existing and supplied['folder_id'] != selected['folder_id']:
            raise ValueError('The existing Release destination cannot be changed by this authorization.')
        selected = supplied
    return selected


def destination_label(destination):
    return ('SharePoint' if destination['provider']=='sharepoint' else 'Google Drive') + ' / ' + destination['folder_name']


def public(row, store=None):
    if row is None:
        return None
    files = row['intent']['files']
    progress = row['progress'].get('files', {})
    counts = dict(published=0, pending=0, blocked=0, failed=0)
    details = {}
    for file in files:
        entry = dict(progress.get(file, {'state': 'waiting', 'message': 'Waiting for approval and verification'}))
        # A delivery admitted before Stop may finish afterward. Its exact durable
        # receipt remains visible without reviving authorization or scheduling work.
        if store is not None and entry.get('artifact_digest'):
            saved = receipt(store, row, file, entry['artifact_digest'])
            if saved:
                entry = {**entry, 'state': 'published', 'receipt': saved, 'message': 'Delivered'}
        category = {'published':'published', 'failed':'failed', 'blocked':'blocked', 'stopped':'blocked'}.get(entry['state'], 'pending')
        if row['status'] == 'stopped' and category == 'pending':
            category = 'blocked'
        elif row['status'] == 'failed' and category == 'pending':
            category = 'failed'
        counts[category] += 1
        details[file] = entry
    return dict(id=row['id'], status=row['status'], run_id=row['run_id'], files=list(files),
                destination_label=destination_label(row['intent']['destination']), destination=row['intent']['destination'],
                progress=counts, file_progress=details, stopped_at=row.get('stopped_at'),
                expires_at=row['intent']['expires_at'], revision=row['revision'])


def preview(store, sid, owner, files):
    run = current_run(store, sid, owner)
    row = persistence.latest(store, sid, owner, run_id=run['execution_id']) if run else None
    result = dict(available=False, reason=None, run_id=run['execution_id'] if run else None,
                  destination=None, destination_label=None, authorization=public(row, store))
    try:
        run, source, records = selection(store, sid, owner, files)
        destination = destination_for(store, sid, owner, source, records, files)
        result.update(available=True, destination=destination, destination_label=destination_label(destination))
    except ValueError as exc:
        result['reason'] = str(exc)
    return result


def authorize(store, sid, owner, run_id, files, destination, request_id):
    import publish
    if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', request_id):
        raise ValueError('A bounded unique request ID is required.')
    # A lost-response replay must not recompute a later expiry or folder name.
    prior = persistence.by_request(store, owner, sid, request_id)
    if prior:
        if prior['run_id'] != run_id or sorted(files) != list(prior['intent']['files']) or destination != prior['intent']['destination']:
            raise ValueError('This request ID belongs to different release permission.')
        return prior
    with store.transaction():
        with store._db.cursor() as cur:
            store._db.execute(cur,'UPDATE scan_runs SET owner_email=owner_email WHERE id=%s AND owner_email=%s',(sid,owner))
        prior = persistence.by_request(store,owner,sid,request_id)
        if prior:
            if prior['run_id'] != run_id or sorted(files) != list(prior['intent']['files']) or destination != prior['intent']['destination']:
                raise ValueError('This request ID belongs to different release permission.')
            return prior
        run, source, records = selection(store, sid, owner, files, run_id)
        destination = destination_for(store, sid, owner, source, records, files, destination)
        existing = store.release_for_scan(sid, owner)
        intent = dict(version=1, source=source, source_revision=run['input_snapshot_id'],
                      files={f: record_identity(records[f]) for f in sorted(files)}, destination=destination,
                      release_folder_name=(existing or {}).get('folder_name') or publish.release_folder_name(),
                      release_parent_id=existing.get('parent_folder_id') if existing else destination['folder_id'],
                      expires_at=(datetime.now(timezone.utc)+timedelta(hours=24)).isoformat())
        return persistence.create(store, owner, sid, run_id, request_id, intent)


def require_authority(store, row, file):
    if not row or row['status'] not in ACTIVE or file not in row['intent']['files']:
        raise ValueError('Automatic release is not active for this file.')
    if datetime.now(timezone.utc) >= datetime.fromisoformat(row['intent']['expires_at']):
        raise ValueError('Automatic release authorization expired. Enable it again explicitly.')
    run, source, records = selection(store, row['scan_id'], row['owner_email'], list(row['intent']['files']), row['run_id'])
    if source != row['intent']['source'] or run['input_snapshot_id'] != row['intent']['source_revision']:
        raise ValueError('The authorized run or source changed.')
    record = records[file]
    if record_identity(record) != row['intent']['files'][file]:
        raise ValueError('Source identity changed. Reassess before release.')
    existing = store.release_for_scan(row['scan_id'], row['owner_email'])
    if existing and (existing.get('parent_folder_id') != row['intent']['release_parent_id']
                     or existing.get('folder_name') != row['intent']['release_folder_name']):
        raise ValueError('The authorized release destination changed.')
    return record


def ready(store, row, file):
    record = require_authority(store, row, file)
    if run_files(store, row['run_id']).get(file) != 'done':
        raise ValueError('Waiting for this run to finish remediating the file.')
    if not record.get('compliant') or not record.get('remediated_at') or not re.fullmatch('[0-9a-f]{64}', record.get('corrected_sha256') or ''):
        raise ValueError('Waiting for a verified corrected artifact.')
    if store.count_unapplied_approved_values(row['scan_id'], file):
        raise ValueError('Approved changes still need application and verification.')
    for item in store.list_hitl_queue(scan_id=row['scan_id'], owner=row['owner_email'], include_superseded=True):
        if item.get('file') != file or item.get('superseded'):
            continue
        if item.get('status') not in {'approved', 'resolved'}:
            raise ValueError('Per-file review or manual work remains.')
        if item.get('status') == 'approved' and item.get('proposals'):
            if item.get('approved_source_revision') != row['intent']['source_revision']:
                raise ValueError('Approval belongs to a different assessed source.')
    require_current_record(store, row['scan_id'], file, record['corrected_sha256'], record['remediated_at'], owner=row['owner_email'])
    return record


def receipt(store, row, file, digest):
    release = store.release_for_scan(row['scan_id'], row['owner_email'])
    if not release or release.get('parent_folder_id') != row['intent']['release_parent_id'] or release.get('folder_name') != row['intent']['release_folder_name']:
        return None
    saved = store.get_release_document(release['id'], file, row['owner_email'])
    return saved if saved and saved.get('status') == 'published' and saved.get('artifact_digest') == artifact_tag(digest) else None


def publish_admission(store, authorization_id, owner, sid, file, digest, *, queued=False):
    """Stop's linearization barrier: queued jobs must obtain fresh permission.

    A permit committed before Stop is in-flight; it may finish. Stop prevents all
    later permits, including jobs already queued in a different worker process.
    """
    with store.transaction():
        row = persistence.get(store, authorization_id, owner, lock=True)
        if not row or row['scan_id'] != sid:
            raise ValueError('Automatic release authorization not found.')
        record = ready(store, row, file)
        frozen = row['progress'].get('files', {}).get(file, {}).get('artifact_digest')
        if frozen and not queued:
            raise DeliveryAlreadyAdmitted('Delivery is already admitted. Reconcile its existing receipt.')
        if queued and not frozen:
            raise ValueError('Queued delivery has no prior exact automatic admission.')
        if frozen and frozen != digest:
            raise ValueError('This authorization already admitted a different artifact. Confirm a new authorization.')
        if digest != record['corrected_sha256']:
            raise ValueError('The verified artifact changed after dispatch was requested.')
        return persistence.update_file(store, row['id'], owner, file, dict(state='publishing', artifact_digest=digest,
            remediated_at=record['remediated_at'], message='Delivery admitted; an in-flight request may finish after Stop.'))


def publish_job(store, payload, job, callback):
    from worker import FatalJobError
    tag = payload.get('artifact_digest') or ''
    try:
        publish_admission(store, payload['automatic_release_id'], payload['owner'], payload['scan_id'], payload['file'], tag.removeprefix('sha256:'), queued=True)
    except ValueError as exc:
        raise FatalJobError(str(exc)) from exc
    return callback(payload, job)


def advance(store, payload, job):
    from routes.scans import publish_files
    from worker import check_cancel
    row = persistence.get(store, payload['authorization_id'], payload['owner'])
    if not row or row['status'] not in ACTIVE or payload['revision'] != row['progress'].get('_tick_revision', 0):
        return
    dispatched = 0
    pending_jobs = {}
    with store._db.cursor() as cur:
        store._db.execute(cur,"SELECT payload,status FROM jobs WHERE scan_id=%s AND type='publish_file'",(row['scan_id'],))
        for item in store._db.fetchall(cur):
            data = json.loads(item['payload']) if isinstance(item['payload'],str) else item['payload']
            if data.get('automatic_release_id') == row['id']:
                pending_jobs.setdefault(data.get('file'),[]).append(item['status'])
    for file in row['intent']['files']:
        check_cancel()
        row = persistence.get(store, row['id'], row['owner_email'])
        if row['status'] not in ACTIVE:
            return
        entry = row['progress'].get('files', {}).get(file, {})
        if entry.get('state') in {'published', 'failed'}:
            continue
        try:
            if entry.get('artifact_digest'):
                saved = receipt(store, row, file, entry['artifact_digest'])
                if saved:
                    persistence.update_file(store,row['id'],row['owner_email'],file,
                        dict(state='published',receipt=saved,message='Delivered'))
                elif pending_jobs.get(file) and all(s in {'dead','cancelled'} for s in pending_jobs[file]):
                    persistence.update_file(store,row['id'],row['owner_email'],file,
                        dict(state='failed',message='Delivery job stopped or failed. Reconcile its receipt before authorizing another attempt.'))
                # Once admitted, freeze the artifact and reconcile its receipt.
                # A changed artifact or lost provider result never buys a new delivery.
                continue
            record = ready(store, row, file)
            digest = record['corrected_sha256']
            saved = receipt(store, row, file, digest)
            if saved:
                persistence.update_file(store, row['id'], row['owner_email'], file, dict(state='published',artifact_digest=digest,receipt=saved,message='Delivered'))
                continue
            if entry.get('state') == 'publishing':
                # A queued or possibly-dispatched request is never blindly bought again.
                continue
            if dispatched >= MAX_DISPATCH_PER_TICK:
                continue
            with store._db.cursor() as cur:
                store._db.execute(cur, "SELECT execution_id FROM stage_executions WHERE scan_id=%s AND stage='release' AND is_current=1 AND state IN ('accepted','queued','processing','paused')",(row['scan_id'],))
                if store._db.fetchone(cur):
                    continue
            row = publish_admission(store, row['id'], row['owner_email'], row['scan_id'], file, digest)
            dispatched += 1
            result = publish_files(row['scan_id'], request_for(row['owner_email'], row['scan_id']),
                dict(files=[file], destination=row['intent']['destination'] if row['intent']['release_parent_id'] else None,
                     release_folder_name=row['intent']['release_folder_name'], automatic_release_id=row['id'],
                     expected_artifacts={file:digest}, expected_destination=row['intent']['destination'] if row['intent']['release_parent_id'] else None))
            outcome = next((r for r in result.get('published',[]) if r.get('file')==file),{})
            confirmed = receipt(store,row,file,digest)
            state = 'published' if confirmed else 'publishing' if outcome.get('status') in {'queued','published'} else 'failed'
            persistence.update_file(store,row['id'],row['owner_email'],file,dict(state=state,artifact_digest=digest,
                message='Delivered' if state=='published' else 'Waiting for delivery receipt' if state=='publishing' else 'Delivery was not confirmed. Inspect the receipt before retrying.',receipt=outcome))
        except DeliveryAlreadyAdmitted:
            continue
        except (ValueError, ReleaseArtifactError) as exc:
            persistence.update_file(store,row['id'],row['owner_email'],file,dict(state='blocked',message=str(exc)))
        except Exception:
            persistence.update_file(store,row['id'],row['owner_email'],file,dict(state='failed',message='Delivery outcome is unknown. Reconcile its receipt before retrying.'))
    with store.transaction():
        row = persistence.get(store,row['id'],row['owner_email'],lock=True)
        if row['status'] not in ACTIVE or payload['revision'] != row['progress'].get('_tick_revision',0):
            return
        states = [r.get('state') for r in row['progress'].get('files',{}).values()]
        expired = datetime.now(timezone.utc) >= datetime.fromisoformat(row['intent']['expires_at'])
        completed = len(states)==len(row['intent']['files']) and all(s=='published' for s in states)
        persistence.save(store,row,status='completed' if completed else 'failed' if expired else 'waiting',
                         progress=row['progress'],schedule=not completed and not expired,delay=20)


def validate_publish_request(store, sid, owner, files, body):
    """Only an exact previously admitted artifact may use automatic authority."""
    row = persistence.get(store,body['automatic_release_id'],owner)
    if not row or row['scan_id'] != sid:
        raise ValueError('Automatic release authorization not found in this scan.')
    expected_destination = row['intent']['destination'] if row['intent']['release_parent_id'] else None
    if body.get('destination') != expected_destination or body.get('release_folder_name') != row['intent']['release_folder_name']:
        raise ValueError('Automatic release destination differs from the authorized destination.')
    for file in files:
        record = ready(store,row,file)
        frozen = row['progress'].get('files',{}).get(file,{}).get('artifact_digest')
        if not frozen or record['corrected_sha256'] != frozen or body.get('expected_artifacts',{}).get(file) != frozen:
            raise ValueError('Automatic release requires the exact admitted verified artifact.')
    return row
