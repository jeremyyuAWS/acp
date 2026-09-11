"""Frozen, owner-scoped follow-up reports delivered alongside published copies."""
import base64
import hashlib
import json
from urllib.parse import quote


def _asset_bytes(asset):
    return base64.b64decode(asset['content'], validate=True) if asset.get('encoding') == 'base64' else asset['content'].encode('utf-8')


def _get(store, bundle_id, owner):
    with store._db.cursor() as cur:
        store._db.execute(cur, 'SELECT * FROM release_report_bundles WHERE id=%s AND owner_email=%s', (bundle_id, owner))
        row = store._db.fetchone(cur)
    if row:
        for key in ('assets', 'receipts', 'roots'):
            row[key] = json.loads(row[key])
    return row


def _public(row):
    if not row:
        return dict(status='not_started', bundle_id=None, reports=[], error=None)
    reports = []
    for index, asset in enumerate(row['assets']):
        receipts = [v for k, v in row['receipts'].items() if k.endswith(':' + str(index))]
        reports.append(dict(name=asset['name'], content_type=asset['content_type'],
                            url=next((r.get('url') for r in receipts if r.get('url')), None),
                            download_url=f"/scans/{quote(row['scan_id'], safe='')}/release/reports/{row['id']}/{index}"))
    return dict(status=row['status'], bundle_id=row['id'], reports=reports, error=row.get('error'))


def _enqueue(store, row):
    return store.enqueue_job('publish_release_reports', dict(bundle_id=row['id'], owner=row['owner_email']), scan_id=row['scan_id'])


def queue_release_reports(store, scan_id, owner, release_id):
    from release_reports import build_release_reports
    release = store.release_status(release_id, owner)
    if not release or release['scan_id'] != scan_id:
        raise KeyError('Release not found')
    fingerprint = hashlib.sha256(json.dumps(['pdf-v2-action-checklist', release_id, release['documents'], release['roots']], sort_keys=True).encode()).hexdigest()
    identity = fingerprint[:24]
    with store.transaction():
        # Serialize creation and retries for this owner's release.
        with store._db.cursor() as cur:
            store._db.execute(cur, 'UPDATE release_executions SET id=id WHERE id=%s AND owner_email=%s', (release_id, owner))
        existing = _get(store, identity, owner)
        if existing:
            return _public(existing)
        assets = build_release_reports(store, scan_id, owner, release_id)
        names = {a['name']: a['name'].rsplit('.', 1)[0] + '-' + identity[:10] + '.' + a['name'].rsplit('.', 1)[1] for a in assets}
        frozen = []
        for asset in assets:
            binary = asset['content_type'] == 'application/pdf'
            content = base64.b64encode(asset['content']).decode('ascii') if binary else asset['content'].decode('utf-8') if isinstance(asset['content'], bytes) else asset['content']
            if asset['content_type'].startswith('text/html'):
                for old, new in names.items():
                    content = content.replace('href="' + old + '"', 'href="' + new + '"')
            frozen.append(dict(name=names[asset['name']], content_type=asset['content_type'], content=content, encoding='base64' if binary else 'utf-8'))
        with store._db.cursor() as cur:
            store._db.execute(cur, '''INSERT INTO release_report_bundles
                (id,release_id,scan_id,owner_email,assets,roots,receipts,status,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,'{}','queued',%s,%s)''',
                (identity, release_id, scan_id, owner, json.dumps(frozen), json.dumps(release['roots']), store._now(), store._now()))
        row = _get(store, identity, owner)
        _enqueue(store, row)
        return _public(row)


def get_latest_release_reports(store, sid, owner):
    with store._db.cursor() as cur:
        store._db.execute(cur, 'SELECT id FROM release_report_bundles WHERE scan_id=%s AND owner_email=%s ORDER BY created_at DESC,id DESC LIMIT 1', (sid, owner))
        row = store._db.fetchone(cur)
    return _public(_get(store, row['id'], owner)) if row else _public(None)


def get_release_report_asset(store, sid, owner, bundle_id, index):
    row = _get(store, bundle_id, owner)
    if not row or row['scan_id'] != sid or type(index) is not int or not 0 <= index < len(row['assets']):
        raise KeyError('Report not found')
    asset = row['assets'][index]
    return {**asset, 'content': _asset_bytes(asset)}


def retry_release_reports(store, sid, owner):
    latest = get_latest_release_reports(store, sid, owner)
    if not latest['bundle_id']:
        raise KeyError('Report not found')
    if latest['status'] == 'completed' and (any(report['content_type'] != 'application/pdf' for report in latest['reports']) or not any(report['name'].startswith('changes-') for report in latest['reports'])):
        result = queue_if_release_settled(store, sid, owner, _get(store, latest['bundle_id'], owner)['release_id'])
        if not result:
            raise ValueError('Wait for publication to finish before generating PDF reports')
        return result
    with store.transaction():
        with store._db.cursor() as cur:
            store._db.execute(cur, "UPDATE release_report_bundles SET status='queued',error=NULL,updated_at=%s WHERE id=%s AND owner_email=%s AND status='failed'", (store._now(), latest['bundle_id'], owner))
            retry = cur.rowcount == 1
        row = _get(store, latest['bundle_id'], owner)
        if retry:
            _enqueue(store, row)
        return _public(row)


