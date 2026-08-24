/**
 * The live-assess card does not appear on Discover.
 *
 * Reported live: the Discover tab rendered "Assessing 148 documents · Document 0 of 148 ·
 * estimating… · Idle" directly above its own "148 documents discovered across 1 source" panel —
 * two progress readings of two different phases stacked on one screen. Discover answers "what do
 * we have"; how far the assessment has got belongs to Assess, which owns a better view of it.
 *
 * The Assess tab was already excluded for the same reason (AssessRunner owns that view, and
 * showing both produced contradictory "Document 0 of 148" vs "10 of 148 · 7%" readings at once).
 * Discover was simply never added to that exclusion.
 *
 * THE COMPONENT IS NOT DELETED, and that is deliberate — CLAUDE.md's standing instruction is to
 * remove the mount, not the code, so a retired surface can come back in one commit.
 * `LiveAssessmentLive` stays live on every other tab; only the Discover case is gated off. This
 * test is the written-down half of that: it fails if the gate is widened again, which is the
 * reminder to update it rather than a regression.
 *
 * Source-level, like assessSetupWiring.test.jsx and assessmentTimeline.test.js: App.jsx is far too
 * large to mount for a one-line gating fact, and this repo already reads it as text for exactly
 * these wiring assertions.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const app = readFileSync(join(here, 'App.jsx'), 'utf8')

/** The `active={...}` expression LiveAssessmentLive is mounted with. */
const activeExpr = () => {
  const m = app.match(/<LiveAssessmentLive[\s\S]{0,400}?active=\{([\s\S]*?)\}\s*\n/)
  expect(m, 'LiveAssessmentLive should still be mounted, with an active gate').toBeTruthy()
  return m[1].replace(/\s+/g, ' ')
}

describe('the live-assess card is gated off Discover', () => {
  it('the assess-phase clause excludes BOTH assess and discover', () => {
    const expr = activeExpr()
    expect(expr).toMatch(/view !== 'assess'/)
    expect(expr).toMatch(/view !== 'discover'/)
  })

  it('a running assess no longer activates the card on Discover', () => {
    // Evaluate the real gate rather than restating it — a regex alone would pass against a gate
    // that mentions 'discover' in any position, including one that re-enables it.
    const gate = new Function('busy', 'assessPhase', 'view', `return (${activeExpr()})`)
    expect(gate(false, 'running', 'discover')).toBe(false)
    expect(gate(false, 'running', 'assess')).toBe(false)
  })

  it('every other tab still shows it during an assess — this is a Discover fix, not a removal', () => {
    const gate = new Function('busy', 'assessPhase', 'view', `return (${activeExpr()})`)
    for (const view of ['overview', 'remediate', 'publish', 'monitor', 'integrations']) {
      expect(gate(false, 'running', view), `${view} should still show the live card`).toBe(true)
    }
  })

  it('a DISCOVER scan in flight still shows progress on Discover', () => {
    // `busy` means doScan/reconnectScan — a discovery run, whose progress is exactly what someone
    // on this tab wants. Narrowing that too would have taken the scan banner out with the assess
    // card, which is not what was asked for.
    const gate = new Function('busy', 'assessPhase', 'view', `return (${activeExpr()})`)
    expect(gate(true, 'idle', 'discover')).toBe(true)
  })

  it('the component itself is kept, per the remove-the-mount-not-the-code rule', () => {
    expect(app).toMatch(/import LiveAssessmentLive from '\.\/LiveAssessmentLive\.jsx'/)
    expect(app).toMatch(/<LiveAssessmentLive/)
  })
})
