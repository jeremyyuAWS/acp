# ADR 0026 — Accessibility Status: the authoritative cross-scope status contract

**Status:** Proposed (2026-07-15)

## Context

ACP's strategy has shifted from *"improve WCAG detection"* to *"be the easiest product to trust."*
The two-axis assessment model (ADR 0023) and the render-gated measurements (ADR 0024/0025) gave every
criterion an honest outcome, but that truth is currently scattered across the drawer's finding rows, a
client-side "Document Health" header (computed in `FileDrawer.jsx`), and the coverage matrix — three
surfaces that can drift, none of which answers, in one glance, *"where is this document and what do I
do next?"*

The customer never buys detectors; they buy **confidence**. The single highest-ROI trust surface is a
status card a reviewer reads first on opening any file. But a card is only worth building once, so it
must be the **one authoritative status surface** — identical for a **File, Folder, Scan, Estate, and
Organization**, differing only in aggregation. That makes it the product's primary navigation and
trust anchor, not another dashboard widget.

Two distinct questions have been conflated and must be separated:

- **Assessment Coverage** — *"Did ACP look?"* Every applicable criterion ACP had a method for.
- **Accessibility Status** — *"Is it ready?"* The readiness decision.

Coverage can be 20/20 while Status is "Ready after 2 reviews" — that nuance is exactly what auditors
and executives need, and today the UI can't express it.

## Decision

Define **Accessibility Status** as a single derived-at-read contract, produced by one backend function
`accessibility_status(scope, id, owner)` (scope ∈ `file | folder | scan | estate | org`) and rendered by
one frontend component `<AccessibilityStatus scope=… id=… />`. It composes the EXISTING sources
(`get_certification_facts`, `scan_decisions` + `hitl_queue` applied flags, `count_unapplied_approved_values`,
reviewer medians from `hitl_events`) through the SAME `_rule_outcome` the coverage matrix uses — so the
number reconciles at every scope and there is exactly one source of truth. Aggregation for the larger
scopes is summation of the per-file counts plus re-derivation of the state; no new measurement.

### The two metrics, kept separate
- **Assessment Coverage** = criteria ACP could evaluate ÷ in-scope (`20/20`, or `18/20` when some need
  manual verification). Answers "did ACP look?"
- **Accessibility Status** = the readiness state below. Answers "is it ready?"

### Vocabulary — internal rigor, plain UI labels
The internal `measured-pass ≠ certified` distinction (ADR 0016/0023) stays internal. Users see only:

| Internal outcome | UI label |
|---|---|
| deterministic pass | **Automatically Verified** |
| review approved AND applied | **Human Verified** |
| REVIEW unresolved | **Needs Review** |
| blocking FAIL | **Needs Remediation** |
| no validator / author-intent | **Not Automatically Assessable** (requires manual verification) |
| barrier can't exist in format | **Not Applicable** |
| document-level terminal state | **Ready for Certification** → **Certified** |

