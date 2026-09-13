"""One exact Office caption retry after an independent pixel contradiction.

Transport, authority and persistence adapters remain server-owned. Unknown semantics,
scanner failures and another image's residual are never stronger-model retry evidence.
"""
from dataclasses import dataclass
from hashlib import sha256
from html import unescape
from io import BytesIO
import re
import zipfile


def presentation_supported(xml, element_index, tag, part, pixels):
    """Raw pixels prove simple facts only if Office displays them without transformation."""
    from lxml import etree
    from PIL import Image
    try:
        root = etree.fromstring(xml.encode(), etree.XMLParser(resolve_entities=False, no_network=True))
        local = 'docPr' if part.startswith('word/') else 'cNvPr'
        namespace = ('http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing' if part.startswith('word/')
                     else 'http://schemas.openxmlformats.org/presentationml/2006/main' if part.startswith('ppt/')
                     else 'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing')
        elements = [element for element in root.iter() if element.tag == '{' + namespace + '}' + local]
        element = elements[element_index]
        container = element.getparent()
        expected = {'inline', 'anchor'} if part.startswith('word/') else {'pic'}
        while container is not None and etree.QName(container).localname not in expected:
            container = container.getparent()
        if container is None:
            return False
        if any(etree.QName(a).localname in {'grpSp', 'grpSpPr', 'grpSpTree'} for a in container.iterancestors()):
            return False
        for child in container.iter():
            name = etree.QName(child).localname
            if name == 'custGeom' or (name == 'prstGeom' and child.get('prst') != 'rect'):
                return False
            if name == 'tile':
                return False
            if name == 'fillRect' and any(int(value) != 0 for value in child.attrib.values()):
                return False
            if name == 'blipFill':
                names = [etree.QName(c).localname for c in child]
                if names.count('blip') != 1 or names.count('stretch') != 1 or any(n not in {'blip', 'srcRect', 'stretch'} for n in names):
                    return False
                stretch = next(c for c in child if etree.QName(c).localname == 'stretch')
                if len(stretch) != 1 or etree.QName(stretch[0]).localname != 'fillRect':
                    return False
            if name == 'srcRect' and any(int(value) != 0 for value in child.attrib.values()):
                return False
            if name == 'xfrm' and any(child.get(key) not in (None, '0', 'false') for key in ('rot', 'flipH', 'flipV')):
                return False
            if name in {'effectLst', 'effectDag'} and len(child):
                return False
            if name == 'blip' and (child.get('cstate') not in (None, 'none', 'email', 'screen', 'print', 'hqprint') or len(child)):
                return False
        if part.startswith('word/'):
            extents = container.xpath('./*[local-name()="extent"]')
            extents += container.xpath('.//*[local-name()="xfrm"]/*[local-name()="ext"]')
        elif part.startswith('ppt/'):
            extents = container.xpath('.//*[local-name()="xfrm"]/*[local-name()="ext"]')
        else:
            anchor = container.getparent()
            if anchor is None or etree.QName(anchor).localname not in {'oneCellAnchor', 'absoluteAnchor'}:
                return False
            extents = anchor.xpath('./*[local-name()="ext"]')
            extents += container.xpath('.//*[local-name()="xfrm"]/*[local-name()="ext"]')
        if not extents:
            return False
        with Image.open(BytesIO(pixels)) as image:
            width, height = image.size
        # Ignore <=1 EMU rounding; a shape-preserving aspect ratio is otherwise exact.
        return all(int(extent.get('cx', '0')) > 0 and int(extent.get('cy', '0')) > 0
                   and abs(int(extent.get('cx')) * height - int(extent.get('cy')) * width) <= max(width, height)
                   for extent in extents)
    except (ValueError, IndexError, etree.XMLSyntaxError, OSError):
        return False


