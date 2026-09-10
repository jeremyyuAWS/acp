"""Read-only, owner-scoped follow-up reports. Publication is not certification."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
from urllib.parse import urlsplit
import base64
from pathlib import Path
from functools import lru_cache
import csv
import io
import re


def _text(value):
    return escape(str(value if value is not None else 'Not recorded'), quote=True)


def _rule(value):
    return str(value or '').removeprefix('SC_').replace('_', '.').split('/')[0]


def _location(row):
    parts = []
    for key, label in [('page', 'Page'), ('page_number', 'Page'), ('pages', 'Pages'),
                       ('slide', 'Slide'), ('slide_number', 'Slide'), ('sheet', 'Sheet'),
                       ('cell', 'Cell'), ('paragraph', 'Paragraph'), ('paragraph_index', 'Paragraph index'),
                       ('element', 'Element'), ('selector', 'Selector'), ('location', 'Location')]:
        value = row.get(key)
        if value is not None and value != '':
            parts.append(f'{label}: {value}')
    return '; '.join(parts) or 'Not recorded'


def _suggestions(task):
    proposals = task.get('proposals') or []
    if isinstance(proposals, dict):
        proposals = [proposals]
    rendered = []
    for proposal in proposals:
        if isinstance(proposal, dict):
            rendered.append('Before: ' + str(proposal.get('before', 'Not recorded')) +
                            '; Suggested: ' + str(proposal.get('proposed_value') or proposal.get('value') or proposal.get('text') or 'Not recorded'))
        elif isinstance(proposal, str):
            rendered.append(proposal)
    return '; '.join(rendered) or task.get('approved_value') or 'Not recorded'


def _link(url, label):
    try:
        parsed = urlsplit(str(url or ''))
        safe = parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username
    except ValueError:
        safe = False
    return f'<a href="{_text(url)}">{_text(label)}</a>' if safe else _text(label)


@lru_cache(maxsize=1)
def _logo():
    return base64.b64encode((Path(__file__).parent / 'assets' / 'mova-logo.png').read_bytes()).decode('ascii')


def _page(title, content):
    return ('<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{_text(title)}</title><style>body{{font:16px/1.5 system-ui;max-width:1280px;margin:2rem auto;padding:1rem;color:#302535;background:#fbf9fc}}'
            'main{background:white;border:1px solid #e4dcea;border-radius:16px;padding:24px}'
            '.brand{display:flex;gap:24px;align-items:center;border-bottom:3px solid #62435d;padding-bottom:16px}.brand img{width:200px;height:auto;max-width:45%}'
            'table{border-collapse:collapse;width:100%;font-size:14px;margin:12px 0}th,td{border-bottom:1px solid #e4dcea;padding:.75rem;text-align:left;vertical-align:top;overflow-wrap:anywhere}'
            'th{background:#f5eff7}caption{text-align:left;font-weight:bold}a{color:#573352}h1{font-size:1.8rem}h2{margin-top:28px}'
            'details{border:1px solid #e4dcea;border-radius:8px;padding:10px;margin:8px 0}summary{cursor:pointer;font-weight:600}'
            '.table-scroll{overflow-x:auto}small{color:#655b6a}.notice{padding:12px;background:#f5eff7;border-radius:8px}'
            '@media(max-width:700px){main{padding:12px}table{min-width:650px}.brand{flex-wrap:wrap}}'
            '@media print{body{background:white;margin:0}main{border:0}.brand img{width:150px}details{break-inside:avoid}table{font-size:10px}}</style>'
            f'<main><header class="brand"><img src="data:image/png;base64,{_logo()}" alt="Mova iO"><div>Accessibility Compliance Platform<br><strong>Scan and remediation report</strong></div></header>'
            f'<h1>{_text(title)}</h1><p class="notice">Published copies may have remaining accessibility issues. '
            'This report does not certify full accessibility compliance. Human follow-up is optional for publication.</p>'
            f'{content}</main></html>').encode('utf-8')


CATEGORIES = {
    'automatic': 'Fully automated', 'approval': 'Fix available — approval needed',
    'suggestion': 'AI suggestion needed', 'manual': 'Manual fix required',
    'unsupported': 'Cannot fix with ACP', 'blocked': 'Blocked',
    'applied': 'Applied — verification pending', 'verified': 'Fixed and verified',
}


def _category(trace=None, task=None, verified=False):
    trace, task = trace or {}, task or {}
    if verified:
        return 'verified'
    if task.get('applied'):
        return 'applied'
    if task.get('status') == 'blocked' or str(trace.get('outcome') or '').upper() in ('ERROR', 'NOT_EVALUATED', 'UNSUPPORTED'):
        return 'blocked'
    if task.get('status') in ('rejected', 'deferred'):
        return 'manual'
    if task.get('proposals') or task.get('approved_value'):
        return 'approval'
    mode = trace.get('fix_mode')
    if mode == 'auto':
        return 'automatic'
    if mode in ('ai-assisted', 'assisted'):
        return 'suggestion'
    if mode in ('human', 'manual', 'human-only') or trace.get('outcome') == 'REVIEW':
        return 'manual'
    if trace.get('remediation_supported') is False or mode in ('unsupported', 'none'):
        return 'unsupported'
    return 'blocked'


def _table(headers, rows):
    return '<div class="table-scroll"><table><thead><tr>' + ''.join(f'<th scope="col">{_text(h)}</th>' for h in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in row) + '</tr>' for row in rows) + '</tbody></table></div>'


def build_release_report_sources(store, scan_id, owner, release_id):
    """Return HTML assets, one per document, plus an aggregate checklist CSV.

    Original totals use sealed assessment evidence only. Verification credit requires
    ledger identity, timestamp AND a matching durable before/after evidence record.
    Current findings, review tasks and changes are intentionally separate units.
    """
    scan = store.get_scan(scan_id, owner=owner)
    release = store.release_status(release_id, owner)
    if not scan or not release or release.get('scan_id') != scan_id:
        raise KeyError('Release not found')
    stages = store.canonical_stage_lineage(scan_id, owner=owner).get('stages', [])
    remediation = next((s for s in stages if s.get('stage') == 'remediate'), {})
    assessment = next((s for s in stages if s.get('stage') == 'assess'), {})
    # Follow remediation's own assessment lineage, never a later reassessment.
    audit = None
    if remediation.get('input_manifest_id'):
        manifest = store.get_stage_output_manifest(remediation['input_manifest_id'], owner=owner) or {}
        for entry in manifest.get('entries', []):
            if isinstance(entry.get('assessment_summary'), dict):
                audit = store._validated_assessment_audit(entry['assessment_summary'])
                break
    elif assessment:
        audit = store.assessment_audit_summary(assessment)
    original = audit.get('findings_recorded') if audit and audit.get('valid') is not False else None
    diffs = store.remediation_diff_page(scan_id, limit=100000)
    ledger = store.list_finding_dispositions(scan_id, remediation['execution_id']) if remediation.get('execution_id') else []
    groups = audit.get('finding_groups') if audit and audit.get('valid') is not False else None
    original_groups = Counter()
    for group in groups or []:
        original_groups[(group['file'], _rule(group['rule_id']))] += int(group.get('finding_count') or 0)
    ledger_groups = Counter((r['file'], _rule(r['rule_id'])) for r in ledger)
    ledger_exact = (original is not None and isinstance(groups, list) and sum(original_groups.values()) == original
                    and original_groups == ledger_groups and len(ledger) == original
                    and len({r['finding_id'] for r in ledger}) == original)
    evidence_by_key = defaultdict(set)
    for d in diffs['items']:
        evidence_by_key[(d['file'], _rule(d['rule_id']))].add(f"remediation_diff:{d['file']}:{d['rule_id']}:{d['seq']}")
    def valid_evidence(row):
        allowed = evidence_by_key[(row['file'], _rule(row['rule_id']))]
        return bool(row.get('fix_evidence_ids')) and all(i in allowed for i in row['fix_evidence_ids'])
    verified = [r for r in ledger if r.get('disposition') == 'resolved_verified' and r.get('verified_at') and valid_evidence(r)]
    verified_total = len(verified) if ledger_exact and diffs['complete'] else None
    traces = store.get_scan_traces(scan_id)
    failed = [r for r in traces if r.get('outcome') == 'FAIL']
    # Unknown outcomes are explicitly unfinished, never inferred as passes.
    scope = store.get_scan_scope(scan_id)
    def selected(row):
        if scope is None:
            return True
        fmt = str(row['file']).rsplit('.', 1)[-1].lower()
        fmt = 'html' if fmt == 'htm' else fmt
        return fmt in scope.get(_rule(row['rule_id']), ())
    unfinished = [r for r in traces if selected(r) and str(r.get('outcome') or '').upper() not in ('PASS', 'FAIL', 'REVIEW', 'NA', 'NOT_APPLICABLE')]
    queue = store.list_hitl_queue(scan_id=scan_id, owner=owner)
    verified_keys = {(r['file'], _rule(r['rule_id'])) for r in diffs['items']}
    open_queue = [r for r in queue if r.get('status') not in ('rejected', 'not_applicable') and not (r.get('status') in ('approved', 'resolved') and r.get('applied') and (r['file'], _rule(r['rule_id'])) in verified_keys)]
    unverified = [r for r in queue if r.get('applied') and (r['file'], _rule(r['rule_id'])) not in verified_keys]
    outcomes = {r['file']: r for r in release['documents']}
    files = {f['file']: f for f in scan['files']}
    names = sorted(outcomes)
    rows = []
    assets = []
    index = []
    appendices = []
    for name in names:
        file = files.get(name, {})
        outcome = outcomes.get(name, {})
        status = outcome.get('status', 'not attempted')
        url = outcome.get('released_document_url') if status == 'published' else None
        checklist = []
        issues = file.get('issues') or []
        for issue in issues:
            rid = _rule(issue.get('rule_id') or issue.get('ruleId') or issue.get('wcag'))
            task = next((q for q in open_queue if q['file'] == name and _rule(q['rule_id']) == rid), {})
            checklist.append([rid, issue.get('detail') or 'Accessibility issue remains', _location(issue), issue.get('severity') or 'Unclassified', issue.get('recommended_action') or issue.get('remediation') or task.get('instruction') or task.get('description') or 'Review and correct this issue in the source document; reassess when convenient.', task.get('assignee') or 'Unassigned', 'Remaining issue'])
        for trace in [t for t in failed if t['file'] == name]:
            rid = _rule(trace['rule_id'])
            if not any(r[0] == rid for r in checklist):
                checklist.append([rid, f"{trace.get('finding_count', 0)} recorded findings: {trace.get('plain_name') or trace.get('rule_name') or rid}", 'Not recorded', 'Unclassified', 'Review and correct this issue in the source document.', 'Unassigned', 'Remaining issue'])
        for task in [q for q in open_queue if q['file'] == name]:
            rid = _rule(task['rule_id'])
            if not any(r[0] == rid for r in checklist):
                checklist.append([rid, task.get('title') or task.get('rule_name') or 'Follow-up review task', _location(task), task.get('severity') or 'Unclassified', task.get('instruction') or 'Inspect the saved copy when convenient; this task does not block publication.', task.get('assignee') or 'Unassigned', 'Applied, verification not recorded' if task.get('applied') else task.get('status') or 'Pending'])
        for trace in [t for t in traces if t['file'] == name and t.get('outcome') == 'REVIEW' and selected(t)]:
            rid = _rule(trace['rule_id'])
            if not any(r[0] == rid for r in checklist):
                checklist.append([rid, trace.get('plain_name') or trace.get('rule_name') or 'Review recommended', 'Not recorded', 'Unclassified', 'Check the meaning or usability of the saved result when convenient.', 'Unassigned', 'Review recommended; not a verified pass'])
        for check in [t for t in unfinished if t['file'] == name]:
            checklist.append([_rule(check['rule_id']), check.get('plain_name') or check.get('rule_name') or 'Check not completed', 'Not recorded', 'Unknown', 'Check manually or rerun with supported analysis.', 'Unassigned', f"Check not completed: {check.get('outcome') or 'unknown'}"])
        slug = re.sub(r'[^A-Za-z0-9._-]+', '-', name)[:65].strip('.-') or 'document'
        report_name = f'checklist-{slug}-{sha256(name.encode()).hexdigest()[:10]}.html'
        detail = f'<p>Document: {_text(name)}<br>Publication: {_text(status)}<br>Published file: {_link(url, url or "Not published")}<br>Release explanation: {_text(outcome.get("explanation"))}</p>'
        original_file = sum(n for (f, _), n in original_groups.items() if f == name) if groups is not None else None
        verified_file = sum(r['file'] == name for r in verified) if ledger_exact and diffs['complete'] else None
        detail += _table(['Finding measure', 'Count'], [[_text(k), _text(v)] for k, v in [
            ('Original assessment findings for this document', original_file),
            ('Original findings fixed and verified', verified_file),
            ('Original findings not yet verified fixed', original_file - verified_file if original_file is not None and verified_file is not None else None),
        ]]) + '<h2>Follow-up checklist</h2>'
        categorized = []
        for row in checklist:
            trace = next((t for t in traces if t['file'] == name and _rule(t['rule_id']) == row[0]), {})
            task = next((q for q in open_queue if q['file'] == name and _rule(q['rule_id']) == row[0]), {})
            category = _category(trace, task)
            categorized.append((category, row))
        detail += _table(['Criterion', 'Issue', 'Location', 'Remediation category', 'Recommended action', 'Owner', 'Status'],
                         [[_text(r[0]), _text(r[1]) + '<br><small>Severity: ' + _text(r[3]) + '</small>', _text(r[2]), _text(CATEGORIES[key]), *[_text(v) for v in r[4:]]] for key, r in categorized]) if checklist else '<p>No remaining issues are recorded in the available evidence. This is not a guarantee of compliance.</p>'
        from wcag_codeset import _name_for
        file_traces = [t for t in traces if t['file'] == name and selected(t)]
        if scope is not None:
            recorded = {_rule(t['rule_id']) for t in file_traces}
            for criterion in scope:
                missing = {'file': name, 'rule_id': criterion, 'outcome': 'Not recorded', 'finding_count': None}
                if _rule(criterion) not in recorded and selected(missing):
                    file_traces.append(missing)
        detail += '<h2>Success criteria coverage</h2><p>All recorded selected criteria for this file. An incomplete or missing check is not a pass.</p>'
        detail += _table(['Success criterion', 'Name / level', 'Recorded outcome', 'Recorded findings'],
                         [[_text(_rule(t['rule_id'])), _text(_name_for(_rule(t['rule_id']))) + ' / ' + _text(t.get('level')),
                           _text(t.get('outcome')), _text(t.get('finding_count'))] for t in file_traces]) if file_traces else '<p>Criterion-level coverage was not recorded.</p>'
        tasks = [q for q in open_queue if q['file'] == name]
        if tasks:
            detail += '<h2>Review task details</h2><p>Tasks may cover several findings; these are not additional findings.</p>'
            detail += _table(['Criterion', 'Task', 'Location', 'Instruction', 'Suggestions', 'Status'],
                             [[_text(_rule(q['rule_id'])), _text(q.get('title') or q.get('rule_name')),
                               _text(_location(q)), _text(q.get('instruction') or q.get('description')),
                               _text(_suggestions(q)), _text(q.get('status'))] for q in tasks])
        changes = [d for d in diffs['items'] if d['file'] == name]
        detail += '<h2>Recorded changes by success criterion</h2><p>Change records are separate from findings. Verified finding totals above require matching ledger evidence.</p>'
        for sc in sorted({_rule(d['rule_id']) for d in changes}):
            records = [d for d in changes if _rule(d['rule_id']) == sc]
            detail += f'<details open><summary>SC {_text(sc)} · {len(records)} change records</summary>'
            detail += _table(['Location', 'Before', 'After'], [[_text(_location(d)), _text(d.get('before')), _text(d.get('after'))] for d in records]) + '</details>'
        if not changes:
            detail += '<p>No change records are available for this file.</p>'
        appendices.append(f'<section class="document-appendix"><h2>Document: {_text(name)}</h2>{detail}</section>')
        assets.append({'name': report_name, 'content': _page(f'Follow-up checklist — {name}', detail), 'content_type': 'text/html; charset=utf-8'})
        category_groups = ''
        for key, label in CATEGORIES.items():
            matches = [r for category, r in categorized if category == key]
            if matches:
                category_groups += f'<details><summary>{_text(label)} · {len(matches)} checklist entries</summary><ul>' + ''.join(f'<li>SC {_text(r[0])} — {_text(r[1])}</li>' for r in matches) + '</ul></details>'
        if verified_file:
            category_groups += f'<p>{_text(CATEGORIES["verified"])} · {verified_file} findings</p>'
        index.append([_text(name), _text(name.rsplit('.', 1)[-1].upper()), _text(status), _text(original_file), _text(verified_file),
                      category_groups or 'No classified checklist entries', _text(sum(t['file'] == name for t in unfinished) if traces else None),
                      _link(url, 'Open published file') if url else 'Not published', f'<a href="{report_name}">Open checklist</a>'])
        rows.extend([[name, url or '', r[0], str(r[1]) + ' · Severity: ' + str(r[3]), r[2], CATEGORIES[key], *r[4:]] for key, r in categorized])
    remaining = sum(int(r.get('finding_count') or 0) for r in failed) if traces else None
    metrics = [('Files published in this release', release['published']), ('Publication failures', release['failed']), ('Not yet published', release['remaining']), ('Original assessment findings (immutable, whole scan)', original), ('Original findings fixed and verified', verified_total), ('Original findings not yet verified fixed', original - verified_total if original is not None and verified_total is not None else None), ('Current recorded remaining findings (whole scan)', remaining), ('Verified change records (not findings)', diffs['total']), ('Applied review records without matching verification evidence (not findings)', len(unverified)), ('Checks not completed (current recorded traces)', len(unfinished) if traces else None)]
    summary = f'<p>Scan: {_text(scan_id)} · Release: {_text(release_id)} · Generated: {_text(datetime.now(timezone.utc).isoformat())}</p>'
    summary += '<p>Original and current counts describe different points in time. Review tasks and change records are not added to finding totals. Not recorded means evidence is unavailable, not zero.</p>'
    summary += _table(['Measure', 'Count'], [[_text(k), _text(v)] for k, v in metrics])
    summary += '<h2>Documents and follow-up checklists</h2><p>Remediation categories describe recorded capability or state; future automatic fixes still require an accepted plan. Checklist entries, findings and change records use separate counts. Expand a category to see SCs by file.</p>' + _table(['Document', 'File type', 'Publication status', 'Original findings', 'Fixed and verified', 'Remediation category / SC', 'Incomplete checks', 'Published file', 'Follow-up'], index)
    summary += '<h2>Detailed printable checklists by document</h2>' + ''.join(appendices)
    assets.insert(0, {'name': 'scan-summary.html', 'content': _page('Remediation and publication summary', summary), 'content_type': 'text/html; charset=utf-8'})
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(['File', 'Published URL', 'Criterion', 'Issue', 'Location', 'Remediation category', 'Recommended action', 'Owner', 'Status'])
    for row in rows:
        # Spreadsheet readers must not interpret user-controlled content as formulas.
        writer.writerow(["'" + str(v) if str(v).lstrip().startswith(('=', '+', '-', '@')) else str(v) for v in row])
    assets.append({'name': 'remaining-issues.csv', 'content': stream.getvalue().encode('utf-8-sig'), 'content_type': 'text/csv; charset=utf-8'})
    return assets


def build_release_reports(store, scan_id, owner, release_id):
    """PDF is the delivery format; retain legacy source generation for audit tests."""
    from release_report_pdf import render_report_pdf
    return [dict(name=asset['name'].removesuffix('.html') + '.pdf',
                 content=render_report_pdf(asset['content']), content_type='application/pdf')
            for asset in build_release_report_sources(store, scan_id, owner, release_id)
            if asset['content_type'].startswith('text/html')]
