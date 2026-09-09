"""Explicit batch authorization → existing apply/verify jobs → guarded Release.

The intent is server-authored and immutable. No later proposal is implicitly authorized.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import release_continuation_store as persistence
from release_artifacts import ReleaseArtifactError, require_current_source

TERMINAL = {'published', 'blocked', 'failed', 'needs_confirmation'}


def proposal_identity(row):
    from remediation_run_insights import PROPOSAL_KEYS
    return {'id': row['id'], 'rule_id': row.get('rule_id'),
            'proposals': [{k: p[k] for k in PROPOSAL_KEYS if k in p} for p in row.get('proposals') or []],
            'snapshots': row.get('proposal_snapshot_ids') or [], 'finding_count': row.get('finding_count')}


def eligibility(row, file):
    import handlers
    ext = file.rsplit('.', 1)[-1].lower()
    rule = row.get('rule_id')
    writers = {'1.1.1': handlers._APPLY_VALUE_EXTS, '2.4.4': handlers._OFFICE_LINK_EXTS,
               '2.4.9': handlers._OFFICE_LINK_EXTS, '4.1.2': handlers._FIELD_NAME_EXTS,
               '1.3.3': handlers._SENSORY_EXTS, '3.1.2': handlers._LANGUAGE_EXTS,
               '2.4.6': handlers._STRUCTURE_LABEL_EXTS, '1.4.5': handlers._IMAGE_OF_TEXT_EXTS}
    if row.get('status') != 'pending' or row.get('superseded') or row.get('applied'):
        return 'Already handled or changed'
    if ext not in writers.get(rule, ()):
        return 'Manual work or no supported proposal writer'
    proposals = row.get('proposals') or []
    snapshots = row.get('proposal_snapshot_ids') or []
    if (not proposals or (row.get('finding_count') or 0) > len(proposals)
            or not all(isinstance(p, dict) and isinstance(p.get('proposed_value'), str)
                       and p['proposed_value'].strip() and p.get('locator') for p in proposals)):
        return 'Missing exact proposed content'
    if len(snapshots) != len(proposals) or not all(snapshots) or row.get('decision_version') is None:
        return 'Proposal version unavailable'
    return None


def record_identity(record):
    return {k: record.get(k) for k in ('drive_file_id', 'source_modified', 'checksum',
                                      'drive_id', 'source_relative_path')}


def queue_rows(store, sid, owner, file):
    return [r for r in store.list_hitl_queue(scan_id=sid, owner=owner, include_superseded=True)
            if r.get('file') == file]


def plan(store, sid, owner, files, destination, folder_name):
    from assessment_policy import selected_documents
    scan = store.get_scan(sid, owner=owner)
    if not scan:
        raise ValueError('scan not found')
    selection = selected_documents(store.get_decisions(sid, owner=owner))
    available = {r['file']: r for r in scan.get('files', [])}
    if not files or set(files) - available.keys() or (selection is not None and set(files) - selection):
        raise ValueError('Release scope changed; choose the current files')
    revision = store.stage_snapshot_id(sid)
    existing = store.release_for_scan(sid, owner)
    if existing:
        actual_parent = existing.get('parent_folder_id')
        if destination and destination['folder_id'] != actual_parent:
            raise ValueError('This scan already has a different Release destination')
        destination = ({'provider': scan['run'].get('source'), 'folder_id': actual_parent,
                        'folder_name': existing.get('parent_folder_name') or 'Existing Release parent'}
                       if actual_parent else None)
        folder_name = existing['folder_name']
    if not existing and scan['run'].get('source') == 'sharepoint':
        import publish
        folder_name = publish.sharepoint_release_name(folder_name, owner)
    elif not folder_name:
        import publish
        folder_name = publish.release_folder_name(owner_email=owner)
    # The previous per-file helper decoded the entire review queue again for
    # every document (177 full queue reads on the observed legacy run).
    records = store.get_file_records(sid, owner=owner)
    rows_by_file = {}
    for row in store.list_hitl_queue(scan_id=sid, owner=owner, include_superseded=True):
        rows_by_file.setdefault(row['file'], []).append(row)
    planned = {}
    for file in sorted(set(files)):
        record = records.get(file) or {}
        rows = rows_by_file.get(file, [])
        classified = [(r, eligibility(r, file)) for r in rows]
        candidates = {r['id'] for r, reason in classified if not reason}
        ready = bool(record.get('compliant') and record.get('remediated_at') and record.get('corrected_sha256'))
        blockers = [reason for r, reason in classified if r.get('status') in {'pending', 'in_review'}
                    and not r.get('superseded') and reason]
        if not record.get('remediated_at') or not record.get('corrected_sha256'):
            candidates = set()
            blockers.append('No verified corrected artifact is available')
        planned[file] = {'record': record_identity(record), 'artifact': record.get('corrected_sha256'),
                         'ready': ready, 'blockers': sorted(set(blockers)),
                         'rows': [{**proposal_identity(r), 'status': r.get('status'),
                                   'version': r.get('decision_version'),
                                   'authorize': r['id'] in candidates} for r in rows]}
    return persistence.create(store, owner, sid, {'source': scan['run'].get('source') or 'local',
        'source_revision': revision, 'files': planned, 'destination': destination,
        'release_folder_name': folder_name})


def request_for(owner, sid):
    import core
    tokens = core.get_scan_tokens(sid)
    return SimpleNamespace(state=SimpleNamespace(user_email=owner), headers={
        'x-drive-token': tokens.get('drive', ''), 'x-sp-token': tokens.get('sp', '')})


def current_inputs(store, row, file, *, authorized):
    from assessment_policy import selected_documents
    intent, sid, owner = row['intent'], row['scan_id'], row['owner_email']
    require_grants(store, owner, review=any(r['authorize'] for r in intent['files'][file]['rows']))
    existing = store.release_for_scan(sid, owner)
    if existing and (existing.get('parent_folder_id') != (intent['destination'] or {}).get('folder_id')
                     or existing.get('folder_name') != intent['release_folder_name']):
        raise ValueError('Release destination changed; confirm again')
    if store.get_scan(sid, owner=owner) is None:
        raise ValueError('Scan access changed')
    selection = selected_documents(store.get_decisions(sid, owner=owner))
    if selection is not None and file not in selection:
        raise ValueError('File selection changed; confirm again')
    if store.stage_snapshot_id(sid) != intent['source_revision']:
        raise ValueError('Assessed source changed; confirm again')
    planned = intent['files'][file]
    record = store.get_file_record(sid, file) or {}
    if record_identity(record) != planned['record']:
        raise ValueError('Source identity changed; confirm again')
    rows = {r['id']: r for r in queue_rows(store, sid, owner, file)}
    if set(rows) != {r['id'] for r in planned['rows']}:
        raise ValueError('Review items changed; new proposals need fresh authorization')
    for expected in planned['rows']:
        current = rows[expected['id']]
        if proposal_identity(current) != {k: expected[k] for k in proposal_identity(current)}:
            raise ValueError('Proposal content changed; confirm again')
        if expected['authorize'] and authorized:
            if (current.get('status') != 'approved'
                    or current.get('last_decision_request_id') != f"{row['id']}:{expected['id']}"
                    or current.get('decision_version') != expected['version'] + 1):
                raise ValueError('Approval changed; confirm again')
        elif current.get('status') != expected['status'] or current.get('decision_version') != expected['version']:
            raise ValueError('Review decisions changed; confirm again')
    digest = row['artifacts'].get(file) or planned['artifact']
    if record.get('corrected_sha256') != digest:
        raise ValueError('Corrected artifact changed outside this authorized flow; confirm again')
    return record


def source_check(row, record):
    import core
    import handlers
    tokens = core.get_scan_tokens(row['scan_id'])
    svc = handlers._drive_client(tokens.get('drive')) if row['intent']['source'] == 'drive' else None
    require_current_source(row['intent']['source'], record, drive_service=svc, sp_token=tokens.get('sp'))


def authorize(store, intent_id, owner):
    # Validate provider/source reads outside the transaction, then recheck durable inputs under
    # the decision transaction. Every exact approval and its apply job commit together.
    row = persistence.get(store, intent_id, owner)
    if not row:
        raise ValueError('Release plan not found')
    if row['status'] != 'draft':
        return row
    for file, selected in row['intent']['files'].items():
        if not selected['ready'] and not any(r['authorize'] for r in selected['rows']):
            continue
        record = current_inputs(store, row, file, authorized=False)
        source_check(row, record)
    with store.transaction():
        row = persistence.get(store, intent_id, owner, lock=True)
        if row['status'] != 'draft':
            return row
        for file, selected in row['intent']['files'].items():
            if not selected['ready'] and not any(r['authorize'] for r in selected['rows']):
                continue
            current_inputs(store, row, file, authorized=False)
        # Reserve the immutable scan Release destination in the approval transaction, so an
        # independent ready-only action cannot choose a different folder between ticks.
        store.ensure_release_execution(row['scan_id'], owner, row['intent']['source'], 0,
            preferred_folder_name=row['intent']['release_folder_name'],
            parent_folder_id=(row['intent']['destination'] or {}).get('folder_id'),
            parent_folder_name=(row['intent']['destination'] or {}).get('folder_name'))
        progress = {}
        for file, selected in row['intent']['files'].items():
            if selected['ready'] or any(r['authorize'] for r in selected['rows']):
                current_inputs(store, row, file, authorized=False)
            approvals = [r for r in selected['rows'] if r['authorize']]
            progress[file] = {'state': 'applying' if approvals else 'ready' if selected['ready'] else 'blocked',
                              'message': '; '.join(selected['blockers']) or 'Verification is required'}
            for item in approvals:
                values = [p['proposed_value'] for p in item['proposals']]
                store.complete_hitl_decision(item['id'], 'approved', None, values[0],
                    resolution=None, approved_values=values, actor=owner,
                    detail='Explicit batch authorization to apply these proposals and publish only after verification',
                    request_id=f"{row['id']}:{item['id']}", expected_version=item['version'],
                    expected_proposal_snapshot_ids=item['snapshots'],
                    expected_source_revision=row['intent']['source_revision'], release_intent_id=row['id'])
        progress['_deadline'] = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        return persistence.save(store, row, status='waiting', progress=progress, schedule=True)


def check_application(store, intent_id, sid, file):
    scan = store.get_scan(sid)
    owner = (scan or {}).get('run', {}).get('owner_email')
    row = persistence.get(store, intent_id, owner)
    if not row or row['scan_id'] != sid or file not in row['intent']['files'] or row['status'] not in {'waiting', 'publishing'}:
        raise ValueError('Release authorization is not active for this file')
    record = current_inputs(store, row, file, authorized=True)
    source_check(row, record)
    return row


def application_jobs(store, row, file):
    import json
    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT id,status,payload,last_error FROM jobs WHERE scan_id=%s AND type='apply_approved_values'",
                          (row['scan_id'],))
        jobs = store._db.fetchall(cur)
    return [j for j in jobs if (json.loads(j['payload']) if isinstance(j['payload'], str) else j['payload']).get('release_intent_id') == row['id']
            and (json.loads(j['payload']) if isinstance(j['payload'], str) else j['payload']).get('file') == file]


def advance(store, payload, job):
    from routes.scans import publish_files
    from worker import check_cancel, JobCancelledError
    row = persistence.get(store, payload['intent_id'], payload['owner'])
    if not row or row['revision'] != payload['revision'] or row['status'] not in {'waiting', 'publishing'}:
        return
    progress = dict(row['progress'])
    for file, planned in row['intent']['files'].items():
        check_cancel()
        if progress[file]['state'] in TERMINAL:
            continue
        try:
            # Application commits the exact output digest independently of tick progress.
            row['artifacts'] = persistence.get(store, row['id'], row['owner_email'])['artifacts']
            record = current_inputs(store, row, file, authorized=True)
            jobs = application_jobs(store, row, file)
            if any(j['status'] in {'queued', 'running'} for j in jobs):
                if datetime.now(timezone.utc) >= datetime.fromisoformat(progress['_deadline']):
                    progress[file] = {'state': 'blocked', 'message': 'Application did not finish within 30 minutes. Check its job before retrying.'}
                continue
            if any(j['status'] in {'dead', 'cancelled'} for j in jobs):
                progress[file] = {'state': 'blocked', 'message': 'Application or verification failed. The file was not published.'}
                continue
            if any(r['authorize'] for r in planned['rows']) and not row['artifacts'].get(file):
                progress[file] = {'state': 'blocked', 'message': 'No verified output from the approved changes. The file was not published.'}
                continue
            if not record.get('compliant') or not record.get('remediated_at') or store.count_unapplied_approved_values(row['scan_id'], file):
                progress[file] = {'state': 'blocked', 'message': '; '.join(planned['blockers']) or 'Verification did not clear every required finding. Manual work remains.'}
                continue
            source_check(row, record)
            current_inputs(store, row, file, authorized=True)
            # Reuse the normal owner/scope/source/artifact/destination and side-effect gates.
            result = publish_files(row['scan_id'], request_for(row['owner_email'], row['scan_id']),
                {'files': [file], 'destination': row['intent']['destination'],
                 'release_folder_name': row['intent']['release_folder_name'],
                 'expected_artifacts': {file: record['corrected_sha256']},
                 'expected_destination': row['intent']['destination']})
            outcome = next((r for r in result.get('published', []) if r.get('file') == file), {})
            if outcome.get('status') == 'published':
                progress[file] = {'state': 'published', 'message': 'Delivered', 'receipt': outcome}
            elif outcome.get('status') == 'queued' or result.get('queued'):
                if datetime.now(timezone.utc) >= datetime.fromisoformat(progress['_deadline']):
                    progress[file] = {'state': 'failed', 'message': 'Delivery is not yet confirmed. Check the delivery receipt before retrying.'}
                else:
                    progress[file] = {'state': 'publishing', 'message': 'Waiting for the delivery receipt'}
            else:
                progress[file] = {'state': 'failed', 'message': outcome.get('explanation') or 'Delivery failed', 'receipt': outcome}
        except JobCancelledError:
            raise
        except (ValueError, ReleaseArtifactError) as exc:
            progress[file] = {'state': 'needs_confirmation', 'message': str(exc)}
        except Exception as exc:
            progress[file] = {'state': 'failed', 'message': str(exc)}
    pending = any(v.get('state') not in TERMINAL for k, v in progress.items() if k != '_deadline')
    persistence.save(store, row, status='waiting' if pending else 'completed', progress=progress,
                     schedule=pending, delay=20)


def resume(store, intent_id, owner):
    with store.transaction():
        row = persistence.get(store, intent_id, owner, lock=True)
        if not row:
            raise ValueError('Release plan not found')
        if row['status'] in {'waiting', 'publishing'}:
            return row
        progress = dict(row['progress'])
        retry = [file for file in row['intent']['files'] if progress.get(file, {}).get('state') == 'failed']
        for file in retry:
            current_inputs(store, row, file, authorized=True)
            progress[file] = {'state': 'ready', 'message': 'Retrying the same authorized artifact'}
        if not retry:
            return row
        progress['_deadline'] = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        return persistence.save(store, row, status='waiting', progress=progress, schedule=True)


def require_grants(store, owner, *, review):
    import core
    import workspace_roles
    import workspace_rollout
    if not workspace_rollout.enforcement_active():
        return
    access = workspace_roles.access_for_email(store, owner, owner_email=core.OWNER_EMAIL,
                                               is_suspended=core.is_suspended)
    required = {'release.publish'} | ({'remediate.review'} if review else set())
    if not required <= set(access.get('capabilities') or ()):
        raise ValueError('Approval or publish permission changed; access must be restored before proceeding')
