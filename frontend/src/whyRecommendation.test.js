import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { whyRecommendation } from './reviewCard.js'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

describe('whyRecommendation — the structured reasoning chain (HITL vision #9)', () => {
  it('composes problem / detected / suggested / because from real fields', () => {
    const card = { sc: '1.1.1', problem: 'The image has no alternative text.',
                   recommendation: 'Bar chart of 2025 revenue by quarter' }
    const w = whyRecommendation(card, {
      trust: { grounding: { state: 'grounded' } },
      kind: { label: 'Bar chart' },
      ocrText: 'Revenue 2025',
    })
    expect(w.problem).toBe('The image has no alternative text.')
    // the actual OCR text is surfaced, exactly what the model read
    expect(w.detected.find((d) => /OCR/.test(d.label)).value).toContain('Revenue 2025')
    expect(w.detected.find((d) => d.label === 'Detected').value).toBe('Bar chart')
    expect(w.suggested).toBe('Bar chart of 2025 revenue by quarter')
    expect(w.because).toMatch(/^WCAG 1\.1\.1/)
    expect(w.because).toMatch(/otherwise/)          // names who is blocked
  })

  it('omits lines it has no real value for — never invents an OCR string or a draft', () => {
    const w = whyRecommendation({ sc: '1.4.3', problem: 'Text is too faint.' },
                                { trust: { grounding: { state: 'visual_only' } } })
    expect(w.suggested).toBeNull()                  // no draft → no "Suggested" line
    expect(w.detected.some((d) => /OCR/.test(d.label))).toBe(false)  // no OCR read → no OCR line
    expect(w.detected.find((d) => d.label === 'Grounding').value).toMatch(/visual interpretation/)
  })

  it('falls back to null when there is nothing to explain', () => {
    expect(whyRecommendation({}, {})).toBeNull()
  })

  it('the card renders it as a one-click "Why this recommendation?" panel, not buried prose', () => {
    const s = read('EvidenceCard.jsx')
    expect(s).toMatch(/const why = whyRecommendation\(card,/)
    expect(s).toMatch(/✨ Why this recommendation\?/)
    expect(s).toMatch(/why\.detected\.map/)
    expect(s).toMatch(/\{why\.because\}/)
  })
})
