"""Bounded approved image-of-text replacement for Word and Excel.

Replace a single inline Word picture or a simple Excel drawing picture with selectable
text. The raster and its relationship are removed, not described. Shared media,
non-body Word placements, groups, crops and transforms are unresolved. Replacement
changes appearance; it does not promise faithful typography or infer transcript text.
Unchanged package members retain their original bytes.
"""
from __future__ import annotations

import io
import re
import zipfile
from copy import deepcopy

from lxml import etree as ET
from apply_office_image_of_text import _media_index, _rid_map

NS = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'xdr': 'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing',
}
REL_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'
LOC = re.compile(r'^image\s+(\d+)$', re.I)
PARSER = ET.XMLParser(resolve_entities=False, no_network=True)


def _q(prefix, name):
    return '{' + NS[prefix] + '}' + name


def _read(zin, part):
    return ET.fromstring(zin.read(part), parser=PARSER)


def _relpart(part):
    directory, name = part.rsplit('/', 1)
    return f'{directory}/_rels/{name}.rels'


def _references(zin, media):
    found = []
    if '_rels/.rels' in zin.namelist():
        for relationship in _read(zin, '_rels/.rels'):
            if (relationship.get('TargetMode', '').lower() != 'external'
                    and (relationship.get('Target') or '').lstrip('/') == media):
                found.append(('', relationship.get('Id')))
    for name in zin.namelist():
        if '/_rels/' not in name or not name.endswith('.rels'):
            continue
        directory, base = name.rsplit('/_rels/', 1)
        owner = directory + '/' + base[:-5]
        found.extend((owner, rid) for rid, target in _rid_map(zin, owner).items()
                     if target == media)
    return found


def _simple_picture(pic):
    # Unsupported transforms/crops would change both intended content and placement.
    if pic.xpath('.//a:srcRect | .//a:tile', namespaces=NS):
        return False
    for transform in pic.xpath('.//a:xfrm', namespaces=NS):
        if any(transform.get(k) not in (None, '0', 'false')
               for k in ('rot', 'flipH', 'flipV')):
            return False
    return len(pic.xpath('.//a:blip', namespaces=NS)) == 1


def _word(root, rid, text):
    blips = root.xpath('.//a:blip[@r:embed=$rid]', namespaces=NS, rid=rid)
    if len(blips) != 1:
        return False
    if sum(value == rid for e in root.iter() for key, value in e.attrib.items()
           if key.startswith('{' + NS['r'] + '}')) != 1:
        return False
    blip = blips[0]
    inline = next((p for p in blip.iterancestors() if p.tag == _q('wp', 'inline')), None)
    if inline is None or not _simple_picture(inline):
        return False
    drawing = inline.getparent()
    run = drawing.getparent()
    paragraph = run.getparent()
    if (drawing.tag != _q('w', 'drawing') or run.tag != _q('w', 'r')
            or len(drawing) != 1
            or len(inline.xpath('.//a:graphicData', namespaces=NS)) != 1
            or inline.xpath('.//a:graphicData', namespaces=NS)[0].get('uri') !=
                'http://schemas.openxmlformats.org/drawingml/2006/picture'
            or paragraph.tag != _q('w', 'p')
            or paragraph.getparent().tag not in (_q('w', 'body'), _q('w', 'tc'))
            or any(c.tag not in (_q('w', 'rPr'), _q('w', 'drawing')) for c in run)
            or sum(c.tag == _q('w', 'drawing') for c in run) != 1):
        return False
    index = run.index(drawing)
    run.remove(drawing)
    for number, line in enumerate(text.split('\n')):
        if number:
            run.insert(index, ET.Element(_q('w', 'br')))
            index += 1
        node = ET.Element(_q('w', 't'))
        node.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
        node.text = line
        run.insert(index, node)
        index += 1
    return True


