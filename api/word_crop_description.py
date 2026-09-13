"""Write explicitly reviewed visible-crop descriptions while preserving the diagram.

This improves access to the approved description; it does not replace raster text
or claim WCAG 1.4.5 clearance. Existing reviews without this disclosed option do
not opt in retroactively.
"""
import hashlib
import io
import json
import zipfile
from lxml import etree as ET
from office_visible_image import visible_word_image, NS
from apply_office_image_replacement import _references
from apply_office_image_of_text import _media_index

W = '{' + NS['w'] + '}'


def reviewed_plans(store, sid, file):
    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT proposals FROM hitl_queue WHERE scan_id=%s AND file=%s AND status='approved' AND resolution=%s AND rule_id IN ('1.4.5','1.4.9')",
                          (sid, file, store.DESCRIBED_RESOLUTION))
        rows = store._db.fetchall(cur)
    plans = {}
    for row in rows:
        for proposal in json.loads(row.get('proposals') or '[]'):
            evidence = proposal.get('visible_crop') or {}
            description = proposal.get('approved_value')
            if evidence.get('selectable_description_supported') is True and description:
                plans[proposal['locator']] = {'description': description, 'visible_crop': evidence}
    return plans


def write_descriptions(data, plans):
    if not plans:
        return data
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        root = ET.fromstring(source.read('word/document.xml'),
                             parser=ET.XMLParser(resolve_entities=False, no_network=True))
        media = _media_index(source)
        changed = False
        ids = [int(e.get(W + 'id')) for e in root.iter(W + 'bookmarkStart')
               if str(e.get(W + 'id', '')).isdigit()]
        next_id = max(ids, default=0) + 1
        for locator, plan in plans.items():
            visible = visible_word_image(data, locator)
            evidence = plan.get('visible_crop') or {}
            text = plan.get('description')
            if (not visible or not isinstance(text, str) or not text.strip() or len(text) > 10000
                    or any(ord(c) < 32 and c not in '\n\r\t' for c in text)
                    or evidence.get('selectable_description_supported') is not True
                    or any(evidence.get(k) != visible[k] for k in
                           ('crop', 'source_image_sha256', 'visible_image_sha256'))):
                continue
            marker = 'acp_crop_' + hashlib.sha256((locator + visible['visible_image_sha256'] + text).encode()).hexdigest()[:24]
            if root.xpath('.//w:bookmarkStart[@w:name=$name]', namespaces=NS, name=marker):
                continue
            image = media[int(locator.split()[-1]) - 1]
            refs = _references(source, image)
            if len(refs) != 1:
                continue
            blips = root.xpath('.//a:blip[@r:embed=$rid]', namespaces=NS, rid=refs[0][1])
            if len(blips) != 1:
                continue
            paragraphs = [p for p in blips[0].iterancestors() if p.tag == W + 'p']
            if not paragraphs or paragraphs[0].getparent().tag not in (W + 'body', W + 'tc'):
                continue
            paragraph = ET.Element(W + 'p')
            ET.SubElement(paragraph, W + 'bookmarkStart', {W + 'id':str(next_id), W + 'name':marker})
            run = ET.SubElement(paragraph, W + 'r')
            for number, line in enumerate(text.replace('\r\n','\n').replace('\r','\n').split('\n')):
                if number:
                    ET.SubElement(run, W + 'br')
                ET.SubElement(run, W + 't', {'{http://www.w3.org/XML/1998/namespace}space':'preserve'}).text = line
            ET.SubElement(paragraph, W + 'bookmarkEnd', {W + 'id':str(next_id)})
            paragraphs[0].addnext(paragraph)
            next_id += 1
            changed = True
        if not changed:
            return data
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as target:
            for entry in source.infolist():
                value = (ET.tostring(root, xml_declaration=True, encoding='UTF-8')
                         if entry.filename == 'word/document.xml' else source.read(entry.filename))
                target.writestr(entry, value)
        return out.getvalue()
