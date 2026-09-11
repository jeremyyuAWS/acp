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
STALL_AFTER_SECONDS = 600
STALLED_CHECK_SECONDS = 300


class DeliveryAlreadyAdmitted(ValueError):
    pass


class FileRemediationFinishedWithoutCopy(ValueError):
    """This authorized file settled without a publishable corrected artifact."""
    pass


class DriveReconnectRequired(ValueError):
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
    stalled_files = 0
    for file in files:
        entry = dict(progress.get(file, {'state': 'waiting', 'message': 'Waiting for a saved corrected copy' if row['intent'].get('allow_remaining_issues') else 'Waiting for approval and verification'}))
        # A delivery admitted before Stop may finish afterward. Its exact durable
        # receipt remains visible without reviving authorization or scheduling work.
        if store is not None and entry.get('artifact_digest'):
            saved = receipt(store, row, file, entry['artifact_digest'])
            if saved:
                entry = {**entry, 'state': 'published', 'receipt': saved, 'message': 'Delivered', 'requires_reconnect': False}
        category = {'published':'published', 'failed':'failed', 'blocked':'blocked', 'stopped':'blocked'}.get(entry['state'], 'pending')
        if row['status'] == 'stopped' and category == 'pending':
            category = 'blocked'
        elif row['status'] == 'failed' and category == 'pending':
            category = 'failed'
        if category in {'pending', 'blocked'} and row['status'] in ACTIVE and row['progress'].get('_delivery_watch', {}).get('needs_attention') and (entry.get('artifact_digest') or entry.get('waiting_for_delivery')):
            category = 'blocked'
            stalled_files += 1
        counts[category] += 1
        details[file] = entry
    return dict(id=row['id'], status=row['status'], run_id=row['run_id'], files=list(files),
                request_id=row['request_id'], source_revision=row['intent']['source_revision'],
                destination_label=destination_label(row['intent']['destination']), destination=row['intent']['destination'],
                progress=counts, file_progress=details, stopped_at=row.get('stopped_at'),
                expires_at=row['intent']['expires_at'], revision=row['revision'],
                allow_remaining_issues=row['intent'].get('allow_remaining_issues', False),
                include_reports=row['intent'].get('include_reports', False),
                requires_reconnect=any(e.get('requires_reconnect') for e in details.values()),
                can_resume=row['intent'].get('source') == 'drive' and row['status'] in ACTIVE and any(
                    e.get('state') == 'blocked' and e.get('artifact_digest') for e in details.values()),
                needs_attention=stalled_files > 0,
                attention_reason=row['progress'].get('_delivery_watch', {}).get('reason') if stalled_files else None,
                last_progress_at=row['progress'].get('_delivery_watch', {}).get('last_progress_at'))


def planning_preview(store, sid, owner, files):
    """Describe a local pre-Start choice without accepting release permission."""
    from assessment_policy import selected_documents
    result = dict(available=False, reason=None, files=[], source_revision=None,
                  destination=None, destination_label=None)
    try:
        scan = store.get_scan(sid, owner=owner)
        if not scan:
            raise ValueError('Scan not found')
        require_grants(store, owner, review=False)
        if (not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES
                or any(not isinstance(f, str) or not f or len(f) > 4096 for f in files)
                or len(set(files)) != len(files)):
            raise ValueError('Choose between 1 and 500 distinct files.')
        selected = selected_documents(store.get_decisions(sid, owner=owner))
        if selected is not None and set(files) - selected:
            raise ValueError('Files must belong to the current document selection.')
        source = (scan.get('run') or {}).get('source')
        if source not in {'drive', 'sharepoint'}:
            raise ValueError('Automatic release requires a connected Google Drive or SharePoint destination.')
        records = store.get_file_records(sid, owner=owner, files=files)
        for file in files:
            record = records.get(file) or {}
            if record.get('score') is None or record.get('status') in {'error', 'queued', 'pending', 'processing'}:
                raise ValueError('Assess every selected file before planning automatic release.')
            if not record.get('drive_file_id') or not record.get('source_modified') or (source == 'sharepoint' and not record.get('drive_id')):
                raise ValueError('Tracked source identity and assessment freshness are required for every selected file.')
        destination = destination_for(store, sid, owner, source, records, files)
        result.update(available=True, files=sorted(files), source_revision=store.remediation_source_revision(sid),
                      destination=destination, destination_label=destination_label(destination))
    except ValueError as exc:
        result['reason'] = str(exc)
    return result


