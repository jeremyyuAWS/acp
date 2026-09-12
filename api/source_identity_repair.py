"""Recover omitted default-drive metadata from frozen Discovery and fresh Graph facts.

This does not authorize remediation, publish files, replace assessment, or read content.
Graph itself establishes the connected delegated grant; token claims are not trusted.
"""
from datetime import datetime, timezone
import json
from time import monotonic
from urllib.parse import quote
import httpx


class RepairBlocked(ValueError):
    pass


def _date(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise RepairBlocked('ambiguous_metadata') from None


def _selection(snapshot):
    run, job = snapshot['run'], snapshot['job']
    scope = run.get('scope') or {}
    if isinstance(scope, str):
        scope = json.loads(scope)
    if run.get('source') != 'sharepoint' or scope.get('kind') != 'sharepoint' or scope.get('site') or scope.get('site_id'):
        raise RepairBlocked('unsupported_selection')
    if not job or job.get('status') != 'done':
        raise RepairBlocked('discovery_provenance_unavailable')
    payload = job.get('payload') or {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    stage = snapshot.get('discover_stage') or {}
    if not payload.get('stage_execution_id') or stage.get('execution_id') != payload['stage_execution_id'] or stage.get('state') != 'succeeded' or stage.get('is_current') != 1:
        raise RepairBlocked('discovery_provenance_unavailable')
    # Only the original default /me/drive selection is repairable. Explicit library,
    # site, multi-folder, or later unknown routing must never be guessed.
    if payload.get('source') != 'sharepoint' or any(payload.get(k) for k in ('site','sites','site_id','drive_id','driveId','folder','folders')):
        raise RepairBlocked('unsupported_selection')
    if snapshot['remediation'] or any(r.get('remediated_at') for r in snapshot['records']):
        raise RepairBlocked('remediation_already_admitted')
    rows = snapshot['inventory']
    if not rows or len(rows) > 500:
        raise RepairBlocked('population_out_of_bounds')
    missing = [r for r in rows if not r.get('drive_id')]
    records = {r['file']: r for r in snapshot['records']}
    for row in missing:
        if not all(isinstance(row.get(k), str) and row[k] for k in ('file','drive_file_id','source_name','source_modified')) or row.get('site_id'):
            raise RepairBlocked('ambiguous_metadata')
        _date(row['source_modified'])
        record = records.get(row['file'])
        if not record or record.get('status') != 'analysed' or record.get('score') is None:
            raise RepairBlocked('assessment_incomplete')
        if record:
            if record.get('drive_file_id') != row['drive_file_id'] or _date(record.get('source_modified')) != _date(row['source_modified']):
                raise RepairBlocked('assessment_source_mismatch')
            if record.get('checksum') and row.get('checksum') and record['checksum'] != row['checksum']:
                raise RepairBlocked('assessment_source_mismatch')
    if len({r['drive_file_id'] for r in missing}) != len(missing):
        raise RepairBlocked('ambiguous_metadata')
    return missing


def probe(store, sid, owner):
    """Read-only candidacy. Fresh Graph permission and identity are checked by POST."""
    try:
        rows = _selection(store.source_identity_repair_snapshot(sid, owner))
        return {'available': bool(rows), 'files': [r['file'] for r in rows],
                'reason': 'missing_default_drive_identity' if rows else 'already_current'}
    except (RepairBlocked, ValueError, TypeError, KeyError):
        return {'available': False, 'files': [], 'reason': 'source_identity_not_repairable'}


def _checksum(expected, hashes):
    if not expected:
        return
    from source_checksum import checksum_algorithm
    algorithm = checksum_algorithm(expected)
    name = {'md5':'md5Hash','sha1':'sha1Hash','sha256':'sha256Hash','quickxor':'quickXorHash'}.get(algorithm)
    actual = hashes.get(name) if isinstance(hashes,dict) and name else None
    if not isinstance(actual,str):
        raise RepairBlocked('source_checksum_unverified')
    if algorithm == 'quickxor':
        matches = actual == expected
    else:
        matches = actual.lower() == expected.lower()
    if not matches:
        raise RepairBlocked('source_checksum_unverified')


def repair(store, sid, owner, token, *, post=None):
    if not isinstance(token, str) or not token:
        raise RepairBlocked('microsoft_connection_required')
    snapshot = store.source_identity_repair_snapshot(sid, owner)
    rows = _selection(snapshot)
    if not rows:
        return {'status': 'already_current', 'repaired_files': 0}
    requests = [{'id': 'drive', 'method': 'GET', 'url': '/me/drive?$select=id,driveType'}]
    requests += [{'id': str(i), 'method': 'GET', 'url': '/me/drive/items/' + quote(r['drive_file_id'], safe='') + '?$select=id,name,parentReference,lastModifiedDateTime,file'} for i,r in enumerate(rows)]
    found = {}
    deadline = monotonic() + 60
    def remaining():
        budget = deadline - monotonic()
        if budget <= 0:
            raise RepairBlocked('provider_metadata_timeout')
        return budget
    def send(batch):
        budget = remaining()
        if post:
            return post(batch)
        try:
            response = httpx.post('https://graph.microsoft.com/v1.0/$batch',
                                  headers={'Authorization': 'Bearer '+token},
                                  json={'requests': batch}, timeout=min(30, budget))
            if response.status_code != 200:
                raise RepairBlocked('microsoft_connection_required' if response.status_code in (401,403) else 'provider_metadata_unavailable')
            return response.json()
        except RepairBlocked:
            raise
        except (httpx.HTTPError, ValueError):
            raise RepairBlocked('provider_metadata_unavailable') from None
    for start in range(0,len(requests),20):
        batch = requests[start:start+20]
        data = send(batch)
        remaining()
        answers = data.get('responses') if isinstance(data,dict) else None
        if not isinstance(answers,list) or len(answers) != len(batch):
            raise RepairBlocked('provider_metadata_unavailable')
        expected_ids = {r['id'] for r in batch}
        for answer in answers:
            if not isinstance(answer,dict):
                raise RepairBlocked('ambiguous_metadata')
            identity = answer.get('id')
            if identity not in expected_ids or identity in found:
                raise RepairBlocked('ambiguous_metadata')
            if answer.get('status') != 200:
                raise RepairBlocked('microsoft_connection_required' if answer.get('status') in (401,403) else 'provider_metadata_unavailable')
            body = answer.get('body')
            if not isinstance(body,dict):
                raise RepairBlocked('ambiguous_metadata')
            found[identity] = body
    drive_id = found['drive'].get('id')
    if not isinstance(drive_id,str) or not drive_id or len(drive_id)>512:
        raise RepairBlocked('ambiguous_metadata')
    if any(r.get('drive_id') and r['drive_id'] != drive_id for r in snapshot['inventory']):
        raise RepairBlocked('source_drive_mismatch')
    records = {r['file']:r for r in snapshot['records']}
    for i,row in enumerate(rows):
        item = found[str(i)]
        if not isinstance(item.get('parentReference'),dict) or not isinstance(item.get('file'),dict):
            raise RepairBlocked('source_identity_mismatch')
        if item.get('id') != row['drive_file_id'] or item.get('name') != row['source_name'] or (item.get('parentReference') or {}).get('driveId') != drive_id or not isinstance(item.get('file'),dict):
            raise RepairBlocked('source_identity_mismatch')
        if _date(item.get('lastModifiedDateTime')) != _date(row['source_modified']):
            raise RepairBlocked('source_changed')
        hashes = item['file'].get('hashes') or {}
        if not isinstance(hashes,dict):
            raise RepairBlocked('ambiguous_metadata')
        _checksum(row.get('checksum'), hashes)
        _checksum((records.get(row['file']) or {}).get('checksum'), hashes)
    remaining()
    try:
        count = store.backfill_verified_default_drive(sid,owner,snapshot,drive_id)
    except ValueError as exc:
        raise RepairBlocked(str(exc)) from None
    return {'status':'repaired','repaired_files':count}
