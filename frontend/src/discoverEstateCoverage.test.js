import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// The estate coverage funnel (discovered → assessment-eligible → remediation-eligible) is shown on the
// DISCOVER tab — where discovery happens — not only on Overview. Source-level, matching the Overview
// coverage pin: a full Discover mount needs the whole sources/files/scope stack, and one that rendered
// nothing would pass a "there is a coverage section" check by rendering nothing.
const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, 'Discover.jsx'), 'utf8')

describe('Discover shows the estate coverage funnel', () => {
  it('imports EstateCoverage and the shared funnel-progress helper', () => {
    expect(src).toMatch(/import EstateCoverage from '\.\/EstateCoverage\.jsx'/)
    expect(src).toMatch(/import \{ estateProgressFromFiles \} from '\.\/estateProgress\.js'/)
  })

  it('renders the funnel from the scan inventory, guarded so it never shows an empty section', () => {
    // Same inventory the three-denominator model is built on, and the same shared progress helper the
    // Overview funnel uses — so the two tabs can never disagree about the same estate.
    expect(src).toMatch(/scope\?\.inventory && scope\.inventory\.discovered > 0 &&/)
    expect(src).toMatch(/<EstateCoverage inventory=\{scope\.inventory\} progress=\{estateProgressFromFiles\(files\)\}/)
  })
})
