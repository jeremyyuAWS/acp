"""Read-only, owner-scoped follow-up reports. Publication is not certification."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
from urllib.parse import urlsplit
import csv
import io
import re


def _text(value):
    return escape(str(value if value is not None else 'Not recorded'), quote=True)


def _rule(value):
    return str(value or '').removeprefix('SC_').replace('_', '.').split('/')[0]


def _link(url, label):
    try:
        parsed = urlsplit(str(url or ''))
        safe = parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username
    except ValueError:
        safe = False
    return f'<a href="{_text(url)}">{_text(label)}</a>' if safe else _text(label)


def _page(title, content):
    return ('<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{_text(title)}</title><style>body{{font:16px/1.5 system-ui;max-width:1100px;margin:2rem auto;padding:1rem;color:#222}}'
            'table{border-collapse:collapse;width:100%}th,td{border:1px solid #aaa;padding:.6rem;text-align:left;vertical-align:top}'
            'caption{text-align:left;font-weight:bold}a{color:#164fa3}h1{font-size:1.8rem}</style>'
            f'<main><h1>{_text(title)}</h1><p>Published copies may have remaining accessibility issues. '
            'This report does not certify full accessibility compliance. Human follow-up is optional for publication.</p>'
            f'{content}</main></html>').encode('utf-8')


def _table(headers, rows):
    return '<table><thead><tr>' + ''.join(f'<th scope="col">{_text(h)}</th>' for h in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in row) + '</tr>' for row in rows) + '</tbody></table>'


def build_release_reports(store, scan_id, owner, release_id):
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
    open_queue = [r for r in queue if r.get('status') not in ('rejected', 'not_applicable') and not (r.get('status') == 'resolved' and r.get('applied') and (r['file'], _rule(r['rule_id'])) in verified_keys)]
    unverified = [r for r in queue if r.get('applied') and (r['file'], _rule(r['rule_id'])) not in verified_keys]
    outcomes = {r['file']: r for r in release['documents']}
    files = {f['file']: f for f in scan['files']}
    names = sorted(outcomes)
    rows = []
    assets = []
    index = []
    for name in names:
        file = files.get(name, {})
        outcome = outcomes.get(name, {})
        status = outcome.get('status', 'not attempted')
        url = outcome.get('released_document_url') if status == 'published' else None
        checklist = []
        issues = file.get('issues') or []
        for issue in issues:
            rid = _rule(issue.get('rule_id') or issue.get('wcag'))
            task = next((q for q in open_queue if q['file'] == name and _rule(q['rule_id']) == rid), {})
            checklist.append([rid, issue.get('detail') or 'Accessibility issue remains', issue.get('page') or issue.get('location') or 'Not recorded', issue.get('severity') or 'Unclassified', task.get('instruction') or task.get('description') or 'Review and correct this issue in the source document; reassess when convenient.', task.get('assignee') or 'Unassigned', 'Remaining issue'])
        for trace in [t for t in failed if t['file'] == name]:
            rid = _rule(trace['rule_id'])
            if not any(r[0] == rid for r in checklist):
                checklist.append([rid, f"{trace.get('finding_count', 0)} recorded findings: {trace.get('plain_name') or trace.get('rule_name') or rid}", 'Not recorded', 'Unclassified', 'Review and correct this issue in the source document.', 'Unassigned', 'Remaining issue'])
        for task in [q for q in open_queue if q['file'] == name]:
            rid = _rule(task['rule_id'])
            if not any(r[0] == rid for r in checklist):
                checklist.append([rid, task.get('title') or task.get('rule_name') or 'Follow-up review task', task.get('location') or task.get('pages') or 'Not recorded', task.get('severity') or 'Unclassified', task.get('instruction') or 'Inspect the saved copy when convenient; this task does not block publication.', task.get('assignee') or 'Unassigned', 'Applied, verification not recorded' if task.get('applied') else task.get('status') or 'Pending'])
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
        detail += _table(['Criterion', 'Issue', 'Location', 'Severity', 'Recommended action', 'Owner', 'Status'], [[_text(v) for v in r] for r in checklist]) if checklist else '<p>No remaining issues are recorded in the available evidence. This is not a guarantee of compliance.</p>'
        assets.append({'name': report_name, 'content': _page(f'Follow-up checklist — {name}', detail), 'content_type': 'text/html; charset=utf-8'})
        index.append([_text(name), _text(status), _link(url, 'Open published file') if url else 'Not published', f'<a href="{report_name}">Open checklist</a>'])
        rows.extend([[name, url or '', *r] for r in checklist])
    remaining = sum(int(r.get('finding_count') or 0) for r in failed) if traces else None
    metrics = [('Files published in this release', release['published']), ('Publication failures', release['failed']), ('Not yet published', release['remaining']), ('Original assessment findings (immutable, whole scan)', original), ('Original findings fixed and verified', verified_total), ('Original findings not yet verified fixed', original - verified_total if original is not None and verified_total is not None else None), ('Current recorded remaining findings (whole scan)', remaining), ('Verified change records (not findings)', diffs['total']), ('Applied review records without matching verification evidence (not findings)', len(unverified)), ('Checks not completed (current recorded traces)', len(unfinished) if traces else None)]
    summary = f'<p>Scan: {_text(scan_id)} · Release: {_text(release_id)} · Generated: {_text(datetime.now(timezone.utc).isoformat())}</p>'
    summary += '<p>Original and current counts describe different points in time. Review tasks and change records are not added to finding totals. Not recorded means evidence is unavailable, not zero.</p>'
    summary += _table(['Measure', 'Count'], [[_text(k), _text(v)] for k, v in metrics])
    summary += '<h2>Documents and follow-up checklists</h2>' + _table(['Document', 'Publication status', 'Published file', 'Follow-up'], index)
    assets.insert(0, {'name': 'scan-summary.html', 'content': _page('Remediation and publication summary', summary), 'content_type': 'text/html; charset=utf-8'})
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(['File', 'Published URL', 'Criterion', 'Issue', 'Location', 'Severity', 'Recommended action', 'Owner', 'Status'])
    for row in rows:
        # Spreadsheet readers must not interpret user-controlled content as formulas.
        writer.writerow(["'" + str(v) if str(v).lstrip().startswith(('=', '+', '-', '@')) else str(v) for v in row])
    assets.append({'name': 'remaining-issues.csv', 'content': stream.getvalue().encode('utf-8-sig'), 'content_type': 'text/csv; charset=utf-8'})
    return assets
