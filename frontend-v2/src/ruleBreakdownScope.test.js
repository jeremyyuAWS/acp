import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { SCOPE_SCS, OUT_OF_SCOPE_SCS, CORE_SCS, SCOPE_IS_SUBSET_OF_CORE } from './activeScope.js'

const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, 'Transparency.jsx'), 'utf8')

describe('estate "By WCAG criterion" panel — the agreed scope by default, at/below the assessed level', () => {
  it('takes its criteria list from activeScope, never from a literal in this file', () => {
    // The default is the tracked 17 now, not the agreed 14 — but the GUARD is unchanged in
    // spirit: both branches come from an imported set, never from a literal typed here.
    expect(src).toMatch(/const criteria = showAllCore \? criteriaFor\(true\) : TRACKED_17/)
    // The 14 are defined server-side (SCOPE_PRESETS) and reach the SPA through the generated
    // scopePresets.js. A second hand-typed copy on the customer-facing panel is the failure this
    // pins: two lists of the same agreed checklist drift, and nothing here would report it.
    expect(src).not.toMatch(/'1\.3\.2'|"1\.3\.2"/)
    expect(src).not.toMatch(/Deva/)                         // customer name never reaches the UI
  })

  it('evaluated rows are filtered to the assessed level and the active criteria list', () => {
    expect(src).toMatch(/\(LEVEL_RANK\[r\.level\] \|\| 1\) <= targetRank && criteria\.has\(r\.id\)/)
    // …and so is the checklist-parity list, so the header denominator and the rows agree.
    expect(src).toMatch(/c\.docApplies !== false && \(LEVEL_RANK\[c\.level\] \|\| 3\) <= targetRank && criteria\.has\(c\.sc\)/)
  })

  it('has a Hide-N/A toggle that collapses rows with no pass or fail result', () => {
    expect(src).toMatch(/const \[hideNA, setHideNA\] = useState\(true\)/)   // N/A hidden by default
    expect(src).toMatch(/const naCount = rules\.filter\(\(r\) => r\.pass === 0 && r\.fail === 0\)\.length/)
    expect(src).toMatch(/const shown = hideNA \? rules\.filter\(\(r\) => r\.pass > 0 \|\| r\.fail > 0\) : rules/)
    expect(src).toMatch(/Hide N\/A \(\$\{naCount\}\)/)
  })

  it('the scope narrowing is one labelled control, not a silent default', () => {
    expect(src).toMatch(/const \[showAllCore, setShowAllCore\] = useState\(false\)/)  // scoped by default
    expect(src).toMatch(/outOfScopeNote\(outOfScopeFindings\)/)   // …and it says what it is leaving out
    // The note is NOT conditional on the hidden criteria being clean. A criterion that vanishes
    // only when it would have looked bad is worse than one that never vanishes at all.
    expect(src).toMatch(/\{!showAllCore && \(\s*<p className="muted"/)
  })
})

describe('the agreed scope itself', () => {
  it('is the 14 criteria the backend defines, and a strict subset of the 20-check core', () => {
    expect(SCOPE_SCS.size).toBe(14)
    expect(SCOPE_IS_SUBSET_OF_CORE).toBe(true)
    // The difference is derived, so "N of the 20 are outside the scope" cannot go stale.
    expect(OUT_OF_SCOPE_SCS.size).toBe(CORE_SCS.size - SCOPE_SCS.size)
    expect([...OUT_OF_SCOPE_SCS].sort()).toEqual(['1.3.3', '1.4.10', '1.4.11', '1.4.12', '1.4.4', '2.1.2'])
  })
})
