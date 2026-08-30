// ADR 0021 §E · the "house style applied" chip — what the org's review memory asked the model
// for, read straight off the /ai/suggest draft response that used it.
//
// WHY THIS EXISTS AT ALL. Review memory changes the PROMPT behind a draft a human is about to
// certify. ADR 0021 is explicit that the influence must never be a hidden hand: "A draft shaped
// by memory says so, on the card, expandable to the exact guidance and (for derived rules) the
// evidence that justified it." The backend has emitted a COUNT (`house_style_applied`) since
// stage 1 and nothing consumed it; a count is not expandable into anything, so the response now
// also carries the rules themselves (`house_style`) and this reads them back.
//
// THE RULES ARE THE PROMPT'S OWN, NOT A SECOND LOOKUP. `api/routes/ai.py` builds both the
// injected guidance and this list from one `store.memory_applied_rules` call, so the chip is a
// report of what the model was actually asked. A chip assembled from an independent query could
// drift from the prompt and quietly claim a rule that never reached the model — worse than
// showing nothing, because a reviewer would have no way to notice.
//
// EVIDENCE IS THE ROW'S OWN COUNT. An accepted derived rule keeps `kind: 'derived'` and the
// `evidence` JSON that justified it (acceptance flips status, not kind). The chip quotes those
// counts and computes nothing — no percentage, no confidence, no "strong signal" (ADR 0016).
// Deliberately shares `evidenceLine` with the Settings panel rather than re-deriving the
// sentence: one wording for one fact, in both places a reviewer might read it.
import { evidenceLine } from './reviewMemory.js'

const KIND_LABEL = { style: 'House style', glossary: 'Glossary', derived: 'From your reviewers' }

/**
 * The chip model for a /ai/suggest response, or null when the draft was NOT shaped by memory.
 *
 * Null is the overwhelmingly common case and the important one: `ACP_REVIEW_MEMORY` defaults
 * OFF, and with the flag off (or no active rules, or no org) the backend attaches nothing,
 * because the prompt was byte-for-byte the pre-memory one. No chip means no influence — that
 * equivalence is the whole contract, so this never invents a chip from a bare count.
 */
export function houseStyleFromDraft(resp) {
  const raw = resp && Array.isArray(resp.house_style) ? resp.house_style : null
  if (!raw || raw.length === 0) return null

  const rules = raw
    .map((r) => {
      const guidance = String(r?.guidance || '').trim()
      if (!guidance) return null            // a rule with no text shaped nothing worth naming
      const kind = String(r?.kind || '')
      return {
        id: r?.id || null,
        kind,
        kindLabel: KIND_LABEL[kind] || 'House style',
        guidance,
        // null scope means "every criterion / every format" — the same wording the Settings
        // panel uses, so the two surfaces describe one rule identically.
        ruleId: r?.rule_id || null,
        format: r?.format || null,
        evidence: evidenceLine(r?.evidence),
        // A derived rule whose evidence cannot be read: say so rather than render a confident
        // blank line. Only a `derived` row is expected to carry evidence at all, so an
        // unreadable one on an authored rule is not a defect and is not flagged.
        evidenceMissing: kind === 'derived' && !!r?.evidence && evidenceLine(r?.evidence) === null,
      }
    })
    .filter(Boolean)

  if (rules.length === 0) return null

  return {
    rules,
    count: rules.length,
    // The chip's own face. Says how many rules and that they came from this org's memory; the
    // guidance itself is one disclosure away, never summarised into a claim here.
    label: `House style applied · ${rules.length} rule${rules.length === 1 ? '' : 's'}`,
  }
}