def image_target(data, locator):
    from apply_alt import parse_locator, resolve_target
    from formats.office.images import ALT_TARGETS
    from remediate_office import _image_bytes_for
    parsed = parse_locator(locator)
    if not parsed or len(data) > 8 * 1024 * 1024:
        return None
    part, fragment = parsed
    with zipfile.ZipFile(BytesIO(data)) as package:
        if sum(i.file_size for i in package.infolist()) > 32 * 1024 * 1024:
            return None
        entries = {i.filename: package.read(i) for i in package.infolist()}
    for pattern, tag, wrapper, _ in ALT_TARGETS:
        if not pattern.match(part):
            continue
        xml = entries.get(part, b'').decode('utf-8')
        elements = list(re.finditer(rf'<{tag}\b([^>]*?)(/?)>', xml))
        named = [m for m in elements if re.search(r'\bname="([^"]*)"', m[1])
                 and unescape(re.search(r'\bname="([^"]*)"', m[1])[1]) == fragment]
        if len(named) > 1:
            return None
        offset = resolve_target(xml, tag, fragment)
        element = next((m for m in elements if m.start() == offset), None)
        if not element:
            return None
        spans = ([m.span() for m in re.finditer(rf'<{wrapper}[ >].*?</{wrapper}>', xml, re.S)]
                 if wrapper else None)
        found = _image_bytes_for(xml, element, tag, spans, entries, part)
        if not found or not presentation_supported(xml, elements.index(element), tag, part, found[1]):
            return None
        descr = re.search(r'\bdescr="([^"]*)"', element[1])
        return (unescape(descr[1]) if descr else '', found[1]) if found else None
    return None


def retry_caption(*, original, failed, locator, written_caption, baseline, failed_check,
                  validate, generate, persist, archive, current, intent):
    """Apply only an independently approved alternative; never credit the original draft.

    persist commits an immutable intent/audit or raises. current must recheck frozen source,
    active standing approval and cancellation. generate returns settled managed usage only.
    Actual verifier callback in intent is server-owned and receives the written Office bytes.
    """
    from apply_alt import apply_alt_text
    from unverified_changes import structurally_readable
    if (not baseline.ok or not failed_check.ok or not failed_check.cleared({'1.1.1'})
            or failed_check.residual - baseline.residual):
        return None
    try:
        target = image_target(failed, locator)
        original_target = image_target(original, locator)
    except (ValueError, KeyError, zipfile.BadZipFile, UnicodeError):
        return None
    if not target or not original_target or target[0] != written_caption or target[1] != original_target[1]:
        return None
    first_validation = validate(written_caption, target[1])
    if (first_validation.get('status') != 'rejected'
            or 'pixel_shape_or_color_contradiction' not in first_validation.get('reason_codes', [])):
        return None
    if not current():
        return None
    proof = {k: v for k, v in intent.items() if k != 'verify'}
    proof.update(locator=locator, previous_artifact_sha256=sha256(original).hexdigest(),
                 failed_artifact_sha256=sha256(failed).hexdigest(),
                 pixel_sha256=sha256(target[1]).hexdigest(), original_caption=written_caption,
                 failure_validation=first_validation)
    # Archive the actually failed bytes before dispatch. Missing storage blocks spending.
    archived = archive(failed)
    proof['failed_artifact_url'] = archived.get('failed') if isinstance(archived, dict) else archived
    if isinstance(archived, dict):
        proof['previous_artifact_url'] = archived.get('original')
    if not proof['failed_artifact_url']:
        return None
    persist('intent', proof)
    if not current():
        persist('stopped', {**proof, 'reason': 'authorization_changed'})
        return None
    response = generate(target[1], proof)
    if response.get('deferred') or response.get('settled') is not True:
        persist('stopped', {**proof, 'reason': 'generation_not_confirmed', 'attempts': response.get('attempts', [])})
        return None
    replacement = response.get('text', '').strip()
    validation = validate(replacement, target[1])
    if validation.get('approved') is not True:
        persist('rejected', {**proof, 'reason': 'replacement_not_independently_validated', 'validation': validation})
        return None
    if not current():
        persist('stopped', {**proof, 'reason': 'authorization_changed_after_generation'})
        return None
    persist('replacement_approved', {**proof, 'replacement_caption': replacement,
        'replacement_validation': validation, 'response': response,
        'approval_identity': 'standing-caption-retry:' + proof['operation_id']})
    # The model must produce the supported independently validated caption itself.
    # Do not silently turn an unverified draft into a different canonical description.
    fixed, applied, unresolved = apply_alt_text(failed, {locator: replacement})
    if unresolved or len(applied) != 1 or not structurally_readable(failed, fixed, intent['file']):
        persist('rejected', {**proof, 'reason': 'replacement_write_failed'})
        return None
    target_after = image_target(fixed, locator)
    if not target_after or target_after != (replacement, target[1]):
        persist('rejected', {**proof, 'reason': 'replacement_readback_failed'})
        return None
    check = intent['verify'](fixed)
    if (not check.ok or not check.cleared({'1.1.1'})
            or check.residual - baseline.residual or not current()):
        persist('rejected', {**proof, 'reason': 'replacement_reassessment_failed'})
        return None
    result = {**proof, 'replacement_caption': replacement, 'replacement_validation': validation,
              'replacement_sha256': sha256(fixed).hexdigest(), 'response': response,
              'writer_identity': 'office-caption-retry:' + proof['operation_id'],
              'approval_identity': 'standing-caption-retry:' + proof['operation_id']}
    persist('validated', result)
    return fixed, check, applied, result


