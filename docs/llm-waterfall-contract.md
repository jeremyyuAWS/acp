# Bounded LLM remediation waterfall contract

This is an **opt-in orchestration module and fixture-tested contract**, not a shipped
remediation path. It makes no network calls, alters no source document, changes no
provider setting, and has no route/worker/store wiring. Parent owns product/UI
integration; the spending sibling owns the durable reservation ledger.

## Status, 2026-09-09: still unwired, and NOT the waterfall that ships

The September 9, 2026 integration deadline passed with this module unreached from any
production path. Verified by call-site trace, not by reading this file:
`run_waterfall` has exactly one caller, `api/ai.py::run_verified_remediation`, and that
function is itself called only from `tests/test_llm_waterfall_provider.py`. No route
handler and no worker reaches either.

**Two different things are called "the waterfall", and only one of them ships.** Anyone
reasoning about production behaviour from this document is reasoning about the wrong
module:

| | This contract | What actually runs |
|---|---|---|
| Entry point | `run_waterfall` (via `run_verified_remediation`) | `managed_text_generate` → `managed_generate_attempts` |
| Reached in production | **No** — tests only | Yes, via `api/providers.py:285` |
| Fix families | `html-root-language` only | generic text proposals + `pptx-slide-title.v1` |
| Independent verifier | Yes — five evidence fields, all literal `True` | **None** |
| What gates a change | `verify()`, then approval mode | A person approving the proposal |

The approval contract below — the five-field evidence object, `AUTO_FAMILIES`,
`auto_eligible` — governs **only** the left-hand column. It does not describe, constrain,
or certify the shipped path.

**Do not assume the shipped path always requires a person.** `api/remediation_impact.py`
sets `ai_automatic: False`, but that gates AI policy levels above 1 and nothing else.
`auto_approve_ai` is legal precisely at level 1, and under it the worker approves its own
AI proposals (`handlers.py:1184` → `ai_standing_approval`), applies them, and automatic
release publishes them — the release gate checks `status`, never who approved. So the
shipped path has *no* independent verifier AND an unattended mode. Its remaining check on
the draft is the second-model AI review, which ADR 0056 makes mandatory on that path.
One model's verdict on another's draft is not the evidence contract below, and must not
be described as if it were.

Treat this module as the *design target* for supervised auto-application (ADR 0056), not
as a description of current behaviour.

## API and approval

`api/llm_remediation_waterfall.py::run_waterfall` accepts a `Request`, exactly two
**distinct** `Model` configurations, and injected callbacks. Each model gets at most
one attempt. An objectively rejected candidate proceeds to the second model against
the **original source**, never a cumulatively damaged intermediate document. Every
attempt records model, idempotency key, maximum/actual cost, provider call ID when
available, candidate hash, independent evidence, stage, and reasons.

Generation supplies only `Generation(patch, cost_usd, call_id)`. Confidence, model
agreement, model-written verification claims, and extra patch fields cannot grant
approval. `verify(request, candidate)` is a trusted server verifier, independent of
generation. All five evidence fields must be literal `True`: objective,
issue_resolved, no_content_loss, no_regression, scope_preserved. A model must never
be allowed to populate this evidence object or select the verifier.

* `hitl`: even a fully verified fix ends `awaiting_approval`.
* `auto`: ends `approved` only when server `auto_eligible is True`, the fix family
  is explicitly allowlisted, and all independent checks succeed. Other fully
  verified cases require human approval.
* Unknown evidence, subjective decisions, callback errors, cost failures, and
  exhaustion end `exception`, with attempt evidence/reasons and no approvable
  candidate. Failed objective verification can try model two; uncertainty cannot.

`approved` authorizes this **specific candidate**, not broad document conformance
or publication. The host must compare the live source hash/version to the request
before applying or promoting the candidate. An approval may not silently target a
new source revision. A persisted approval must retain its verifier/policy version;
policy changes require explicit re-evaluation, not blind terminal replay.

## Narrow supported objective family

