// Evidence-based confidence model.
//
// A GENUINE, bounded confidence signal — never a fabricated percentage. (Contrast
// sim.js, which keeps a demo-only numeric `confidence:` for the SIM persona; commit
// 4fc6bc1 removed every fabricated % from the real-data paths and replaced it with
// honest escalation copy.) This model re-introduces a confidence signal for real
// data WITHOUT inventing a number: it is a three-level enum, and every level is
// derived from — and displayed next to — a concrete signal the pipeline already
// produces.
//
// The three signals, all pre-existing:
//
//   1. Rule determinism — the WCAG catalog `tier` (wcagCatalog.js, the same field
//      the coverage table keys its Fix column off of). Tier 1 deterministic
//      structural/attribute checks are high-confidence; Tier 2 agentic-AI / heuristic
//      lanes (alt text 1.1.1, link purpose 2.4.4, info-and-relationships 1.3.1,
//      name/role/value 4.1.2) are semantic judgements → medium; Tier 3 needs a human
//      → low.
//   2. Remediation verification — a fix that CLEARED the residual re-scan
//      (api/handlers.py `_remediate_file` → `_verify_residual_scs`, persisted as
//      remediation_state 'complete' and read into FileDrawer's `remediatedRuleIds`)
//      is a verified "fixed" → high. A fix that was applied but NOT yet re-scan-
//      confirmed is only medium ("confirmation pending"). A fix that did not clear is
//      never shown as fixed at all — the backend keeps it as an open FAIL routed to
//      HITL, so it surfaces here at its detection-method confidence, not as a
//      trusted "fixed".
//   3. PII validation — a checksum-validated match (SSN allocation rules + card Luhn,
//      api/pii.py) is high; a pattern-only match (email / phone / IP) is medium.
//
// This value is DERIVED at render time, never stored — so there is no new stored
// field and no schema/ADR-for-storage burden (see docs/adr/0016). The `basis` string
// is always rendered next to the level so the signal is auditable and can never be
// mistaken for an invented score.

import { WCAG } from './wcagCatalog.js'

// Three levels, ordered. `rank` lets callers pick the weakest across a group
// (a criterion is only as trustworthy as its least-certain contributing signal).
export const CONFIDENCE = {
  HIGH:   { key: 'high',   label: 'High',   rank: 3 },
  MEDIUM: { key: 'medium', label: 'Medium', rank: 2 },
  LOW:    { key: 'low',    label: 'Low',    rank: 1 },
}

// SC → detection method, straight from the maintained catalog tier (single source
// of truth). 'deterministic' | 'heuristic' | 'human' | 'unknown'.
const _tierBySc = Object.fromEntries(WCAG.map((c) => [c.sc, c.tier || '']))
export function methodForSc(sc) {
  const tier = _tierBySc[sc] || ''
  if (tier.startsWith('Tier 1')) return 'deterministic'
  if (tier.startsWith('Tier 2')) return 'heuristic'
  if (tier.startsWith('Tier 3')) return 'human'
  return 'unknown'
}

