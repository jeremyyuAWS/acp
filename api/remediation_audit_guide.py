"""Pure, conservative projection of recorded findings into an offline repair guide.

No provider calls, guessed locations, criterion-level subtraction, or invented AI text.
Editor instructions are general guidance; recorded proposals remain recommendations.
"""
import json
from pathlib import PurePath
import re

_GUIDANCE = {
    '1.1.1': ('Non-text Content', 'Provide a concise text alternative conveying the purpose; mark purely decorative objects decorative.'),
    '1.3.1': ('Info and Relationships', 'Use semantic headings, lists, table headers and labels rather than visual formatting alone.'),
    '1.3.2': ('Meaningful Sequence', 'Put content in a logical reading sequence and confirm it with assistive technology.'),
    '1.3.3': ('Sensory Characteristics', 'Rewrite instructions so they identify controls by name or purpose, not only shape, position or sound.'),
    '1.4.1': ('Use of Color', 'Add text, patterns or symbols so color is not the only way information is conveyed.'),
    '1.4.3': ('Contrast (Minimum)', 'Check the actual foreground and background; target 4.5:1 for ordinary text or 3:1 for qualifying large text.'),
    '1.4.5': ('Images of Text', 'Replace unnecessary raster text with editable text; preserve wording, layout and any required exception.'),
    '1.4.11': ('Non-text Contrast', 'Check meaningful controls and graphics against adjacent colors; provide at least 3:1 where required.'),
    '2.1.1': ('Keyboard', 'Test every interactive feature using only the keyboard and repair inaccessible controls or provide an equivalent accessible alternative.'),
    '2.1.2': ('No Keyboard Trap', 'Test entering and leaving every interactive object with the keyboard; ensure there is a documented way to leave.'),
    '2.4.2': ('Page / Doc Titled', 'Set a descriptive document title that identifies its subject and purpose.'),
    '2.4.3': ('Focus Order', 'Test the interactive focus sequence and arrange controls so the sequence preserves meaning and operation.'),
    '2.4.4': ('Link Purpose (In Context)', 'Replace vague link text with meaningful destination or action text, retaining the correct target.'),
    '2.4.6': ('Headings and Labels', 'Use descriptive headings and control labels that explain topic or purpose; verify they match the content.'),
    '3.1.1': ('Language of Page', 'Set the correct primary document language and verify it reflects the content.'),
    '3.1.2': ('Language of Parts', 'Mark passages in another language with the correct language, excluding names and other applicable exceptions.'),
    '4.1.2': ('Name, Role, Value', 'Give each interactive control an accessible name and correct role, state and value; test changes with assistive technology.'),
}
_EDITORS = {
    'docx': 'Open the saved Word document and locate the recorded paragraph, table, link or picture. Use styles, table properties, picture accessibility properties or the relevant text properties.',
    'xlsx': 'Open the saved Excel workbook and locate the recorded sheet, cell, drawing or chart. Edit the cell text, table headers, drawing accessibility properties or relevant formatting.',
    'pptx': 'Open the saved PowerPoint presentation and locate the recorded slide and object. Edit the object text, accessibility properties, reading order or relevant formatting.',
    'pdf': 'Open the saved PDF in an accessibility-capable PDF editor, such as Acrobat Pro. Locate the recorded page, tag or form field; use tag properties, reading order, document properties or form-field properties.',
}
_ACTIONS = {
 'docx': {'1.1.1': 'Edit the picture’s alt text or decorative setting.', '1.3.1': 'Use heading styles, real list numbering and table header-row properties.', '1.3.2': 'Review paragraph order and the placement of anchored objects.', '2.4.2': 'Set the Title in file properties.', '3.1.1': 'Select document text and set the primary proofing language.', '3.1.2': 'Select the passage and set its proofing language.', '4.1.2': 'Check content-control names and form labels.'},
 'xlsx': {'1.1.1': 'Edit the drawing or chart alt text.', '1.3.1': 'Use meaningful worksheet names and table headers; review merged cells.', '1.3.2': 'Review worksheet and cell order, including charts and drawings.', '2.4.2': 'Set the Title in workbook properties.', '3.1.1': 'Check the workbook language supported by the authoring tools.', '3.1.2': 'Check language marking supported for the specific passage; if unavailable, provide an accessible alternative.', '4.1.2': 'Check control names, labels, states and linked-cell values.'},
 'pptx': {'1.1.1': 'Edit the selected slide object’s alt text or decorative setting.', '1.3.1': 'Use semantic slide titles and table header properties.', '1.3.2': 'Review slide order and object reading order.', '2.4.2': 'Set the Title in presentation properties.', '3.1.1': 'Set the primary text proofing language and check all slides.', '3.1.2': 'Select the passage and set its proofing language.', '4.1.2': 'Check interactive object names, action labels and states.'},
 'pdf': {'1.1.1': 'Inspect the exact Figure tag and set its alternate text; mark decorative material as an artifact when appropriate.', '1.3.1': 'Repair heading, list and table tags, including header associations; prefer correcting the authoring source for complex structures.', '1.3.2': 'Review the tag-tree reading sequence against the visible page.', '2.4.2': 'Set the document Title and configure the viewer to display it.', '3.1.1': 'Set the document’s primary language in document properties.', '3.1.2': 'Set the Lang property on the exact tagged passage; do not guess tag associations.', '4.1.2': 'Inspect the exact form field’s accessible name, type and state.'},
}

