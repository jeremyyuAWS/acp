import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

describe('#123 — cross-check a drafted alt against a second independent AI look', () => {
  it('validateAlt hits /ai/validate with the current alt, and returns {} on any miss', () => {
    const src = read('api.js')
    expect(src).toMatch(/validateAlt = \(scanId, file, ruleId, locator, alt\)/)
    expect(src).toMatch(/\/ai\/validate\?scan_id=/)
    expect(src).toMatch(/alt=\$\{encodeURIComponent\(alt\)\}/)
  })

  it('EvidenceCard cross-checks the CURRENT value (not a re-draft)', () => {
    const src = read('EvidenceCard.jsx')
    expect(src).toMatch(/const crossCheck = \(i\)/)
    expect(src).toMatch(/validateAlt\(item\.scan_id, item\.file, item\.rule_id, instances\[i\]\?\.locator, values\[i\]\)/)
    expect(src).toMatch(/onCrossCheck=\{crossCheck\}/)
  })

  it('ProposalEditors shows the verdict honestly — agree, or the second opinion as evidence', () => {
    const src = read('ProposalEditors.jsx')
    expect(src).toMatch(/onCrossCheck && filled/)
    expect(src).toMatch(/⚖ Cross-check/)
    // consistent → a plain confirmation; divergent → the model's independent description, no score.
    expect(src).toMatch(/verdict === 'consistent'/)
    expect(src).toMatch(/second_opinion/)
    expect(src).not.toMatch(/Cross-check[\s\S]{0,400}\d+\s*%/)   // never a percentage
  })
})
