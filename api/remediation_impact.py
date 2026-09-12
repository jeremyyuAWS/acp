"""Run-backed remediation forecasts. Counts are finding instances, not queue cards."""
from collections import defaultdict
import re

LANES = ('automatic', 'review', 'manual', 'blocked')
# `ai_automatic` gates AI POLICY LEVELS ABOVE 1 only. It is NOT a statement that no AI
# proposal can be applied unattended: `auto_approve_ai` is valid precisely at level 1
# (remediation_impact_settings.normalize), so a level-1 run with standing approval does
# apply and release AI values with no per-change human review. The reason string used to
# claim the opposite and was read that way; it now says what the flag actually does.
CAPABILITIES = {'assign': True, 'execute': True, 'save_future': True, 'ai_budget': True, 'ai_automatic': False, 'supported_ai_levels': [0, 1],
                'ai_automatic_reason': ('AI policy levels above 1 are unavailable on this execution path. '
                                        'At level 1, AI drafts still reach a person unless you turn on automatic '
                                        'approval for the run, which applies and releases eligible AI values '
                                        'without individual review and requires the AI reviewer.')}


def criterion(value):
    match = re.search(r'(\d+)[._](\d+)[._](\d+)', str(value or ''))
    return '.'.join(match.groups()) if match else str(value or '')


def _count(rows):
    return {'findings': sum(r['finding_count'] for r in rows),
            'files': len({r['file'] for r in rows})}


def _route(row, policy):
    if row.get('processing_blocked'):
        return 'blocked', 'processing_unavailable'
    if row.get('verification_failed') or row.get('rejected'):
        return 'manual', 'failed_or_rejected_fix'
    if row.get('human_only') or row.get('subjective'):
        return 'manual', 'accessibility_judgment'
    if row.get('evidence_complete') is False:
        return 'blocked', 'missing_evidence'
    if row.get('origin') == 'rule_based':
        if policy['rule_based'] == 0:
            return 'review', 'approval_required'
        if policy['rule_based'] == 1 and not row.get('validated'):
            return 'review', 'validation_required'
        if row.get('remediation_supported') is True:
            return 'automatic', 'eligible_rule_based_fix'
        return 'blocked', 'eligibility_unknown'
    if row.get('origin') == 'ai':
        if policy['ai'] == 0:
            return 'manual', 'ai_disabled'
        # Standing approval (`auto_approve_ai`) applies and releases eligible AI values
        # with no per-change human review, so forecasting them as `review` told the
        # operator the opposite of what their own run would do. Only the rules
        # ai_standing_approval can act on are moved; everything else still needs a
        # person, and the lane stays a FORECAST — application-time eligibility
        # (a writer, an exact locator, an accepted AI review) can still route a row
        # back to the human queue, which is the safe direction to be wrong in.
        if policy.get('auto_approve_ai') is True:
            from ai_standing_approval import RULES
            if (row.get('criterion') or criterion(row.get('rule_id'))) in RULES:
                return 'automatic', 'ai_standing_approval'
        return 'review', ('proposal_approval' if row.get('has_proposal') else 'draft_required')
    if row.get('remediation_supported') is False:
        return 'manual', 'source_editing'
    return 'blocked', 'routing_unknown'


def _routed(rows, policy):
    result = []
    for row in rows:
        lane, reason = _route(row, policy)
        result.append({**row, 'lane': lane, 'primary_reason': reason})
    # Writers operate on criteria, not individual findings. Never widen an allow-list
    # around a protected finding sharing the same criterion in the same document.
    groups = defaultdict(list)
    for row in result:
        groups[(row['file'], row['criterion'])].append(row)
    for group in groups.values():
        if any(r['lane'] != 'automatic' for r in group):
            for row in group:
                if row['lane'] == 'automatic':
                    row.update(lane='review', primary_reason='shared_criterion_requires_review')
    return result