`html-root-language` is a deliberately restricted demonstration: `apply_html_language`
accepts a structured `{"language":"en"}` patch and changes only a canonical root
`<html>` or `<html lang="…">` opening tag. An optional uppercase HTML doctype and
whitespace are preserved. Other root attributes/markup variants require review.
The accepted language subset is two/three lowercase letters with an optional
uppercase two-letter region, not a complete BCP 47 validator.

`verify_html_language` requires an independently established `expected_language`
and an `authority_ref` from trusted metadata or a human decision. A nonempty
reference is a contract with the host, **not proof that a string supplied by a model
or browser client is authoritative**. The host must resolve/validate it. The
verifier checks the exact authorized substitution and requires a single parsed
HTML root. Everything except the authorized root attribute must match character
for character. No image alt meaning, reading order, prose rewriting, inferred
language, or accessibility conformance certification is approved by this helper.
Existing malformed HTML unrelated to the root is preserved; this does not certify
baseline validity. The proof is of the authorized change and preservation.

For production PDF/Office/HTML fix families, register a separately reviewed
allowlist entry only after implementing format-specific copy application,
independent issue re-scan, content/media inventory preservation, scope comparison,
and regression checks against the original. If any required check cannot resolve,
return unknown and route to an exception. Do not generalize the language helper's
proof to semantic fixes. Existing `api/ai.py::_escalate_vision` can inform generation
adapter/provider selection and tracing, but currently makes calls and records
cost after dispatch; it must not be invoked around or outside the new reservation
boundary. Its usable-alt-text gate does not implement this approval contract.

## Spending callback contract

Callbacks are trusted server code; they must be bounded by provider token/timeout
limits and must not retry internally. Otherwise the two-attempt guarantee is false.
All USD inputs are nonnegative finite decimal strings (no floating point).

1. `reserve(attempt_id, model, max_cost_usd) -> reservation_id`: atomically reserve a
   verified worst-case request bound before any model dispatch; raise if denied.
2. `claim_dispatch(reservation_id) -> bool`: must return literal `True` exactly once
   after durable commit. Reservation replay alone does not authorize generation.
3. `generate(model, request) -> Generation`: one bounded provider request with
   trustworthy actual cost. The host must enforce that the actual model matches
   the configured identity and bound, including provider-side retries.
4. `settle(reservation_id, actual_cost_usd)`: account the real cost, raise if not
   confirmed. Over-bound usage is recorded and stops approval/fallback.
5. `mark_uncertain(reservation_id, reason)`: preserve the reservation and block
   additional spending after provider failure or unknown/invalid usage. Never
   release a hold simply because a request timed out.

`BudgetAdapter(ledger, owner_id, run_id, pricing_refs)` binds the sibling ledger's
`reserve`, `claim_dispatch`, `settle`, and `mark_uncertain` methods. Its budget must
already exist in USD. It rounds USD **up** to integer microcurrency units for both
bounds and usage, and requires a nonempty server pricing reference for each model.
It accepts settlement only when the returned `state` is `settled`; a recorded
`breached` result blocks the waterfall. The adapter does not create budgets,
validate price tables, or release/reconcile reservations.

## Durability and ownership

`persist(snapshot)` must atomically durably save JSON or raise. The host owns an
exclusive per-operation lock spanning load/run/save; persist alone is not a lock.
Snapshots contain candidate content and must live in authorized document storage,
not unrestricted logs. Fingerprints bind the source, request policy, model list,
and cost bounds. This is not a signed token; persisted state is trusted server data.

Snapshots are saved before reservation, before dispatch, before generation, before
settlement, before copy/verification, and at decisions. Persistence failure
propagates and blocks subsequent effects. Terminal snapshots replay without
callbacks; an initial empty `ready` snapshot can restart. Any interrupted running
snapshot becomes a detailed reconciliation exception without duplicate calls.
This conservative recovery intentionally sacrifices automatic progress rather
than guessing whether a model call or charge happened. In-memory exceptions are
not a substitute for a functioning durable store.

