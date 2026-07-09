// Two-track (really three-track) remediation model — the single source of truth for
// "does ACP auto-apply this, does a human one-click approve an AI proposal, or does a
// human have to judge it?" The Intelligent Review Workspace and the Remediation tab both
// consult this so the deterministic ~70% is NEVER held behind a human click, while the
// AI-assisted and human lanes get the right primary action + badge.
//
// Built on confidence.js's methodForSc (the maintained WCAG tier), corrected by two
// override sets: the catalog labels some genuinely-human criteria (e.g. 2.1.1 keyboard)
// as "Tier 1 · Deterministic" because a document analyser can *detect* them — but detecting
// is not fixing, so they must never be auto-applied.

import { methodForSc } from './confidence.js'

// SCs whose fix is a semantic VALUE a human approves (AI can propose it, but it's applied
// only on approval): alt text, link purpose (link-only), name/role/value, language of parts.
const ASSISTED_SCS = new Set(['1.1.1', '2.4.4', '2.4.9', '4.1.2', '3.1.2'])
// SCs that need genuine human judgement — AI still proposes, but ACP never auto-applies:
// keyboard operability, keyboard traps, sensory references, images-of-text intent,
// non-text contrast of interactive UI.
const HUMAN_JUDGEMENT_SCS = new Set(['2.1.1', '2.1.2', '1.3.3', '1.4.5', '1.4.11'])

const TRACKS = {
  auto:     { track: 'auto',     action: 'Auto-applied',    badge: { label: 'Auto Applied',     tone: 'auto' } },
  assisted: { track: 'assisted', action: 'Approve & Apply', badge: { label: 'Review Suggested', tone: 'assisted' } },
  human:    { track: 'human',    action: 'Review & edit',   badge: { label: 'Human Required',   tone: 'human' } },
}

// { sc, outcome?, confidence? } → { track, action, badge }.
// confidence is the confidence.js shape ({ level: { key }, basis }); a Low-confidence
// deterministic result is demoted to 'assisted' so ACP never claims "auto-applied" for
// something it isn't sure cleared.
export function remediationTrack({ sc, outcome = null, confidence = null } = {}) {
  const s = (sc || '').replace(/^SC_/, '').replace(/_/g, '.')
  if (HUMAN_JUDGEMENT_SCS.has(s)) return TRACKS.human
  const method = methodForSc(s)
  if (method === 'human') return TRACKS.human
  if (ASSISTED_SCS.has(s) || method === 'heuristic') return TRACKS.assisted
  if (confidence && confidence.level && confidence.level.key === 'low') return TRACKS.assisted
  if (method === 'deterministic') return TRACKS.auto
  return TRACKS.assisted   // unknown tier → propose for approval, never silently auto-apply
}
