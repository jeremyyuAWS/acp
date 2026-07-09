import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { fmtEffort, EFFORT_BASIS } from './effort.js'   // not FileDrawer: it drags in pdfjs
import { recommendFor } from './sim.js'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

// Effort minutes come from fixed per-finding constants in sim.js — nothing measures the real
// work. They may inform triage; they may never appear as a quantified claim in a customer's
// conformance artifact, and they may never render as if observed.

describe('effort estimates are labelled, never asserted', () => {
  it('renders with an "est." prefix so it cannot read as a measurement', () => {
    expect(fmtEffort(258)).toBe('est. 4.3 hrs')
    expect(fmtEffort(14)).toBe('est. 14 min')
    expect(fmtEffort(0)).toBe('no work')
    expect(fmtEffort(null)).toBe('—')
  })

  it('states its basis, and that basis admits it is not measured', () => {
    expect(EFFORT_BASIS).toMatch(/not a measurement|not measured/i)
  })
})

describe('the certification PDF carries no invented numbers', () => {
  const pdf = read('pdfReport.js')

  it('makes no effort or savings claim', () => {
    const code = pdf.split('\n').filter((l) => !l.trim().startsWith('//')).join('\n')
    expect(code).not.toMatch(/person-days/)
    expect(code).not.toMatch(/saving/i)
    expect(code).not.toMatch(/Est\. effort/)
    expect(code).not.toMatch(/effort saved/i)
  })

  it('keeps no per-severity minute constants to rebuild one from', () => {
    const code = pdf.split('\n').filter((l) => !l.trim().startsWith('//')).join('\n')
    expect(code).not.toMatch(/SEV_MIN|AUTO_MIN|personDays/)
  })
})

describe('recommendFor emits no fabricated confidence', () => {
  it('never returns a confidence percentage', () => {
    // It used to return `90 + (n % 9)` — a percentage from the finding count modulo a number.
    const f = { type: 'pptx', status: 'analysed', compliant: false, score: 40, issues: [
      { wcag: 'SC_1_1_1', severity: 'CRITICAL' }, { wcag: 'SC_1_4_3', severity: 'SERIOUS' }] }
    expect(recommendFor(f)).not.toHaveProperty('confidence')
  })

  it('has no confidence literal left in the source', () => {
    expect(read('sim.js')).not.toMatch(/^\s*confidence:/m)
  })
})