def settled_response(history, ctx, operation, result, next_model):
    """Provider envelopes and history IDs alone are never proof of settled usage."""
    if result.get('deferred') or not result.get('history_attempt_id'):
        return False
    rows = history.list_operation(ctx.owner_id, ctx.scan_id, ctx.run_id, operation, file=ctx.file)
    matches = [row for row in rows if row['attempt_id'] == result['history_attempt_id']
               and row['file'] == ctx.file and row['model'] == next_model
               and row['status'] == 'drafted' and row['spending_state'] == 'settled'
               and row['input_sha256'] == result.get('input_sha256')
               and (row.get('result') or {}).get('text') == result.get('text')]
    return len(matches) == 1


@dataclass(frozen=True)
class RetryAuthority:
    """Server-only dispatch capability, produced after exact contradiction/intent checks."""
    owner_id: str
    run_id: str
    scan_id: str
    file: str
    check: object


def attempt(store, **kwargs):
    """Approved-value workers restore only their exact durable original run context."""
    from ai_run_policy import optional_current_run_context, run_context
    import json
    if optional_current_run_context() is not None:
        return _attempt(store, **kwargs)
    tickets = kwargs['tickets']
    if len(tickets) != 1 or not tickets[0].get('run_id'):
        return None
    run_id = tickets[0]['run_id']
    with store._db.cursor() as cur:
        store._db.execute(cur, "SELECT id FROM jobs WHERE batch_id=%s AND scan_id=%s AND type='remediate_file' ORDER BY created_at,id", (run_id, kwargs['scan_id']))
        jobs = [store.get_job(row['id']) for row in store._db.fetchall(cur)]
    parents = [job for job in jobs if job and job.get('payload', {}).get('file') == kwargs['filename']]
    if len(parents) != 1:
        return None
    parent = parents[0]
    durable = parent['payload']
    with run_context(store, durable, parent):
        return _attempt(store, **kwargs)


