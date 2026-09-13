"""Valid Word relationship/metadata dialects must still supply their own image pixels."""
import io
import re
import sys
import zipfile
from pathlib import Path

from docx import Document
from lxml import etree
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'api'))
import remediate_office as office
from formats.office.images import undescribed_images


def image_package():
    document = Document()
    pictures = []
    for colour in ['blue', 'red']:
        image = io.BytesIO()
        Image.new('RGB', (96, 72), colour).save(image, format='PNG')
        pictures.append(image.getvalue())
        document.add_picture(io.BytesIO(image.getvalue()))
    buffer = io.BytesIO()
    document.save(buffer)
    with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as package:
        return {name: package.read(name) for name in package.namelist()}, pictures


def lookup(parts, index=0):
    xml = parts['word/document.xml'].decode()
    element = list(re.finditer(r'<wp:docPr\b([^>]*?)(/?)>', xml))[index]
    return office._image_bytes_for(xml, element, 'wp:docPr', None, parts, 'word/document.xml')


def test_opaque_relationship_id_reaches_exact_pixels_and_deferred_evidence():
    parts, pixels = image_package()
    xml = parts['word/document.xml'].decode()
    original = re.search(r'r:embed="([^"]+)"', xml)[1]
    opaque = 'rIdSyntheticImageAlpha'
    parts['word/document.xml'] = xml.replace(f'r:embed="{original}"', f'r:embed="{opaque}"').encode()
    parts['word/_rels/document.xml.rels'] = parts['word/_rels/document.xml.rels'].replace(f'Id="{original}"'.encode(), f'Id="{opaque}"'.encode())
    assert len(undescribed_images(parts)) == 2
    assert lookup(parts) == (opaque, pixels[0])
    evidence = []
    applied, deferred = office._fix_image_alt(parts, vision_enabled=False, evidence=evidence)
    assert not applied and deferred == 2
    assert {entry['locator'] for entry in evidence} >= {f'word/document.xml#{opaque}'}
    assert all(entry.get('thumb') for entry in evidence)


def test_large_valid_nonvisual_extension_does_not_hide_image_or_cross_into_sibling():
    parts, pixels = image_package()
    root = etree.fromstring(parts['word/document.xml'])
    props = root.xpath('//*[local-name()="docPr"]')[0]
    ns = 'http://schemas.openxmlformats.org/drawingml/2006/main'
    extension = etree.SubElement(etree.SubElement(props, f'{{{ns}}}extLst'), f'{{{ns}}}ext', uri='urn:acp:synthetic:metadata')
    etree.SubElement(extension, '{urn:acp:synthetic:metadata}payload').text = 'x' * 12000
    parts['word/document.xml'] = etree.tostring(root)
    assert len(undescribed_images(parts)) == 2
    assert lookup(parts)[1] == pixels[0]
    assert lookup(parts, 1)[1] == pixels[1]


def test_external_image_remains_unresolved_without_borrowing_neighbor_pixels():
    parts, pixels = image_package()
    xml = parts['word/document.xml'].decode()
    rid = re.search(r'r:embed="([^"]+)"', xml)[1]
    root = etree.fromstring(parts['word/_rels/document.xml.rels'])
    relationship = next(rel for rel in root if rel.get('Id') == rid)
    relationship.set('TargetMode', 'External')
    relationship.set('Target', 'https://example.invalid/image.png')
    parts['word/_rels/document.xml.rels'] = etree.tostring(root)
    assert lookup(parts) is None
    assert lookup(parts, 1)[1] == pixels[1]


def test_missing_container_close_cannot_borrow_pixels_after_next_docpr():
    parts, pixels = image_package()
    xml = parts['word/document.xml'].decode()
    # A broken first drawing has neither pixels nor a closing inline marker.
    # The next docPr is still a hard boundary, even when the next inline ends first.
    xml = re.sub(r' r:embed="[^"]+"', '', xml, count=1)
    xml = xml.replace('</wp:inline>', '', 1)
    parts['word/document.xml'] = xml.encode()
    assert lookup(parts) is None
    assert lookup(parts, 1)[1] == pixels[1]


def prefixed_relationships(parts, *, opaque=False, external=False):
    """Reserialize a real package's relationships with valid arbitrary namespace prefix."""
    name = 'word/_rels/document.xml.rels'
    root = etree.fromstring(parts[name])
    namespace = 'http://schemas.openxmlformats.org/package/2006/relationships'
    replacement = etree.Element(f'{{{namespace}}}Relationships', nsmap={'pkg': namespace})
    first_rid = re.search(r'r:embed="([^"]+)"', parts['word/document.xml'].decode())[1]
    for relationship in root:
        attrs = dict(relationship.attrib)
        if attrs['Id'] == first_rid:
            if opaque:
                attrs['Id'] = 'opaque-image-guid'
            if external:
                attrs.update(TargetMode='External', Target='https://example.invalid/image.png')
        etree.SubElement(replacement, f'{{{namespace}}}Relationship', **attrs)
    if opaque:
        parts['word/document.xml'] = parts['word/document.xml'].replace(
            f'r:embed="{first_rid}"'.encode(), b'r:embed="opaque-image-guid"')
    parts[name] = etree.tostring(replacement)


def test_prefixed_relationship_namespace_reaches_exact_images_and_evidence():
    parts, pixels = image_package()
    prefixed_relationships(parts, opaque=True)
    assert len(undescribed_images(parts)) == 2
    assert lookup(parts) == ('opaque-image-guid', pixels[0])
    assert lookup(parts, 1)[1] == pixels[1]
    evidence = []
    applied, deferred = office._fix_image_alt(parts, vision_enabled=False, evidence=evidence)
    assert not applied and deferred == 2
    assert all(entry.get('thumb') for entry in evidence)


def test_prefixed_external_relationship_does_not_borrow_internal_sibling():
    parts, pixels = image_package()
    prefixed_relationships(parts, external=True)
    assert lookup(parts) is None
    assert lookup(parts, 1)[1] == pixels[1]


def test_malformed_relationships_cannot_resolve_partial_xml():
    parts, _ = image_package()
    name = 'word/_rels/document.xml.rels'
    parts[name] = parts[name].replace(b'</Relationships>', b'')
    assert lookup(parts) is None
    assert lookup(parts, 1) is None


def test_duplicate_relationship_id_is_ambiguous_and_not_resolved():
    parts, pixels = image_package()
    name = 'word/_rels/document.xml.rels'
    root = etree.fromstring(parts[name])
    rid = re.search(r'r:embed="([^"]+)"', parts['word/document.xml'].decode())[1]
    first = next(rel for rel in root if rel.get('Id') == rid)
    duplicate = etree.SubElement(root, first.tag, **dict(first.attrib))
    duplicate.set('Target', 'media/image2.png')
    parts[name] = etree.tostring(root)
    assert lookup(parts) is None
    assert lookup(parts, 1)[1] == pixels[1]
