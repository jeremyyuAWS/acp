"""Explicit, expiring standard-price text profiles. Never activates a provider."""
from copy import deepcopy
from datetime import datetime, timezone

VERIFIED_UNTIL = int(datetime(2026, 10, 8, tzinfo=timezone.utc).timestamp())
RECOMMENDED_RUN_BUDGET_USD = '25.00'


def _spec(provider, model, input_price, output_price, context, output_limit, source):
    return dict(provider=provider, model=model, pricing_ref=f'{source}#verified-2026-09-08',
                input_usd_per_million=input_price, output_usd_per_million=output_price,
                context_token_limit=context, output_token_limit=output_limit,
                verified_until=VERIFIED_UNTIL, timeout_seconds=60)


# Standard global first-party pricing, text only. Reserve full provider context
# ceilings as required by StrictTextGenerator; these are NOT prompt estimates.
# Sources also record snapshot IDs and context/output ceilings.
PROFILES = {
    'openai-balanced': [
        _spec('openai', 'gpt-4.1-mini-2025-04-14', '0.40', '1.60', 1047576, 512,
              'https://developers.openai.com/api/docs/models/gpt-4.1-mini'),
        _spec('openai', 'gpt-4.1-2025-04-14', '2.00', '8.00', 1047576, 1024,
              'https://developers.openai.com/api/docs/models/gpt-4.1'),
    ],
    'anthropic-balanced': [
        _spec('anthropic', 'claude-haiku-4-5-20251001', '1.00', '5.00', 200000, 512,
              'https://platform.claude.com/docs/en/about-claude/pricing'),
        _spec('anthropic', 'claude-sonnet-5', '2.00', '10.00', 1000000, 1024,
              'https://platform.claude.com/docs/en/about-claude/pricing'),
    ],
}

# Mixed-provider chain. Both first-party keys are configured, so escalate ACROSS
# providers cheapest-first by reserved maximum cost:
#   claude-haiku-4-5  0.20256 USD  ->  gpt-4.1-mini  0.4198496 USD
# Every step is a deepcopy of a spec already verified above, so this profile makes
# no new pricing/limit claim of its own; changing a price there changes it here.
#
# NOTE: llm_waterfall_provider.StrictTextGenerator currently requires every spec to
# match providers.active_text_provider(), so dispatching this chain raises
# "all models must use the owner-selected text provider" until that governance rule
# is widened. The catalog entry is deliberately ahead of the transport.
PROFILES['mixed-balanced'] = [
    deepcopy(PROFILES['anthropic-balanced'][0]),   # claude-haiku-4-5-20251001
    deepcopy(PROFILES['openai-balanced'][0]),      # gpt-4.1-mini-2025-04-14
]


# Optional catalog candidate; never part of an old run's implicit two positions.
# Verified 2026-09-09 from first-party model limits/pricing. No paid probe.
SECOND_FALLBACK = {
    'anthropic-balanced': {**_spec('anthropic', 'claude-opus-5', '5.00', '25.00',
        1000000, 1024, 'https://platform.claude.com/docs/en/models/opus-5/overview'),
        'plain_text_only': True},
}

# Third step for the mixed chain: claude-sonnet-5, reused verbatim from
# anthropic-balanced (2.01024 USD reserved, still cheapest-first). No new claim.
SECOND_FALLBACK['mixed-balanced'] = deepcopy(PROFILES['anthropic-balanced'][1])

# There is no SECOND_FALLBACK entry for 'openai-balanced': the only OpenAI specs
# verified in this file are gpt-4.1-mini and gpt-4.1, and both are already the two
# steps of that chain. A third step would duplicate a model ID (rejected by
# StrictTextGenerator) or require a spec nobody has verified here yet.


def model_config(profile: str, *, include_second_fallback: bool = False) -> list[dict]:
    if profile not in PROFILES:
        raise ValueError('unknown bounded text profile')
    selected = deepcopy(PROFILES[profile])
    if include_second_fallback and profile in SECOND_FALLBACK:
        selected.append(deepcopy(SECOND_FALLBACK[profile]))
    return selected
