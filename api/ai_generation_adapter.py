"""Code-owned structural validation for bounded drafting; never approval evidence."""
from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
from pathlib import Path
import json
import re

_CURRENT = ContextVar('generation_adapter', default=None)


def current_generation_adapter():
    return _CURRENT.get()


@contextmanager
def generation_adapter(context):
    token = _CURRENT.set(context)
    try:
        yield context
    finally:
        _CURRENT.reset(token)


def validate_slide_title(text):
    if not isinstance(text, str) or not text.strip():
        return 'incomplete_requested_content'
    if (text != text.strip() or len(text) > 90 or any(ord(c) < 32 or ord(c) == 127 for c in text)
            or any(c in text for c in '<>{}[]`"')
            or re.search(r'(?i)^(?:title|suggestion|here\b|sure\b|slide\s*\d|untitled|placeholder|insert\b|tbd\b|n/a\b)', text)
            or ':' in text or '\u2028' in text or '\u2029' in text):
        return 'invalid_required_structure'
    words = text.split()
    if not 3 <= len(words) <= 8:
        return 'incomplete_requested_content' if len(words) < 3 else 'invalid_required_structure'
    if not all(re.search(r'\w', word) for word in words):
        return 'invalid_required_structure'
    return None


def slide_title_context(path, locator, *, empty_count):
    """Only a sole assessed finding and sole empty title have unambiguous membership."""
    from ai_run_policy import optional_current_run_context
    from remediation_contribution import SOURCE
    ctx, source = optional_current_run_context(), SOURCE.get()
    if (empty_count != 1 or ctx is None or not getattr(ctx, 'policy', {}).get('generation_chain')
            or not source or source[:2] != (ctx.scan_id, ctx.file)):
        return None
    try:
        if sha256(Path(path).read_bytes()).hexdigest() != source[2]:
            return None
        db = ctx.ledger.db
        with db.cursor() as cur:
            db.execute(cur, 'SELECT baseline_json,snapshot_id FROM remediation_contribution_runs WHERE owner_id=%s AND scan_id=%s AND run_id=%s', (ctx.owner_id, ctx.scan_id, ctx.run_id))
            baseline = db.fetchone(cur)
        if not baseline or not baseline['snapshot_id']:
            return None
        matches = [r for r in json.loads(baseline['baseline_json']) if r['file'] == ctx.file and r['rule_id'] == '2.4.6']
        if len(matches) != 1 or not matches[0].get('finding_id'):
            return None
        return dict(adapter_id='pptx-slide-title.v1', source_sha256=source[2],
                    assessment_revision=baseline['snapshot_id'], finding_ids=[matches[0]['finding_id']],
                    locator=locator, validator=validate_slide_title)
    except (OSError, ValueError, KeyError, TypeError):
        return None
