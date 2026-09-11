"""Durable applied-but-unverified writes, kept separate from fixed findings."""
import io
import json
import zipfile


def structurally_readable(before, after, filename):
    """Reject corrupt writer output even when the WCAG verifier is unavailable."""
    try:
        ext = filename.rsplit('.', 1)[-1].lower()
        if ext == 'pdf':
            import fitz
            with fitz.open(stream=before, filetype='pdf') as old, fitz.open(stream=after, filetype='pdf') as new:
                return not new.is_encrypted and not new.is_repaired and new.page_count > 0 and old.page_count == new.page_count
        if ext in {'docx', 'pptx', 'xlsx'}:
            from lxml import etree
            with zipfile.ZipFile(io.BytesIO(before)) as old, zipfile.ZipFile(io.BytesIO(after)) as new:
                if new.testzip() is not None or not set(old.namelist()).issubset(new.namelist()):
                    return False
                parser = etree.XMLParser(resolve_entities=False, no_network=True)
                for name in new.namelist():
                    if name.endswith(('.xml', '.rels')):
                        etree.fromstring(new.read(name), parser)
                return True
    except Exception:
        return False
    return False


def pending_records(store, scan_id, filename):
    digest = (store.get_file_record(scan_id, filename) or {}).get('corrected_sha256')
    if not digest:
        return []
    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT id,rule_id,action,detail FROM decision_log WHERE scan_id=%s AND file=%s AND action IN ('apply.saved_unverified','apply.reverified') ORDER BY ts,id", (scan_id, filename))
        rows = store._db.fetchall(cur)
    parsed=[]
    for row in rows:
        entry=json.loads(row['detail'])
        if entry.get('artifact_sha256') == digest:
            parsed.append({**entry, 'event_id':row['id'], 'rule_id':row['rule_id'], 'action':row['action']})
    cleared={r.get('source_event_id') for r in parsed if r['action']=='apply.reverified'}
    return [r for r in parsed if r['action']=='apply.saved_unverified' and r['event_id'] not in cleared]


def blocks_certification(store, scan_id, filename):
    try:
        return bool(pending_records(store, scan_id, filename))
    except (KeyError, TypeError, ValueError):
        return True


def saved_changes(store, scan_id, filename):
    """Report pending evidence for the current artifact, excluding reverified rows."""
    return [{**change, 'file': filename, 'rule_id': entry['rule_id'],
             'applied':True, 'verified':False, 'verification':'not_verified',
             'artifact_sha256':entry['artifact_sha256'], 'reason':entry.get('reason'),
             'note':'AI applied · not verified'}
            for entry in pending_records(store, scan_id, filename) for change in entry.get('changes', [])]


def record_verification(store, scan_id, filename, data, verification):
    """Clear exact durable writes only after rechecking these same bytes; idempotent."""
    from hashlib import sha256
    from remediation_contribution import writer_tickets, record_writer_result
    digest=sha256(data).hexdigest()
    if not verification.ok:
        return 0
    count=0
    with store.transaction():
        if (store.get_file_record(scan_id, filename) or {}).get('corrected_sha256') != digest:
            return 0
        diffs=list(store.get_remediation_diffs(scan_id, filename) or [])
        for entry in pending_records(store, scan_id, filename):
            baseline=entry.get('baseline_residual')
            if not verification.cleared({entry['rule_id']}) or (verification.residual - set(baseline or ())):
                continue
            values={c['locator']:c['after'] for c in entry.get('changes', []) if c.get('locator')}
            tickets=writer_tickets(store,scan_id,filename,entry.get('item_ids',[]),entry.get('source_sha256'),actual_values=values)
            if (not tickets or {t['item_id'] for t in tickets} != set(entry.get('item_ids', []))
                    or any(t['source_sha256'] != entry.get('source_sha256')
                           or t['rule_id'] != entry['rule_id']
                           or not json.loads(t['finding_ids_json']) for t in tickets)):
                continue  # Retain pending when exact finding lineage is unavailable.
            record_writer_result(store,tickets,outcome='verified_cleared',artifact_sha256=digest,
                reference='Exact saved AI write reverified',writer_attempt_id='reverify:'+str(entry['event_id']))
            store.log_decision('system','apply.reverified',scan_id=scan_id,file=filename,
                rule_id=entry['rule_id'],detail=json.dumps({'source_event_id':entry['event_id'],'artifact_sha256':digest}))
            diffs.extend({'rule_id':entry['rule_id'],'before':c.get('before',''),'after':c.get('after',''),
                'note':'AI applied; exact saved copy subsequently verified · '+str(c.get('locator',''))}
                for c in entry.get('changes',[]))
            count+=1
        if count:
            store.record_remediation_diffs(scan_id,filename,diffs)
            if not verification.residual:
                store.mark_file_compliant_if_reviewed(scan_id,filename)
    return count
