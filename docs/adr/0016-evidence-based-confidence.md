# ADR 0016 — Evidence-based confidence signal (derived, never a fabricated %)

Status: Accepted
Date: 2026-07-09

## Context

The 2026-07-08 production data-honesty audit (commit `4fc6bc1`) removed every
fabricated confidence percentage from the real-data paths. The offending numbers —
`conf = 42 + (hash % 26)` on HITL items, the seeded `recommendFor()` % on file rec
cards, Upload's hardcoded "agent confidence 52%" — were invented; they encoded no
real signal and read as false precision on an evidence document. They were replaced
with honest escalation copy ("automated fixes ran first; this needs human
judgement"). The numeric `confidence:` field survives **only** in `sim.js`, for the
SIM demo persona, and is never shown on real data.

That left a gap: users (and reviewers, and the certification PDF) had no confidence
signal at all on real findings, even though the pipeline already produces several
genuine ones. We want the signal back — but derived from concrete evidence, never
invented.

The pipeline already carries three real signals:

1. **Rule determinism.** Every WCAG criterion is classified by `tier` in
   `frontend/src/wcagCatalog.js` (the same field the coverage table's Fix column is
   built from): Tier 1 deterministic structural/attribute checks; Tier 2 agentic-AI /
   heuristic lanes (alt text 1.1.1, link purpose 2.4.4, info-and-relationships 1.3.1,
   name/role/value 4.1.2); Tier 3 human-in-the-loop. A deterministic check that fires
   is unambiguously a real finding; a heuristic lane is a semantic approximation that
   can false-positive.
2. **Remediation verification.** `api/handlers.py` `_remediate_file` re-scans the
   fixed bytes via `_verify_residual_scs` and only credits a criterion as cleared when
   it drops out of the residual re-scan (persisted as `remediation_state = 'complete'`,
   read into `FileDrawer`'s `remediatedRuleIds`). A fix that did **not** clear is kept
   as an open FAIL routed to HITL — never shown as fixed.
3. **PII validation.** `api/pii.py` only emits a match after a validation gate: SSN
   (`_valid_ssn` allocation rules) and credit card (`_luhn`) are checksum-validated;
   email / phone / IP are regex/range only.

## Decision

Add a single, documented confidence model in `frontend/src/confidence.js` and surface
it in FileDrawer, ReviewCenter, PiiPanel, and the certification PDF.

- **Bounded enum, never a number.** Three levels — `High` / `Medium` / `Low` — each
  paired with a human-readable **`basis` string** that is ALWAYS rendered next to the
  level. No percentage is ever produced; a test asserts the model emits no `%`.
- **Derivation:**
  - `High` — a deterministic rule check, a checksum-validated PII match, or a fix that
    cleared the residual re-scan.
  - `Medium` — an AI / heuristic detection lane, a pattern-only PII match, or a fix
    applied but not yet re-scan-confirmed.
  - `Low` — a criterion that requires human judgement (routed to review with no
    automated signal).
  - An objective re-scan clear outranks the detection method; an unconfirmed fix is
    demoted to `Medium` (never blindly trusted `High`); an unknown SC defaults to
    `Medium`, never `High`, so the model never over-claims.
- **Derived at render time, NOT stored.** Confidence is a pure function of signals
  that already exist (catalog `tier`, `remediation_state`, PII type). There is no new
  database column, no new API field, and no scan-result schema change. This is why
  this ADR documents a *model*, not a stored field: the trigger in the task brief
  ("ADR if it becomes a stored field") is deliberately avoided — keeping it derived
  means it can never drift from the evidence it summarizes.

## Consequences

- Every confidence a user sees traces to a concrete signal and shows its basis, so it
  is auditable and cannot be mistaken for false precision. This is safe to put on the
  certification PDF as evidence.
- The SIM-only fabricated `confidence:` numbers in `sim.js` are untouched and remain
  demo-only — the real-data honesty guarantee from `4fc6bc1` holds.
- Because it is derived, the model stays correct for free as the pipeline evolves: a
  criterion re-tiered in the catalog, or a fix that newly clears re-scan, changes its
  confidence with no data migration.
- If a future feature needs confidence at scan time on the server (e.g. to gate
  auto-publish), it can port `confidence.js`'s pure logic to the backend against the
  same signals; only if it is then *persisted* would this ADR need a successor.
- Covered by `frontend/src/confidence.test.js` (20 cases), including an explicit "no
  fabricated percentages" assertion.
