# Second fallback execution contract

A third generation position is opt-in through the approved immutable
`remediation_impact_policy.generation_chain` (version 1). The ordered enabled text
steps are `primary`, `fallback_1`, `fallback_2`, with positions 0, 1, 2 and exact
provider/model IDs. Two-position selections are also supported. Omission keeps
legacy two-position behavior even when the server catalog contains three models.
Review and final review remain separately bounded purposes, outside this ordinal.

All selected positions must match the current verified server catalog and the
owner-selected provider. A third model is never activated by credential presence,
settings refresh, old-job replay, model output, or a graph read. Plan capabilities
expose only verified model options; unavailable configuration has an explicit
reason. All positions share the existing atomic run spending ledger. A paid
request is dispatched once; only confirmed pre-dispatch releases can use the
existing finite 16-identity retry budget. Unknown usage blocks further dispatch
pending reconciliation. Refusal, overrun, missing permission, cancellation, stale
source, and missing exact adapter evidence stop the chain.

The initial supported three-position adapter is `pptx-slide-title.v1`: exactly
one empty title in a PPTX file and one matching immutable assessed 2.4.6 finding.
The adapter checks the actual file bytes against the assessed-source binding and
validates a plain 3–8 word title, at most 90 characters, without placeholders or
structural markup. This is usability evidence for a proposal, never semantic
correctness, approval, or verified accessibility. Ambiguous multiple-title files
and all other generation adapters remain unavailable for the third-position
path. Separate supported files can each receive their own proposal; already
usable proposals are replayed, never redrafted or merged with conflicting values.

Before dispatch, existing history JSON retains immutable `execution` metadata:
chain version, stable step ID, generation position, parent attempt, explicit
escalation reason, assessed source SHA-256, assessment revision, finding IDs,
locator, adapter ID and request ID. Completion preserves that binding and adds
`validation_outcome`. Eligible escalation codes are `empty_response`, `truncated`,
`invalid_required_structure`, and `incomplete_requested_content`. A retained usable
output is replayable only with matching operation/source/finding identity and
settled spend. Both eligible predecessors are required for second-fallback credit.
No schema migration or raw-worklog modification is needed.

The existing contribution feed adds `fallback_2_ai` and
`fallback_2_additional_findings`. Retries and proposal revisions do not increase
counts, and missing parent/source/finding/proposal joins remain unavailable.
The waterfall adds `run_graph` (`remediation-run-graph.v1`), computed from all
retained scoped attempts and review receipts independently of history pagination.
It reports configured order, actual attempts, purpose, explicit parent edges,
source membership, costs and coverage. Legacy order is not guessed from model
names. Historical dispatch alone is not proof of live work: without an exact
worker lease link, `in_flight` is false and state is `outcome_unknown`.

Synthetic tests exercise the real slide proposer, managed transport, ledger,
recording, trace linkage, proposal capture and graph: two files produce two
second-fallback contributions and replay without another request or charge.
They also cover stops, unknown usage, budget contention, restart after two settled
unusable outputs, metadata immutability and owner isolation. No paid calls or
customer publication are part of these tests. Production enablement remains a
separate explicit per-run selection with a verified third model configuration.

## Optional Anthropic catalog candidate

The existing `anthropic-balanced` implicit profile remains Haiku 4.5 then Sonnet 5.
Its optional third catalog candidate is `claude-opus-5`, with a 1,000,000-token
context reservation, 1,024 output-token request cap, standard input/output rates
of $5/$25 per million tokens, and the existing October 8 snapshot expiry. Limits
and pricing were checked September 9, 2026 against the official
[model reference](https://platform.claude.com/docs/en/models/opus-5/overview) and
[pricing](https://platform.claude.com/docs/en/about-claude/pricing). The documented
[text-only request configuration](https://platform.claude.com/docs/en/models/opus-5/migration-guide)
uses `thinking.type=disabled` with `output_config.effort=high`; no provider fallback
or refusal-override option is sent. Invalid visible markup still fails validation.

This is verified server configuration, not proof that a particular account has
model access. Catalog rows expose `access_verified:false` and explain that no
account probe was performed. Provider 401/403 yields `provider_access_denied`,
blocks further attempts and retains unknown exposure for reconciliation. No
paid capability probe, credential change or accepted-run expansion is performed.