There is deliberately no automatic resume of partially completed attempts. The
host must inspect attempt stage and ledger/provider records, reconcile reserved
or dispatched attempts (including reserve-success/save-failure windows), and
make a new explicitly authorized operation if needed. Cross-process concurrency
and actual database durability belong to the ledger and host operation store;
the waterfall's fixture tests verify ordering/fail-closed behavior.

## Integration still required

* Wire route/worker opt-in without changing shared provider globals. Bind tenant,
  run, source version, eligibility policy, and trusted evidence server-side.
* Store snapshots atomically under an exclusive operation lock, add recovery
  reconciliation, and persist/promote candidate copies with source-version checks.
* Adapt actual providers with verified bounds, one dispatch, bounded output and
  deadlines, accurate usage, matching model identity, and no hidden retries.
* Connect `awaiting_approval` to the existing HITL approval mechanism and
  `exception` to the exception queue, displaying attempts/evidence/cost/reasons.
* Run the spending ledger and waterfall together, then an end-to-end mocked
  worker/UI case. Fixture unit success is not evidence that production is wired.

No production changes, merges, deployments, or paid model calls are authorized in
this task.

## Claude independent verifier/evaluation handoff

No Claude command or callable Claude tool was available in this session. This
brief is prepared for a separate authorized Claude runtime; none was invoked.
The parent has supplied the user a Claude brief for independent DOCX/PPTX
verification in `api/ai_document_verification.py` and
`tests/test_ai_document_verification.py`; Claude has not been confirmed started.
Treat the HTML audit below as supplemental evaluation scope for that handoff,
not a request to create a second task or duplicate ownership.

**Scope:** independently audit `verify_html_language` and the five-field approval
contract, without editing provider settings or making paid model calls. Build an
adversarial fixture corpus and a separate test file; keep the existing module,
budget files, routes, and store under their current owners.

**Deliverables:** cases for duplicate/nested/foreign HTML roots, malformed comments,
script literals containing root tags, unusual encodings/newlines/entities, existing
language conflicts, root attribute injection, unsupported language tags, missing
or spoofed authority, truthy/nonboolean evidence, source revision changes, and
model-generated confidence claims. Distinguish unsupported/unknown from objective
failure. Exercise every persistence boundary and dispatch/settlement race using
mock providers; verify zero extra model calls after uncertainty and no source
mutation. Report false approvals first, with minimal reproductions; then coverage
limits and concrete recommendations for the next independently verifiable Office
or PDF fix family. Do not change approval policy based on model agreement.

**Acceptance:** no false auto-approvals across the adversarial corpus; every HITL
case retains human approval; exceptions preserve actionable evidence and spending
holds; clearly separate local proof from integration or production validation.


## Local validation

68 tests passed with the spending sibling module on the Python import path:
63 standalone contract cases plus five real SQLite integration cases (success,
fallback, budget denial, timeout/held reservation, and charged overrun). The
integration cases also reject redispatch when the waterfall snapshot is lost.
They automatically skip when the spending module is absent from an isolated
checkout, and run normally once both modules are integrated. No provider was
called. PostgreSQL coverage belongs to the separately owned spending ledger;
this waterfall integration run used SQLite only.

## Run-scoped provider integration

`llm_waterfall_provider.py` adds a strict real HTTP text adapter and hooks into
`providers.text_generate`. In an explicit capped run, existing text drafting
uses `ai_run_policy.current_run_context(required=False)` and its durable ledger,
owner, run, and enabled policy. Outside a managed run, legacy behavior remains
unchanged and no spending-cap claim is made.

Every managed text request reserves its verified maximum, exclusively claims
one dispatch, and settles measured token usage. An empty but accounted response
can try the second model once. Provider failures, unknown/model-mismatched usage,
unsupported cache/audio accounting, or cost failures stop without a fallback;
uncertain usage retains a blocked reservation. Semantic drafts always return
`approval_required=True`; producing nonempty text is not evidence of objective
correctness. `ctx.deferred` contains detailed reasons/attempts for the worker to
persist and display. Ledger rows durably preserve spend/attempt identity even if
the worker crashes before handling the returned draft. A worker retry uses fresh
attempt IDs and consumes the same immutable run cap.