def build_impact_preview(rows, policy, *, files=(), active_policy=None, scan_id=None,
                         population_complete=True):
    active_policy = active_policy or {'rule_based': 2, 'ai': 1}
    for p in (policy, active_policy):
        if p.get('rule_based') not in (0, 1, 2) or p.get('ai') not in (0, 1, 2, 3):
            raise ValueError('invalid remediation impact policy')
    normalized = []
    for index, row in enumerate(rows):
        count = int(row.get('finding_count', 1) or 0)
        if count <= 0 or row.get('resolved'):
            continue
        normalized.append({**row, 'id': row.get('id') or f'finding-group-{index}',
                           'finding_count': count, 'criterion': criterion(row.get('rule_id'))})
    routed = _routed(normalized, policy)
    baseline = _routed(normalized, active_policy)
    active_lanes = {lane: _count([r for r in baseline if r['lane'] == lane]) for lane in LANES}
    lanes = {}
    for lane in LANES:
        items = [r for r in routed if r['lane'] == lane]
        reasons = defaultdict(list)
        for r in items:
            reasons[r['primary_reason']].append(r)
        lanes[lane] = {**_count(items), 'delta': _count(items)['findings'] - active_lanes[lane]['findings'],
                       'reasons': [{'reason': reason, **_count(group)} for reason, group in sorted(reasons.items())]}
    metadata = {f['file']: f for f in files}
    by_file = defaultdict(list)
    for row in routed:
        by_file[row['file']].append(row)
    details = []
    for name, group in sorted(by_file.items()):
        meta = metadata.get(name, {})
        counts = {lane: sum(r['finding_count'] for r in group if r['lane'] == lane) for lane in LANES}
        if meta.get('complete') is False or meta.get('blocked') or counts['blocked']:
            outlook = 'blocked_incomplete'
        elif counts['manual'] or counts['review']:
            outlook = 'human_work'
        elif meta.get('complete') is not True:
            outlook = 'unavailable'
        else:
            outlook = 'could_complete'
        details.append({'file': name, 'findings': sum(counts.values()), **counts, 'outlook': outlook})
    opened = _count(routed)
    return {'contract_version': 'remediation-impact.v1', 'scan_id': scan_id,
            'policy': policy, 'active_policy': active_policy, 'open': opened,
            'lanes': lanes, 'active_lanes': active_lanes, 'findings': routed, 'files': details,
            'file_outlook': {name: {'files': sum(f['outlook'] == name for f in details)}
                             for name in ('could_complete', 'human_work', 'blocked_incomplete', 'unavailable')},
            'integrity': {'complete': population_complete,
                          'open_equals_lane_sum': opened['findings'] == sum(b['findings'] for b in lanes.values()),
                          'file_counts_overlap_across_lanes': True},
            'capabilities': {**CAPABILITIES, 'execute': policy['ai'] <= 1},
            'forecast_note': 'Completion is conditional on successful application and verification.'}


def _verified_credits(store, scan_id):
    """Read only the latest execution batch; an applied proposal is not proof."""
    if not hasattr(store, '_db'):
        return {}
    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT batch_id FROM jobs WHERE scan_id=%s AND type='remediate_file' "
                          "ORDER BY created_at DESC,id DESC LIMIT 1", (scan_id,))
        batch = store._db.fetchone(cur)
    if not batch or not batch.get('batch_id'):
        return {}
    manifest = store.current_stage_output_manifest(scan_id, 'assess') or {}
    current_snapshot = manifest.get('manifest_id') or store.stage_snapshot_id(scan_id)
    groups = defaultdict(list)
    for row in store.list_finding_dispositions(scan_id, batch['batch_id']):
        if row.get('snapshot_id') == current_snapshot:
            groups[(row['file'], criterion(row['rule_id']))].append(row)
    return {key: {'total': len(group), 'verified': sum(
        row.get('disposition') == 'resolved_verified' and bool(row.get('verified_at'))
        and bool(row.get('fix_evidence_ids')) for row in group)} for key, group in groups.items()}


def load_run_findings(store, scan_id, owner):
    """Use every current FAIL trace, then enrich it from review evidence.

    The queue is not the population: deterministic findings often have no review
    card. Queue-only deferrals are tasks/checks and must not inflate finding totals.
    """
    scan = store.get_scan(scan_id, owner=owner)
    if scan is None:
        raise LookupError('scan not found')
    import handlers
    records = {f['file']: f for f in scan.get('files', [])}
    names = set(records)
    source = (scan.get('run') or {}).get('source')
    queue = defaultdict(list)
    for q in store.list_hitl_queue(scan_id=scan_id, owner=owner):
        queue[(q['file'], criterion(q.get('rule_id')))].append(q)
    credits = _verified_credits(store, scan_id)
    rows = []
    for trace in store.get_scan_traces(scan_id):
        if trace.get('outcome') != 'FAIL' or trace.get('file') not in names:
            continue
        count = int(trace.get('finding_count') or 0)
        credit = credits.get((trace['file'], criterion(trace.get('rule_id'))), {})
        if credit.get('total') == count:
            count -= credit['verified']
        if count <= 0:
            continue
        evidence = queue.get((trace['file'], criterion(trace.get('rule_id'))), [])
        mode = trace.get('fix_mode')
        record = records[trace['file']]
        processing_blocked = (not trace['file'].lower().endswith(handlers.remediable_extensions())
                              or (source == 'drive' and not record.get('drive_file_id')))
        proposals = [p for q in evidence for p in (q.get('proposals') or []) if isinstance(p, dict)]
        rows.append({**trace, 'finding_count': count, 'processing_blocked': processing_blocked,
                     'origin': 'rule_based' if mode == 'auto' else ('ai' if mode == 'ai-assisted' else 'human'),
                     'remediation_supported': mode in ('auto', 'ai-assisted'),
                     'has_proposal': bool(proposals),
                     # Queue validation lacks source-version binding.
                     'validated': False,
                     'human_only': mode in ('human', 'manual', 'human-only'),
                     'rejected': any(q.get('status') == 'rejected' for q in evidence),
                     'verification_failed': any(q.get('apply_outcome') for q in evidence)})
    manifest = store.get_scan_manifest(scan_id)
    coverage = {f['file']: f for f in manifest.get('files', [])}
    files = [{**f, 'complete': coverage.get(f['file'], {}).get('complete'),
              'blocked': str(f.get('status', '')).lower() in ('error', 'failed', 'unreadable', 'discovered')}
             for f in scan.get('files', [])]
    return rows, files


