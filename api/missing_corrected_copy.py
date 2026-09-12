"""Cache-only explanation for a completed repair that produced no corrected bytes.

Diagnostics never create artifacts, approvals, provider requests or release permission.
"""
import io
import re

MAX_SOURCE_BYTES = 8 * 1024 * 1024
GENERIC = ('Remediation finished without a saved corrected copy. The original is unchanged; '
           'remaining issues are listed for follow-up.')


def project_documents(store, scan_id, owner, documents):
    """Presentation only: do not enrich persisted receipts or report snapshots."""
    candidates = [doc['file'] for doc in documents if doc.get('file')
                  and doc.get('status') == 'failed'
                  and doc.get('failure_category') == 'no_corrected_copy']
    if not candidates:
        return documents
    try:
        records = store.get_file_records(scan_id, owner=owner, files=candidates)
    except Exception:
        return documents
    result = []
    for doc in documents:
        shown = dict(doc)
        if doc.get('file') in candidates and doc['file'] in records:
            record = records[doc['file']]
            if record.get('remediated_at') and re.fullmatch('[0-9a-f]{64}', record.get('corrected_sha256') or ''):
                result.append(shown)
                continue
            message = explanation(store, scan_id, owner, doc['file'], record)
            if message != GENERIC:
                shown['recovery_explanation'] = message
        result.append(shown)
    return result


def explanation(store, scan_id, owner, file, record):
    if not file.lower().endswith('.pdf'):
        return GENERIC
    try:
        pending_structure = any(
            item.get('file') == file and item.get('rule_id') == '1.3.1'
            and not item.get('superseded')
            and item.get('status') not in {'resolved', 'not_applicable'}
            for item in store.list_hitl_queue(scan_id=scan_id, owner=owner,
                                             include_superseded=True))
        if not pending_structure or not record.get('checksum'):
            return GENERIC
        import blob
        from source_checksum import matches_source_checksum
        data = blob.download_report_evidence(owner, scan_id, file, original=True,
                    checksum=record['checksum'], max_bytes=MAX_SOURCE_BYTES)
        if not data or len(data) > MAX_SOURCE_BYTES or not matches_source_checksum(data, record['checksum']):
            return GENERIC
        import pikepdf
        with pikepdf.open(io.BytesIO(data)) as pdf:
            # A damaged tree or encrypted document is not proof of missing tags.
            if pdf.is_encrypted or '/StructTreeRoot' in pdf.Root:
                return GENERIC
        return ('No corrected copy was created: this PDF has no accessibility tag tree, '
                'and its remaining structure issue needs document reconstruction. '
                'The current automatic structural repair requires existing tags. '
                'The original is unchanged. Supply a tagged replacement or repair the PDF, '
                'then assess it and explicitly approve a new remediation and publishing plan.')
    except Exception:
        # Optional diagnosis must not turn unavailable evidence into a new failure or
        # mislabel missing/unreadable bytes as corrupt or untagged.
        return GENERIC
