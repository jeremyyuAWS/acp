import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

describe('#131 — refine the AI draft (shorter / more detail / regenerate)', () => {
  it('suggestFix forwards a style modifier as a query param', () => {
    const src = read('api.js')
    expect(src).toMatch(/suggestFix = \(scanId, file, ruleId, locator = null, style = null\)/)
    expect(src).toMatch(/style \? `&style=\$\{encodeURIComponent\(style\)\}` : ''/)
  })

  it('ProposalEditors offers refine buttons only once a draft exists to refine', () => {
    const src = read('ProposalEditors.jsx')
    expect(src).toMatch(/onDraft && filled && \(/)
    expect(src).toMatch(/\['shorter', 'Shorter'\], \['detailed', 'More detail'\], \['regenerate', '↻ Regenerate'\]/)
    expect(src).toMatch(/onClick=\{\(\) => onDraft\(i, k\)\}/)
  })

  it('EvidenceCard threads the style through the per-image draft call', () => {
    const src = read('EvidenceCard.jsx')
    expect(src).toMatch(/const draftInstance = async \(i, style = ''\)/)
    expect(src).toMatch(/suggestFix\(item\.scan_id, item\.file, item\.rule_id, instances\[i\]\?\.locator, style \|\| null\)/)
  })
})
