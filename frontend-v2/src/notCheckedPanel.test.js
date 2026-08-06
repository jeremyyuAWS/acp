import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { assessmentIn, DOCUMENTS_20 } from './assessCoverage.js'

// ADR 0026 Epic 1 — the automated boundary, stated plainly. Two contracts:
// (1) the drawer's "What we did NOT check automatically" panel lists every unassessable criterion
//     with an honest per-outcome reason; (2) no silent gaps — every core criterion × format
//     resolves to one of the six explicit lanes, never undefined.
const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, 'FileDrawer.jsx'), 'utf8')

describe('"What we did NOT check automatically" — the honest boundary panel', () => {
  it('derives from the same rows as the manifest and covers all four unassessable outcomes', () => {
    expect(src).toMatch(/const notChecked = rows\.filter\(\(r\) => \['HUMAN', 'AT', 'GAP', 'NA'\]\.includes\(r\.outcome\)\)/)
    expect(src).toMatch(/What we did NOT check automatically/)
  })

  it('every unassessable outcome carries an honest reason, not a blank', () => {
    expect(src).toMatch(/HUMAN: 'Author intent \/ runtime behaviour/)
    expect(src).toMatch(/AT: 'Only provable by interaction/)
    expect(src).toMatch(/GAP: 'Statically detectable but the check/)
    expect(src).toMatch(/NA: `This barrier can/)
    expect(src).toMatch(/Nothing was skipped silently/)
  })
})

describe('no silent gaps — every core criterion × format resolves to an explicit lane', () => {
  it('assessmentIn never returns undefined for the 20-core across all five formats', () => {
    const LANES = new Set(['auto', 'review', 'human', 'gap', 'at', 'na'])
    for (const sc of DOCUMENTS_20) {
      for (const fmt of ['docx', 'xlsx', 'pptx', 'pdf', 'html']) {
        expect(LANES.has(assessmentIn(sc, fmt)), `${sc}|${fmt}`).toBe(true)
      }
    }
  })
})
