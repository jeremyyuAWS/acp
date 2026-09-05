/**
 * The live Assessment card follows the user across every tab, including Assess itself. The
 * detailed AssessRunner file list is complementary activity detail, not a replacement for the
 * compact stage-level card directly below the tabs.
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
  it('does not suppress the card on any workflow tab', () => {
    const expr = activeExpr()
    expect(expr).toBe("assessPhase === 'running'")
    expect(expr).not.toMatch(/\bview\b/)
  })

  it('shows on Discover and Remediate while Assessment is running', () => {
    const gate = new Function('busy', 'assessPhase', 'view', `return (${activeExpr()})`)
    expect(gate(false, 'running', 'discover')).toBe(true)
    expect(gate(false, 'running', 'remediate')).toBe(true)
    expect(gate(false, 'running', 'assess')).toBe(true)
  })

  it('every away tab shows the live card', () => {
    const gate = new Function('busy', 'assessPhase', 'view', `return (${activeExpr()})`)
    for (const view of ['discover', 'assess', 'remediate', 'overview', 'publish', 'monitor',
      'integrations', 'liveops', 'analytics', 'knowledge', 'acr', 'settings']) {
      expect(gate(false, 'running', view), `${view} should still show the live card`).toBe(true)
    }
  })

  it('is mounted once outside the changing tab content so navigation cannot tear it down', () => {
    const card = app.indexOf('<LiveAssessmentLive')
    const main = app.indexOf('<main id="main-content"')
    expect(card).toBeGreaterThan(-1)
    expect(main).toBeGreaterThan(card)
    expect(app.match(/<LiveAssessmentLive/g)).toHaveLength(1)
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
