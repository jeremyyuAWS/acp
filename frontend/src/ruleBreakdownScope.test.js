import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, 'Transparency.jsx'), 'utf8')

describe('estate "By WCAG criterion" panel — strictly the document-core 20, at/below the assessed level', () => {
  it('always scopes to the document-core 20 (no toggle)', () => {
    expect(src).toMatch(/const documentsOnly = true/)
    expect(src).not.toMatch(/setDocumentsOnly/)             // no per-panel scope toggle
    expect(src).not.toMatch(/Deva/)                         // customer name fully removed from the UI
  })

  it('evaluated rows are filtered to the assessed level and the 20-core', () => {
    expect(src).toMatch(/\(LEVEL_RANK\[r\.level\] \|\| 1\) <= targetRank && DOCUMENTS_20\.has\(r\.id\)/)
  })

  it('has a Hide-N/A toggle that collapses rows with no pass or fail result', () => {
    expect(src).toMatch(/const \[hideNA, setHideNA\] = useState\(true\)/)   // N/A hidden by default
    expect(src).toMatch(/const naCount = rules\.filter\(\(r\) => r\.pass === 0 && r\.fail === 0\)\.length/)
    expect(src).toMatch(/const shown = hideNA \? rules\.filter\(\(r\) => r\.pass > 0 \|\| r\.fail > 0\) : rules/)
    expect(src).toMatch(/Hide N\/A \(\$\{naCount\}\)/)
  })
})