def preview(store, sid, owner, files):
    run = current_run(store, sid, owner)
    row = persistence.latest(store, sid, owner, run_id=run['execution_id']) if run else None
    result = dict(available=False, reason=None, run_id=run['execution_id'] if run else None,
                  destination=None, destination_label=None, authorization=public(row, store),
                  planning=planning_preview(store, sid, owner, files))
    try:
        run, source, records = selection(store, sid, owner, files)
        destination = destination_for(store, sid, owner, source, records, files)
        result.update(available=True, destination=destination, destination_label=destination_label(destination))
    except ValueError as exc:
        result['reason'] = str(exc)
    return result


def authorize(store, sid, owner, run_id, files, destination, request_id, expected_source_revision=None, *, allow_remaining_issues=False, include_reports=False):
    import publish
    if type(allow_remaining_issues) is not bool or type(include_reports) is not bool:
        raise ValueError("Release options must be booleans.")
    if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', request_id):
        raise ValueError('A bounded unique request ID is required.')
    # A lost-response replay must not recompute a later expiry or folder name.
    prior = persistence.by_request(store, owner, sid, request_id)
    if prior:
        if (expected_source_revision is not None and expected_source_revision != prior['intent']['source_revision']) or prior['run_id'] != run_id or sorted(files) != list(prior['intent']['files']) or destination != prior['intent']['destination'] or allow_remaining_issues != prior['intent'].get('allow_remaining_issues', False) or include_reports != prior['intent'].get('include_reports', False):
            raise ValueError('This request ID belongs to different release permission.')
        return prior
    with store.transaction():
        with store._db.cursor() as cur:
            store._db.execute(cur,'UPDATE scan_runs SET owner_email=owner_email WHERE id=%s AND owner_email=%s',(sid,owner))
        prior = persistence.by_request(store,owner,sid,request_id)
        if prior:
            if (expected_source_revision is not None and expected_source_revision != prior['intent']['source_revision']) or prior['run_id'] != run_id or sorted(files) != list(prior['intent']['files']) or destination != prior['intent']['destination'] or allow_remaining_issues != prior['intent'].get('allow_remaining_issues', False) or include_reports != prior['intent'].get('include_reports', False):
                raise ValueError('This request ID belongs to different release permission.')
            return prior
        run, source, records = selection(store, sid, owner, files, run_id)
        if expected_source_revision is not None and expected_source_revision != run['input_snapshot_id']:
            raise ValueError('The assessed source changed after Plan. Review the plan and start again.')
        destination = destination_for(store, sid, owner, source, records, files, destination)
        existing = store.release_for_scan(sid, owner)
        intent = dict(version=2, allow_remaining_issues=allow_remaining_issues, include_reports=include_reports, source=source, source_revision=run['input_snapshot_id'],
                      files={f: record_identity(records[f]) for f in sorted(files)}, destination=destination,
                      release_folder_name=(existing or {}).get('folder_name') or publish.release_folder_name(timezone_name=publish.user_release_timezone(store, owner), owner_email=owner),
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
    work_state = run_files(store, row['run_id']).get(file)
    partial = row['intent'].get('allow_remaining_issues') is True
    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT payload FROM jobs WHERE scan_id=%s AND type='apply_approved_values' AND status IN ('queued','running','processing','retry')", (row['scan_id'],))
        for job in store._db.fetchall(cur):
            payload = json.loads(job['payload']) if isinstance(job['payload'], str) else job['payload']
            if payload.get('file') == file:
                raise ValueError('Waiting for active corrections to finish writing this file.')
    if partial and work_state in {'dead', 'cancelled'}:
        raise FileRemediationFinishedWithoutCopy('Remediation for this file stopped or failed. No corrected copy was published; the original is unchanged.')
    if work_state != 'done':
        raise ValueError('Waiting for this run to finish remediating the file.')
    if partial and (not record.get('remediated_at') or not re.fullmatch('[0-9a-f]{64}', record.get('corrected_sha256') or '')):
        raise FileRemediationFinishedWithoutCopy('Remediation finished without a saved corrected copy. The original is unchanged; remaining issues are listed for follow-up.')
    if (not partial and not record.get('compliant')) or not record.get('remediated_at') or not re.fullmatch('[0-9a-f]{64}', record.get('corrected_sha256') or ''):
        raise ValueError('Waiting for a saved corrected artifact.' if partial else 'Waiting for a verified corrected artifact.')
    if not partial and store.count_unapplied_approved_values(row['scan_id'], file):
        raise ValueError('Approved changes still need application and verification.')
    for item in store.list_hitl_queue(scan_id=row['scan_id'], owner=row['owner_email'], include_superseded=True):
        if partial or item.get('file') != file or item.get('superseded'):
            continue
        if item.get('status') not in {'approved', 'resolved'}:
            raise ValueError('Per-file review or manual work remains.')
        if item.get('status') == 'approved' and item.get('proposals'):
            if item.get('approved_source_revision') != row['intent']['source_revision']:
                raise ValueError('Approval belongs to a different assessed source.')
    require_current_record(store, row['scan_id'], file, record['corrected_sha256'], record['remediated_at'], owner=row['owner_email'], allow_remaining_issues=partial)
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
        return persistence.update_file(store, row['id'], owner, file, dict(state='publishing', artifact_digest=digest, waiting_for_delivery=False,
            remediated_at=record['remediated_at'], message='Delivery admitted; an in-flight request may finish after Stop.'))


def publish_job(store, payload, job, callback):
    from worker import FatalJobError
    tag = payload.get('artifact_digest') or ''
    try:
        publish_admission(store, payload['automatic_release_id'], payload['owner'], payload['scan_id'], payload['file'], tag.removeprefix('sha256:'), queued=True)
    except ValueError as exc:
        raise FatalJobError(str(exc)) from exc
    return callback(payload, job)


def delivery_watch(progress, pending_jobs):
    """Watch actual delivery transitions, never continuation heartbeats or row updates."""
    entries = progress.get('files', {})
    eligible = any(e.get('state') not in {'published', 'failed'} and
                   (e.get('artifact_digest') or e.get('waiting_for_delivery'))
                   for e in entries.values())
    signature = json.dumps({
        'files': {f: {k: e.get(k) for k in ('state', 'artifact_digest', 'receipt', 'waiting_for_delivery')}
                  for f, e in entries.items()},
        'jobs': {f: sorted(states) for f, states in pending_jobs.items()},
    }, sort_keys=True)
    previous = progress.get('_delivery_watch', {})
    now = datetime.now(timezone.utc)
    changed = previous.get('signature') != signature
    last = now.isoformat() if changed else previous.get('last_progress_at', now.isoformat())
    try:
        elapsed = (now - datetime.fromisoformat(last)).total_seconds()
    except (ValueError, TypeError):
        last, elapsed = now.isoformat(), 0
    stalled = eligible and elapsed >= STALL_AFTER_SECONDS
    return dict(signature=signature, last_progress_at=last, needs_attention=stalled,
                reason=('No delivery progress for 10 minutes. Check the destination and delivery receipt before retrying; a copy may already exist.'
                        if stalled else None))


def resume(store, authorization_id, owner, scan_id):
    """Wake the original permission after reconnect; never extend or replace it."""
    with store.transaction():
        row = persistence.get(store, authorization_id, owner, lock=True)
        if not row or row['scan_id'] != scan_id or row['status'] not in ACTIVE:
            raise ValueError('This release permission cannot be resumed. Review a new plan explicitly.')
        for file in row['intent']['files']:
            require_authority(store, row, file)
        progress = dict(row['progress'])
        entries = {f: dict(e) for f, e in progress.get('files', {}).items()}
        for file, entry in entries.items():
            if entry.get('state') == 'published' or entry.get('failure_category') == 'no_corrected_copy':
                continue
            if entry.get('artifact_digest'):
                record = ready(store, row, file)
                if entry['artifact_digest'] != record['corrected_sha256']:
                    raise ValueError('The admitted corrected copy changed. Review a new plan explicitly.')
                entry.update(state='publishing', resume_requested=True, requires_reconnect=False,
                    message='Checking the saved delivery before resuming.')
        progress['files'] = entries
        progress.pop('_delivery_watch', None)
        return persistence.save(store, row, status='waiting', progress=progress, schedule=True, delay=0)


def dispatch(store, row, file, digest):
    from routes.scans import publish_files
    request = request_for(row['owner_email'], row['scan_id'])
    if row['intent']['source'] == 'drive' and not request.headers.get('x-drive-token'):
        raise DriveReconnectRequired('Reconnect Google Drive to resume this saved release. No new upload has been requested.')
    return publish_files(row['scan_id'], request,
        dict(files=[file], destination=row['intent']['destination'] if row['intent']['release_parent_id'] else None,
             release_folder_name=row['intent']['release_folder_name'], automatic_release_id=row['id'],
             allow_remaining_issues=row['intent'].get('allow_remaining_issues', False),
             expected_artifacts={file: digest}, expected_destination=row['intent']['destination'] if row['intent']['release_parent_id'] else None))


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
                        dict(state='published',receipt=saved,message='Delivered',requires_reconnect=False,resume_requested=False))
                elif pending_jobs.get(file) and all(s in {'dead','cancelled'} for s in pending_jobs[file]):
                    if row['intent']['source'] == 'drive':
                        if entry.get('resume_requested') and dispatched < MAX_DISPATCH_PER_TICK:
                            dispatch(store, row, file, entry['artifact_digest'])
                            dispatched += 1
                            persistence.update_file(store,row['id'],row['owner_email'],file,
                                dict(state='publishing', resume_requested=False, requires_reconnect=False, message='Checking the saved delivery before resuming.'))
                        else:
                            persistence.update_file(store,row['id'],row['owner_email'],file,
                                dict(state='blocked', message='Delivery job stopped or failed. Reconnect Google Drive and resume to check its receipt safely.'))
                    else:
                        persistence.update_file(store,row['id'],row['owner_email'],file,
                            dict(state='failed',message='Delivery job stopped or failed. Reconcile its receipt before authorizing another attempt.'))
                elif row['intent']['source'] == 'drive' and not pending_jobs.get(file) and dispatched < MAX_DISPATCH_PER_TICK:
                    # Legacy synchronous delivery has no durable worker. The queue helper
                    # retains its stage/reservation identities and only admits frozen bytes.
                    dispatch(store, row, file, entry['artifact_digest'])
                    dispatched += 1
                    persistence.update_file(store,row['id'],row['owner_email'],file,
                        dict(state='publishing', resume_requested=False, requires_reconnect=False, message='Checking the saved delivery before resuming.'))
                else:
                    persistence.update_file(store,row['id'],row['owner_email'],file,
                        dict(state='publishing', message='Delivery not yet confirmed. Waiting for a recorded receipt; a copy may already exist.'))
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
                if store._db.fetchone(cur) and row['intent']['source'] != 'drive':
                    persistence.update_file(store,row['id'],row['owner_email'],file,
                        dict(state='waiting', waiting_for_delivery=True, message='Corrected copy is ready. Waiting for the current delivery to finish.'))
                    continue
            row = publish_admission(store, row['id'], row['owner_email'], row['scan_id'], file, digest)
            dispatched += 1
            result = dispatch(store, row, file, digest)
            outcome = next((r for r in result.get('published',[]) if r.get('file')==file),{})
            confirmed = receipt(store,row,file,digest)
            state = 'published' if confirmed else 'publishing' if outcome.get('status') in {'queued','published'} else 'failed'
            persistence.update_file(store,row['id'],row['owner_email'],file,dict(state=state,artifact_digest=digest,
                message='Delivered' if state=='published' else 'Waiting for delivery receipt' if state=='publishing' else 'Delivery was not confirmed. Inspect the receipt before retrying.',receipt=outcome))
        except DeliveryAlreadyAdmitted:
            continue
        except FileRemediationFinishedWithoutCopy as exc:
            persistence.update_file(store,row['id'],row['owner_email'],file,dict(state='failed',message=str(exc),failure_category='no_corrected_copy'))
        except DriveReconnectRequired as exc:
            persistence.update_file(store,row['id'],row['owner_email'],file,dict(state='blocked',message=str(exc),requires_reconnect=True,waiting_for_delivery=False))
        except (ValueError, ReleaseArtifactError) as exc:
            persistence.update_file(store,row['id'],row['owner_email'],file,dict(state='blocked',message=str(exc),waiting_for_delivery=False))
        except Exception:
            persistence.update_file(store,row['id'],row['owner_email'],file,
                dict(state='blocked' if row['intent']['source'] == 'drive' else 'failed',
                     message='Delivery outcome is unknown. Reconcile its receipt before retrying.'))
    with store.transaction():
        row = persistence.get(store,row['id'],row['owner_email'],lock=True)
        if row['status'] not in ACTIVE or payload['revision'] != row['progress'].get('_tick_revision',0):
            return
        states = [r.get('state') for r in row['progress'].get('files',{}).values()]
        expired = datetime.now(timezone.utc) >= datetime.fromisoformat(row['intent']['expires_at'])
        completed = len(states)==len(row['intent']['files']) and all(s=='published' for s in states)
        terminal = len(states)==len(row['intent']['files']) and all(s in {'published', 'failed'} for s in states)
        if (terminal or expired) and row['intent'].get('include_reports'):
            from release_report_delivery import queue_release_reports
            release = store.release_for_scan(row['scan_id'], row['owner_email'])
            if release:
                # Include selected files that finished without a copy even if another
                # file created the release only later in this tick. Never replace a receipt.
                failures = [(file, entry) for file, entry in row['progress'].get('files', {}).items()
                            if entry.get('failure_category') == 'no_corrected_copy']
                if failures:
                    store.ensure_release_execution(row['scan_id'], row['owner_email'], row['intent']['source'],
                        len(row['intent']['files']), preferred_folder_name=release['folder_name'],
                        parent_folder_id=release.get('parent_folder_id'), parent_folder_name=release.get('parent_folder_name'))
                    for file, entry in failures:
                        saved = store.get_release_document(release['id'], file, row['owner_email'])
                        if not saved or saved.get('status') != 'published':
                            store.record_release_document(release['id'], row['owner_email'],
                                dict(file=file, status='failed', failure_category='no_corrected_copy', explanation=entry['message']))
                # Freeze reports and enqueue delivery in the same transaction as completion.
                queue_release_reports(store, row['scan_id'], row['owner_email'], release['id'])
        progress = {**row['progress'], '_delivery_watch': delivery_watch(row['progress'], pending_jobs)}
        stalled = progress['_delivery_watch']['needs_attention']
        persistence.save(store,row,status='completed' if completed else 'failed' if terminal or expired else 'blocked' if stalled else 'waiting',
                         progress=progress,schedule=not terminal and not expired,delay=STALLED_CHECK_SECONDS if stalled else 20)


def validate_publish_request(store, sid, owner, files, body):
    """Only an exact previously admitted artifact may use automatic authority."""
    row = persistence.get(store,body['automatic_release_id'],owner)
    if not row or row['scan_id'] != sid:
        raise ValueError('Automatic release authorization not found in this scan.')
    if body.get('allow_remaining_issues', False) != row['intent'].get('allow_remaining_issues', False):
        raise ValueError('Automatic release options differ from the accepted plan.')
    expected_destination = row['intent']['destination'] if row['intent']['release_parent_id'] else None
    if body.get('destination') != expected_destination or body.get('release_folder_name') != row['intent']['release_folder_name']:
        raise ValueError('Automatic release destination differs from the authorized destination.')
    for file in files:
        record = ready(store,row,file)
        frozen = row['progress'].get('files',{}).get(file,{}).get('artifact_digest')
        if not frozen or record['corrected_sha256'] != frozen or body.get('expected_artifacts',{}).get(file) != frozen:
            raise ValueError('Automatic release requires the exact admitted verified artifact.')
    return row