def build_run_impact(store, scan_id, owner, policy=None, scope=None):
    """Shared read-only contract for the card and execution admission."""
    from remediation_impact_settings import read_impact_policy
    active = read_impact_policy(store, owner)
    rows, files = load_run_findings(store, scan_id, owner)
    if scope is not None:
        selected_names = set(scope)
        rows = [r for r in rows if r['file'] in selected_names]
        files = [f for f in files if f['file'] in selected_names]
    selected = policy or active
    scan = store.get_scan(scan_id, owner=owner)
    run = scan.get('run') or {}
    # Partial traces during a running assessment are not a complete population.
    assessed = bool(run.get('assessed_at'))
    result = build_impact_preview(rows, selected, files=files, active_policy=active,
                                  scan_id=scan_id, population_complete=assessed)
    result['capabilities']['ai_enabled'] = store.get_ai_enabled()
    from ai_generation_chain import chain_options
    result['capabilities']['generation_chain'] = chain_options(rows)
    if (selected['ai'] > 0 and len(selected.get('generation_chain', {}).get('steps', [])) == 3
            and not result['capabilities']['generation_chain']['supported']):
        result['capabilities'].update(execute=False, reason=result['capabilities']['generation_chain']['reason'])
    if not assessed:
        result['capabilities'].update(execute=False, reason='Assessment results are not yet available.')
    elif not result['capabilities']['ai_enabled'] and selected['ai'] > 0:
        result['capabilities'].update(execute=False, reason='AI is disabled in application settings. Choose Off to run rule-based fixes.')
    if selected['ai'] > 0 and selected.get('generation_chain'):
        options = result['capabilities']['generation_chain']
        catalog = options['models']
        if any(i >= len(catalog) or step['model'] != catalog[i]['model']
               or step['provider'] != catalog[i]['provider']
               for i, step in enumerate(selected['generation_chain']['steps'])):
            result['capabilities'].update(execute=False, reason='The approved generation models are unavailable in current settings.')
    if selected['ai'] > 1:
        result['capabilities'].update(execute=False, reason=CAPABILITIES['ai_automatic_reason'])
    if (selected.get('document_wide_model_profile') == 'native-pdf-quality.v1'
            and any(str(f.get('file', '')).lower().endswith('.pdf') for f in files)):
        from types import SimpleNamespace
        from native_pdf_quality import configured_native_pdf_generator
        from llm_waterfall_provider import dispatch_endpoint
        # Same current governance, credentials and expiring model checks as dispatch.
        # This creates a generator only: it never sends a probe or reserves money.
        def no_transport(*args, **kwargs):
            raise RuntimeError('Readiness preflight cannot call a provider')
        try:
            readiness = SimpleNamespace(policy=selected, enabled=result['capabilities']['ai_enabled'],
                                        file=next(f['file'] for f in files if str(f.get('file', '')).lower().endswith('.pdf')))
            generator = configured_native_pdf_generator(readiness, post=no_transport)
            if any(not dispatch_endpoint(spec, generator.providers) for spec in generator.specs.values()):
                raise ValueError('Native PDF provider endpoint unavailable')
        except Exception:
            result['capabilities'].update(execute=False, reason=(
                'The PDF quality profile is not ready. An administrator must permit OpenAI and Anthropic '
                'and configure their credentials, connections, and current GPT-4.1 / Sonnet 5 model settings. '
                'Choose Document context to use the standard AI settings.'))
    result['scope'] = {'type': 'selected_files' if scope is not None else 'assessment', 'files': len(files)}
    result['assessment_gaps'] = {'files': sum(bool(f.get('complete') is not True or f.get('blocked')) for f in files)}
    if hasattr(store, 'remediation_status'):
        from ai_run_policy import read_run_budget
        batch_id = store.remediation_status(scan_id).get('batch_id')
        result['ai_spending'] = read_run_budget(store, owner, scan_id, batch_id) if batch_id else None
    return result


