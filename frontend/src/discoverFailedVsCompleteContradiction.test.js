// Found live 2026-08-29: a "scan failed: 500" banner rendered directly above a "Discovery
// complete" card holding the previous run's own results — a flat contradiction, with the raw
// HTTP status code as the only explanation offered. scanFailureMessage.js supplies the fix
// (scanFailureDetail turns a bare status into plain language; hasFallbackInventory says when a
// previous run's results are still on screen underneath); this pins that App.jsx actually wires
// both in, not just that the helpers exist.
//
// Source-shape assertion, same reasoning as discoverBannerContradiction.test.js: App.jsx owns
// ~40 pieces of state behind a sign-in wall and a live API, so the property under test is a claim
// about the code, not about a rendered pixel.
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, 'App.jsx'), 'utf8')

describe('the failure banner explains a raw status and a stale-looking completed card', () => {
  it('imports scanFailureDetail and hasFallbackInventory', () => {
    expect(src).toMatch(/import \{ scanFailureDetail, hasFallbackInventory \} from '\.\/scanFailureMessage\.js'/)
  })

  it('both scan-failure catch sites route the raw message through scanFailureDetail', () => {
    const occurrences = src.match(/setErr\(`scan failed: \$\{scanFailureDetail\(e\?\.message \?\? e\)\}`\)/g) || []
    expect(occurrences.length).toBe(2)
  })

  it('the err banner shows a reassurance line gated on hasFallbackInventory', () => {
    const bannerBlock = src.match(/\{err && \([\s\S]*?\)\}\n/)
    expect(bannerBlock, 'err banner block should be found').toBeTruthy()
    expect(bannerBlock[0]).toMatch(/hasFallbackInventory\(run\?\.completed_at\)/)
    expect(bannerBlock[0]).toMatch(/unaffected and still shown below/)
  })
})
