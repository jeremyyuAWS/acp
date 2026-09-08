"""Strict, opt-in text transport for governed remediation; no default prices.

Unlike the legacy drafting adapters this never hides usage failures, retries,
aliases the selected model, or falls back to another provider.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
import os
import time
from uuid import uuid4
from typing import Callable

from llm_remediation_waterfall import Generation, Model, Request, _money


class PreDispatchRejected(ValueError):
    """Transport was never invoked; this attempt cannot incur a provider charge."""


@dataclass(frozen=True)
class TextModelSpec:
    provider: str
    model: str
    pricing_ref: str
    input_usd_per_million: str
    output_usd_per_million: str
    context_token_limit: int  # verified hard provider/model context ceiling
    output_token_limit: int
    verified_until: int  # expiry of the server-owned pricing/model-limit snapshot
    timeout_seconds: int = 30

    def validate(self, now: float) -> None:
        if self.provider not in {'openai', 'anthropic'} or not self.model.strip() or not self.pricing_ref.strip():
            raise ValueError('explicit supported provider/model/pricing reference required')
        for amount in (self.input_usd_per_million, self.output_usd_per_million):
            if _money(amount) <= 0:
                raise ValueError('verified positive token prices required')
        for value in (self.context_token_limit, self.output_token_limit, self.verified_until, self.timeout_seconds):
            if type(value) is not int or value <= 0:
                raise ValueError('positive integer model bounds and expiry required')
        if self.output_token_limit > self.context_token_limit or self.timeout_seconds > 120:
            raise ValueError('invalid output or timeout bound')
        if now >= self.verified_until:
            raise ValueError('pricing/model-limit snapshot expired')

    def maximum_cost(self) -> str:
        # Reserving the full verified context ceiling avoids an estimated tokenizer
        # count being mistaken for a verified spending bound.
        return str((Decimal(self.context_token_limit) * _money(self.input_usd_per_million)
                    + Decimal(self.output_token_limit) * _money(self.output_usd_per_million)) / 1_000_000)


class StrictTextGenerator:
    def __init__(self, specs: tuple[TextModelSpec, TextModelSpec], *,
                 post: Callable | None = None, clock: Callable = time.time,
                 provider_module=None):
        if provider_module is None:
            import providers as provider_module
        self.providers = provider_module
        self.clock = clock
        if len(specs) != 2 or specs[0].model == specs[1].model:
            raise ValueError('exactly two distinct model IDs required')
        for spec in specs:
            spec.validate(clock())
        # Reuse existing owner opt-in; mere credential presence never activates
        # a second provider or changes the global selection.
        active = self.providers.active_text_provider()
        if any(spec.provider != active for spec in specs):
            raise ValueError('both models must use the owner-selected text provider')
        if not self.providers._text_key_for(active):
            raise ValueError('selected provider credential unavailable')
        self.specs = {spec.model: spec for spec in specs}
        self.models = tuple(Model(spec.model, spec.maximum_cost()) for spec in specs)
        self.pricing_refs = {spec.model: spec.pricing_ref for spec in specs}
        if post is None:
            import httpx
            post = httpx.post
        self.post = post

    def __call__(self, model: str, request: Request) -> Generation:
        spec = self.specs[model]
        spec.validate(self.clock())
        if self.providers.active_text_provider() != spec.provider:
            raise ValueError('provider governance changed; dispatch blocked')
        if request.family != 'html-root-language' or not request.authority_ref or not request.expected_language:
            raise ValueError('supported family and authoritative language required')
        prompt = ('Return only a JSON object with the key "language". Correct the HTML root language '
                  'using the authorized language metadata. Do not infer language or rewrite content.\n'
                  + json.dumps({'authorized_language': request.expected_language,
                                'html': request.source}, ensure_ascii=True))
        result = self.generate_text(model, prompt)
        try:
            patch = json.loads(result['text'])
        except (ValueError, TypeError):
            patch = {}
        if not isinstance(patch, dict) or result['bounds_exceeded']:
            patch = {}
        return Generation(patch, result['cost_usd'], result['call_id'])

    def generate_text(self, model: str, prompt: str) -> dict:
        try:
            spec = self.specs[model]
            spec.validate(self.clock())
            if self.providers.active_text_provider() != spec.provider:
                raise ValueError('provider governance changed; dispatch blocked')
            # A conservative payload bound prevents unbounded prompt construction
            # reaching transport. Reservation still uses the full context ceiling.
            if len(prompt.encode('utf-8')) + 1024 > spec.context_token_limit:
                raise ValueError('source exceeds bounded text request size')
            key = self.providers._text_key_for(spec.provider)
            if not key:
                raise ValueError('selected provider credential unavailable')
            payload = {'model': spec.model, 'messages': [{'role': 'user', 'content': prompt}]}
            if spec.provider == 'openai':
                endpoint = self.providers._OPENAI_TEXT_BASE_URL.rstrip('/') + '/chat/completions'
                payload['max_completion_tokens'] = spec.output_token_limit
                headers = {'Authorization': f'Bearer {key}'}
            else:
                endpoint = self.providers._ANTHROPIC_MESSAGES_URL
                payload['max_tokens'] = spec.output_token_limit
                headers = {'x-api-key': key, 'anthropic-version': self.providers._ANTHROPIC_API_VERSION}
        except Exception as exc:
            raise PreDispatchRejected(str(exc) if isinstance(exc, ValueError) else "request rejected before transport") from exc
        # One request, redirects off, no SDK retry. Never log headers/body/errors.
        response = self.post(endpoint, json=payload, headers=headers,
                             timeout=spec.timeout_seconds, follow_redirects=False)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or data.get('model') != spec.model:
            raise ValueError('response model identity missing or mismatched')
        usage = data.get('usage')
        if not isinstance(usage, dict):
            raise ValueError('provider usage missing')
        if spec.provider == 'openai':
            details = usage.get('prompt_tokens_details') or {}
            output_details = usage.get('completion_tokens_details') or {}
            if (not isinstance(details, dict) or not isinstance(output_details, dict)
                    or any(details.get(k, 0) != 0 for k in ('cached_tokens', 'audio_tokens'))
                    or output_details.get('audio_tokens', 0) != 0):
                raise ValueError('unsupported cached/audio token accounting')
            input_tokens = usage.get('prompt_tokens')
            output_tokens = usage.get('completion_tokens')
            choices = data.get('choices')
            if not isinstance(choices, list) or len(choices) != 1:
                raise ValueError('expected exactly one completion')
            text = choices[0].get('message', {}).get('content')
        else:
            input_tokens = usage.get('input_tokens')
            output_tokens = usage.get('output_tokens')
            # Cache billing has separate rates. This MVP sends no cache-control;
            # unexpected cached usage must not be silently costed at the wrong rate.
            if any(usage.get(k, 0) != 0 for k in ('cache_creation_input_tokens', 'cache_read_input_tokens')):
                raise ValueError('unsupported cached token accounting')
            blocks = data.get('content')
            if not isinstance(blocks, list) or len(blocks) != 1 or blocks[0].get('type') != 'text':
                raise ValueError('expected exactly one text block')
            text = blocks[0].get('text')
        if any(type(n) is not int or n <= 0 for n in (input_tokens, output_tokens)):
            raise ValueError('positive measured token usage required')
        # Return actual cost even on a provider overrun so the ledger records and
        # blocks it. Never clamp usage to the reservation or default missing to zero.
        cost = (Decimal(input_tokens) * _money(spec.input_usd_per_million)
                + Decimal(output_tokens) * _money(spec.output_usd_per_million)) / 1_000_000
        return {'text': text if isinstance(text, str) else '',
                'cost_usd': str(cost), 'call_id': str(data.get('id') or ''),
                'model': spec.model, 'provider': spec.provider,
                'zone': self.providers.zone_for_url(endpoint),
                'prompt_tokens': input_tokens, 'completion_tokens': output_tokens,
                'bounds_exceeded': input_tokens > spec.context_token_limit or output_tokens > spec.output_token_limit}


def managed_context():
    """No implicit management for existing unbudgeted calls."""
    try:
        from ai_run_policy import current_run_context
    except ModuleNotFoundError as exc:
        if exc.name != 'ai_run_policy':
            raise
        return None
    return current_run_context(required=False)


def defer_managed(reason: str, *, kind: str = 'text', attempts=None) -> dict:
    ctx = managed_context()
    item = {'reason': reason, 'kind': kind, 'status': 'deferred',
            'attempts': attempts or []}
    if ctx is not None and hasattr(ctx, 'deferred'):
        ctx.deferred.append(item)
    return {'text': '', 'deferred': True, **item}


def managed_text_generate(prompt: str) -> dict:
    """Budgeted semantic DRAFT only; never an automatic approval decision.

    An unusable but fully accounted response can try the second model. Unknown
    usage retains its reservation and ends this call without another attempt.
    """
    from llm_remediation_waterfall import BudgetAdapter
    ctx = managed_context()
    if ctx is None:
        raise ValueError('managed text generation requires a durable run context')
    if not ctx.enabled:
        return defer_managed('ai_disabled_or_budget_zero')
    try:
        generator = configured_generator()
        budget = BudgetAdapter(ctx.ledger, ctx.owner_id, ctx.run_id, generator.pricing_refs)
    except Exception:
        return defer_managed('verified_model_pricing_unavailable')
    attempts = []
    # Durable run scope + prompt identity prevents a worker retry from buying the
    # same draft again after a later upload failure. A completed attempt without
    # a reusable result requires reconciliation, not an automatic new purchase.
    operation = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
    for index, model in enumerate(generator.models, 1):
        attempt_id = f'text:{operation}:{index}:0'
        attempt = {'attempt_id': attempt_id, 'model': model.name,
                   'max_cost_usd': model.max_cost_usd, 'status': 'reserving'}
        attempts.append(attempt)
        try:
            maximum = int((_money(model.max_cost_usd) * 1_000_000).to_integral_value(rounding=ROUND_CEILING))
            for retry in range(16):
                attempt_id = f'text:{operation}:{index}:{retry}'
                row = ctx.ledger.reserve(ctx.owner_id, ctx.run_id, attempt_id, maximum,
                                         generator.pricing_refs[model.name])
                if row['state'] != 'released':
                    break
            else:
                raise ValueError('pre-dispatch retry limit reached')
            token = attempt_id
            attempt['attempt_id'] = attempt_id
            if budget.claim_dispatch(token) is not True:
                attempt['status'] = 'existing_attempt_requires_reconciliation'
                return defer_managed('existing_draft_attempt_requires_reconciliation', attempts=attempts)
        except Exception:
            attempt['status'] = 'reservation_or_dispatch_denied'
            return defer_managed('budget_admission_denied', attempts=attempts)
        try:
            result = generator.generate_text(model.name, prompt)
        except PreDispatchRejected:
            attempt['status'] = 'rejected_before_dispatch'
            try:
                ctx.ledger.release(ctx.owner_id, ctx.run_id, token, confirmed_not_charged=True)
            except Exception:
                attempt['reconciliation_required'] = True
                return defer_managed('budget_release_failed', attempts=attempts)
            return defer_managed('request_rejected_before_dispatch', attempts=attempts)
        except Exception:
            attempt['status'] = 'usage_unknown'
            try:
                budget.mark_uncertain(token, 'provider_failure_or_unknown_usage')
            except Exception:
                attempt['reconciliation_required'] = True
            return defer_managed('provider_usage_unknown', attempts=attempts)
        attempt.update(cost_usd=result['cost_usd'], call_id=result['call_id'], status='settling')
        try:
            budget.settle(token, result['cost_usd'])
        except Exception:
            attempt['status'] = 'settlement_failed_or_breached'
            return defer_managed('budget_settlement_failed_or_breached', attempts=attempts)
        if result['bounds_exceeded']:
            attempt['status'] = 'provider_limit_exceeded'
            return defer_managed('provider_limit_exceeded', attempts=attempts)
        if result['text'].strip():
            attempt['status'] = 'drafted'
            return {**result, 'attempts': attempts, 'approval_required': True}
        attempt['status'] = 'empty_response'
    return defer_managed('attempts_exhausted', attempts=attempts)


def configured_generator() -> StrictTextGenerator:
    config = json.loads(os.environ.get('ACP_BOUNDED_TEXT_MODELS_JSON', 'null'))
    if not isinstance(config, list) or len(config) != 2:
        raise ValueError('two verified model configurations required')
    return StrictTextGenerator(tuple(TextModelSpec(**item) for item in config))


def managed_text_ready() -> bool:
    ctx = managed_context()
    if ctx is None or not ctx.enabled:
        defer_managed('ai_disabled_or_budget_zero')
        return False
    try:
        configured_generator()
    except Exception:
        defer_managed('verified_model_pricing_unavailable')
        return False
    return True
