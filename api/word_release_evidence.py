"""Optional exact-artifact Word revision companions for release reports."""
import hashlib
import json
import re
from html import escape

MAX_BYTES = 32 * 1024 * 1024
DOCX_TYPE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'


def build_word_evidence(store, scan_id, owner, name, outcome):
    if not name.lower().endswith('.docx'):
        return '', []
    heading = '<h2>Word tracked-change companion</h2>'
    def unavailable(reason):
        return heading + '<p>Companion unavailable: ' + escape(reason) + '. Recorded before/after changes remain available.</p>', []
    if store.get_scan(scan_id, owner=owner) is None:
        return unavailable('the release does not belong to this owner')
    expected = outcome.get('artifact_digest')
    if outcome.get('status') != 'published' or not re.fullmatch(r'sha256:[0-9a-f]{64}', str(expected or '')):
        return unavailable('an exact published artifact was not recorded')
    try:
        import blob
        record = store.get_file_record(scan_id, name) or {}
        checksum = str(record.get('checksum') or '').lower()
        algorithm = {32: 'md5', 40: 'sha1', 64: 'sha256'}.get(len(checksum))
        if not algorithm or not re.fullmatch(r'[0-9a-f]+', checksum):
            return unavailable('the assessed original has no verifiable source checksum')
        corrected = blob.download_report_evidence(owner, scan_id, name, max_bytes=MAX_BYTES)
        if not corrected or len(corrected) > MAX_BYTES:
            return unavailable('the corrected copy is missing or exceeds the evidence size limit')
        if 'sha256:' + hashlib.sha256(corrected).hexdigest() != expected:
            return unavailable('the saved copy no longer matches this release')
        source = blob.download_report_evidence(owner, scan_id, name, original=True,
            checksum=record.get('checksum'), max_bytes=MAX_BYTES)
        if not source or len(source) > MAX_BYTES:
            return unavailable('the cached original is missing or exceeds the evidence size limit')
        if hashlib.new(algorithm, source).hexdigest() != checksum:
            return unavailable('the cached original differs from its recorded source checksum')
        from office_tracked_changes import build_tracked_companion
        companion, report = build_tracked_companion(source, corrected)
        identity = hashlib.sha256(name.encode()).hexdigest()[:10]
        slug = re.sub(r'[^A-Za-z0-9._-]+', '-', name)[:65].strip('.-') or 'document'
        stem = f'tracked-{slug}-{identity}'
        assets = [dict(name=stem + '.json', content=json.dumps(report, indent=2),
            content_type='application/json', report_kind='tracked_changes_evidence',
            file=name, artifact_digest=expected)]
        body = heading + '<p>The primary corrected copy contains applied changes. This optional companion uses native Word revisions for supported text edits; metadata and unsupported changes remain in the change audit. It does not establish accessibility compliance.</p>'
        body += '<p>Cached original SHA-256: ' + report['source_sha256'] + '<br>Published corrected SHA-256: ' + report['corrected_sha256'] + '</p>'
        if companion:
            assets.append(dict(name=stem + '.docx', content=companion, content_type=DOCX_TYPE,
                report_kind='tracked_changes', file=name, artifact_digest=expected))
            body += '<p>Download the native tracked-change companion from Release → Supporting reports.</p>'
        else:
            body += '<p>No supported native text revisions were found. This does not mean no accessibility properties changed.</p>'
        body += '<p>Download tracking coverage and artifact identities from Release → Supporting reports.</p>'
        return body, assets
    except Exception:
        return unavailable('the original and corrected packages could not be safely compared')