Managed `ai.suggest_fix` cannot fall back to Ollama, and its availability gate
checks bounded text configuration rather than requiring a local Ollama model.
All vision adapters and direct legacy AI entry points defer in managed contexts
until their pricing can be bounded. Guards run before AI dispatch; no credential
is logged or included in a result. Existing vision/draft paths outside a capped
run preserve their behavior. Parent worker integration must establish the context
around the whole job and persist `ctx.deferred` when the job ends.

### Server-owned model configuration

`ACP_BOUNDED_TEXT_MODELS_JSON` is a JSON array of exactly two `TextModelSpec`
objects. This task does not populate it or invent current prices. Both models
must use the already owner-selected text provider (`openai` or `anthropic`) and
exact response model IDs, with no aliases. Required fields:

* `provider`, `model`, `pricing_ref` (auditable approved pricing snapshot).
* `input_usd_per_million`, `output_usd_per_million`: positive decimal strings.
* `context_token_limit`: verified hard provider/model context ceiling, not an
  estimate from the prompt. The full ceiling is reserved for input tokens.
* `output_token_limit`: positive integer, bounded by the context ceiling.
* `verified_until`: integer Unix expiry for the price/model-limit snapshot.
* `timeout_seconds`: optional integer, default 30, maximum 120.

The host must validate these values against the provider's actual model contract
before provisioning this server config; a caller-provided price or a nonempty
reference alone is not proof. The transport sends a single text-only request,
uses a provider-enforced output limit, disables redirects, and has no SDK retries.
It does not support tools, images, cache pricing, audio, custom pricing tiers, or
opaque gateways that alter model/usage. Such responses retain the reservation for
reconciliation. Missing, expired, unsupported, or mismatched config defers with
no model call. No free/default rate or default price-table entry is accepted.

### Verified fix facade

`ai.run_verified_remediation(request, persist=..., previous=...)` derives ledger,
owner, and run from the enabled durable context; conflicting optional identity
arguments are rejected. It uses server model config by default. It preflights
supported HTML/authority evidence, then calls the independently verified waterfall.
The parent must still construct the request's mode/eligibility from the accepted
run policy, persist snapshots under an operation lock, and compare the source
revision before candidate promotion. Unsupported Office/PDF/semantic fixes are
not licensed for automatic approval by the draft provider integration.

This change wires the provider boundary and facade; worker context establishment,
exception persistence/UI, immutable enqueue policy, and candidate promotion are
separate parent/sibling integration responsibilities. No deployment or paid API
validation was performed.

## Integrated worker status (2026-09-08)

The integration branch now establishes `ai_run_policy.run_context` around the
remediation worker, persists accepted budgets with canonical queued executions,
and records deferred provider reasons. The planner accepts a USD cap, passes it
through the sealed run policy, and displays ledger spending separately from the
forecast. Existing jobs without an explicit cap retain their legacy behavior.

Managed text drafting uses the configured two-model profile. Vision and other
unbounded paths defer rather than bypass the spending limit. Stable prompt
identities prevent purchasing the same draft again on a job retry; when a paid
result is no longer available for reuse, reconciliation is required. Confirmed
pre-dispatch rejection releases its reservation. Unknown transport outcomes do
not. These rules concern metered provider charges, not infrastructure costs.

The objective automatic-approval facade still requires a production caller with
trusted evidence and durable candidate promotion. It is not a general automatic
approval capability. Semantic drafts remain in human review; deterministic
remediation does not require configuring AI. Configure the explicitly selected
provider and `ACP_BOUNDED_TEXT_PROFILE=anthropic-balanced` (or an approved custom
model snapshot) before positive-budget managed drafts can run. The UI does not
silently adopt the profile script's suggested $25 cap.
