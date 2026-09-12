"""Bounded extracted Office context and exact existing picture targets.

Never transmits the original Office archive. Images are grounded through their
own picture relationship; duplicate names and linked pictures are not authorized.
"""
import io
import re
import zipfile
import posixpath
from lxml import etree
from experiments.document_wide_ai.contracts.v1 import (
    CONTRACT_VERSION, DocumentContextManifest, DocumentFormat, Finding, Locator,
    ExtractionIssue, sha256_hex,
)
from experiments.document_wide_ai.application.allowlist import SET_OFFICE_IMAGE_ALT_TEXT, allowed_operations_for_manifest
from experiments.document_wide_ai.packaging.limits import check_limits, DocumentTooLarge
from formats.office.images import undescribed_images

R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def _relationships(z, part):
    name = posixpath.join(posixpath.dirname(part), '_rels', posixpath.basename(part)+'.rels')
    if name not in z.namelist():
        return {}
    root = etree.fromstring(z.read(name), etree.XMLParser(resolve_entities=False, no_network=True))
    return {r.get('Id'): posixpath.normpath(posixpath.join(posixpath.dirname(part), r.get('Target', ''))) .lstrip('/')
            if not r.get('Target', '').startswith('/') else r.get('Target').lstrip('/')
            for r in root if r.get('TargetMode') != 'External'}


def _part_aliases(z):
    slides, drawings = {}, {}
    if 'ppt/presentation.xml' in z.namelist():
        root = etree.fromstring(z.read('ppt/presentation.xml'))
        rels = _relationships(z, 'ppt/presentation.xml')
        for index, slide in enumerate(root.xpath('//*[local-name()="sldId"]')):
            slides[rels.get(slide.get('{'+R+'}id'))] = index
    if 'xl/workbook.xml' in z.namelist():
        root = etree.fromstring(z.read('xl/workbook.xml'))
        rels = _relationships(z, 'xl/workbook.xml')
        for sheet in root.xpath('//*[local-name()="sheet"]'):
            part = rels.get(sheet.get('{'+R+'}id'))
            if part not in z.namelist():
                continue
            sheet_root = etree.fromstring(z.read(part))
            sheet_rels = _relationships(z, part)
            for drawing in sheet_root.xpath('//*[local-name()="drawing"]'):
                target = sheet_rels.get(drawing.get('{'+R+'}id'))
                drawings.setdefault(target, set()).add(sheet.get('name', ''))
    return slides, drawings


def targets(data):
    result = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        slides, drawings = _part_aliases(z)
        for part in z.namelist():
            if not re.fullmatch(r'(?:ppt/(?:slides/slide|slideLayouts/slideLayout|slideMasters/slideMaster)|xl/drawings/drawing)\d+\.xml', part):
                continue
            root = etree.fromstring(z.read(part), etree.XMLParser(resolve_entities=False, no_network=True))
            for pic in root.xpath('//*[local-name()="pic"]'):
                props = pic.xpath('.//*[local-name()="cNvPr"]')
                blips = pic.xpath('.//*[local-name()="blip"]')
                if len(props) != 1 or not props[0].get('name'):
                    continue
                key = part+'#'+props[0].get('name')
                rid = blips[0].get('{'+R+'}embed') if len(blips) == 1 else None
                if key in result:
                    result[key] = (set(), None)
                else:
                    aliases = {key.casefold()}
                    if part in slides:
                        aliases.add(f"pptx:slide:{slides[part]}:element:{props[0].get('name')}".casefold())
                    for sheet in drawings.get(part, ()):
                        aliases.add(f"xlsx:sheet:{sheet}:drawing:{props[0].get('id')}".casefold())
                    result[key] = (aliases, part+'#'+rid if rid else None)
    from collections import Counter
    counts = Counter(alias for aliases, _ in result.values() for alias in aliases)
    return {key: ({alias for alias in aliases if counts[alias] == 1}, rid)
            for key, (aliases, rid) in result.items()}


def build_office_manifest(data, *, document_id, assessment_revision, selected_criteria, limits):
    fmt = DocumentFormat(document_id.rsplit('.', 1)[1].lower())
    issues, text = [], []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        entries = {n: z.read(n) for n in z.namelist()}
        if len(entries) != len(z.namelist()):
            raise ValueError('document_extraction_incomplete')
        # Text, table/cell values, shared strings, and slide/layout/master context.
        # Each block carries its exact part identity instead of invented pagination.
        for part in sorted(entries):
            if not re.fullmatch(r'(?:ppt/(?:slides/slide|slideLayouts/slideLayout|slideMasters/slideMaster|notesSlides/notesSlide)\d+|xl/(?:worksheets/sheet\d+|sharedStrings))\.xml', part):
                continue
            root = etree.fromstring(entries[part], etree.XMLParser(resolve_entities=False, no_network=True))
            if part.startswith('xl/worksheets/'):
                values = [cell.get('r', '?')+': '+ ' '.join(cell.xpath('.//*[local-name()="t" or local-name()="v"]/text()'))
                          for cell in root.xpath('//*[local-name()="c"]')]
            else:
                values = root.xpath('//*[local-name()="t" or local-name()="v"]/text()')
            if values:
                text.append('['+part+']\n'+'\n'.join(values))
        context = '\n'.join(text)
        images = undescribed_images(entries) if '1.1.1' in selected_criteria else []
    resolved = targets(data)
    findings = []
    for i, image in enumerate(images):
        aliases, rid = resolved.get(image['locator'], (set(), None))
        if not aliases or not rid:
            issues.append(ExtractionIssue('unsupported_image_target', 'Picture name is ambiguous or embedded visual relationship is unavailable.'))
            continue
        findings.append(Finding(f'{fmt.value}-image-{i}', 'office.missing-alt-text', '1.1.1',
            Locator(fmt, None, image['part'], image['name'], sha256_hex(b'<missing>')),
            'Existing embedded picture; semantic accuracy requires review.'))
    try:
        check_limits(text_chars=len(context), page_count=0, image_count=len(images), finding_count=len(findings), limits=limits)
    except DocumentTooLarge as exc:
        raise ValueError('document_too_large') from exc
    return DocumentContextManifest(CONTRACT_VERSION, 'office-context-extractor.v1', 'document-wide-ai-adapter.v1',
        document_id, fmt, sha256_hex(data), assessment_revision, selected_criteria, tuple(findings),
        tuple(op for op in allowed_operations_for_manifest() if op.op == SET_OFFICE_IMAGE_ALT_TEXT and op.format == fmt),
        context, extraction_issues=tuple(issues))
