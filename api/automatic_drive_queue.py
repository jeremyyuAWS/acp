"""Narrow queue adoption for one immutable automatic Google Drive permission."""
from datetime import datetime, timezone
import hashlib
import json


def enqueue(store, sid, payloads, *, snapshot_id, request_fingerprint, input_manifest_id=None, manual_owner=None):
    import automatic_release as flow
    import automatic_release_store as persistence
    import publish
    if not payloads or len(payloads) > flow.MAX_FILES:
        raise ValueError('An exact bounded automatic delivery selection is required.')
    first = payloads[0]
    owner, authorization = first.get('owner'), first.get('automatic_release_id')
    with store.transaction():
        release = store.release_for_scan(sid, owner)
        if not release:
            raise ValueError('The frozen release destination is missing.')
        manual = manual_owner is not None
        if manual:
            from release_continuation import require_grants
            from release_artifacts import require_current_record
            require_grants(store, owner, review=False)
            scan = store.get_scan(sid, owner=owner)
            if manual_owner != owner or authorization or not scan or (scan.get('run') or {}).get('source') != 'drive':
                raise ValueError('Explicit Drive delivery does not match this owner and scan.')
            row = dict(intent=dict(files={p.get('file'): {} for p in payloads}), progress=dict(files={
                p.get('file'): dict(artifact_digest=(p.get('artifact_digest') or '').removeprefix('sha256:'), resume_requested=True) for p in payloads}))
        else:
            row = persistence.get(store, authorization, owner, lock=True)
            if not row or row['scan_id'] != sid or row['intent']['source'] != 'drive':
                raise ValueError('Automatic Drive permission does not match this scan.')
        seen = set()
        for payload in payloads:
            file = payload.get('file')
            if file in seen or payload.get('owner') != owner or payload.get('scan_id') != sid or payload.get('automatic_release_id') != authorization or payload.get('release_id') != release['id']:
                raise ValueError('Delivery payload differs from the automatic permission.')
            seen.add(file)
            if manual:
                record = require_current_record(store, sid, file,
                    (payload.get('artifact_digest') or '').removeprefix('sha256:'),
                    payload.get('remediated_at'), owner=owner,
                    allow_remaining_issues=bool(payload.get('allow_remaining_issues')))
            else:
                record = flow.ready(store, row, file)
            frozen = row['progress'].get('files', {}).get(file, {}).get('artifact_digest')
            if not frozen or frozen != record['corrected_sha256'] or payload.get('artifact_digest') != 'sha256:' + frozen or payload.get('remediated_at') != record['remediated_at'] or (not manual and bool(payload.get('allow_remaining_issues')) != bool(row['intent'].get('allow_remaining_issues'))):
                raise ValueError('Delivery requires the exact previously admitted artifact and review policy.')
        with store._db.cursor() as cur:
            if store._db.supports_skip_locked:
                store._db.execute(cur, 'SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (f'stage:{sid}:release',))
            store._db.execute(cur, "SELECT * FROM stage_executions WHERE scan_id=%s AND stage='release' AND is_current=1 AND state IN ('accepted','queued','processing','paused','processing_complete','reconciling','failed','interrupted','cancelled')", (sid,))
            execution = store._db.fetchone(cur)
            if not execution:
                return store.enqueue_stage_batch(sid, 'release', 'publish_file', payloads,
                    snapshot_id=snapshot_id, request_fingerprint=request_fingerprint,
                    input_manifest_id=input_manifest_id)
            if execution.get('owner_email') != owner or execution.get('cancel_requested_at') or execution['state'] in {'paused', 'processing_complete', 'reconciling', 'cancelled'}:
                raise ValueError('The current release cannot accept additional delivery work.')
            batch = execution['execution_id']
            store._db.execute(cur, 'SELECT w.*,j.payload AS queued_payload,j.status AS job_status FROM stage_work_items w LEFT JOIN jobs j ON j.id=w.job_id WHERE w.execution_id=%s', (batch,))
            items = store._db.fetchall(cur)
            by_file = {}
            # Never adopt another release, even when it happens to name the same file.
            for item in items:
                file = item['input_id']
                if manual and file not in seen:
                    # A subset retry must leave its siblings untouched, including
                    # completed documents filtered out by the route as exact reuses.
                    if item.get('job_id'):
                        prior = item['queued_payload']
                        prior = json.loads(prior) if isinstance(prior, str) else prior
                        if not prior or prior.get('owner') != owner or prior.get('scan_id') != sid or prior.get('automatic_release_id') or prior.get('release_id') != release['id']:
                            raise ValueError('A different delivery intent owns the current release.')
                    else:
                        record = store.get_file_record(sid, file) or {}
                        folders, name = publish.normalize_relative_path(record.get('source_relative_path') or record.get('parent_folder') or file, file)
                        destination = f"google:me:{release['id']}:{'/'.join([*folders, name])}"
                        store._db.execute(cur, 'SELECT effect_type,destination FROM side_effect_receipts WHERE execution_id=%s AND work_item_id=%s', (batch, item['work_item_id']))
                        effects = store._db.fetchall(cur)
                        if not effects or any(e['effect_type'] != 'drive.publish' or e['destination'] != destination for e in effects):
                            raise ValueError('A different delivery reservation owns the current release.')
                    by_file[file] = item
                    continue
                entry = row['progress'].get('files', {}).get(file, {})
                if file not in row['intent']['files'] or not entry.get('artifact_digest'):
                    raise ValueError('A different release is already active.')
                if item.get('job_id'):
                    prior = item['queued_payload']
                    prior = json.loads(prior) if isinstance(prior, str) else prior
                    if not prior or prior.get('automatic_release_id') != authorization or prior.get('release_id') != release['id'] or prior.get('artifact_digest') != 'sha256:' + entry['artifact_digest']:
                        raise ValueError('A different delivery intent owns the current release.')
                else:
                    record = store.get_file_record(sid, file) if manual else flow.require_authority(store, row, file)
                    folders, name = publish.normalize_relative_path(record.get('source_relative_path') or record.get('parent_folder') or file, file)
                    destination = f"google:me:{release['id']}:{'/'.join([*folders, name])}"
                    store._db.execute(cur, 'SELECT * FROM side_effect_receipts WHERE execution_id=%s AND work_item_id=%s', (batch, item['work_item_id']))
                    for effect in store._db.fetchall(cur):
                        if effect['effect_type'] != 'drive.publish' or effect['destination'] != destination or effect['content_digest'] != entry['artifact_digest']:
                            raise ValueError('The prior delivery reservation does not match the frozen artifact.')
                        # Other files may still queue, but this item cannot race its old owner.
                        if file in seen and effect['status'] == 'reserved' and effect.get('lease_expires_at') and datetime.fromisoformat(effect['lease_expires_at'].replace('Z', '+00:00')) > datetime.now(timezone.utc):
                            raise ValueError('Waiting for the existing delivery reservation to expire before checking its receipt.')
                by_file[file] = item
            now = store._now()
            job_ids, statuses, changed = [], [], False
            for original in payloads:
                file = original['file']
                item = by_file.get(file)
                payload = dict(original, snapshot_id=execution['input_snapshot_id'], stage_execution_id=batch)
                if item and item.get('job_id') and item['job_status'] not in {'dead', 'cancelled'}:
                    job_ids.append(item['job_id']); statuses.append(item['job_status']); continue
                if item and item.get('job_id'):
                    entry = row['progress'].get('files', {}).get(file, {})
                    if not entry.get('resume_requested'):
                        raise ValueError('Reconnect and resume explicitly before retrying a failed delivery.')
                    job_id = item['job_id']
                    store._db.execute(cur, "UPDATE jobs SET status='queued',attempts=0,payload=%s,run_after=%s,locked_at=NULL,locked_by=NULL,lease_expires_at=NULL,phase=NULL,last_error=NULL,cancel_requested_at=NULL,updated_at=%s WHERE id=%s", (json.dumps(payload), now, now, job_id))
                else:
                    job_id = store.enqueue_job('publish_file', payload, scan_id=sid, batch_id=batch)
                work_item = store._work_item_identity(batch, file)
                store._db.execute(cur, "INSERT INTO stage_work_items(work_item_id,execution_id,input_id,job_id,state,revision,attempt,created_at,updated_at) VALUES(%s,%s,%s,%s,'queued',1,0,%s,%s) ON CONFLICT(work_item_id) DO UPDATE SET job_id=excluded.job_id,state='queued',revision=stage_work_items.revision+1,attempt=0,lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,terminal_reason=NULL,result_digest=NULL,updated_at=excluded.updated_at", (work_item, batch, file, job_id, now, now))
                message = hashlib.sha256(f'outbox\0{work_item}'.encode()).hexdigest()
                store._db.execute(cur, "INSERT INTO stage_outbox(message_id,execution_id,work_item_id,topic,payload,created_at) VALUES(%s,%s,%s,'publish_file',%s,%s) ON CONFLICT(message_id) DO NOTHING", (message, batch, work_item, json.dumps(dict(job_id=job_id, execution_id=batch, work_item_id=work_item)), now))
                job_ids.append(job_id); statuses.append('queued'); changed = True
            if changed:
                store._db.execute(cur, "UPDATE stage_executions SET state='queued',expected_items=(SELECT COUNT(*) FROM stage_work_items WHERE execution_id=%s),terminal_items=(SELECT COUNT(*) FROM stage_work_items WHERE execution_id=%s AND state IN ('completed','failed','cancelled','skipped')),revision=revision+1,updated_at=%s WHERE execution_id=%s", (batch, batch, now, batch))
            return dict(batch_id=batch, job_ids=job_ids, statuses=statuses, reused=not changed)