def assign_impact_work(store, scan_id, owner, files, assignee, policy=None):
    """Assign server-derived human work only; do not send notifications or approve fixes."""
    if not isinstance(assignee, str) or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', assignee.strip()):
        raise ValueError('Enter a valid assignee email address.')
    assignee = assignee.strip()
    requested = list(dict.fromkeys(files))
    forecast = build_run_impact(store, scan_id, owner, policy, scope=requested)
    if not forecast['integrity']['complete']:
        raise ValueError('Assessment results are not yet available.')
    groups = defaultdict(dict)
    for row in forecast['findings']:
        if row['lane'] == 'automatic':
            continue
        key = row['criterion']
        entry = groups[row['file']].setdefault(key, {'rule_id': key,
                    'rule_name': row.get('rule_name') or key, 'finding_count': 0})
        entry['finding_count'] += row['finding_count']
    results = []
    for filename in requested:
        rules = groups.get(filename, {})
        if not rules:
            results.append({'file': filename, 'status': 'skipped', 'tasks': 0, 'findings': 0,
                            'message': 'No remaining human findings in this selection.'})
            continue
        assigned, findings, seen = 0, 0, set()
        try:
            # Existing terminal rows must not have their count changed by queue seeding.
            existing = [q for q in store.list_hitl_queue(scan_id=scan_id, owner=owner,
                                                        include_superseded=True) if q['file'] == filename]
            existing_rules = {criterion(q.get('rule_id')) for q in existing}
            missing = [r for sc, r in rules.items() if sc not in existing_rules]
            if missing:
                store.queue_hitl_review_for_file(scan_id, filename, missing)
            candidates = store.list_hitl_queue(scan_id=scan_id, owner=owner)
            for item in candidates:
                sc = criterion(item.get('rule_id'))
                if item['file'] != filename or sc not in rules or item.get('status') != 'pending':
                    continue
                # assign_hitl_item is intentionally unconditional for its single-item route.
                # This bulk path must preserve a decision made concurrently with the preview.
                with store._db.cursor() as cur:
                    store._db.execute(cur, "UPDATE hitl_queue SET assignee=%s WHERE id=%s "
                                      "AND scan_id=%s AND file=%s AND status='pending' "
                                      "AND scan_id IN (SELECT id FROM scan_runs WHERE owner_email=%s)",
                                      (assignee, item['id'], scan_id, filename, owner))
                    changed = cur.rowcount == 1
                if changed:
                    assigned += 1
                    if sc not in seen:
                        findings += rules[sc]['finding_count']
                        seen.add(sc)
            result = {'file': filename, 'status': 'assigned' if assigned else 'skipped',
                      'tasks': assigned, 'findings': findings}
            if not assigned:
                result['message'] = 'Matching work is already under review or has a recorded decision.'
            results.append(result)
        except Exception:
            # Earlier per-file assignments remain durable; disclose partial progress for retry.
            results.append({'file': filename, 'status': 'error', 'tasks': assigned,
                            'findings': findings, 'message': 'Assignment could not finish for this file. Retry or inspect its review queue.'})
    return {'assignee': assignee, 'tasks_assigned': sum(r['tasks'] for r in results),
            'findings_assigned': sum(r['findings'] for r in results),
            'files_assigned': sum(r['tasks'] > 0 for r in results), 'results': results}


def provider_summary(ai_enabled):
    """Configuration disclosure only. Never probe a connection or serialize an adapter."""
    import ai
    import providers
    summary = {'global_ai_enabled': bool(ai_enabled)}
    try:
        text = providers.text_provider_provenance() or {
            'provider': 'ollama', 'model': ai.OLLAMA_MODEL,
            'zone': providers.zone_for_url(ai.OLLAMA_BASE_URL)}
        summary['text'] = {key: text.get(key) for key in ('provider', 'model', 'zone')}
        summary['text']['connection'] = 'not_tested'
    except Exception:
        summary['text'] = {'provider': None, 'model': None, 'connection': 'unavailable'}
    try:
        vision = providers.active_vision_provider()
        summary['vision'] = {'provider': vision.name, 'model': getattr(vision, 'model', None),
                             'zone': getattr(vision, 'zone', None), 'connection': 'not_tested'}
    except Exception:
        summary['vision'] = {'provider': None, 'model': None, 'connection': 'unavailable'}
    return summary
