"""Unchanged release retries reuse exact successful evidence, never stale clearance."""
import hashlib
import json

import pytest

from test_corrected_artifact_publication_boundaries import SID, OWNER, _clear
from release_candidate_assessment import assess_candidate
from release_artifacts import ReleaseArtifactError

FILE = 'candidate.pdf'


@pytest.fixture
def artifact(isolated_store, monkeypatch):
    import io
    import core
    from pypdf import PdfWriter
    store = isolated_store
    store.init_scan_run(SID, 'local', 1, '2026-09-12T00:00:00Z', 'rubric', 'hash', owner=OWNER)
    store.save_file_result(SID, {'file': FILE, 'engine': 'pdf', 'status': 'analysed',
        'score': 100, 'compliant': 1, 'issues': [], 'errors': [], 'skipped_rules': 0},
        '2026-09-12T00:00:00Z')
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    output = io.BytesIO()
    writer.write(output)
    data = output.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    at = store.record_remediation(SID, FILE, blob_url='blob://candidate', corrected_sha256=digest)
    monkeypatch.setattr(core, 'store', store)
    monkeypatch.setattr(store, 'get_scan_scope', lambda *a, **kw: {'2.4.2': ['pdf']})
    monkeypatch.setattr(store, 'scope_for_file', lambda sid, name, scope: scope)
    return store, data, digest, at


@pytest.fixture
def checked(artifact, monkeypatch):
    import proposals
    import verification_identity
    monkeypatch.setattr(verification_identity, 'evaluator_identity', lambda: 'engine-v1')
    store, data, digest, at = artifact
    calls = []
    def verify(*args, **kwargs):
        calls.append(args)
        return _clear()
    monkeypatch.setattr(proposals, 'verify_residual', verify)
    def assess(**kwargs):
        return assess_candidate(store, SID, FILE, OWNER, digest, at,
                                data=data, release_id='batch', **kwargs)
    return store, data, digest, at, calls, assess


def test_same_release_retries_check_bytes_and_reuse_success(checked):
    _, _, _, _, calls, assess = checked
    first, second = assess(), assess()
    assert len(calls) == 1
    assert first['assessment_reused'] is False
    assert second['assessment_reused'] is True


@pytest.mark.parametrize('change', ['engine', 'scope', 'timestamp', 'release', 'unknown', 'legacy'])
def test_other_evidence_never_reuses_clearance(checked, monkeypatch, change):
    import verification_identity
    store, data, digest, at, calls, assess = checked
    prior = assess()
    if change == 'engine':
        monkeypatch.setattr(verification_identity, 'evaluator_identity', lambda: 'engine-v2')
    elif change == 'scope':
        monkeypatch.setattr(store, 'get_scan_scope', lambda *a, **kw: {})
    elif change == 'timestamp':
        at = store.record_remediation(SID, FILE, blob_url='blob://candidate', corrected_sha256=digest)
    elif change in {'unknown', 'legacy'}:
        prior = {**prior, 'assessment_ok': change == 'legacy', 'evaluator_identity': None}
        store.log_decision(OWNER, 'release.corrected_copy_assessed', scan_id=SID,
                           file=FILE, detail=json.dumps(prior))
    assess_candidate(store, SID, FILE, OWNER, digest, at, data=data,
                     release_id='other' if change == 'release' else 'batch')
    assert len(calls) == 2


def test_changed_download_rejected_even_when_clearance_is_cached(checked):
    store, _, digest, at, calls, assess = checked
    assess()
    with pytest.raises(ReleaseArtifactError, match='bytes changed'):
        assess_candidate(store, SID, FILE, OWNER, digest, at, data=b'other bytes', release_id='batch')
    assert len(calls) == 1


def test_new_unapplied_approval_blocks_reused_check(checked, monkeypatch):
    store, _, _, _, calls, assess = checked
    assess()
    monkeypatch.setattr(store, 'count_unapplied_approved_values', lambda *a: 1)
    with pytest.raises(ReleaseArtifactError) as error:
        assess()
    assert error.value.category == 'approved_changes_unapplied'
    assert len(calls) == 1