def _attempt(store, *, scan_id, filename, original, failed, values, applied,
            baseline, failed_check, tickets, verify):
    """Production adapter: immutable run consent, frozen next tier and measured ledger."""
    import copy
    import json
    from types import SimpleNamespace
    from ai_run_policy import optional_current_run_context
    from ai_attempt_history import AttemptHistory
    from ai_standing_approval import authorization, _source
    from llm_waterfall_provider import configured_generator, managed_generate_attempts
    from document_wide_provider import _image_transport
    from caption_validation import validate_caption
    import blob
    if not retry_filename_supported(filename):
        return None
    ctx = optional_current_run_context()
    if (ctx is None or not ctx.enabled or ctx.scan_id != scan_id or ctx.file != filename
            or len(values) != 1 or len(applied) != 1 or len(tickets) != 1
            or ctx.policy.get('ai_review', {}).get('enabled') is True):
        return None
    locator, caption = next(iter(values.items()))
    ticket = tickets[0]
    if ticket.get('run_id') != ctx.run_id:
        return None
    if (ticket['locator'] != locator or ticket['approved_value'] != caption
            or applied[0].get('locator') != locator or applied[0].get('after') != caption):
        return None
    item = store.get_hitl_item(ticket['item_id']) or {}
    if item.get('status') != 'approved' or item.get('applied'):
        return None
    # Contradicted numeric claims require a new individual decision, not standing consent.
    if any(p.get('automatic_write_blocked') or p.get('requires_individual_review') or p.get('numeric_contradiction')
           or p.get('describable') is False for p in item.get('proposals', [])):
        return None
    with store._db.cursor() as cur:
        store._db.execute(cur, 'SELECT proposal_id FROM remediation_contribution_proposals WHERE owner_id=%s AND scan_id=%s AND run_id=%s AND proposal_id=%s',
            (ctx.owner_id, scan_id, ctx.run_id, ticket['proposal_id']))
        if not store._db.fetchone(cur):
            return None
    generator = configured_generator()
    from ai_generation_chain import normalize_chain
    from document_wide_provider import VISION_MODELS
    chain = normalize_chain(ctx.policy.get('generation_chain'))
    if (len(generator.models) < 2 or len(generator.models) < len(chain['steps'])
            or any(generator.models[i].name != step['model']
                   or generator.specs[step['model']].provider != step['provider']
                   for i, step in enumerate(chain['steps']))
            or any(generator.models[i].name not in VISION_MODELS.get(
                    generator.specs[generator.models[i].name].provider, set())
                   or generator.specs[generator.models[i].name].plain_text_only for i in (0,1))):
        return None
    previous = [row for row in AttemptHistory(ctx.ledger.db).list_run(ctx.owner_id, scan_id, ctx.run_id)
                if row['file'] == filename and row['status'] == 'drafted'
                and row['spending_state'] == 'settled'
                and ticket['model_call_id'] in row.get('trace_call_ids', [])]
    if (len(previous) != 1 or previous[0]['model'] != generator.models[0].name
            or generator.models[0].name == generator.models[1].name):
        return None
    # Current exact source/artifact and enabled override are rechecked around each effect.
    record = _source(store, ctx.owner_id, scan_id, filename, ctx.run_id)
    source_identity = {k: record.get(k) for k in ('checksum', 'source_modified', 'drive_file_id', 'drive_id', 'source_relative_path')}
    revision = authorization(store, ctx.owner_id, scan_id, ctx.run_id)
    from ai_run_approval_override import read as read_approval
    consent_revision = read_approval(store, ctx.owner_id, scan_id, ctx.run_id)['revision']
    if record['corrected_sha256'] != sha256(original).hexdigest():
        return None
    operation = sha256((ctx.owner_id + ':' + ctx.run_id + ':' + filename + ':office-caption-retry.v1').encode()).hexdigest()

    def current():
        from worker import check_cancel
        check_cancel()
        try:
            if (authorization(store, ctx.owner_id, scan_id, ctx.run_id) != revision
                    or read_approval(store, ctx.owner_id, scan_id, ctx.run_id)['revision'] != consent_revision):
                return False
            stage = store.get_stage_execution(ctx.run_id, owner=ctx.owner_id) or {}
            now = _source(store, ctx.owner_id, scan_id, filename, ctx.run_id)
            current_item = store.get_hitl_item(ticket['item_id']) or {}
            return (stage.get('is_current') and stage.get('state') in {'accepted', 'queued', 'processing', 'processing_complete', 'succeeded'}
                    and not stage.get('cancel_requested_at')
                    and now.get('corrected_sha256') == record['corrected_sha256']
                    and all(now.get(k) == v for k, v in source_identity.items())
                    and current_item.get('status') == 'approved' and not current_item.get('applied')
                    and current_item.get('decision_version') == item.get('decision_version')
                    and current_item.get('approved_value_sha256') == item.get('approved_value_sha256')
                    and current_item.get('approved_proposal_snapshot_ids') == item.get('approved_proposal_snapshot_ids')
                    and not any(p.get('automatic_write_blocked') for p in current_item.get('proposals', [])))
        except ValueError:
            return False

    def persist(action, proof):
        with store.transaction():
            if action == 'intent':
                with store._db.cursor() as cur:
                    if store._db.supports_skip_locked:
                        store._db.execute(cur, 'SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (operation,))
                    store._db.execute(cur, 'SELECT detail FROM decision_log WHERE scan_id=%s AND file=%s AND action=%s',
                                      (scan_id, filename, 'office_retry.intent'))
                    if any(json.loads(r['detail']).get('run_id') == ctx.run_id for r in store._db.fetchall(cur)):
                        raise ValueError('office_retry_already_attempted')
            if action == 'replacement_approved':
                persist_replacement_approval(store, proof)
            if action == 'intent':
                from remediation_contribution import record_writer_result
                record_writer_result(store, tickets, outcome='could_not_verify',
                    artifact_sha256=proof['failed_artifact_sha256'],
                    reference='Independent pixel/caption contradiction; original draft remains unverified',
                    writer_attempt_id='failed-caption:' + operation)
            store.log_decision('system', 'office_retry.' + action, scan_id=scan_id, file=filename,
                               rule_id='1.1.1', detail=json.dumps(proof, sort_keys=True))

    def archive(data):
        original_url = blob.upload_immutable_retry(ctx.owner_id, scan_id, filename, original, 'application/octet-stream')
        if not original_url:
            return None
        return {'original': original_url, 'failed': blob.upload_immutable_retry(ctx.owner_id, scan_id, filename, data, 'application/octet-stream')}

    def generate(pixels, proof):
        # Reuse the governed image transport's size/format/context/model allowlists.
        loc = SimpleNamespace(key=lambda: locator)
        request = SimpleNamespace(manifest=SimpleNamespace(
            findings=[SimpleNamespace(locator=loc)],
            evidence=[SimpleNamespace(kind=SimpleNamespace(value='image'), source_locator=loc,
                                      image_ref='sha256:' + sha256(pixels).hexdigest())]))
        wrapped = _image_transport(copy.copy(generator), request, {'sha256:' + sha256(pixels).hexdigest(): pixels})
        prompt = ('Describe only the visible flat shape and color in this image. The prior caption was independently contradicted. '
                  'Return one accurate concise caption, with no instructions or invented details. '
                  'Request identity: ' + operation + '. Pixel hash: ' + proof['pixel_sha256'])
        from time import perf_counter
        started = perf_counter()
        result = managed_generate_attempts(prompt, ctx, wrapped, purpose='review', tier_indices=(2,), operation_id=operation,
            verified_retry=RetryAuthority(ctx.owner_id, ctx.run_id, scan_id, filename, current))
        history = AttemptHistory(ctx.ledger.db)
        result['settled'] = settled_response(history, ctx, operation, result, generator.models[1].name)
        if result['settled']:
            call_id = store.record_ai_call(surface='office_verified_retry', provider=generator.specs[generator.models[1].name].provider,
                model=generator.models[1].name, zone='cloud', latency_ms=int((perf_counter()-started)*1000), ok=True, scan_id=scan_id, file=filename)
            history.bind_trace(ctx.owner_id, scan_id, ctx.run_id, operation, call_id, file=filename)
            rows = history.list_operation(ctx.owner_id, scan_id, ctx.run_id, operation, file=filename)
            settled = next(row for row in rows if row['attempt_id'] == result['history_attempt_id'])
            if settled['trace_call_ids'] != [call_id]:
                raise ValueError('office_retry_trace_not_exact')
            result['model_call_id'] = call_id
        return result

    return retry_caption(original=original, failed=failed, locator=locator, written_caption=caption,
        baseline=baseline, failed_check=failed_check, validate=validate_caption,
        generate=generate, persist=persist, archive=archive, current=current,
        intent={'operation_id': operation, 'owner_id': ctx.owner_id, 'run_id': ctx.run_id,
                'file': filename, 'scan_id': scan_id, 'source_revision': revision, 'consent_revision': consent_revision,
                'source_identity': source_identity, 'original_proposal_id': ticket['proposal_id'],
                'original_approval_event_id': ticket['approval_event_id'], 'item_id': ticket['item_id'],
                'next_model': generator.models[1].name, 'parent_attempt_id': previous[0]['attempt_id'],
                'verify': verify})


def retry_filename_supported(filename):
    return (isinstance(filename, str) and bool(filename) and '%' not in filename
            and '\\' not in filename and not any(part in {'.', '..', ''} for part in filename.split('/')))


def persist_replacement_approval(store, proof):
    """A distinct immutable proposal and standing approval precede the replacement write."""
    from remediation_contribution import digest, encoded, now
    owner, scan, run, file = (proof[k] for k in ('owner_id', 'scan_id', 'run_id', 'file'))
    response = proof['response']; caption = proof['replacement_caption']
    if not proof['replacement_validation'].get('approved') or not response.get('settled'):
        raise ValueError('office_retry_replacement_not_approved')
    proposal = {'locator': proof['locator'], 'before': proof['original_caption'],
                'proposed_value': caption, 'source': 'AI independently validated retry',
                'model': proof['next_model'], 'source_sha256': proof['failed_artifact_sha256'],
                'model_call_id': response['model_call_id'], 'pixel_sha256': proof['pixel_sha256'],
                'caption_validation': proof['replacement_validation'],
                'standing_consent_revision': proof['consent_revision'], 'approval_identity': proof['approval_identity']}
    proposal_hash = digest(proposal)
    identity = digest([owner, scan, run, file, proof['operation_id'], proposal_hash])
    value_hash = digest([caption]); event = proof['approval_identity']
    attempt_id = response['history_attempt_id']; call = response['model_call_id']; created = now()
    with store._db.cursor() as cur:
        db = store._db
        db.execute(cur, """INSERT INTO ai_proposal_snapshots
            (snapshot_id,owner_id,scan_id,run_id,file,rule_id,item_id,proposal_index,proposal_sha256,
             source_excerpt_sha256,attempt_id,model_call_id,proposal_json,retention,created_at)
            VALUES(%s,%s,%s,%s,%s,'1.1.1',%s,0,%s,%s,%s,%s,%s,'full',%s)
            ON CONFLICT(owner_id,run_id,item_id,proposal_index,proposal_sha256) DO NOTHING""",
            (identity, owner, scan, run, file, proof['item_id'], proposal_hash,
             digest(proof['original_caption']), attempt_id, call, encoded(proposal), created))
        db.execute(cur, """INSERT INTO hitl_events
            (id,scan_id,file,rule_id,item_id,action,edited,reviewer,created_at,model_call_id,
             proposal_snapshot_ids,source_revision,approved_value_sha256,decision_primary,final_value)
            VALUES(%s,%s,%s,'1.1.1',%s,'standing_approve',0,'system',%s,%s,%s,%s,%s,0,%s)
            ON CONFLICT(id) DO NOTHING""",
            (event, scan, file, proof['item_id'], created, call, encoded([identity]),
             proof['source_revision'], value_hash, caption))
        db.execute(cur, """SELECT * FROM remediation_contribution_proposals
            WHERE owner_id=%s AND scan_id=%s AND run_id=%s AND proposal_id=%s""",
            (owner, scan, run, proof['original_proposal_id']))
        old = db.fetchone(cur)
        if not old:
            raise ValueError('office_retry_original_contribution_missing')
        if old:
            db.execute(cur, """INSERT INTO remediation_contribution_proposals
                (owner_id,scan_id,run_id,proposal_id,proposal_sha256,source_sha256,assessment_revision,
                 file,rule_id,item_id,finding_ids_json,origin,attempt_id,operation_id,created_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'1.1.1',%s,%s,'fallback_ai',%s,%s,%s)
                ON CONFLICT(owner_id,run_id,proposal_id) DO NOTHING""",
                (owner, scan, run, identity, proposal_hash, proof['failed_artifact_sha256'],
                 proof['source_revision'], file, proof['item_id'], old['finding_ids_json'],
                 attempt_id, proof['operation_id'], created))
    return {'owner_id': owner, 'scan_id': scan, 'run_id': run, 'file': file, 'rule_id': '1.1.1',
            'item_id': proof['item_id'], 'proposal_id': identity, 'approval_event_id': event,
            'model_call_id': call, 'source_revision': proof['source_revision'],
            'approved_value_sha256': value_hash, 'actual_source_sha256': proof['failed_artifact_sha256']}


def contradicted_captions(data, actual_values):
    """Independent rejection is a verification gate even when no retry is authorized."""
    from caption_validation import validate_caption
    rejected = []
    for locator, caption in actual_values.items():
        try:
            target = image_target(data, locator)
        except (ValueError, KeyError, zipfile.BadZipFile, UnicodeError):
            continue
        if not target or target[0] != caption:
            continue
        verdict = validate_caption(caption, target[1])
        if (verdict.get('status') == 'rejected'
                and 'pixel_shape_or_color_contradiction' in verdict.get('reason_codes', [])):
            rejected.append(locator)
    return rejected
