import { describe, it, expect } from 'vitest'
import { DOCUMENTS_20 } from './documents20.js'
import { WCAG } from './wcagCatalog.js'

// The 20-check core is a contractual list on the customer's own standard slide. If someone
// edits it, that's a decision — not a typo — so it has to break a test.
describe('20-check document core', () => {
  it('is exactly the 20 criteria on the standard', () => {
    expect([...DOCUMENTS_20].sort()).toEqual([
      '1.1.1', '1.3.1', '1.3.2', '1.3.3', '1.4.1', '1.4.10', '1.4.11', '1.4.12',
      '1.4.3', '1.4.4', '1.4.5', '2.1.1', '2.1.2', '2.4.2', '2.4.3', '2.4.4',
      '2.4.6', '3.1.1', '3.1.2', '4.1.2',
    ].sort())
    expect(DOCUMENTS_20.size).toBe(20)
  })

  it('every criterion exists in the WCAG catalog and applies to documents', () => {
    for (const sc of DOCUMENTS_20) {
      const c = WCAG.find((x) => x.sc === sc)
      expect(c, `${sc} missing from wcagCatalog`).toBeTruthy()
      expect(c.docApplies, `${sc} is marked web-only`).not.toBe(false)
    }
  })

  it('is all A/AA — the core never certifies against AAA', () => {
    for (const sc of DOCUMENTS_20) {
      expect(['A', 'AA']).toContain(WCAG.find((x) => x.sc === sc).level)
    }
  })
})
