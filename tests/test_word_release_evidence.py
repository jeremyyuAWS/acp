"""Companions are bound to the published copy and remain separate binary assets."""
import hashlib
import io
import json
from types import SimpleNamespace

import pytest
from docx import Document
from word_release_evidence import build_word_evidence, DOCX_TYPE
from release_report_delivery import _asset_bytes


def document(text):
    doc = Document()
    doc.add_paragraph(text)
    output = io.BytesIO()
    doc.save(output)
    return output.getvalue()


@pytest.fixture
def copies(monkeypatch):
    import blob
    source = document('Use the green button')
    corrected = document('Use the Submit button')
    calls = []
    def read(owner, sid, name, **kwargs):
        calls.append((owner, sid, name, kwargs))
        return source if kwargs.get('original') else corrected
    monkeypatch.setattr(blob, 'download_report_evidence', read)
    store = SimpleNamespace(get_scan=lambda sid, owner=None: {} if owner == 'owner' else None,
        get_file_record=lambda *args: {'checksum': hashlib.sha256(source).hexdigest()})
    outcome = dict(status='published', artifact_digest='sha256:' + hashlib.sha256(corrected).hexdigest())
    return store, source, corrected, outcome, calls


def test_actual_companion_and_json_are_distinct_from_primary(copies):
    store, source, corrected, outcome, calls = copies
    html, assets = build_word_evidence(store, 'scan', 'owner', 'report.docx', outcome)
    companion = next(a for a in assets if a['content_type'] == DOCX_TYPE)
    evidence = json.loads(next(a['content'] for a in assets if a['content_type'] == 'application/json'))
    assert companion['artifact_digest'] == outcome['artifact_digest']
    assert evidence['corrected_sha256'] == hashlib.sha256(corrected).hexdigest()
    assert evidence['source_sha256'] == hashlib.sha256(source).hexdigest()
    assert hashlib.sha256(_asset_bytes(companion)).hexdigest() == evidence['companion_sha256']
    assert _asset_bytes(companion) != corrected
    assert 'Supporting reports' in html and '<a href=' not in html
    assert len(calls) == 2 and all(c[0] == 'owner' for c in calls)


@pytest.mark.parametrize('change', ['owner', 'status', 'digest', 'source', 'missing_source', 'opaque_source'])
def test_owner_version_source_and_publication_guards(copies, change):
    store, source, corrected, outcome, calls = copies
    owner = 'owner'
    if change == 'owner': owner = 'other'
    if change == 'status': outcome['status'] = 'failed'
    if change == 'digest': outcome['artifact_digest'] = 'sha256:' + 'f' * 64
    if change == 'source': store.get_file_record = lambda *args: {'checksum': 'f' * 64}
    if change == 'missing_source': store.get_file_record = lambda *args: {}
    if change == 'opaque_source': store.get_file_record = lambda *args: {'checksum': 'provider-etag'}
    html, assets = build_word_evidence(store, 'scan', owner, 'report.docx', outcome)
    assert not assets and 'unavailable' in html
    if change in {'owner', 'status'}: assert not calls


def test_binary_asset_frozen_round_trip():
    import base64
    original = document('Native Word binary')
    assert _asset_bytes({'content': base64.b64encode(original).decode(), 'encoding': 'base64'}) == original


def test_real_report_bundle_keeps_native_companion(isolated_store, monkeypatch):
    import blob
    from release_report_delivery import queue_release_reports, get_release_report_asset, retry_release_reports
    source, corrected = document('Use the green button'), document('Use the Submit button')
    monkeypatch.setattr(blob, 'download_report_evidence',
        lambda *args, **kw: source if kw.get('original') else corrected)
    sid, owner, name = 'native-report', 'owner', 'report.docx'
    isolated_store.init_scan_run(sid, 'sharepoint', 1, '2026-09-12T00:00:00Z', 'rubric', 'hash', owner=owner)
    isolated_store.save_file_result(sid, {'file': name, 'engine': 'office', 'status': 'pass',
        'score': 100, 'compliant': True, 'skipped_rules': 0, 'checksum': hashlib.sha256(source).hexdigest()}, '2026-09-12T00:00:00Z')
    release = isolated_store.ensure_release_execution(sid, owner, 'sharepoint', 1)
    digest = 'sha256:' + hashlib.sha256(corrected).hexdigest()
    isolated_store.record_release_document(release['id'], owner, dict(file=name, status='published', artifact_digest=digest))
    bundle = queue_release_reports(isolated_store, sid, owner, release['id'])
    companion = next((i, a) for i, a in enumerate(bundle['reports']) if a['report_kind'] == 'tracked_changes')
    i, asset = companion
    assert asset['artifact_digest'] == digest and asset['file'] == name
    downloaded = get_release_report_asset(isolated_store, sid, owner, bundle['bundle_id'], i)
    evidence_index = next(i for i, a in enumerate(bundle['reports']) if a['report_kind'] == 'tracked_changes_evidence')
    evidence = json.loads(get_release_report_asset(isolated_store, sid, owner, bundle['bundle_id'], evidence_index)['content'])
    assert hashlib.sha256(downloaded['content']).hexdigest() == evidence['companion_sha256']
    assert downloaded['content'] != corrected
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur, "UPDATE release_report_bundles SET status='completed' WHERE id=%s", (bundle['bundle_id'],))
    import release_report_delivery
    monkeypatch.setattr(release_report_delivery, 'queue_if_release_settled',
        lambda *a, **kw: pytest.fail('Native attachments must not trigger legacy PDF regeneration'))
    assert retry_release_reports(isolated_store, sid, owner)['status'] == 'completed'
