// Contract: the Validation-coverage matrix must never drift from what actually
// ships. The matrix reads wcagCatalog.js's `source` field; the deterministic
// checks that ship are the rule modules in rules/index.js. This binds the two so
// adding/removing a rule module without updating the catalog fails CI.
import { readFileSync, existsSync } from 'node:fs'
import path from 'node:path'
import { describe, it, expect } from 'vitest'
import { WCAG } from './wcagCatalog.js'
import { allRules } from './rules/index.js'

const bySc = Object.fromEntries(WCAG.map((c) => [c.sc, c]))
const shippedModules = allRules.map((r) => r.meta.id)

// Resolve a repo-root-relative file by walking up from cwd (vitest runs from
// frontend/; CI may vary) — import.meta.url isn't a file:// URL under vitest.
const repoFile = (rel) => {
  let dir = process.cwd()
  for (let i = 0; i < 6; i++) {
    const p = path.join(dir, rel)
    if (existsSync(p)) return p
    dir = path.dirname(dir)
  }
  throw new Error(`repo file not found: ${rel}`)
}

// The three surfaces that can ACTUALLY validate a criterion — a claim of
// "Live now" is only honest if one of these backs it. Read from source so the
// test tracks reality, not a hand-kept allowlist.
const scannerSCs = new Set(
  ['api/scanner.py', 'api/ocr.py', 'api/textchecks.py'].flatMap((f) =>
    [...readFileSync(repoFile(f), 'utf8').matchAll(/wcag":\s*"(\d+\.\d+\.\d+)/g)].map((m) => m[1])
  )
)
const partnerSCs = new Set(
  Object.entries(JSON.parse(readFileSync(repoFile('config/rule-catalog.json'), 'utf8')))
    .filter(([fmt]) => fmt !== '_meta')
    .flatMap(([, rules]) => rules.map((r) => r.wcag_sc))
)
const feModules = new Set(shippedModules)
const isBacked = (sc) => feModules.has(sc) || scannerSCs.has(sc) || partnerSCs.has(sc)

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

  it("every 'Shipped (demo)' criterion is backed by a REAL validator", () => {
    // No agentic escape hatch: a criterion is only 'Live now' if a frontend rule
    // module, the backend _analyse_html scanner, or the partner engine actually
    // validates it. A claimed 'Automated + Agentic' path that ships no code is
    // fabricated coverage and must read as Roadmap ('MDK net-new'), not Live now.
    const overclaimed = WCAG
      .filter((c) => c.source === 'Shipped (demo)')
      .filter((c) => !isBacked(c.sc))
      .map((c) => `${c.sc} (${c.approach})`)
    expect(overclaimed, `Live now with no real validator: ${overclaimed.join(', ')}`).toEqual([])
  })

  it("no shipped module is a Human/AT criterion (those route to HITL, not auto)", () => {
    const humanButShipped = shippedModules
      .filter((sc) => bySc[sc])
      .filter((sc) => /Human/i.test(bySc[sc].approach || ''))
    expect(humanButShipped, `Human/AT criteria with an auto module: ${humanButShipped.join(', ')}`).toEqual([])
  })
})
