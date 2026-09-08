# Higher-quality text drafts with a bounded run budget

Prepared September 8, 2026 on top of the spending/provider/worker integration
at `ffa9e42e`. This extension is not a production deployment or a paid model evaluation.

Use a **$25 metered-provider cap per remediation execution**, keeping rules at 2
and AI at 1 (Draft for review). This replaces the proposed $0.0001-per-call target
for this profile. It does not override an existing run's immutable cap, change
owner defaults automatically, authorize another provider, or cover infrastructure.
Concurrent runs each have their own cap; this is not an account-wide daily limit.

Prepare the non-secret settings with:

```
python scripts/prepare_ai_profile.py --profile anthropic-balanced
python scripts/prepare_ai_profile.py --profile openai-balanced
```

Select ONE profile matching the existing enabled provider. Set the printed
`ACP_BOUNDED_TEXT_PROFILE` environment value on the worker and save the printed
future-run policy through the existing owner-scoped revision-checked policy route.
The script only prints a proposal. A configured `ACP_BOUNDED_TEXT_MODELS_JSON`
always takes precedence, including invalid custom config (no silent fallback).
Without either setting, bounded text still refuses dispatch.

| Profile | First model | Fallback | Output limits |
|---|---|---|---|
| openai-balanced | gpt-4.1-mini-2025-04-14 | gpt-4.1-2025-04-14 | 512 / 1,024 |
| anthropic-balanced | claude-haiku-4-5-20251001 | claude-sonnet-5 | 512 / 1,024 |

The OpenAI profile uses non-reasoning models supported by the existing text
transport. The Anthropic profile does not request extended/adaptive thinking;
the strict transport supports plain text responses only.

Standard global first-party input/output USD per million tokens:
OpenAI mini 0.40/1.60, GPT-4.1 2/8, Haiku 1/5, Sonnet 5 2/10.
Verified against [OpenAI mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini),
[GPT-4.1](https://developers.openai.com/api/docs/models/gpt-4.1),
[Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing), and
[Anthropic model limits and IDs](https://platform.claude.com/docs/en/models/overview).
Snapshots expire October 8, 2026 UTC; re-verify the contract before renewal.
Regional premiums, tools, images and cached usage are not supported by these
profiles. The existing strict transport blocks unexpected billing dimensions.

The ledger reserves each model's FULL context ceiling plus maximum output before
dispatch: about $0.42/$2.10 for OpenAI and $0.20/$2.01 for Anthropic. These are
conservative holds, not expected request costs. Settlement releases unused funds.
Low remaining balance or many concurrent holds can defer work even when its likely
cost is small. Never substitute an estimated short prompt for the verified ceiling.

Only an empty or token-truncated, fully accounted response tries model two.
Refusals stop without model shopping. Unknown usage/transport failures retain the
hold and stop; every extra attempt needs its own ledger reservation. Nonempty
complete drafts still require human approval, and no model-written confidence
or agreement grants conformance. This is not semantic quality grading.

Evaluate on representative findings before claiming more automation: compare
reviewer acceptance, edit rate, review time and total settled cost per accepted
fix against the existing model. This change does not add PDF write-back, vision
pricing, or enable the currently unsupported automatic-AI execution levels.
