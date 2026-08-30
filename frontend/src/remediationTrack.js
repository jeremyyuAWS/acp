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

// THE LANE COMES FROM THE PROVEN TABLE, NOT FROM THE SETS BELOW.
//
// capability.js mirrors api/remediation_capability.REMEDIATION verbatim, kept in lock-step by
// tests/test_capability_frontend_sync.py, and every lane in it was derived by an actual
// remediate → re-scan round trip (tests/test_remediation_capability.py). This module used to
// answer the same question from its own hand-maintained sets, and capability.js's own header
// already named the pattern: the frontend "used to carry THREE disagreeing versions of this
// fact", of which two were consolidated into it — "Both should read from here." This module was
// the third, and it was the one the review card reads for its badge and primary action.
//
// Measured before changing it, by running this module against the Python table across all 122
// in-scope pairs: 59 disagreed. 24 of those OVERSTATED — the badge said "Auto Applied" or
// "Review Suggested" for a pair the backend records as `human`, i.e. a reviewer was promised a
// fix that no lane exists to deliver (2.4.4 pdf, 2.5.3 pdf, 1.4.12 docx/pptx/pdf, 4.1.2
// xlsx/pptx, and more). The root cause is structural rather than a stale entry: the sets below
// are keyed on the CRITERION ALONE, and eleven criteria have different lanes in different
// formats — 1.4.1 is assisted on docx and human on xlsx/pptx/pdf; 2.4.4 is assisted on the
// Office formats and human on pdf. No format-blind table can be right about those.
import { CAPABILITY_FALLBACK } from './capability.js'
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

// { sc, fmt?, outcome?, confidence?, capability? } → { track, action, badge }.
//
// `fmt` is the file's extension in any case ("docx", "PDF"); `capability` is the live map from
// GET /capability, defaulting to the bundled mirror. confidence is the confidence.js shape
// ({ level: { key }, basis }); a Low-confidence result is demoted out of 'auto' so ACP never
// claims "auto-applied" for something it isn't sure cleared.
export function remediationTrack({ sc, fmt = null, outcome = null, confidence = null,
                                   capability = null } = {}) {
  const s = (sc || '').replace(/^SC_/, '').replace(/_/g, '.')
  const table = capability || CAPABILITY_FALLBACK
  const forFmt = table[String(fmt || '').toLowerCase()]

  if (forFmt) {
    // The table knows this format, so it is the answer — including by OMISSION. capability.js:
    // "A pair absent from a format's map is out of scope for that format and treated as human."
    // That is the honest reading: a criterion this format is not even assessed on certainly has
    // no fix lane, and saying "Auto Applied" about it is the overstatement measured above.
    const lane = forFmt[s] || 'human'
    if (lane === 'auto' && confidence && confidence.level && confidence.level.key === 'low') {
      return TRACKS.assisted
    }
    return TRACKS[lane] || TRACKS.assisted
  }

  // No usable format — reviewCard derives it from the filename and falls back to "DOC" when a
  // file has no extension, and callers outside the card may pass none at all. Defaulting those
  // to `human` would badge every such finding "Human Required" on no evidence, so the previous
  // criterion-only heuristic is kept for exactly this case rather than deleted.
  if (HUMAN_JUDGEMENT_SCS.has(s)) return TRACKS.human
  const method = methodForSc(s)
  if (method === 'human') return TRACKS.human
  if (ASSISTED_SCS.has(s) || method === 'heuristic') return TRACKS.assisted
  if (confidence && confidence.level && confidence.level.key === 'low') return TRACKS.assisted
  if (method === 'deterministic') return TRACKS.auto
  return TRACKS.assisted   // unknown tier → propose for approval, never silently auto-apply
}
