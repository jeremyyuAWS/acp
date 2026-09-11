"""Opt-in document generation feeding the existing review and verified writer lane."""
from __future__ import annotations

import hashlib
import json

SUPPORTED = {'.docx': ('1.1.1',), '.pdf': ('1.1.1', '4.1.2')}


def enabled(context, filename):
    return bool(context and context.policy.get('document_wide_ai') is True
                and any(filename.lower().endswith(ext) for ext in SUPPORTED))


def suppressed_criteria(context, filename):
    if not enabled(context, filename):
        return set()
    return {sc for ext, criteria in SUPPORTED.items() if filename.lower().endswith(ext) for sc in criteria}


def _record(store, context, action, value):
    store.log_decision('system', 'document_wide.' + action, scan_id=context.scan_id,
                       file=context.file, detail=json.dumps({**value, 'owner_id': context.owner_id,
                           'run_id': context.run_id}, sort_keys=True))


def _saved(store, context, request_id):
    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT detail FROM decision_log WHERE scan_id=%s AND file=%s AND action=%s ORDER BY ts DESC",
                          (context.scan_id, context.file, 'document_wide.generated'))
        rows = store._db.fetchall(cur)
    for row in rows:
        value = json.loads(row['detail'])
        if value.get('request_id') == request_id:
            return value
    return None


