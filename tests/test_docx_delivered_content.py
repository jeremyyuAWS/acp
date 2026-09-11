"""A real corrected DOCX must reach delivery, not merely a successful change record."""
import hashlib
import io
import zipfile

from lxml import etree
from docx.oxml.ns import qn

from test_docx_structural_dispatch import fixture
from remediate_office import _remediate_docx_structure


def test_saved_docx_heading_and_table_changes_reach_sharepoint(tmp_path, monkeypatch):
    import publish
    import scanner

    source = tmp_path / 'patient-rights.docx'
    fixture(source, outline=True, wrapped=True)
    original = source.read_bytes()
    with zipfile.ZipFile(io.BytesIO(original)) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    changes = []
    _remediate_docx_structure(entries, changes, in_scope=lambda sc: sc == '1.3.1')
    saved = io.BytesIO()
    with zipfile.ZipFile(saved, 'w') as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    corrected = saved.getvalue()
    assert corrected != original
    assert len(changes) == 2
    expected = hashlib.sha256(corrected).hexdigest()
    delivered = {}
    monkeypatch.setattr(publish._blob, 'download_remediated', lambda *args: corrected)
    monkeypatch.setattr(publish, '_sp_child', lambda *args: None)

    def upload(token, **kwargs):
        assert kwargs['conflict_behavior'] == 'fail'
        assert '/items/release-folder:' in kwargs['put_url']
        delivered['bytes'] = kwargs['content']
        return {'id': 'corrected-item', 'webUrl': 'https://example.invalid/corrected'}

    monkeypatch.setattr(scanner, '_sp_write', upload)
    monkeypatch.setattr(publish, '_sp_content_matches', lambda token, drive, item, digest:
                        item == 'corrected-item' and hashlib.sha256(delivered['bytes']).hexdigest() == digest)
    result = publish.archive_copy_publish_sharepoint(
        'test-token', 'drive', 'release-folder', 'owner@example.invalid', 'release',
        'scan', source.name, None, 'original-item', expected_digest=expected)
    assert result['verified'] is True
    assert result['checksum'] == expected
    assert delivered['bytes'] == corrected
    assert source.read_bytes() == original
    with zipfile.ZipFile(io.BytesIO(delivered['bytes'])) as archive:
        xml = etree.fromstring(archive.read('word/document.xml'))
        assert xml.find('.//' + qn('w:outlineLvl')).get(qn('w:val')) == '0'
        assert xml.find('.//' + qn('w:tblHeader')) is not None
        # Preserve the rest of the DOCX package, including unrelated styles/media.
        for name, content in entries.items():
            assert archive.read(name) == content
