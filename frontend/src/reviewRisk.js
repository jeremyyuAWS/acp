import { sevOf } from './hitlMeta.js'
import { reviewType } from './reviewCard.js'

// Review risk tier + estimated effort (HITL vision roadmap #6). Composes signals the item already
// carries — the review type (deterministic confirm / AI proposal / manual authoring), the WCAG
// severity, and whether the proposal is grounded — into ONE prioritization the reviewer can sort by
// and clear quick wins first. Every input is real; the tier is a rule, not a fabricated score.
const TIERS = {
  critical: { key: 'critical', label: 'Critical', color: 'var(--error-fg)', bg: '#FBE7E2', rank: 4 },
  high:     { key: 'high',     label: 'High',     color: '#8A5A00', bg: '#FBEECB', rank: 3 },
  medium:   { key: 'medium',   label: 'Medium',   color: '#2C5209', bg: '#EDF4E3', rank: 2 },
  low:      { key: 'low',      label: 'Low',      color: '#475569', bg: '#ECEEF1', rank: 1 },
}
const UP = { low: 'medium', medium: 'high', high: 'critical', critical: 'critical' }

// Rough per-tier reviewer effort. An ESTIMATE (rendered with a ~ and the word "est"), NOT a
// confidence/accuracy number — ADR 0016 forbids fabricated scores, not honest effort hints.
const EST_SECONDS = { low: 5, medium: 30, high: 60, critical: 180 }

export function fmtEst(s) {
  return s < 60 ? `~${s}s` : `~${Math.round(s / 60)} min`
}

export function reviewRisk(item) {
  const type = reviewType(item)                 // confirm | proposal | author
  const sev = sevOf(item)                        // high | medium | low
  const grounded = !!(item?.proposals?.[0]?.grounded)
  let tier
  if (type === 'confirm') tier = 'low'           // an applied, re-validated fix — a rubber-stamp
  else if (type === 'author') tier = 'critical'  // no draft — a human writes it from scratch
  else tier = grounded ? 'medium' : 'high'       // AI proposal: grounded = fast confirm, else review
  if (sev === 'high') tier = UP[tier]            // a high-severity WCAG failure bumps the tier up
  const est = EST_SECONDS[tier]
  return {
    ...TIERS[tier],
    estSeconds: est,
    estLabel: fmtEst(est),
    // The honest inputs behind the tier — shown so it's explainable, never opaque.
    factors: { reviewType: type, severity: sev, grounded },
  }
}

// Sort comparator: most critical first (default), or quickest first (clear easy work first).
export function riskComparator(mode = 'critical') {
  return (a, b) => {
    const ra = reviewRisk(a), rb = reviewRisk(b)
    return mode === 'quick' ? ra.estSeconds - rb.estSeconds : rb.rank - ra.rank
  }
}