_SEVERITY = {'CRITICAL': 0, 'SERIOUS': 1, 'MAJOR': 1, 'MODERATE': 2, 'MINOR': 3}


def _sc(row):
    value = str(row.get('sc') or row.get('wcag') or row.get('rule_id') or row.get('ruleId') or row.get('criterion') or '')
    if value.upper().startswith('SC_'):
        value = value[3:]
    value = value.replace('_', '.')
    match = re.search(r'\d+\.\d+\.\d+', value)
    return match.group(0) if match else value


def _id(row):
    return row.get('finding_id') or row.get('issue_id')


def _location(row):
    parts = []
    for key, label in [('location', ''), ('locator', ''), ('source_locator', ''), ('page', 'page '), ('slide', 'slide '), ('sheet', 'sheet '), ('cell', 'cell '), ('element', 'element ')]:
        value = row.get(key)
        if value is not None and value != '':
            text = label + str(value)
            if text not in parts:
                parts.append(text)
    return ' · '.join(parts) or 'Location not recorded — locate the issue in the document before editing.'


def _identity(row):
    # Never use a download URL or filename as proof of version identity.
    value = row.get('artifact_digest') or row.get('corrected_sha256') or row.get('artifact_sha256') or row.get('remediated_sha256') or row.get('artifact_version_id')
    return _normalize_identity(value)


def _normalize_identity(value):
    if isinstance(value, str):
        if value.lower().startswith('sha256:'):
            value = value[7:]
        if re.fullmatch(r'[0-9a-fA-F]{64}', value):
            value = value.lower()
    return value


def _stale(row, identity):
    bound = _identity(row)
    return bool(row.get('stale') or (identity and bound and _normalize_identity(identity) != bound))


def _base(row, fmt):
    sc = _sc(row)
    title, recommendation = _GUIDANCE.get(sc, ('Recorded accessibility finding', 'Inspect the recorded issue and repair it using the editor’s accessibility tools.'))
    return {'criterion': sc, 'title': title, 'finding_id': _id(row),
            'location': _location(row), 'priority': str(row.get('severity') or 'MINOR').upper(),
            'recommendation': recommendation, 'editor_steps': [
                _EDITORS.get(fmt, 'Open the saved file in its authoring application and locate the recorded issue.'),
                _ACTIONS.get(fmt, {}).get(sc, recommendation),
                'Save a new copy, rerun accessibility assessment and check the affected content with assistive technology. A saved edit alone does not establish conformance.'],
            'original_value': row.get('before') if row.get('before') is not None else row.get('current_value'),
            'technical_status': 'Technical verification not recorded',
            'human_status': 'Human confirmation of meaning not recorded'}


def _same_finding(a, b):
    if _id(a) and _id(b):
        return _id(a) == _id(b) and _sc(a) == _sc(b)
    # Exact locators can ground recommendations, but cannot establish resolution.
    loc_a, loc_b = _location(a), _location(b)
    return not loc_a.startswith('Location not recorded') and loc_a == loc_b and _sc(a) == _sc(b)


