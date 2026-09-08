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


def model_config(profile: str) -> list[dict]:
    if profile not in PROFILES:
        raise ValueError('unknown bounded text profile')
    return deepcopy(PROFILES[profile])
