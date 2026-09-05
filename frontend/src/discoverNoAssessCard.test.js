/**
 * The live Assessment card follows the user across every tab except Assess itself, where
 * AssessRunner owns the fuller version. This is deliberate workflow continuity: navigating to
 * Discover, Remediate, Overview or an operational view must not replace actual progress with a
 * generic “assessment is running” warning.
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

describe('the live-assess card follows the user across tabs', () => {
  it('suppresses only the duplicate card on the Assess tab', () => {
    const expr = activeExpr()
    expect(expr).toMatch(/view !== 'assess'/)
    expect(expr).not.toMatch(/view !== 'discover'/)
    expect(expr).not.toMatch(/view !== 'remediate'/)
  })

  it('shows on Discover and Remediate while Assessment is running', () => {
    const gate = new Function('busy', 'assessPhase', 'view', `return (${activeExpr()})`)
    expect(gate(false, 'running', 'discover')).toBe(true)
    expect(gate(false, 'running', 'remediate')).toBe(true)
    expect(gate(false, 'running', 'assess')).toBe(false)
  })

  it('every away tab shows the live card', () => {
    const gate = new Function('busy', 'assessPhase', 'view', `return (${activeExpr()})`)
    for (const view of ['discover', 'remediate', 'overview', 'publish', 'monitor', 'integrations', 'liveops']) {
      expect(gate(false, 'running', view), `${view} should still show the live card`).toBe(true)
    }
  })

  it('a DISCOVER scan in flight does NOT activate the assess card on any tab', () => {
    // `busy` means doScan/reconnectScan — a discovery run. The assess panel must never show
    // "Preparing assessment" during discovery regardless of which tab is active, because the
    // assess card has no meaningful data to show during discovery and displayed confusingly.
    const gate = new Function('busy', 'assessPhase', 'view', `return (${activeExpr()})`)
    for (const view of ['discover', 'overview', 'remediate', 'publish', 'monitor', 'integrations']) {
      expect(gate(true, 'idle', view), `assess card must not show during discovery on ${view}`).toBe(false)
    }
  })

  it('does not stack the generic continuity banner above the live Assessment card', () => {
    expect(app).toMatch(/workflow=\{primaryWorkflow\?\.stage === 'assess' && assessPhase === 'running'[\s\S]*?\? null : primaryWorkflow\}/)
  })

  it('the component itself is kept, per the remove-the-mount-not-the-code rule', () => {
    expect(app).toMatch(/import LiveAssessmentLive from '\.\/LiveAssessmentLive\.jsx'/)
    expect(app).toMatch(/<LiveAssessmentLive/)
  })
})
