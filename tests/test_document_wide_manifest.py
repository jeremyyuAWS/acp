import hashlib
import json
from types import SimpleNamespace

import pytest

from document_wide_manifest import assessed_locations, build_manifest, criterion, package_images
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


@pytest.mark.parametrize("value", ["4.1.2", "SC_4_1_2", "4.1.2 Name, Role, Value"])
def test_detector_criterion_labels_keep_the_exact_sc(value):
    assert criterion(value) == "4.1.2"


@pytest.mark.parametrize("value", ["4.1.2x", "prefix4.1.2", "4.1.2.3", "4.1.2\nother"])
def test_malformed_criterion_labels_are_not_inferred(value):
    assert criterion(value) is None


def test_multiple_pdf_fields_preserve_assessed_identities(isolated_store, monkeypatch):
    data = make_pdf(field_names=("Text1", "Text2"))
    rows = setup_manifest(isolated_store, monkeypatch, data, "a.pdf", "4.1.2", ["pdf:field:1:1", "pdf:field:1:0"])
    manifest = build_manifest(isolated_store, "scan", "a.pdf", data)
    assert len(manifest.findings) == 2
    assert manifest.findings[0].finding_id == rows[1]["finding_id"]
    assert manifest.findings[1].finding_id == rows[0]["finding_id"]


def test_pdf_detector_locations_survive_real_ledger_freeze(isolated_store, tmp_path):
    from formats.pdf.detectors.name_role_value import detect
    path = tmp_path / 'a.pdf'
    path.write_bytes(make_pdf(field_names=('Text1', 'Text2')))
    findings = detect(path)
    store = isolated_store
    with store._db.cursor() as cur:
        store._db.execute(cur, "INSERT INTO scan_runs(id,source,status) VALUES('pdf-locations','drive','done')")
        store._db.execute(cur, "INSERT INTO file_records(scan_id,file,drive_file_id,checksum) VALUES('pdf-locations','a.pdf','pdf-id','hash')")
        store._db.execute(cur, "INSERT INTO scan_rule_traces(scan_id,file,rule_id,rule_name,plain_name,level,fix_mode,outcome,finding_count) VALUES('pdf-locations','a.pdf','4.1.2','Name, Role, Value','Field names','A','human','FAIL',2)")
        for finding in findings:
            store._db.execute(cur, "INSERT INTO issue_records(scan_id,file,rule_id,wcag,severity,detail,location) VALUES('pdf-locations','a.pdf',%s,%s,%s,%s,%s)",
                (finding['ruleId'], finding['wcag'], finding['severity'], finding['detail'], finding['location']))
    rows = store.seed_finding_dispositions('pdf-locations', 'batch', snapshot_id='assessment')
    assert {row['instance_key'] for row in rows} == {'pdf:field:1:0', 'pdf:field:1:1'}
    assert len({row['finding_id'] for row in rows}) == 2
