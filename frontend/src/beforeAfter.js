import { parseContrast } from './contrastEvidence.js'

const scOf = (r) => String(r || '').replace(/^SC[_ ]?/i, '').replace(/_/g, '.').match(/^\d+\.\d+\.\d+/)?.[0] || ''
const HEADING_RE = /H(\d+)\s+to\s+H(\d+)/

// A typed before/after descriptor for the card's finding, or null (→ the card keeps its prose).
// One pattern for every rule (HITL vision: same card anatomy, no per-rule UI). Every value is REAL —
// contrast colours+ratio, the actual skipped heading levels, or the value the AI proposed — never a
// fabricated "after" (ADR 0016): when the concrete after isn't known yet, the descriptor carries
// null and the renderer shows what WILL be set, clearly framed, not an invented value.
export function beforeAfter(card) {
  const sc = card?.sc || scOf(card?.rule_id)
  const detail = card?.detail || ''
  const contrast = parseContrast(detail)
  if (contrast) return { kind: 'contrast', contrast }          // 1.4.3 / 1.4.6 → colour swatch
  if (sc === '2.4.6' || sc === '2.4.10') {                     // heading level skip → outline
    const m = HEADING_RE.exec(detail)
    if (m) {
      const a = parseInt(m[1], 10), b = parseInt(m[2], 10)
      if (a > 0 && b > a) return { kind: 'heading', before: [a, b], after: [a, a + 1] }
    }
  }
  if (sc === '3.1.1') {                                        // language of page/document → tag
    return { kind: 'lang', after: (card?.recommendation || '').trim() || null }
  }
  return null
}