def process_file(store, context):
    """Generate only from the durable corrected artifact. Never apply or grant credit here."""
    if not enabled(context, context.file):
        return
    if not context.enabled:
        _record(store, context, 'deferred', {'reason': 'Cloud AI and a positive spending limit are required for document-wide suggestions.'})
        return
    import blob
    from document_wide_manifest import build_manifest, package_images
    from document_wide_provider import generate_document
    from experiments.document_wide_ai.request.builder import build_request
    from experiments.document_wide_ai.validation.validator import validate_edit_response

    sid, filename = context.scan_id, context.file
    revision = store.remediation_source_revision(sid)
    record = store.get_file_record(sid, filename) or {}
    data = blob.download_remediated(context.owner_id, sid, filename)
    digest = hashlib.sha256(data).hexdigest() if data else None
    if not digest or digest != record.get('corrected_sha256'):
        _record(store, context, 'deferred', {'reason': 'No current stored corrected artifact is available.'})
        return
    try:
        manifest = build_manifest(store, sid, filename, data)
    except ValueError as exc:
        reasons = {
            'document_too_large': 'The document exceeds the pilot file-size or archive extraction limits.',
            'document_extraction_incomplete': 'ACP could not fully extract the document within the pilot limits (100 pages, 60,000 text characters, and 20 target findings).',
            'document_source_changed': 'The saved document changed before generation. Run remediation again for the current copy.',
            'document_selected_criteria_missing': 'The saved assessment does not identify the selected criteria. Assess the document again.',
            'document_assessment_lineage_missing': 'The saved assessment finding identities are unavailable. Assess the document again.',
        }
        if str(exc) not in reasons:
            raise
        _record(store, context, 'deferred', {'reason': reasons[str(exc)]})
        return
    input_mode = ('native_pdf' if filename.lower().endswith('.pdf')
                  and context.policy.get('document_wide_input_mode') == 'native_pdf'
                  else 'extracted')
    # Preserve legacy request identities; native input must never reuse an
    # extracted-context reply when the accepted mode changes for a new execution.
    request_key = context.run_id + manifest.to_json()
    if input_mode == 'native_pdf':
        request_key += ':native-pdf.v1'
    request_id = hashlib.sha256(request_key.encode()).hexdigest()
    if not manifest.findings:
        _record(store, context, 'deferred', {'reason': 'No remaining findings have a supported document-wide target.',
            'extraction_issues': [{'kind': e.kind, 'detail': e.detail, 'finding_ids': list(e.related_finding_ids)} for e in manifest.extraction_issues]})
        return
    result = _saved(store, context, request_id)
    if result is None:
        if input_mode == 'native_pdf':
            from document_wide_manifest import package_native_pdf
            try:
                payload = {'pdf_bytes': package_native_pdf(data, manifest)}
            except ValueError as exc:
                _record(store, context, 'deferred', {'request_id': request_id,
                    'input_mode': input_mode, 'reason': str(exc)})
                return
        else:
            payload = {'images': package_images(data, manifest)}
        response = generate_document(build_request(manifest, request_id=request_id), **payload)
        if not response.get('envelope'):
            _record(store, context, 'deferred', {'request_id': request_id, 'reason': response.get('reason', 'No valid AI response was returned.')})
            return
        validation = validate_edit_response(manifest, response['envelope'])
        by_id = {f.finding_id: f for f in manifest.findings}
        proposals = {}
        for edit in validation.valid_edits:
            sc = by_id[edit.finding_ids[0]].success_criterion
            if sc not in suppressed_criteria(context, filename):
                continue
            proposals.setdefault(sc, []).append({
                'locator': ((edit.locator.part_name + '#' + edit.locator.element_ref)
                            if edit.locator.part_name else edit.locator.element_ref), 'before': edit.expected_original_value,
                'proposed_value': edit.proposed_value, 'rationale': edit.rationale,
                'source': 'ai', 'requires_semantic_review': True, 'model': response.get('model'),
                'model_call_id': response.get('model_call_id'),
                'finding_ids': list(edit.finding_ids), 'baseline_finding_ids': list(edit.finding_ids), 'document_wide_request_id': request_id,
                'source_sha256': digest, 'assessment_revision': manifest.assessment_revision,
                'document_wide_input_mode': input_mode,
            })
        result = {'request_id': request_id, 'input_mode': input_mode,
                  'source_sha256': digest, 'proposals': proposals,
                  'unresolved': [{'finding_id': u.finding_id, 'reason': u.reason} for u in validation.unresolved],
                  'omitted_finding_ids': list(validation.model_omitted_finding_ids),
                  'rejected': [{'edit_id': e.edit_id, 'reason': e.reason} for e in validation.rejected_edits],
                  'extraction_issues': [{'kind': e.kind, 'detail': e.detail, 'finding_ids': list(e.related_finding_ids)} for e in manifest.extraction_issues]}
        _record(store, context, 'generated', result)
    canonical_rows = store.list_finding_dispositions(sid, context.run_id)
    with store.transaction():
        # A provider call can outlive cancellation or a replacement run. Re-check
        # the accepted execution at the persistence boundary, including cached replies.
        stage = store.get_stage_execution(context.run_id, owner=context.owner_id) or {}
        if (stage.get('owner_email') != context.owner_id or stage.get('scan_id') != sid
                or stage.get('stage') != 'remediate' or not stage.get('is_current')
                or stage.get('cancel_requested_at')
                or stage.get('state') not in {'accepted', 'queued', 'processing'}
                or stage.get('input_snapshot_id') != revision):
            _record(store, context, 'deferred', {'request_id': request_id,
                    'reason': 'The remediation run was cancelled, replaced, or is no longer active.'})
            return
        if (store.remediation_source_revision(sid) != revision or
                (store.get_file_record(sid, filename) or {}).get('corrected_sha256') != digest):
            _record(store, context, 'deferred', {'request_id': request_id, 'reason': 'The assessment or corrected artifact changed during generation.'})
            return
        rows = store.list_hitl_queue(scan_id=sid, owner=context.owner_id)
        for sc, proposals in result['proposals'].items():
            existing = next((r for r in rows if r.get('file') == filename and r.get('rule_id') == sc), None)
            if existing and (existing.get('status') != 'pending' or existing.get('applied')):
                _record(store, context, 'deferred', {'request_id': request_id, 'reason': 'An existing review decision was preserved.', 'sc': sc})
                continue
            count = len({r['finding_id'] for r in canonical_rows if r.get('file') == filename and r.get('rule_id') == sc})
            if not count:
                _record(store, context, 'deferred', {'request_id': request_id, 'reason': 'Canonical finding count unavailable.', 'sc': sc})
                continue
            store.enqueue_proposals(sid, filename, sc, proposals, validated=False, finding_count=count)
