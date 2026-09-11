"""Bound document context to saved assessment identities, never invented ordinals."""
from dataclasses import replace
import hashlib
import io
import json
import re
import zipfile

from experiments.document_wide_ai.contracts.v1 import Evidence, EvidenceKind, ExtractionIssue
from experiments.document_wide_ai.packaging.manifest_builder import build_docx_manifest, build_pdf_manifest
from experiments.document_wide_ai.packaging.limits import ExtractionLimits

LIMITS = ExtractionLimits(max_text_chars=60000, max_pages=100, max_images=8, max_findings=100)


def criterion(value):
    match = re.fullmatch(r'(?:SC_)?([1-4])[._]([0-9]+)[._]([0-9]+)', str(value or ''))
    return '.'.join(match.groups()) if match else None


def assessed_locations(issues, sc, count):
    """Use detector locations only when the entire counted group is represented uniquely."""
    rows = [i for i in issues if criterion(i.get('wcag')) == sc]
    locations = [str(i.get('location') or '').strip() for i in rows]
    if len(rows) != count or not all(locations) or len({x.casefold() for x in locations}) != count:
        return None
    return sorted(locations, key=str.casefold)


def _docx_targets(data):
    from lxml import etree
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
          'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
          'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
          'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
    result = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for part in z.namelist():
            if not re.fullmatch(r'word/(?:document|header\d*|footer\d*)\.xml', part):
                continue
            root = etree.fromstring(z.read(part), etree.XMLParser(resolve_entities=False, no_network=True))
            for index, paragraph in enumerate(root.findall('.//w:p', ns)):
                for drawing in paragraph.findall('.//w:drawing', ns):
                    for props in drawing.findall('.//wp:docPr', ns):
                        name = props.get('name')
                        if not name:
                            continue
                        key = part + '#' + name
                        blips = drawing.findall('.//a:blip', ns)
                        rid = blips[0].get('{'+ns['r']+'}embed') if len(blips) == 1 else None
                        aliases = {key.casefold()}
                        if part == 'word/document.xml':
                            aliases.add(f"docx:drawing:{props.get('id')}:paragraph:{index}".casefold())
                        # Repeated names are ambiguous to the production writer too.
                        if key in result:
                            result[key] = (set(), None)
                        else:
                            result[key] = (aliases, part+'#'+rid if rid else None)
    return result


def _bounded_source(data, filename):
    if not isinstance(data, bytes) or len(data) > 20 * 1024 * 1024:
        raise ValueError('document_too_large')
    if filename.lower().endswith('.docx'):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if len(z.infolist()) > 4000 or sum(i.file_size for i in z.infolist()) > 80 * 1024 * 1024:
                raise ValueError('document_too_large')


