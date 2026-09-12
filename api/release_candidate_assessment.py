"""Reassess the exact corrected candidate at a new publication boundary.

The original Assess record remains the immutable baseline. A release-specific decision
stores the candidate assessment; upload checks still bind the delivered bytes to its hash.
"""
from hashlib import sha256
import json

from release_artifacts import ReleaseArtifactError, require_current_record


def assess_candidate(store, scan_id, filename, owner, digest, remediated_at, *,
                     allow_remaining_issues=False, data=None, release_id=None):
    if store.get_scan(scan_id, owner=owner) is None:
        raise ReleaseArtifactError('The corrected assessment does not belong to this owner.')
    require_current_record(store, scan_id, filename, digest, remediated_at,
                                    owner=owner, allow_remaining_issues=allow_remaining_issues)
    count = getattr(store, 'count_unapplied_approved_values', None)
    if callable(count) and count(scan_id, filename):
        raise ReleaseArtifactError('Approved changes still need to be written before publishing.',
                                   category='approved_changes_unapplied')
    if data is None:
        import blob
        data = blob.download_remediated(owner, scan_id, filename)
    if not data or sha256(data).hexdigest() != digest:
        raise ReleaseArtifactError('Corrected bytes changed before the release assessment.')
    structurally_readable = True
    extension = filename.rsplit('.', 1)[-1].lower()
    if extension in {'docx', 'xlsx', 'pptx', 'pdf'}:
        from remediated_copy_audit import inspect
        readable = inspect(data, extension)
        structurally_readable = readable['readable']
    from proposals import verify_residual
    verification = verify_residual(data, filename, scan_id=scan_id)
    assessment = verification.assessment or {}
    assessment_ok = (verification.ok and assessment.get('status') == 'analysed'
                     and isinstance(assessment.get('issues'), list))
    scope = store.get_scan_scope(scan_id, refresh=True)
    scope = store.scope_for_file(scan_id, filename, scope)
    evidence = {'artifact_sha256': digest, 'remediated_at': remediated_at,
                'release_id': release_id, 'assessment_scope':
                    {code: sorted(formats) for code, formats in scope.items()} if scope else None,
                'assessment_ok': assessment_ok,
                'assessment_status': assessment.get('status') or 'unavailable',
                'remaining_criteria': sorted(verification.residual),
                'remaining_issues': assessment.get('issues'),
                'skipped_rules': assessment.get('skipped_rules'),
                'errors': assessment.get('errors'),
                'reason': verification.reason or None,
                'allow_remaining_issues': allow_remaining_issues is True}
    store.log_decision(owner, 'release.corrected_copy_assessed', scan_id=scan_id,
                       file=filename, detail=json.dumps(evidence, default=list))
    # Recheck identity after expensive engines finish. Never attest to an old candidate
    # while another approved writer has replaced its record during the assessment.
    require_current_record(store, scan_id, filename, digest, remediated_at,
                           owner=owner, allow_remaining_issues=allow_remaining_issues)
    if callable(count) and count(scan_id, filename):
        raise ReleaseArtifactError('Approved changes arrived during the release assessment.',
                                   category='approved_changes_unapplied')
    if not structurally_readable:
        raise ReleaseArtifactError('The corrected copy is unreadable; repair or replace it before publishing.',
                                   category='corrected_copy_unreadable')
    remaining = bool(verification.residual or assessment.get('issues'))
    if not allow_remaining_issues and (not assessment_ok or remaining):
        raise ReleaseArtifactError('The corrected copy still has findings.' if assessment_ok
                                   else 'The corrected copy could not be fully assessed. Retry assessment before publishing.',
                                   category='release_assessment_remaining' if assessment_ok
                                   else 'release_assessment_unavailable')
    return evidence


def saved_assessment(store, scan_id, owner, filename, digest, *, release_id=None):
    """Read only exact owned-artifact assessment evidence; historical copies cannot leak."""
    if not digest or store.get_scan(scan_id, owner=owner) is None or not hasattr(store, '_db'):
        return None
    digest = digest.removeprefix('sha256:')
    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT detail FROM decision_log WHERE scan_id=%s AND file=%s AND actor=%s AND action='release.corrected_copy_assessed' ORDER BY ts DESC,id DESC", (scan_id, filename, owner))
        rows = store._db.fetchall(cur)
    for row in rows:
        try:
            evidence = json.loads(row['detail'])
        except (TypeError, ValueError):
            continue
        if evidence.get('artifact_sha256') == digest and (release_id is None or evidence.get('release_id') == release_id):
            return evidence
    return None
