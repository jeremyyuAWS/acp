// The conformance level of a finding — one derivation, so a fourth copy does not appear.
//
// A real scan finding carries `{rule_id, wcag, severity}` and NO conformance level, so it has to be
// derived from the criterion. There are two catalogues and the order matters:
//
//   1. the rule modules (`rules/*.js`), which cover only the ~29 criteria ACP has a remediator for;
//   2. the hand-kept WCAG catalogue, which carries the correct level for every 2.1/2.2 criterion.
//
// Step 2 is the one that was missing and cost real accuracy: ACP DETECTS more than it can fix —
// 1.4.9, 1.4.6, 2.4.9 are all AAA and come from detectors with no rule module. Without the
// catalogue they defaulted to 'A' and wrongly BLOCKED conformance at an AA target. AssessRunner
// fixed that locally; `coreStats` still carries the two-step version, which is why this lives in
// its own module rather than being imported from either of them.
//
// KNOWN DIVERGENCE, stated rather than silently corrected: `coreStats.js` derives levels without
// the catalogue fallback, so for a detector-only AAA criterion it can count a finding that this
// module correctly excludes at an AA target. Aligning it would move numbers on RiskScore and the
// Assess tile, which is a change worth making deliberately and on its own, not as a side effect of
// adding a metrics module.
import { allRules } from './rules'
import { WCAG } from './wcagCatalog.js'
import { scOfWcag } from './coreStats.js'

export const RANK = { A: 1, AA: 2, AAA: 3 }

const SC_LEVEL = Object.fromEntries(allRules.map((r) => [r.meta.id, r.meta.level]))
const CATALOG_LEVEL = Object.fromEntries(WCAG.map((c) => [c.sc, c.level]))

/**
 * 'A' | 'AA' | 'AAA' for one finding.
 *
 * Explicit field (SIM sends one) → rule module → WCAG catalogue → 'A'. The final default is
 * deliberately the STRICTEST reading: an unknown criterion blocks at every target rather than
 * quietly not counting. A finding that should not have blocked is arguable; one that vanished is
 * not visible at all.
 */
export function findingLevel(x) {
  const sc = scOfWcag(x && x.wcag)
  return (x && x.level) || SC_LEVEL[sc] || CATALOG_LEVEL[sc] || 'A'
}
