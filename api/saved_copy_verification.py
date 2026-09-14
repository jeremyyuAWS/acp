"""Owner- and exact-version-bound saved-copy checks; never rewrite or publish bytes."""
from release_candidate_assessment import saved_assessment, assess_candidate
from release_artifacts import ReleaseArtifactError


_UNSET = object()


def current_assessment(store, scan_id, owner, file, *, evaluator=_UNSET):
    record = store.get_file_records(scan_id, files=[file], owner=owner).get(file)
    if not record or not record.get('corrected_sha256') or not record.get('remediated_at'):
        return None
    evidence = saved_assessment(store, scan_id, owner, file, record['corrected_sha256'])
    if not evidence or evidence.get('remediated_at') != record['remediated_at']:
        return None
    from verification_identity import evaluator_identity, scope_identity
    if evaluator is _UNSET:
        evaluator = evaluator_identity()
    if not evaluator:
        return None
    scope = store.scope_for_file(scan_id, file, store.get_scan_scope(scan_id, refresh=True))
    if evidence.get('assessment_scope') != scope_identity(scope) or evidence.get('evaluator_identity') != evaluator:
        return None
    return evidence


def project_documents(store, scan_id, owner, documents):
    from verification_identity import evaluator_identity
    evaluator = evaluator_identity()
    records = store.get_file_records(scan_id, files=[row['file'] for row in documents], owner=owner)
    return [{**row, 'corrected_sha256': records.get(row['file'], {}).get('corrected_sha256'),
             'remediated_at': records.get(row['file'], {}).get('remediated_at'),
             'corrected_copy_assessment': current_assessment(store, scan_id, owner, row['file'], evaluator=evaluator)}
            for row in documents]


def verify_saved_copy(store, scan_id, owner, file, digest, remediated_at):
    # assess_candidate verifies ownership, actual bytes, current record both before and
    # after the detector runs, and outstanding approved writes. Only evidence is recorded.
    if not digest or not remediated_at:
        raise ReleaseArtifactError('Choose the current saved copy before retrying verification.', category='artifact_provenance_unknown')
    return assess_candidate(store, scan_id, file, owner, digest, remediated_at,
                            allow_remaining_issues=True)