def build_remediation_audit_guide(files, decisions=None, evidence=None, facts=None):
    """Return per-file display dictionaries without mutating report inputs.

    ``files[].issues`` are the assessment findings, not unique criteria. The legacy
    evidence projection may lack version and finding IDs; retain that uncertainty.
    ``decisions`` and ``facts`` aggregates cannot prove individual resolution.
    """
    by_file = {}
    for doc in evidence or []:
        if isinstance(doc, dict):
            by_file.setdefault(doc.get('file'), []).append(doc)
    documents = []
    for file in files or []:
        name = str(file.get('file') or file.get('name') or 'Unnamed document')
        fmt = PurePath(name).suffix.lstrip('.').lower()
        identity = _identity(file)
        artifact = {'display': str(identity) if identity else 'Saved artifact version/hash not recorded', 'identity': identity}
        applied, proposals = [], []
        for doc in by_file.get(name, []):
            for item in doc.get('applied') or []:
                row = _base(item, fmt)
                stale = _stale(item, identity) or _stale(doc, identity)
                row.update(kind='change', saved_value=item.get('after'),
                           status='Stale change evidence — verify against the saved file' if stale else 'Recorded saved change',
                           technical_status='Stale evidence; verification must be repeated' if stale else ('Re-scan checked in recorded evidence' if item.get('validated') is True else 'Technical verification not recorded'),
                           reason=item.get('note'), thumb=item.get('thumb'), before_thumb=item.get('before_thumb'), after_thumb=item.get('after_thumb'))
                if item.get('human_confirmed') is True or item.get('semantic_confirmed') is True:
                    row['human_status'] = 'Human confirmation recorded' if not stale else 'Human confirmation belongs to stale evidence'
                row['_source'] = item
                row['_current'] = bool(identity and (_identity(item) or _identity(doc)) == identity and not stale)
                applied.append(row)
            for group in doc.get('proposed') or []:
                for proposal in group.get('proposals') or []:
                    if not isinstance(proposal, dict):
                        continue
                    source = {**group, **proposal}
                    source['_stale'] = _stale(source, identity) or _stale(doc, identity)
                    proposal_hash = proposal.get('source_sha256')
                    if proposal_hash and identity:
                        source['_stale'] = source['_stale'] or _normalize_identity(proposal_hash) != _normalize_identity(identity)
                    proposals.append(source)
        raw_tasks = (facts or {}).get('audit_review_tasks')
        if raw_tasks is not None:
            # Raw tasks preserve every target; legacy evidence uses one per SC.
            proposals = []
            for task in raw_tasks:
                if task.get('file') != name or task.get('applied') in (True, 1) or task.get('status') in ('rejected', 'not_applicable'):
                    continue
                raw_proposals = task.get('proposals') or []
                if isinstance(raw_proposals, str):
                    try:
                        raw_proposals = json.loads(raw_proposals)
                    except (ValueError, TypeError):
                        raw_proposals = []
                if not isinstance(raw_proposals, list):
                    raw_proposals = []
                for proposal in raw_proposals:
                    if not isinstance(proposal, dict):
                        continue
                    source = {**task, **proposal}
                    source['_processing'] = task.get('status') in ('queued', 'processing', 'applying', 'verifying')
                    source['_stale'] = _stale(source, identity)
                    proposal_hash = proposal.get('source_sha256')
                    if proposal_hash and identity:
                        source['_stale'] = source['_stale'] or _normalize_identity(proposal_hash) != _normalize_identity(identity)
                    source['proposed_value'] = proposal.get('proposed_value') if proposal.get('proposed_value') is not None else (proposal.get('value') if proposal.get('value') is not None else proposal.get('text'))
                    source['rationale'] = proposal.get('rationale') or proposal.get('reason')
                    proposals.append(source)
        remaining = []
        used = set()
        for issue in file.get('issues') or []:
            if not isinstance(issue, dict):
                continue
            # Only durable per-finding and current-version evidence can retire a baseline item.
            resolved = any(_id(issue) and _id(change['_source']) == _id(issue) and _sc(change['_source']) == _sc(issue)
                           and change['_current'] and change['_source'].get('validated') is True for change in applied)
            if resolved:
                continue
            row = _base(issue, fmt)
            row.update(kind='finding', status='Needs remediation or verification', description=issue.get('message') or issue.get('detail') or issue.get('description'))
            matching = [(i, p) for i, p in enumerate(proposals) if _same_finding(issue, p) and not p['_stale']]
            # Ambiguous proposal matches are not assigned arbitrarily.
            if len(matching) == 1:
                index, proposal = matching[0]
                used.add(index)
                row.update(proposed_value=proposal.get('proposed_value'), reason=proposal.get('rationale') or proposal.get('why_review'), status=('Processing — recommendation not recorded as saved' if proposal.get('_processing') else 'AI recommendation — not recorded as saved'), source=proposal.get('source'))
            remaining.append(row)
        for index, proposal in enumerate(proposals):
            if index in used:
                continue
            row = _base(proposal, fmt)
            row.update(kind='proposal', status='Stale recommendation — regenerate before use' if proposal['_stale'] else ('Processing — unlinked recommendation not recorded as saved' if proposal.get('_processing') else 'Unlinked recommendation — confirm the target before editing'),
                       proposed_value=None if proposal['_stale'] else proposal.get('proposed_value'), reason=None if proposal['_stale'] else proposal.get('rationale') or proposal.get('why_review'))
            remaining.append(row)
        remaining.sort(key=lambda row: (_SEVERITY.get(row['priority'], 3), row['criterion']))
        for change in applied:
            change.pop('_source')
            change.pop('_current')
        documents.append({'file': name, 'name': name, 'format': fmt.upper(), 'artifact': artifact,
                          'applied': applied, 'remaining': remaining,
                          'assessment_findings_remaining': sum(r['kind'] == 'finding' for r in remaining),
                          'coverage_note': 'Recommendations are guidance. Unlinked proposals are not additional assessment findings; recorded changes do not establish that every baseline issue is resolved.'})
    return documents
