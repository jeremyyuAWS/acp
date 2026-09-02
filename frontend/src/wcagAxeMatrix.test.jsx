/**
 * WCAG axe-core matrix — automated accessibility scan in WCAG mode.
 *
 * Mounts key components with [data-wcag="on"] set on <html> and runs axe-core
 * configured for WCAG 2.1 AA rules.  Only "critical" and "serious" violations
 * from the axe ruleset are treated as failures — informational findings are
 * logged but not blocking, because jsdom does not provide colour/visual
 * information (contrast checks are handled by wcagContrastTokens.test.js).
 *
 * Each describe block mounts one self-contained surface.  The shared
 * beforeEach/afterEach manages the WCAG toggle and root cleanup.
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import axe from 'axe-core'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

// Enable [data-wcag="on"] on the document root for every test in this file.
beforeEach(() => { document.documentElement.dataset.wcag = 'on' })
afterEach(() => {
  delete document.documentElement.dataset.wcag
  unmountAll()
})

/** Run axe-core on a container and return violations of impact "critical"|"serious". */
async function runAxe(container) {
  const results = await axe.run(container, {
    runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] },
  })
  return results.violations.filter(v => v.impact === 'critical' || v.impact === 'serious')
}

// ── AssessRunProgress (uses .assesslist with .alstate.pending) ────────────

const { default: AssessRunProgress } = await import('./AssessRunProgress.jsx')

const SNAPSHOT_RUNNING = {
  status: 'running',
  phase: 'assessing',
  phaseLabel: 'Checking WCAG',
  live_queue: {
    current: { file: 'Clinical/handbook.pdf', criterionName: '1.1.1 Non-text Content' },
    workers: { busy: 4, idle: 0, max: 4 },
    queued: 12, inFlight: 4,
  },
  kpis: { completed: 3 },
  totals: { eligible: 20, discovered: 20 },
}

describe('AssessRunProgress — running state (WCAG mode)', () => {
  it('has no critical/serious axe violations', async () => {
    const { container, root } = createTestRoot()
    await act(async () => {
      root.render(createElement(AssessRunProgress, {
        snapshot: SNAPSHOT_RUNNING,
        throughput: { etaText: '~2 min remaining' },
        onStop: () => {},
      }))
    })
    const violations = await runAxe(container)
    expect(violations, violations.map(v => `${v.id}: ${v.description}`).join('\n'))
      .toHaveLength(0)
  })
})

describe('AssessRunProgress — preparing state (WCAG mode)', () => {
  it('has no critical/serious axe violations', async () => {
    const { container, root } = createTestRoot()
    const preparingSnapshot = {
      ...SNAPSHOT_RUNNING,
      kpis: { completed: 0 },
      live_queue: {
        ...SNAPSHOT_RUNNING.live_queue,
        workers: { busy: 2, idle: 0, max: 4 },
        queued: 0, inFlight: 0,
      },
    }
    await act(async () => {
      root.render(createElement(AssessRunProgress, {
        snapshot: preparingSnapshot,
        throughput: null,
        onStop: () => {},
      }))
    })
    const violations = await runAxe(container)
    expect(violations, violations.map(v => `${v.id}: ${v.description}`).join('\n'))
      .toHaveLength(0)
  })
})
