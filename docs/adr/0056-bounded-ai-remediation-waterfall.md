# ADR 0056 — The bounded AI remediation waterfall: spend it once, prove it later, apply it never (yet)

**Status:** Accepted — describes what is built and running as of 2026-09-09; the
auto-application half is explicitly **not** decided here and is gated on ADR 0030 §3
**Date:** 2026-09-09
**Related:** ADR 0019 (AI provider gateway + governance), ADR 0030 (the auto-apply gate —
what evidence lets ACP write a fix), ADR 0031 (certification is gated by coverage, not
confidence), ADR 0021 (enterprise review memory / house style).
Contracts: `docs/ai-spending-budget-contract.md`, `docs/llm-waterfall-contract.md`,
`docs/second-fallback-execution.md`, `docs/remediation-live-waterfall.md`,
`docs/waterfall-impact-prd.md`. Shipped across #1881–#1910.

## Context

ACP drafts some remediation values with a language model (alt text, link text, slide
titles). Until this work, three things were true and all three were problems:

1. **Spend was unbounded and unaccounted.** A remediation run could dispatch provider
   calls with no per-run ceiling, no record of what a call was *allowed* to cost before
   it was made, and no way to tell a charge that settled from one whose outcome was
   never confirmed.
2. **A failed draft was the end of the road.** One model, one attempt. An empty or
   truncated response produced no suggestion and no second chance, and nothing recorded
   *why* it failed in a form another model could act on.
3. **Nobody could say what the AI actually contributed.** "AI helped" was a claim with
   no denominator. There was no way to answer "of the findings in this run, how many got
   a usable suggestion, from which model, and did the second model add anything the
   first did not?"

The obvious fix — call a stronger model, then a cheaper one, then a reviewer — is a
*waterfall*, and a waterfall is exactly the shape that turns an unbounded-spend problem
into an unbounded-spend problem multiplied by three. So the ledger had to come first.

## Decision

**A remediation run admits a bounded, ordered sequence of paid generation attempts
against an immutable per-run ceiling, records the lineage of every attempt, and produces
proposals that a human still has to approve.**

Five parts, each with its own contract document:

### 1. The reservation ledger owns the money (`api/ai_spending_budget.py`)

`BudgetLedger` reserves a **verified worst-case cost before dispatch**, commits a
dispatch claim durably, and settles the actual charge afterward. Amounts are integers in
millionths of a currency unit — never floats — and every conversion from a provider's
decimal price rounds **up**. Insufficient balance raises `BudgetExceeded` before any
network call.

The ordering is the point: `reserve → claim_dispatch → generate → settle`. A crash
between claim and settle leaves an *outstanding hold*, not a silent free call, and
unknown usage blocks further dispatch pending reconciliation. Schema lands additively in
store version 44.

**No cap field means a legacy unmanaged run — not free AI, and not a cap.** Explicit
`"0.00"` is managed and disables paid AI. Invalid explicit values fail closed.

### 2. The run context binds policy to a durable job (`api/ai_run_policy.py`)

`run_context(store, payload, job)` wraps the *entire* remediation handler, validates the
owner/scan/file against the durable job, and installs a `ContextVar`. Outside a managed
job there is no context and `current_run_context()` refuses. Legacy fallback and vision
calls are blocked inside managed context; only the bounded adapter may spend.

### 3. The generation chain is an ordinal, not a model list (`api/ai_generation_chain.py`)

Positions `primary`, `fallback_1`, `fallback_2` at indices 0, 1, 2, with exact
provider/model IDs frozen into the approved run policy. A later position is reachable
**only** from an eligible predecessor failure — `empty_response`, `truncated`,
`invalid_required_structure`, `incomplete_requested_content`. A model that returns a
confident wrong answer does not escalate; only an unusable one does.

Order is never inferred from model names, and a third position is never activated by
credential presence, a settings refresh, an old-job replay, or model output.

### 4. Every attempt carries immutable lineage (`api/ai_attempt_history.py`, `api/remediation_run_graph.py`)

Before dispatch, an attempt records chain version, step ID, generation position, parent
attempt, escalation reason, assessed source SHA-256, assessment revision, finding IDs,
locator, adapter ID and request ID. Completion adds `validation_outcome` without
disturbing the binding. `run_graph` reconstructs configured order, actual attempts,
parent edges and costs from retained attempts — independently of history pagination.

