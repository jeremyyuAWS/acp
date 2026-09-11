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


def blocks_certification(store, scan_id, filename):
    record = store.get_file_record(scan_id, filename) or {}
    digest = record.get('corrected_sha256')
    if not digest:
        return False
    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT detail FROM decision_log WHERE scan_id=%s AND file=%s AND action='apply.saved_unverified'", (scan_id, filename))
        rows = store._db.fetchall(cur)
    for row in rows:
        try:
            if json.loads(row['detail'])['artifact_sha256'] == digest:
                return True
        except (KeyError, TypeError, ValueError):
            # An unreadable durable unverified record is not a verified pass.
            return True
    return False


def saved_changes(store, scan_id, filename):
    """Report evidence for only the current saved artifact, never earlier attempts."""
    digest = (store.get_file_record(scan_id, filename) or {}).get('corrected_sha256')
    if not digest:
        return []
    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT rule_id,detail FROM decision_log WHERE scan_id=%s AND file=%s AND action='apply.saved_unverified' ORDER BY ts,id", (scan_id, filename))
        rows = store._db.fetchall(cur)
    result = []
    for row in rows:
        try:
            entry = json.loads(row['detail'])
            if entry.get('artifact_sha256') == digest:
                result.extend({**change, 'file': filename, 'rule_id': row['rule_id'],
                    'applied': True, 'verified': False, 'verification': 'not_verified',
                    'artifact_sha256': digest, 'reason': entry.get('reason'),
                    'note': 'AI applied · not verified'} for change in entry.get('changes', []))
        except (TypeError, ValueError):
            continue
    return result
