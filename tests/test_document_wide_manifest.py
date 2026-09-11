import hashlib
import json
from types import SimpleNamespace

import pytest

from document_wide_manifest import assessed_locations, build_manifest, package_images
from experiments.document_wide_ai.fixtures.make_fixtures import make_docx, make_pdf
from finding_ledger import stable_finding_id


def setup_manifest(store, monkeypatch, data, filename, sc, locations):
    ctx = SimpleNamespace(owner_id='owner', scan_id='scan', run_id='run', file=filename)
    monkeypatch.setattr('llm_waterfall_provider.managed_context', lambda: ctx)
    digest = hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(store, 'get_file_record', lambda *a: {'corrected_sha256': digest})
    monkeypatch.setattr(store, 'get_scan_scope', lambda *a: {sc: frozenset({filename.rsplit('.', 1)[1]})})
    monkeypatch.setattr(store, 'scope_for_file', lambda s, f, scope: scope)
    monkeypatch.setattr(store, 'list_finding_dispositions', lambda *a: [])
    rows = [{'finding_id': stable_finding_id('document', sc, loc), 'file': filename,
             'rule_id': sc, 'instance_key': loc} for loc in locations]
    with store._db.cursor() as cur:
        store._db.execute(cur, 'INSERT INTO remediation_contribution_runs(owner_id,scan_id,run_id,snapshot_id,baseline_json,files_json,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                          ('owner', 'scan', 'run', 'saved-assessment', json.dumps(rows), json.dumps([filename]), 'now'))
    return rows


def test_two_images_use_real_assessed_locations_not_enumeration(isolated_store, monkeypatch):
    data = make_docx(image_count=2)
    locations = ['docx:drawing:2:paragraph:2', 'docx:drawing:1:paragraph:1']
    rows = setup_manifest(isolated_store, monkeypatch, data, 'a.docx', '1.1.1', locations)
    manifest = build_manifest(isolated_store, 'scan', 'a.docx', data)
    assert {f.finding_id for f in manifest.findings} == {r['finding_id'] for r in rows}
    assert manifest.findings[0].finding_id == rows[1]['finding_id']
    images = package_images(data, manifest)
    assert len(manifest.evidence) == 2
    assert len(images) == 1  # Two placements of the same image share bounded image bytes.
    assert all(ref == 'sha256:'+hashlib.sha256(raw).hexdigest() for ref, raw in images.items())


def test_multiple_legacy_ordinals_are_never_guessed_into_images(isolated_store, monkeypatch):
    data = make_docx(image_count=2)
    rows = setup_manifest(isolated_store, monkeypatch, data, 'a.docx', '1.1.1', ['aggregate-instance:s:1', 'aggregate-instance:s:2'])
    manifest = build_manifest(isolated_store, 'scan', 'a.docx', data)
    assert not manifest.findings
    assert {fid for i in manifest.extraction_issues for fid in i.related_finding_ids} == {r['finding_id'] for r in rows}


def test_single_legacy_finding_has_unambiguous_target(isolated_store, monkeypatch):
    data = make_pdf()
    rows = setup_manifest(isolated_store, monkeypatch, data, 'a.pdf', '4.1.2', ['aggregate-instance:s:1'])
    manifest = build_manifest(isolated_store, 'scan', 'a.pdf', data)
    assert len(manifest.findings) == 1
    assert manifest.findings[0].finding_id == rows[0]['finding_id']
    assert manifest.assessment_revision == 'saved-assessment'


def test_candidate_must_match_the_saved_artifact(isolated_store, monkeypatch):
    data = make_pdf()
    setup_manifest(isolated_store, monkeypatch, data, 'a.pdf', '4.1.2', ['aggregate-instance:s:1'])
    with pytest.raises(ValueError, match='document_source_changed'):
        build_manifest(isolated_store, 'scan', 'a.pdf', data+b'changed')


def test_resolved_findings_are_not_generated_again(isolated_store, monkeypatch):
    data = make_pdf()
    rows = setup_manifest(isolated_store, monkeypatch, data, 'a.pdf', '4.1.2', ['aggregate-instance:s:1'])
    monkeypatch.setattr(isolated_store, 'list_finding_dispositions', lambda *a: [{'finding_id': rows[0]['finding_id'], 'disposition': 'resolved_verified'}])
    assert not build_manifest(isolated_store, 'scan', 'a.pdf', data).findings


def test_unselected_criteria_do_not_enter_the_request(isolated_store, monkeypatch):
    data = make_docx()
    setup_manifest(isolated_store, monkeypatch, data, 'a.docx', '1.1.1', ['aggregate-instance:s:1'])
    monkeypatch.setattr(isolated_store, 'get_scan_scope', lambda *a: {'2.4.2': frozenset({'docx'})})
    assert not build_manifest(isolated_store, 'scan', 'a.docx', data).findings


def test_freeze_locations_requires_complete_unique_assessment_group():
    rows = [{'wcag': 'SC_1_1_1', 'location': 'drawing:2'}, {'wcag': '1.1.1', 'location': 'drawing:1'}]
    assert assessed_locations(rows, '1.1.1', 2) == ['drawing:1', 'drawing:2']
    assert assessed_locations(rows, '1.1.1', 3) is None
    assert assessed_locations(rows + [rows[0]], '1.1.1', 3) is None