def _excel(root, rid, text):
    blips = root.xpath('.//a:blip[@r:embed=$rid]', namespaces=NS, rid=rid)
    if len(blips) != 1:
        return False
    if sum(value == rid for e in root.iter() for key, value in e.attrib.items()
           if key.startswith('{' + NS['r'] + '}')) != 1:
        return False
    pic = next((p for p in blips[0].iterancestors() if p.tag == _q('xdr', 'pic')), None)
    if pic is None or not _simple_picture(pic):
        return False
    anchor = pic.getparent()
    if (anchor.getparent() is not root or anchor.tag not in
            tuple(_q('xdr', n) for n in ('oneCellAnchor', 'twoCellAnchor', 'absoluteAnchor'))
            or sum(c.tag in (_q('xdr', 'pic'), _q('xdr', 'sp'), _q('xdr', 'grpSp'),
                            _q('xdr', 'graphicFrame'), _q('xdr', 'cxnSp')) for c in anchor) != 1):
        return False
    geometry = pic.find(_q('xdr', 'spPr'))
    nv = pic.find(_q('xdr', 'nvPicPr'))
    cnv = nv.find(_q('xdr', 'cNvPr')) if nv is not None else None
    if geometry is None or cnv is None:
        return False
    # Anchor coordinates remain byte-equivalent at the element level; text uses the
    # original box with normal auto-fit, without choosing an invented font size.
    sp = ET.Element(_q('xdr', 'sp'))
    nvsp = ET.SubElement(sp, _q('xdr', 'nvSpPr'))
    new_cnv = deepcopy(cnv)
    new_cnv.attrib.pop('descr', None)
    new_cnv.set('name', 'Accessible text ' + cnv.get('id', ''))
    nvsp.append(new_cnv)
    ET.SubElement(nvsp, _q('xdr', 'cNvSpPr'), txBox='1')
    sp.append(deepcopy(geometry))
    body = ET.SubElement(sp, _q('xdr', 'txBody'))
    props = ET.SubElement(body, _q('a', 'bodyPr'), wrap='square')
    ET.SubElement(props, _q('a', 'normAutofit'))
    ET.SubElement(body, _q('a', 'lstStyle'))
    for line in text.split('\n'):
        paragraph = ET.SubElement(body, _q('a', 'p'))
        run = ET.SubElement(paragraph, _q('a', 'r'))
        ET.SubElement(run, _q('a', 't')).text = line
    anchor.replace(pic, sp)
    return True


def apply_office_image_replacement(data: bytes, ext: str, values: dict[str, str]):
    """Return (bytes, applied records, unresolved locators), same write contract as PPTX."""
    if not values:
        return data, [], []
    ext = ext.lower().lstrip('.')
    if ext not in ('docx', 'xlsx'):
        return data, [], list(values)
    applied, unresolved, changes, removed = [], [], {}, set()
    with zipfile.ZipFile(io.BytesIO(data)) as zin:
        media = _media_index(zin)
        for locator, text in values.items():
            match = LOC.fullmatch(str(locator).strip())
            if (not match or not isinstance(text, str) or not text.strip()
                    or len(text) > 10000 or any(ord(c) < 32 and c not in '\n\t\r' for c in text)):
                unresolved.append(locator)
                continue
            index = int(match[1]) - 1
            if not 0 <= index < len(media) or media[index] in removed:
                unresolved.append(locator)
                continue
            image = media[index]
            refs = _references(zin, image)
            if len(refs) != 1:
                unresolved.append(locator)
                continue
            owner, rid = refs[0]
            supported = (owner == 'word/document.xml' if ext == 'docx' else
                         bool(re.fullmatch(r'xl/drawings/drawing\d+\.xml', owner)))
            if not supported:
                unresolved.append(locator)
                continue
            try:
                root = ET.fromstring(changes.get(owner, zin.read(owner)), parser=PARSER)
                writer = _word if ext == 'docx' else _excel
                if not writer(root, rid, text.replace('\r\n', '\n').replace('\r', '\n')):
                    unresolved.append(locator)
                    continue
                relpath = _relpart(owner)
                relroot = ET.fromstring(changes.get(relpath, zin.read(relpath)), parser=PARSER)
                relationships = relroot.findall('{' + REL_NS + '}Relationship')
                target = [r for r in relationships if r.get('Id') == rid]
                if len(target) != 1:
                    unresolved.append(locator)
                    continue
                relroot.remove(target[0])
            except (ET.XMLSyntaxError, KeyError):
                unresolved.append(locator)
                continue
            changes[owner] = ET.tostring(root, xml_declaration=True, encoding='UTF-8')
            changes[relpath] = ET.tostring(relroot, xml_declaration=True, encoding='UTF-8')
            removed.add(image)
            applied.append({'locator': locator, 'before': 'image of text', 'after': text})
        if not applied:
            return data, [], unresolved
        # Most writers use extension defaults, but remove explicit overrides if
        # present rather than leave a content-type declaration for a deleted part.
        types = _read(zin, '[Content_Types].xml')
        overrides = [e for e in types if e.tag.endswith('}Override')
                     and (e.get('PartName') or '').lstrip('/') in removed]
        for e in overrides:
            types.remove(e)
        if overrides:
            changes['[Content_Types].xml'] = ET.tostring(types, xml_declaration=True, encoding='UTF-8')
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                if info.filename not in removed:
                    zout.writestr(info, changes.get(info.filename, zin.read(info.filename)))
    return out.getvalue(), applied, unresolved
