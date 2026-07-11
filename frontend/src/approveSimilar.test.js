import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

describe('#132 — approve-similar groups byte-identical images only', () => {
  it('ProposalEditors counts identical thumbs and offers "apply to N" only for real duplicates', () => {
    const src = read('ProposalEditors.jsx')
    // Grouping key is the exact thumb data URL — only byte-identical images group, never look-alikes.
    expect(src).toMatch(/dupCount\[p\.thumb\] = \(dupCount\[p\.thumb\] \|\| 0\) \+ 1/)
    // The action shows only when there's a value to copy AND a genuine duplicate to copy it to.
    expect(src).toMatch(/onApplyToSimilar && p\?\.thumb && dupCount\[p\.thumb\] > 1 && filled/)
    expect(src).toMatch(/Apply to \{dupCount\[p\.thumb\]\} identical/)
  })

  it('EvidenceCard copies the description to every instance sharing the same image', () => {
    const src = read('EvidenceCard.jsx')
    expect(src).toMatch(/const applyToSimilar = \(i\)/)
    // Copies row i's value to every instance whose thumb matches — the same image, reused.
    expect(src).toMatch(/instances\[j\]\?\.thumb === t \? prev\[i\] : x/)
    expect(src).toMatch(/onApplyToSimilar=\{applyToSimilar\}/)
  })
})