def _upload(root, asset, tokens, key):
    import publish
    import scanner
    data = _asset_bytes(asset)
    digest = hashlib.sha256(data).hexdigest()
    if root['provider'] == 'sharepoint':
        token = tokens.get('sp')
        if not token:
            raise ValueError('SharePoint connection is unavailable')
        drive = root['provider_location'].removeprefix('graph:')
        drive = None if drive == 'me' else drive
        existing = publish._sp_child(token, drive, root['folder_id'], asset['name'])
        if existing:
            if not publish._sp_content_matches(token, drive, existing['id'], digest):
                raise ValueError('A report with different content already exists')
            return dict(id=existing['id'], url=existing.get('webUrl'), checksum=digest)
        base = f"{scanner._sp_base(drive)}/items/{root['folder_id']}:/{quote(asset['name'], safe='')}:"
        result = scanner._sp_write(token, put_url=base + '/content', session_url=base + '/createUploadSession',
                                   content=data, content_type=asset['content_type'], conflict_behavior='fail', force_session=True)
        if not result.get('id') or not publish._sp_content_matches(token, drive, result['id'], digest):
            raise ValueError('Report upload could not be verified')
        return dict(id=result['id'], url=result.get('webUrl'), checksum=digest)
    if root['provider'] == 'drive':
        from handlers import _make_svc
        if not tokens.get('drive'):
            raise ValueError('Google Drive connection is unavailable')
        svc = _make_svc('drive', tokens)
        result = publish.upload_published(svc, root['folder_id'], asset['name'], data, idempotency_key=key, return_details=True)
        # Read back bytes: absent provider checksums are not verification evidence.
        actual = svc.files().get_media(fileId=result['id']).execute()
        if hashlib.sha256(actual).hexdigest() != digest:
            raise ValueError('Report upload could not be verified')
        return {**result, 'checksum': digest}
    raise ValueError('Unsupported report destination')


def process_release_reports(store, bundle_id, owner):
    import core
    from release_continuation import require_grants
    row = _get(store, bundle_id, owner)
    if not row:
        raise KeyError('Report not found')
    if row['status'] == 'completed':
        return _public(row)
    try:
        require_grants(store, owner, review=False)
        release = store.release_status(row['release_id'], owner)
        if not release or release['scan_id'] != row['scan_id'] :
            raise ValueError('Published folder is not available')
        current = {(r['provider'], r['provider_location'], r['folder_id']) for r in release['roots']}
        if any((r['provider'], r['provider_location'], r['folder_id']) not in current for r in row['roots']):
            raise ValueError('Published folder changed')
        tokens = core.get_scan_tokens(row['scan_id']) if row['roots'] else {}
        with store._db.cursor() as cur:
            store._db.execute(cur, "UPDATE release_report_bundles SET status='publishing',error=NULL,updated_at=%s WHERE id=%s AND owner_email=%s AND status!='completed'", (store._now(), bundle_id, owner))
        for root_index, root in enumerate(row['roots']):
            for asset_index, asset in enumerate(row['assets']):
                key = str(root_index) + ':' + str(asset_index)
                if key in row['receipts']:
                    continue
                result = _upload(root, asset, tokens, bundle_id + ':' + key)
                with store.transaction():
                    with store._db.cursor() as cur:
                        store._db.execute(cur, 'UPDATE release_report_bundles SET id=id WHERE id=%s AND owner_email=%s', (bundle_id, owner))
                    row['receipts'] = _get(store, bundle_id, owner)['receipts']
                    row['receipts'][key] = result
                    with store._db.cursor() as cur:
                        store._db.execute(cur, 'UPDATE release_report_bundles SET receipts=%s,updated_at=%s WHERE id=%s AND owner_email=%s', (json.dumps(row['receipts']), store._now(), bundle_id, owner))
        with store._db.cursor() as cur:
            store._db.execute(cur, "UPDATE release_report_bundles SET status='completed',error=NULL,updated_at=%s WHERE id=%s AND owner_email=%s", (store._now(), bundle_id, owner))
    except Exception:
        # Keep provider errors/tokens out of public metadata and leave document receipts intact.
        with store._db.cursor() as cur:
            store._db.execute(cur, "UPDATE release_report_bundles SET status='failed',error=%s,updated_at=%s WHERE id=%s AND owner_email=%s AND status!='completed'", ('Reports could not be delivered. Download them here or reconnect and retry.', store._now(), bundle_id, owner))
    return _public(_get(store, bundle_id, owner))


def queue_if_release_settled(store, sid, owner, release_id=None):
    release = store.release_status(release_id, owner) if release_id else store.release_for_scan(sid, owner)
    if not release or release.get('scan_id') != sid:
        return None
    release = store.release_status(release['id'], owner)
    documents = release.get('documents', [])
    if len(documents) < int(release.get('documents_total') or 0) or not documents:
        return None
    if any(d.get('status') not in {'published', 'failed'} for d in documents):
        return None
    return queue_release_reports(store, sid, owner, release['id'])
