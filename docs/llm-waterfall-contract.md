# Bounded LLM remediation waterfall contract

This is an **opt-in orchestration module and fixture-tested contract**, not a shipped
remediation path. It makes no network calls, alters no source document, changes no
provider setting, and has no route/worker/store wiring. Target integration deadline:
September 9, 2026, 10 a.m. Pacific. Parent owns product/UI integration; the spending
sibling owns the durable reservation ledger.

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
