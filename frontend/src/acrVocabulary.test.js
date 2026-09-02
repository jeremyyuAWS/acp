import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { FINAL_STATUSES, REMARKS_REQUIRED } from './acrApi.js'

/**
 * The four VPAT conformance terms exist in two places — api/acr_catalog.py and acrApi.js — and
 * PRD §9 forbids inventing a fifth. Two hand-maintained lists of the same closed vocabulary is
 * precisely how one acquires an extra entry: someone adds "Supports with exceptions" to a
 * dropdown, the backend rejects it, and the bug surfaces as a mysterious 422 rather than as the
 * vocabulary violation it is.
 *
 * The frontend list cannot simply import the Python one, so this reads acr_catalog.py and asserts
 * the two agree — the same shape as the existing capability/assess coverage contract tests
 * (capability.test.js, assessCoverage.test.js), which pin frontend constants against their
 * backend source for the same reason.
 */

const here = dirname(fileURLToPath(import.meta.url))
const catalog = readFileSync(join(here, '../../api/acr_catalog.py'), 'utf8')

// Pull the constants out of their assignments rather than the frozenset literal, so a reordering
// of the frozenset cannot break this while a renamed term slips past.
const pyConst = (name) => {
  const m = new RegExp(`^${name}\\s*=\\s*"([^"]+)"`, 'm').exec(catalog)
  return m ? m[1] : null
}

describe('the VPAT conformance vocabulary is one closed set', () => {
  it('matches api/acr_catalog.py exactly', () => {
    const backend = ['SUPPORTS', 'PARTIALLY_SUPPORTS', 'DOES_NOT_SUPPORT', 'NOT_APPLICABLE']
      .map(pyConst)
    expect(backend).not.toContain(null)
    expect([...FINAL_STATUSES].sort()).toEqual([...backend].sort())
  })

  it('has exactly four terms', () => {
    expect(FINAL_STATUSES).toHaveLength(4)
    expect(new Set(FINAL_STATUSES).size).toBe(4)
  })

  it('requires remarks for the three limitation statuses and not for Supports', () => {
    expect(REMARKS_REQUIRED).toHaveLength(3)
    expect(REMARKS_REQUIRED).not.toContain(pyConst('SUPPORTS'))
    for (const s of REMARKS_REQUIRED) expect(FINAL_STATUSES).toContain(s)
  })

  it('contains no internal workflow state', () => {
    // PRD §9: ACP's internal states are permitted, and must never appear as a conformance level.
    for (const internal of ['not_evaluated', 'needs_review', 'decided']) {
      expect(FINAL_STATUSES).not.toContain(internal)
    }
  })
})
