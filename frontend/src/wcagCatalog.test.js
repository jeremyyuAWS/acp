// Contract: the Validation-coverage matrix must never drift from what actually
// ships. The matrix reads wcagCatalog.js's `source` field; the deterministic
// checks that ship are the rule modules in rules/index.js. This binds the two so
// adding/removing a rule module without updating the catalog fails CI.
import { describe, it, expect } from 'vitest'
import { WCAG } from './wcagCatalog.js'
import { allRules } from './rules/index.js'

const bySc = Object.fromEntries(WCAG.map((c) => [c.sc, c]))
const shippedModules = allRules.map((r) => r.meta.id)

describe('WCAG catalog ↔ rule registry', () => {
  it('every shipped rule module has a catalog entry', () => {
    const missing = shippedModules.filter((sc) => !bySc[sc])
    expect(missing, `rule modules with no catalog row: ${missing.join(', ')}`).toEqual([])
  })

  it("every shipped rule module is marked 'Shipped (demo)' (Live now)", () => {
    // A deterministic check that ships must read as Live now — not Roadmap,
    // not Partner-only. This is the drift that would understate coverage.
    const mislabelled = shippedModules
      .filter((sc) => bySc[sc])
      .filter((sc) => bySc[sc].source !== 'Shipped (demo)')
      .map((sc) => `${sc}=${bySc[sc].source}`)
    expect(mislabelled, `shipped modules not marked Live now: ${mislabelled.join(', ')}`).toEqual([])
  })

  it("every 'Shipped (demo)' criterion is backed by a module or the agentic AI path", () => {
    // The reverse drift — a criterion claimed Live now that nothing actually
    // validates (e.g. a Human/AT criterion mislabelled Shipped). Deterministic
    // modules OR the 'Automated + Agentic' LLM path are the only valid backings.
    const shippedSet = new Set(shippedModules)
    const overclaimed = WCAG
      .filter((c) => c.source === 'Shipped (demo)')
      .filter((c) => !shippedSet.has(c.sc) && !/Agentic/i.test(c.approach || ''))
      .map((c) => `${c.sc} (${c.approach})`)
    expect(overclaimed, `Live now with no backing check: ${overclaimed.join(', ')}`).toEqual([])
  })

  it("no shipped module is a Human/AT criterion (those route to HITL, not auto)", () => {
    const humanButShipped = shippedModules
      .filter((sc) => bySc[sc])
      .filter((sc) => /Human/i.test(bySc[sc].approach || ''))
    expect(humanButShipped, `Human/AT criteria with an auto module: ${humanButShipped.join(', ')}`).toEqual([])
  })
})
