"""Durable applied-but-unverified writes, kept separate from fixed findings."""
import io
import json
import zipfile


def structurally_readable(before, after, filename):
    """Reject corrupt writer output even when the WCAG verifier is unavailable."""
    try:
        ext = filename.rsplit('.', 1)[-1].lower()
        if ext == 'pdf':
            import pikepdf
            # Use the PDF runtime deployed with ACP. Recovery is disabled so a
            # repaired/malformed candidate cannot masquerade as a successful write.
            with pikepdf.open(io.BytesIO(before), attempt_recovery=False) as old, pikepdf.open(
                    io.BytesIO(after), attempt_recovery=False) as new:
                return (not new.is_encrypted and len(new.pages) > 0
                        and len(old.pages) == len(new.pages) and not new.check_pdf_syntax())
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
        store._db.execute(cur, "SELECT id,ts,rule_id,action,detail FROM decision_log WHERE scan_id=%s AND file=%s AND action IN ('apply.saved_unverified','apply.reverified') ORDER BY ts,id", (scan_id, filename))
        rows = store._db.fetchall(cur)
    parsed=[{**json.loads(row['detail']), 'event_id':row['id'], 'rule_id':row['rule_id'],
             'action':row['action'], 'recorded_at':row['ts']} for row in rows]
    # A later edit to a different criterion must not erase an outstanding semantic
    # obligation. Carry it only along durable writer edges for this file. A new assessment is not semantic confirmation.
    ancestors = {digest}
    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT actual_source_sha256,artifact_sha256 FROM ai_validation_outcomes WHERE scan_id=%s AND file=%s AND source_revision IS NOT NULL", (scan_id, filename))
        edges = [(r.get('actual_source_sha256'), r.get('artifact_sha256')) for r in store._db.fetchall(cur)]
    edges.extend((r.get('source_sha256'),r.get('artifact_sha256')) for r in parsed
                 if r.get('assessment_revision') and r['action']=='apply.saved_unverified')
    while True:
        earlier={before for before,after in edges if before and after in ancestors}
        if earlier.issubset(ancestors):
            break
        ancestors.update(earlier)
    relevant=[r for r in parsed if r.get('artifact_sha256')==digest or
              (r.get('requires_semantic_review') is True and
               r.get('assessment_revision') and r.get('artifact_sha256') in ancestors)]
    cleared={r.get('source_event_id') for r in parsed if r['action']=='apply.reverified'
             and r.get('artifact_sha256') in ancestors}
    with store._db.cursor() as cur:
        store._db.execute(cur, '''SELECT v.item_id,v.rule_id,v.artifact_sha256,v.proposal_snapshot_id,
            v.actual_approved_value_sha256,v.created_at,e.approved_value_sha256,e.proposal_snapshot_ids
            FROM ai_validation_outcomes v JOIN hitl_events e ON e.id=v.approval_event_id
            WHERE v.scan_id=%s AND v.file=%s AND e.scan_id=v.scan_id AND e.file=v.file
              AND e.item_id=v.item_id AND e.action IN ('approve','edit')
              AND v.outcome='verified_cleared' ''', (scan_id,filename))
        confirmations=store._db.fetchall(cur)
    human_confirmed=[r for r in confirmations
        if r.get('artifact_sha256') in ancestors and r.get('actual_approved_value_sha256')
        and r['actual_approved_value_sha256']==r.get('approved_value_sha256')
        and r.get('proposal_snapshot_id') in json.loads(r.get('proposal_snapshot_ids') or '[]')]
    def confirmed(entry):
        return (entry.get('requires_semantic_review') is True and bool(entry.get('item_ids'))
                and all(any(r['item_id']==item and r['rule_id']==entry['rule_id']
                            and r.get('created_at') and r['created_at'] > entry['recorded_at']
                            for r in human_confirmed) for item in entry['item_ids']))
    return [{**r, 'artifact_sha256': digest, 'applied_artifact_sha256': r.get('artifact_sha256')}
            for r in relevant if r['action']=='apply.saved_unverified' and r['event_id'] not in cleared
            and not confirmed(r)]


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
            if entry.get('requires_semantic_review') is True:
                continue  # Presence-only scans cannot certify model-generated meaning.
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