A retained usable output replays only on matching operation/source/finding identity and
settled spend, so **a replay never books the same charge twice**.

### 5. Reporting counts what it can prove (`docs/waterfall-impact-prd.md`)

Contribution counts are **saved proposal versions**, not fixed findings. "AI may help" is
eligibility, not predicted success. A second model being called is not evidence it
helped, and additional-suggestion credit requires recorded attempt lineage joining both
eligible predecessors. Where a measure cannot be computed the UI says **"Not yet known"**
— never zero.

This is the part most likely to erode under product pressure, and it is the part that
makes the rest defensible.

## What this ADR does NOT decide

**It does not authorize applying an AI proposal without a person.**
`api/remediation_impact.py:6-7` sets `ai_automatic: False` with the reason "Automatic
application of AI proposals is not supported by this execution path," and that remains
the shipped behaviour. Everything above governs how a *suggestion* is produced, priced
and explained. A human approving it is still the only thing that makes it a change.

Two separate modules are both called "the waterfall", and the distinction is
load-bearing:

| | `api/llm_remediation_waterfall.py` | `api/llm_waterfall_provider.py` |
|---|---|---|
| Reached in production | **No** — `run_waterfall`'s only caller is `ai.run_verified_remediation`, whose only callers are tests | **Yes** — via `api/providers.py:285` |
| Independent verifier | Yes: five evidence fields, all literal `True` | None |
| Scope | `html-root-language` only | generic text proposals, `pptx-slide-title.v1` |

The first is a **design target for supervised auto-application**, fixture-tested and
deliberately unwired. The second is what ships. Reading the first as a description of
production behaviour is the specific error this table exists to prevent.

### What would let auto-application happen

ADR 0030 §3 already answers this and is not superseded: auto-apply is granted **per
criterion by verification completeness**, not by model strength or confidence. ADR 0031
adds that no model unlocks a `PARTIAL`-coverage detector. Applied to the waterfall, three
things are outstanding:

1. **An independent server-side verifier per fix family** — format-specific copy
   application, issue re-scan, content/media inventory preservation, scope comparison and
   regression check against the original. `verify_html_language` is the worked example of
   the shape; it exists for exactly one trivial family.
2. **Versioned reliability data per model/reviewer configuration and change family.**
   `api/remediation_impact_estimates.py` returns `calibration_unavailable` today. Reviewer
   agreement between two models is explicitly *not* calibration — two models sharing a
   provider and a prior can be wrong together.
3. **Exact proposal-version → source-revision verification lineage**, so an approval
   provably targets the revision it was granted against.

A threshold preference can be captured with a run. **It is not an operational
auto-approval permission**, and must not be presented as one.

## Consequences

**Good.** Spend is bounded per run and attributable per attempt. A failed draft escalates
once, for a recorded reason, against the original source rather than a damaged
intermediate. Replay is free. Reporting understates rather than overstates, and says so
when it cannot measure.

**Costs, accepted.** The ledger adds a durable write before every paid call — correctness
bought with latency. Fail-closed means a reconciliation gap stops AI for that run rather
than guessing. The honest-reporting rule guarantees the impact panel will sometimes show
"Not yet known" where a competitor shows a number.

**Sharp edge.** A qualifying scope is now offered the full three-position chain
*pre-selected* (#1907; see `docs/second-fallback-execution.md`), so a default approved run
can dispatch three paid models where it once dispatched two. The cap still binds. The
disclosure that tells the user this is the thing to protect in review — it has already
been removed once, in an open PR, in the same diff that raised the default.

## Alternatives rejected

**Cap spend at the provider account instead of per run.** Rejected: an account-level cap
cannot tell a runaway run from a large legitimate one, and it fails an entire tenant to
contain one job.

**Let the generating model report its own confidence and escalate below a threshold.**
Rejected outright. Self-reported confidence, model agreement and model-written
verification claims cannot grant approval — a model must never populate its own evidence
object or select its own verifier. This is the single hardest line in the contract and the
reason the escalation triggers are all *structural* failures (empty, truncated, malformed)
rather than semantic ones.

**Ship auto-application behind a feature flag and calibrate in production.** Rejected: the
outputs are documents released to the public. The failure mode is a confidently wrong alt
text on a published file, which is worse than no alt text because it is invisible to the
reviewer who trusted it. Calibrate first, on retained evidence, per ADR 0030 §3.