def build_manifest(store, scan_id, filename, data):
    from llm_waterfall_provider import managed_context
    from assessment_selection import selected_for_file
    ctx = managed_context()
    if ctx is None or ctx.scan_id != scan_id or ctx.file != filename:
        raise ValueError('document_context_missing')
    record = store.get_file_record(scan_id, filename) or {}
    actual = hashlib.sha256(data).hexdigest()
    if record.get('corrected_sha256') != actual:
        raise ValueError('document_source_changed')
    scope = store.scope_for_file(scan_id, filename, store.get_scan_scope(scan_id))
    selected = selected_for_file(scope, filename)
    if selected is None:
        raise ValueError('document_selected_criteria_missing')
    with store._db.cursor() as cur:
        store._db.execute(cur, 'SELECT snapshot_id,baseline_json FROM remediation_contribution_runs WHERE owner_id=%s AND scan_id=%s AND run_id=%s',
                          (ctx.owner_id, scan_id, ctx.run_id))
        baseline = store._db.fetchone(cur)
    if not baseline:
        raise ValueError('document_assessment_lineage_missing')
    rows = [r for r in json.loads(baseline['baseline_json']) if r['file'] == filename and r['rule_id'] in selected]
    dispositions = {r['finding_id']: r.get('disposition') for r in store.list_finding_dispositions(scan_id, ctx.run_id)}
    rows = [r for r in rows if dispositions.get(r['finding_id']) not in {'resolved_verified', 'excluded_by_policy', 'superseded_by_reassessment'}]
    _bounded_source(data, filename)
    builder = build_docx_manifest if filename.lower().endswith('.docx') else build_pdf_manifest if filename.lower().endswith('.pdf') else None
    if builder is None:
        raise ValueError('document_format_unsupported')
    packaged = builder(data, document_id=filename, assessment_revision=baseline['snapshot_id'],
                       selected_criteria=tuple(sorted(selected)), limits=LIMITS)
    if any(i.kind in {'extraction_failed', 'extraction_truncated'} for i in packaged.extraction_issues):
        raise ValueError('document_extraction_incomplete')
    targets = _docx_targets(data) if filename.lower().endswith('.docx') else {}
    findings, issues, matched = [], list(packaged.extraction_issues), set()
    for target in packaged.findings:
        loc = target.locator
        key = loc.part_name+'#'+loc.element_ref if loc.part_name else loc.element_ref
        aliases = targets.get(key, ({key.casefold()}, None))[0]
        candidates = [r for r in rows if r['rule_id'] == target.success_criterion
                      and str(r.get('instance_key', '')).casefold() in aliases]
        group = [r for r in rows if r['rule_id'] == target.success_criterion]
        # A single legacy assessed finding and a single current target are unambiguous.
        if not candidates and len(group) == 1 and len(packaged.findings) == 1 and str(group[0].get('instance_key', '')).startswith('aggregate-instance:'):
            candidates = group
        if len(candidates) == 1 and candidates[0]['finding_id'] not in matched:
            row = candidates[0]
            matched.add(row['finding_id'])
            findings.append(replace(target, finding_id=row['finding_id']))
    for row in rows:
        if row['finding_id'] not in matched:
            issues.append(ExtractionIssue('finding_not_packaged', 'No unambiguous supported target remains in this saved document.', (row['finding_id'],)))
    manifest = replace(packaged, findings=tuple(findings), extraction_issues=tuple(issues))
    if targets:
        evidence = []
        for finding in findings:
            key = finding.locator.part_name+'#'+finding.locator.element_ref
            rid_locator = targets.get(key, (None, None))[1]
            image = _image(data, rid_locator) if rid_locator else None
            if image is None:
                issues.append(ExtractionIssue('missing_visual_evidence', 'Image content is unavailable or exceeds the image limit.', (finding.finding_id,)))
                continue
            evidence.append(Evidence(EvidenceKind.IMAGE, finding.locator, 'Image content needed to describe this assessed image.',
                                     image_ref='sha256:'+hashlib.sha256(image).hexdigest()))
        manifest = replace(manifest, evidence=tuple(evidence), extraction_issues=tuple(issues))
    return manifest


def _image(data, locator):
    from remediate_office import image_bytes_for_locator
    from PIL import Image
    image = image_bytes_for_locator(data, locator)
    if not image or len(image) > 1024 * 1024:
        return None
    try:
        with Image.open(io.BytesIO(image)) as img:
            if img.format not in {'PNG', 'JPEG'} or max(img.size) > 1568 or img.width * img.height > 2500000:
                return None
            img.verify()
    except Exception:
        return None
    return image


def package_images(data, manifest):
    if hashlib.sha256(data).hexdigest() != manifest.source_sha256:
        raise ValueError('document_source_changed')
    targets = _docx_targets(data) if manifest.document_format.value == 'docx' else {}
    images = {}
    for evidence in manifest.evidence:
        loc = evidence.source_locator
        rid = targets.get(loc.part_name+'#'+loc.element_ref, (None, None))[1]
        image = _image(data, rid) if rid else None
        if image is None or evidence.image_ref != 'sha256:'+hashlib.sha256(image).hexdigest():
            raise ValueError('document_image_changed')
        images[evidence.image_ref] = image
    if len(images) > 8 or sum(map(len, images.values())) > 4 * 1024 * 1024:
        raise ValueError('document_too_large')
    return images
