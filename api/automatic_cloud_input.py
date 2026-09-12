"""Server-owned document input admission; no paid requests or global provider changes."""
from contextlib import contextmanager
from dataclasses import replace
from io import BytesIO
from types import MappingProxyType


def select_document_input(context, data):
    policy = dict(context.policy)
    if policy.get('cloud_input_strategy') != 'automatic' or policy.get('ai_zone') != 'any' or not context.enabled:
        return context, {'strategy': 'unchanged'}
    policy['document_wide_input_mode'] = 'extracted'
    policy['_automatic_input_selected'] = True
    decision = {'strategy': 'automatic', 'input_mode': 'extracted', 'reason': 'office_document_context'}
    selected = replace(context, policy=MappingProxyType(policy))
    if not context.file.lower().endswith('.pdf'):
        if not context.file.lower().endswith(('.docx', '.pptx', '.xlsx')):
            decision['reason'] = 'unsupported_document_format'
        return selected, decision
    try:
        from document_wide_native_pdf import validate_native_pdf
        validate_native_pdf(data)
    except ValueError as exc:
        decision['reason'] = str(exc)
        return selected, decision
    from native_pdf_quality import PROFILE_ID, configured_native_pdf_generator
    from llm_waterfall_provider import configured_generator, dispatch_endpoint
    from document_wide_provider import VISION_MODELS
    native_policy = {**policy, 'document_wide_input_mode': 'native_pdf', 'document_wide_model_profile': PROFILE_ID}
    native = replace(context, policy=MappingProxyType(native_policy))
    try:
        generator = configured_native_pdf_generator(native)
    except ValueError:
        # An authorized single-vendor configuration may still support native PDFs.
        # Credential presence alone never enables a vendor or expands governance.
        native_policy.pop('document_wide_model_profile')
        native = replace(context, policy=MappingProxyType(native_policy))
        try:
            generator = configured_generator()
        except ValueError:
            decision['reason'] = 'native_pdf_models_unavailable'
            return selected, decision
    import pypdf
    pdf = pypdf.PdfReader(BytesIO(data), strict=True)
    text_bytes = sum(len((page.extract_text() or '').encode('utf-8')) for page in pdf.pages)
    # Reserve the manifest's bounded text plus framing before choosing native input.
    allowance = text_bytes + 8192 * len(pdf.pages) + 60000 * 4 + 16384
    for model in generator.models[:2]:
        spec = generator.specs[model.name]
        endpoint = dispatch_endpoint(spec, generator.providers)
        if (spec.plain_text_only or model.name not in VISION_MODELS.get(spec.provider, set())
                or not endpoint or (spec.provider == 'openai' and not endpoint.endswith('/chat/completions'))):
            decision['reason'] = 'native_pdf_model_or_endpoint_unavailable'
            return selected, decision
        if allowance + spec.output_token_limit > spec.context_token_limit:
            decision['reason'] = 'native_pdf_context_limit'
            return selected, decision
    return native, {'strategy': 'automatic', 'input_mode': 'native_pdf', 'reason': 'supported_current_pdf',
                    'model_profile': native_policy.get('document_wide_model_profile')}


@contextmanager
def selected_document_context(context, data, *, frozen_decision=None):
    # The caller has already authenticated the durable run and checked its artifact hash.
    # Preserve ledger/run/owner identities; this derived choice is scoped to this file only.
    from ai_run_policy import _CURRENT
    if frozen_decision is None:
        selected, decision = select_document_input(context, data)
    else:
        decision = frozen_decision
        mode = decision.get('input_mode')
        profile = decision.get('model_profile')
        if (context.policy.get('cloud_input_strategy') != 'automatic' or not context.enabled
                or context.policy.get('ai_zone') != 'any' or mode not in {'native_pdf', 'extracted'}
                or (mode == 'native_pdf' and not context.file.lower().endswith('.pdf'))
                or profile not in (None, 'native-pdf-quality.v1')
                or (profile and mode != 'native_pdf')):
            raise ValueError('Invalid saved automatic input selection')
        policy = {**context.policy, '_automatic_input_selected': True, 'document_wide_input_mode': mode}
        if profile:
            policy['document_wide_model_profile'] = profile
        selected = replace(context, policy=MappingProxyType(policy))
    token = _CURRENT.set(selected)
    try:
        yield selected, decision
    finally:
        _CURRENT.reset(token)


def try_local_text_draft(prompt, context):
    """One optional local attempt only when a fresh capability already exists."""
    import time
    import ai
    from providers import zone_for_url
    if (not context.enabled or context.policy.get('ai_zone') != 'any'
            or context.policy.get('cloud_input_strategy') != 'automatic'
            or zone_for_url(ai.OLLAMA_BASE_URL) != 'local'):
        return None
    cache = ai._TAGS_CACHE
    if (not cache.get('at') or time.monotonic() - cache['at'] >= ai.OLLAMA_PROBE_TTL
            or not ai._tags_have(cache.get('tags'), ai.OLLAMA_MODEL)):
        return None
    from local_text_waterfall import generate
    def record(model, text, data, started, reason):
        return ai._trace_ai('suggest', prompt, text, started, ok=reason is None,
            provider='ollama', zone='local', model=model, cost_usd=0.0,
            prompt_tokens=data.get('prompt_eval_count'), completion_tokens=data.get('eval_count'),
            scan_id=context.scan_id, file=context.file, reason=reason, prompt_version='suggest-v1')
    result = generate(prompt, ai.OLLAMA_BASE_URL, ai.OLLAMA_MODEL,
        headers=ai._OLLAMA_HEADERS, local_only=True, on_attempt=record,
        timeout_seconds=5, max_attempts=1)
    # Untraced or trivial output is not a usable draft. Cloud remains the bounded fallback.
    return result if result and result.get('call_id') and len(result['text'].split()) >= 2 else None