def test_explicit_remaining_does_not_turn_a_cached_failure_into_clearance(checked, monkeypatch):
    import proposals
    _, _, _, _, _, assess = checked
    monkeypatch.setattr(proposals, 'verify_residual', lambda *a, **kw:
        proposals.Verification(True, {'2.4.2'}, assessment={'status': 'analysed',
            'issues': [{'wcag': '2.4.2', 'ruleId': 'pdf.display-doc-title'}]}))
    evidence = assess(allow_remaining_issues=True)
    assert evidence['remaining_criteria'] == ['2.4.2']
    with pytest.raises(ReleaseArtifactError) as error:
        assess()
    assert error.value.category == 'release_assessment_remaining'


def test_mismatched_verifier_hash_is_not_attested(checked, monkeypatch):
    import proposals
    _, _, _, _, _, assess = checked
    monkeypatch.setattr(proposals, 'verify_residual', lambda *a, **kw:
        proposals.Verification(True, assessment={'status': 'analysed', 'issues': []},
                               artifact_sha256='f' * 64))
    with pytest.raises(ReleaseArtifactError, match='different corrected copy'):
        assess()


def test_real_pdf_verification_identifies_the_actual_bytes(tmp_path):
    import io
    from pypdf import PdfWriter
    from proposals import verify_residual
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    output = io.BytesIO()
    writer.write(output)
    data = output.getvalue()
    result = verify_residual(data, 'real.pdf')
    assert result.artifact_sha256 == hashlib.sha256(data).hexdigest()
    assert '2.4.2' in result.residual


def test_no_cache_identity_on_unversioned_runtime(monkeypatch):
    from verification_identity import evaluator_identity
    monkeypatch.delenv('ACP_BUILD_VERSION', raising=False)
    monkeypatch.delenv('ACP_VERSION', raising=False)
    assert evaluator_identity() is None


def test_evaluator_changes_with_actual_engine_config_and_private_settings(tmp_path, monkeypatch):
    import verification_identity
    api, config, analyser = tmp_path / 'api', tmp_path / 'config', tmp_path / 'engine/pdf-analyser/analysers'
    for directory in (api, config, analyser):
        directory.mkdir(parents=True)
    engine_file = analyser / 'check.py'
    engine_file.write_text('rule = 1')
    rubric = config / 'rubric.default.json'
    rubric.write_text('{"disabled": []}')
    monkeypatch.setattr(verification_identity, '__file__', str(api / 'verification_identity.py'))
    monkeypatch.delenv('ACP_PDF_ENGINE', raising=False)
    monkeypatch.delenv('ACP_VERAPDF_REST', raising=False)
    monkeypatch.delenv('ACP_SCANNED_PDF_TIER_A', raising=False)
    monkeypatch.setenv('ACP_BUILD_VERSION', '2026.test.1')
    first = verification_identity.evaluator_identity()
    engine_file.write_text('rule = 2')
    second = verification_identity.evaluator_identity()
    rubric.write_text('{"disabled": ["pdf.document-title"]}')
    third = verification_identity.evaluator_identity()
    monkeypatch.setenv('ACP_TEST_PRIVATE_KEY', 'private-value-never-recorded')
    fourth = verification_identity.evaluator_identity()
    assert len({first, second, third, fourth}) == 4
    assert 'private-value' not in fourth


@pytest.mark.parametrize('key,value', [('ACP_VERAPDF_REST', 'https://external-evaluator.test'),
                                      ('ACP_SCANNED_PDF_TIER_A', 'true')])
def test_mutable_external_evaluator_cannot_reuse_package_version(monkeypatch, key, value):
    from verification_identity import evaluator_identity
    monkeypatch.setenv('ACP_BUILD_VERSION', '2026.test.1')
    monkeypatch.setenv(key, value)
    assert evaluator_identity() is None


def test_scope_change_during_engine_work_is_not_attested(checked, monkeypatch):
    import proposals
    store, _, _, _, _, assess = checked
    changed = {'value': False}
    monkeypatch.setattr(store, 'get_scan_scope', lambda *a, **kw:
                       {} if changed['value'] else {'2.4.2': ['pdf']})
    def verify(*args, **kwargs):
        changed['value'] = True
        return _clear()
    monkeypatch.setattr(proposals, 'verify_residual', verify)
    with pytest.raises(ReleaseArtifactError, match='scope changed'):
        assess()
