// W4 — a documented resolution lane for criteria that would otherwise dead-end.
//
// UNCHECKED (and the other automated-boundary outcomes a document reaches — GAP: a check that
// applies but isn't built yet; AT: only provable by assistive-technology interaction) have no
// onward path in the flow. ACP makes no automated assertion and offers no action, so the box sits
// unresolved forever: a customer who verified the criterion out-of-band (a manual audit, a
// screen-reader pass), or whose engagement legitimately excludes it, has nowhere to record that.
//
// This module is the small, honest model for that. It reuses the SAME "a human records an
// immutable decision" shape as the confirm-the-pass lane (confidence.js /
// accessibility_status.confirm_review_criterion) rather than inventing a parallel outcome system:
//
//   • ATTESTED      — a recorded human claim that the criterion conforms, verified OUTSIDE ACP's
//                     automated checks. It resolves the item toward conformance, but as a human
//                     attestation — never re-labelled an ACP-certified automated pass.
//   • OUT_OF_SCOPE  — a recorded decision that the criterion is not part of this engagement's
//                     certification target. It leaves the in-scope denominator (with its reason on
//                     the record) instead of sitting as an unresolved gap.
//
// Both REQUIRE a reason: an undocumented attestation is exactly the unaccountable state this lane
// exists to prevent (ADR 0016 — nothing resolved without evidence a human can audit later).

export const DISPOSITION = {
  ATTESTED: {
    key: 'attested',
    label: 'Manually attested',
    verb: 'Attest conformance',
    short: 'attested',
    glyph: '✓',
    // Resolves toward conformance — a human attestation, not an automated pass.
    resolvesConformance: true,
  },
  OUT_OF_SCOPE: {
    key: 'out_of_scope',
    label: 'Out of scope',
    verb: 'Mark out of scope',
    short: 'out of scope',
    glyph: '—',
    // Leaves the in-scope denominator; the reason is recorded on the certification record.
    resolvesConformance: false,
  },
}

export const DISPOSITION_KEYS = Object.values(DISPOSITION).map((d) => d.key)

// The outcomes that otherwise dead-end and are the customer's to dispose.
//
//   HUMAN is deliberately EXCLUDED — it already has an onward path (the HITL review queue), and an
//   attest/exclude shortcut there would undercut the very review it routes to.
//   NA ("cannot exist in this file type") is already a resolved non-applicable verdict, not a
//   dead-end.
//
// So: the not-auto-checked outcome plus the two roadmap/interaction boundaries.
export const DISPOSITIONABLE_OUTCOMES = new Set(['UNCHECKED', 'GAP', 'AT'])

export function isDispositionable(outcome) {
  return DISPOSITIONABLE_OUTCOMES.has(outcome)
}

export function dispositionByKey(key) {
  return Object.values(DISPOSITION).find((d) => d.key === key) || null
}

// Normalize a raw disposition record (as persisted / echoed by the API) into the shape the UI and
// the report consume, or null if it isn't a recognised disposition WITH a reason. The reason is
// required — see the module note.
export function normalizeDisposition(raw) {
  if (!raw) return null
  const meta = dispositionByKey(raw.kind)
  const reason = (raw.reason || '').trim()
  if (!meta || !reason) return null
  return { kind: meta.key, reason, actor: raw.actor || null, at: raw.at || null }
}

// True once a disposition resolves the dead-end — attested resolves toward conformance,
// out-of-scope resolves by leaving the scope. Either way the box is no longer terminal.
export function isResolved(raw) {
  return normalizeDisposition(raw) != null
}

// One-line label for a recorded disposition, e.g. "Manually attested — verified with NVDA".
export function dispositionLabel(raw) {
  const d = normalizeDisposition(raw)
  if (!d) return ''
  return `${dispositionByKey(d.kind).label} — ${d.reason}`
}