"Certified" is reserved for the final state (a human sign-off or a generated report) — never a
per-criterion count, and never implied by an automated pass. "Not Automatically Assessable" is framed
as a transparent limitation ("WCAG defines no objective pass/fail test for this — nothing was
skipped"), never as work ACP declined to do.

### State machine (one CTA per state)
`Assessing` (background measurements running) → `Needs Remediation` (**Start Remediation**) →
`Apply Approved Fixes` (**Apply Approved Fixes** — the approved-but-unapplied gate) →
`Ready after Review` (**Review Findings**) → `Re-validating` (post-fix re-scan in flight) →
`Ready for Certification` (**Generate Report**) → `Certified` (**Publish Certification**).

The hero owns the single, state-matched CTA and becomes the workflow launcher.

### Decision-first hierarchy
The card leads with the decision, not the numbers: status glyph + "Ready after 2 reviews" +
"18 of 20 criteria resolved" + a one-line **trust sentence** ("2 criteria still require human
verification before certification") + a segmented progress bar + the estimate + the CTA, with a
`ⓘ Why?` affordance that explains the residual (Epic 2 Explainability).

## The status model (fields → existing source)

| Field | Meaning | Source |
|---|---|---|
| `in_scope` | applicable criteria for the scope's format(s) | catalog scoped by format |
| `coverage` | criteria ACP could evaluate ÷ in_scope | `certification_facts` minus no-method gaps |
| `automatically_verified` | deterministic passes | `_rule_outcome == PASS`, auto lane |
| `human_verified` | approved **and applied** | `scan_decisions` ∩ `hitl_queue.applied` |
| `needs_review` | unresolved REVIEW | `_rule_outcome == REVIEW`, no applied decision |
| `needs_remediation` | blocking fails | `_rule_outcome == FAIL` |
| `not_automatically_assessable` | in-scope, no auto method | `not_evaluated` + human-only |
| `not_applicable` | barrier can't exist | capability = na |
| `unapplied_approved` | approved but not written | `count_unapplied_approved_values` |
| `est_review_secs` | `needs_review × median(review_ms)` | `hitl_events.review_ms`, default until enough samples |
| `state` | the state-machine value | derived |

**Invariant (test-enforced, every scope):**
`automatically_verified + human_verified + needs_review + needs_remediation + not_automatically_assessable + not_applicable == in_scope`.

## Honesty guardrails (ADR 0016, non-negotiable)
1. **Approved ≠ applied.** "Ready for Certification" requires `unapplied_approved == 0` — a promise is
   not a fix.
2. **No fabricated numbers.** No model confidence %. The estimate is labeled `~` and grounded in real
   reviewer medians; a default is shown as a default, never as precision.
3. **Coverage and Status are never conflated,** and `not_automatically_assessable` is always visible —
   never a false "20/20."
4. **Automated pass ≠ certified** internally; the UI's "Automatically Verified" makes no auditor-grade
   claim, and only a human sign-off / generated report reaches "Certified."
5. **One source of truth.** The status counts reconcile with the coverage matrix at every scope
   (reconciliation test) — the hero can never disagree with the detail.

## Blast radius / compatibility
- **Additive at the data layer** — derive-at-read, no schema change, no `/api/v1` break.
- **New runtime surface** — `GET /scans/{sid}/files/{name}/status` + `GET /status?scope=…&id=…`. New,
  not a change to an existing shape.
- **Replaces** the client-side Document Health header math (removes drift; a justified evolution, not
  an opportunistic refactor).
- **Becomes primary navigation** — this is why it warrants an ADR: the vocabulary, the coverage/status
  split, and the state machine become a core contract many surfaces depend on, so they are locked here
  before code hardens around them.

## Alternatives considered
1. **Compute the card in the frontend from existing coverage data.** Rejected — it would drift from
   `certification_facts` and duplicate the outcome logic; two sources of truth for the number
   executives read is the exact failure mode this ADR exists to prevent.
2. **Persist the status.** Rejected for v1 — derive-at-read is always-current and needs no schema/ADR
   churn; persist only if estate-scale performance later demands a cache.
3. **A per-file-only summary (no scope generalization).** Rejected — building it five times as separate
   widgets is how a product feels incoherent; one component across all scopes is the strategic point.
4. **Keep "Auto Certified" wording.** Rejected — "certified" is an auditor-grade term; using it for an
   automated pass erodes the trust the product is trying to earn.

## Target end-state
Opening any file, folder, scan, estate, or organization surfaces the same **Accessibility Status** card:
the decision first, the coverage and resolution behind it, an honest account of what needs a human, a
grounded time estimate, and one CTA that launches the next step. It is the primary navigation and trust
anchor for the whole product — the single place that answers all five customer questions
(did ACP check everything · what couldn't it determine · why · can I verify quickly · can I certify),
at every level of the estate.
