import io
import zipfile
from xml.etree import ElementTree as ET

from office_tracked_changes import build_tracked_companion

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}


def package(body, extra=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr('word/document.xml', f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>')
        z.writestr('word/media/image.png', b'unchanged image')
        for name, value in (extra or {}).items():
            z.writestr(name, value)
    return buf.getvalue()


def para(text):
    return f'<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>{text}</w:t></w:r></w:p>'


def document(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return ET.fromstring(z.read('word/document.xml'))


def view(root, accepted):
    def walk(el):
        if el.tag == f'{{{W}}}' + ('del' if accepted else 'ins'):
            return ''
        if el.tag in {f'{{{W}}}t', f'{{{W}}}delText'}:
            return el.text or ''
        return ''.join(walk(child) for child in el)
    return walk(root)


def test_native_revisions_have_exact_before_after_and_preserve_formats_media():
    before, after = package(para('Click the red button.')), package(para('Click Save.'))
    companion, report = build_tracked_companion(before, after, date='2026-09-12T00:00:00Z')
    root = document(companion)
    assert view(root, True) == 'Click Save.'
    assert view(root, False) == 'Click the red button.'
    assert len(root.findall('.//w:b', NS)) == 2
    assert root.find('.//w:del', NS).attrib[f'{{{W}}}author'] == 'Mova.io ACP'
    assert report['complete'] and report['companion_sha256']
    assert view(document(after), True) == 'Click Save.'
    with zipfile.ZipFile(io.BytesIO(companion)) as z:
        assert z.read('word/media/image.png') == b'unchanged image'


def test_hyperlink_label_keeps_relationship_and_surrounding_text():
    def link(text):
        return '<w:p><w:r><w:t>See </w:t></w:r><w:hyperlink w:anchor="section">' + para(text)[5:-6] + '</w:hyperlink></w:p>'
    companion, report = build_tracked_companion(package(link('click here')), package(link('annual report')))
    root = document(companion)
    assert view(root, True) == 'See annual report'
    assert view(root, False) == 'See click here'
    assert root.find('.//w:hyperlink', NS).attrib[f'{{{W}}}anchor'] == 'section'
    assert report['tracked_changes']


def test_existing_unrelated_revisions_preserved_and_new_ids_unique():
    prior = '<w:p><w:ins w:id="91" w:author="Author"><w:r><w:t>Prior</w:t></w:r></w:ins></w:p>'
    before, after = package(prior + para('Before')), package(prior + para('After'))
    companion, report = build_tracked_companion(before, after)
    root = document(companion)
    assert root.find('.//w:ins', NS).attrib[f'{{{W}}}author'] == 'Author'
    ids = [el.attrib[f'{{{W}}}id'] for el in root.iter() if f'{{{W}}}id' in el.attrib]
    assert len(ids) == len(set(ids))
    assert report['complete']


def test_overlapping_revisions_complex_content_and_structural_edits_decline():
    cases = [
        ('<w:p><w:ins w:id="1"><w:r><w:t>Before</w:t></w:r></w:ins></w:p>', para('After')),
        ('<w:p><w:r><w:t>Before</w:t><w:tab/></w:r></w:p>', para('After')),
        (para('Before'), para('After') + para('Added')),
    ]
    for before, after in cases:
        companion, report = build_tracked_companion(package(before), package(after))
        assert companion is None
        assert report['untracked_changes'] and not report['complete']


def test_metadata_change_is_honestly_untracked():
    before = package(para('Before'), {'docProps/core.xml': '<core/>'})
    after = package(para('After'), {'docProps/core.xml': '<core title="Updated"/>'})
    companion, report = build_tracked_companion(before, after)
    assert companion is not None
    assert not report['complete']
    assert report['untracked_changes'][0]['part'] == 'docProps/core.xml'


def test_invalid_and_nonword_packages_decline_without_claim():
    companion, report = build_tracked_companion(b'corrupt', b'corrupt')
    assert companion is None and report['untracked_changes']
    assert report['companion_sha256'] is None


def test_real_saved_docx_approved_rewrite_and_detector_sees_accepted_primary():
    from docx import Document
    from apply_text_values import apply_sensory_rewrite
    source = Document()
    source.add_paragraph('Click the red button. Keep this sentence.').runs[0].bold = True
    buf = io.BytesIO()
    source.save(buf)
    original = buf.getvalue()
    corrected, applied, unresolved = apply_sensory_rewrite(
        original, 'docx', {'Click the red button.': 'Click Save.'})
    assert applied and not unresolved
    assert Document(io.BytesIO(corrected)).paragraphs[0].text == 'Click Save. Keep this sentence.'
    companion, report = build_tracked_companion(original, corrected)
    assert companion is not None and report['complete']
    root = document(companion)
    assert view(root, True) == 'Click Save. Keep this sentence.'
    assert view(root, False) == 'Click the red button. Keep this sentence.'
    # Client opens the OPC archive; inserted/deleted runs are native revision elements.
    reopened = Document(io.BytesIO(companion))
    assert reopened.part.package is not None
    with zipfile.ZipFile(io.BytesIO(companion)) as z:
        with zipfile.ZipFile(io.BytesIO(corrected)) as primary:
            for name in z.namelist():
                if name != 'word/document.xml':
                    assert z.read(name) == primary.read(name)


def test_unicode_entity_declarations_and_namespace_spoof_are_rejected():
    def raw_package(raw):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('[Content_Types].xml', '<Types/>')
            z.writestr('word/document.xml', raw)
        return buf.getvalue()
    for encoding in ('utf-8', 'utf-16', 'utf-32'):
        xml = f'<?xml version="1.0"?><!DOCTYPE w:document [<!ENTITY x "bad">]><w:document xmlns:w="{W}"><w:body/></w:document>'
        companion, report = build_tracked_companion(raw_package(xml.encode(encoding)), package(para('After')))
        assert companion is None and report['untracked_changes']
    companion, report = build_tracked_companion(
        raw_package(b'<w:document xmlns:w="wrong"><w:body/></w:document>'), package(para('After')))
    assert companion is None and report['untracked_changes']


def test_duplicate_and_oversized_package_metadata_refused_before_full_read(monkeypatch):
    from zipfile import ZipInfo
    oversized = ZipInfo('large.bin')
    oversized.file_size = 257 * 1024 * 1024
    real = zipfile.ZipFile.infolist
    monkeypatch.setattr(zipfile.ZipFile, 'infolist', lambda z: real(z) + [oversized])
    companion, report = build_tracked_companion(package(para('Before')), package(para('After')))
    assert companion is None and report['untracked_changes']