// Confidence for one accessibility finding / criterion.
//   sc                     — bare SC id, e.g. '1.4.3'
//   verifiedCleared        — the fix cleared the residual re-scan (remediation_state
//                            'complete'): the strongest positive evidence we have.
//   reportedFixedUnverified— a fix was applied but not individually re-scan-confirmed
//                            (a whole-file remediation claimed this criterion, but no
//                            per-rule 'complete' row confirms it yet).
// Precedence: an objective re-scan clear beats everything; an unconfirmed fix is
// demoted to medium; otherwise fall back to the detection method.
// `proposal` (optional): an AI-proposed concrete fix value awaiting one-click approval
// (hitl_queue.proposals). It carries { validated, subjective }:
//   validated  — the proposal batch cleared its SC on the post-apply re-scan.
//   subjective — the value is a genuine human judgement (decorative call, sensory rewrite,
//                alt-text intent) that a re-scan can never validate.
// A proposal is never High: nothing an AI *proposed* is trusted until a human approves it.
// A subjective proposal is Low; any other proposal is Medium (validated ones note the
// re-scan evidence). This keeps the "AI proposes → human approves" lane honest — the chip
// tells the reviewer whether they are confirming validated machine work (fast) or making a
// judgement (slower), never implying the platform already decided.
// `short` is a 1–2 word label for narrow contexts (the coverage table's Confidence column);
// `basis` is the full auditable phrase, always kept in the chip's tooltip.
export function confidenceForFinding({ sc, verifiedCleared = false, reportedFixedUnverified = false, proposal = null } = {}) {
  if (verifiedCleared) return { level: CONFIDENCE.HIGH, short: 'Verified', basis: 'fix cleared on re-scan verification' }
  if (reportedFixedUnverified) return { level: CONFIDENCE.MEDIUM, short: 'Fix pending', basis: 'fix applied — re-scan confirmation pending' }
  if (proposal) {
    if (proposal.subjective) return { level: CONFIDENCE.LOW, short: 'Needs review', basis: 'AI proposal — needs human judgement' }
    if (proposal.validated) return { level: CONFIDENCE.MEDIUM, short: 'AI · validated', basis: 'AI proposal validated by re-scan — awaiting approval' }
    return { level: CONFIDENCE.MEDIUM, short: 'AI proposal', basis: 'AI proposal — approve to apply' }
  }
  switch (methodForSc(sc)) {
    case 'deterministic': return { level: CONFIDENCE.HIGH,   short: 'Deterministic', basis: 'deterministic rule check' }
    case 'heuristic':     return { level: CONFIDENCE.MEDIUM, short: 'AI-detected',    basis: 'AI / heuristic detection — semantic judgement' }
    case 'human':         return { level: CONFIDENCE.LOW,    short: 'Human',          basis: 'requires human review' }
    default:              return { level: CONFIDENCE.MEDIUM, short: 'Heuristic',      basis: 'heuristic detection' }
  }
}

// PII match confidence — checksum-validated types vs pattern-only. Mirrors the
// validation gate in api/pii.py: SSN (_valid_ssn allocation rules) and credit_card
// (_luhn) are structurally validated; email / phone / IP are regex/range only.
const _CHECKSUM_PII = new Set(['ssn', 'credit_card'])
export function confidenceForPii(type) {
  if (_CHECKSUM_PII.has(type)) return { level: CONFIDENCE.HIGH, basis: 'checksum-validated (SSN allocation / card Luhn)' }
  return { level: CONFIDENCE.MEDIUM, basis: 'pattern match — not checksum-validated' }
}

// Confidence for a WCAG coverage-table row (the per-criterion PASS/FAIL/FIXED/
// HUMAN/UNCHECKED verdict shown in FileDrawer and the certification PDF). Returns
// null for verdicts where the platform makes NO assertion (UNCHECKED / web-only),
// so those rows show no confidence rather than a misleading one.
//   sc              — bare SC id
//   outcome         — 'PASS' | 'FAIL' | 'FIXED' | 'HUMAN' | 'UNCHECKED' | 'WEB'
//   verifiedCleared — the criterion's fix cleared the residual re-scan
export function confidenceForCoverage({ sc, outcome, verifiedCleared = false } = {}) {
  if (outcome === 'UNCHECKED' || outcome === 'WEB') return null
  // A 🟡 Review verdict (ADR 0023): ACP surfaced concrete evidence of a likely issue but did
  // NOT verify conformance — a human adjudicates. Medium: the evidence is real (deterministic
  // detection) but the conformance call is a human judgement, so it is never High.
  if (outcome === 'REVIEW') return { level: CONFIDENCE.MEDIUM, short: 'Review', basis: 'ACP can’t certify this criterion — a reviewer confirms conformance' }
  // A HUMAN verdict means we deferred to a person precisely because no automated
  // signal covers it — that is low automated confidence regardless of the SC's tier.
  if (outcome === 'HUMAN') return { level: CONFIDENCE.LOW, short: 'Human', basis: 'routed to human review — no automated signal' }
  const reportedFixedUnverified = outcome === 'FIXED' && !verifiedCleared
  return confidenceForFinding({ sc, verifiedCleared, reportedFixedUnverified })
}

// Presentation helper — the CSS class for a level's chip (styles.css `.conf-*`).
export function confClass(level) {
  return `conf conf-${(level && level.key) || 'medium'}`
}
