/**
 * DiscoverCompleteSummary — the card shown after discovery finishes.
 *
 * Shows an immutable snapshot of what was found (eligible, non-assessable, locked, excluded)
 * plus a prominent "Continue to Assessment →" CTA wired to onAdvance. Tests verify the
 * counts appear correctly and the CTA is disabled when pendingActions or needsAck is set.
 */
import { describe, it, expect, vi } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import DiscoverCompleteSummary from './DiscoverCompleteSummary.jsx'

const render = (props) =>
  renderToStaticMarkup(createElement(DiscoverCompleteSummary, props))

const BASE = {
  discoveredCount: 200,
  assessableCount: 170,
  nonAssessableCount: 20,
  lockedCount: 5,
  lifecycleRulesCount: 3,
  onAdvance: null,
  pendingActions: 0,
  needsAck: false,
}

describe('DiscoverCompleteSummary renders completion state', () => {
  it('shows "Discovery complete" heading', () => {
    expect(render(BASE)).toContain('Discovery complete')
  })

  it('shows assessable count with its label', () => {
    const html = render(BASE)
    expect(html).toContain('170')
    expect(html).toContain('eligible for assessment')
  })

  it('shows non-assessable count and label', () => {
    const html = render(BASE)
    expect(html).toContain('20')
    expect(html).toContain('non-assessable')
  })

  it('shows locked count and label', () => {
    const html = render(BASE)
    expect(html).toContain('5')
    expect(html).toContain('could not be opened')
  })

  it('shows lifecycle rules count', () => {
    const html = render(BASE)
    expect(html).toContain('3 lifecycle rules applied')
  })

  it('omits non-assessable row when count is 0', () => {
    const html = render({ ...BASE, nonAssessableCount: 0 })
    expect(html).not.toContain('non-assessable')
  })

  it('omits locked row when count is 0', () => {
    const html = render({ ...BASE, lockedCount: 0 })
    expect(html).not.toContain('could not be opened')
  })

  it('omits lifecycle rules when count is 0', () => {
    const html = render({ ...BASE, lifecycleRulesCount: 0 })
    expect(html).not.toContain('lifecycle rules applied')
  })

  it('omits lifecycle rules when count is null', () => {
    const html = render({ ...BASE, lifecycleRulesCount: null })
    expect(html).not.toContain('lifecycle rules applied')
  })

  it('shows "Continue to Assessment" CTA', () => {
    const html = render(BASE)
    expect(html).toContain('Continue to Assessment')
  })
})

describe('CTA gating', () => {
  it('CTA is not disabled when no pending actions and no ack needed', () => {
    const html = render({ ...BASE, pendingActions: 0, needsAck: false })
    expect(html).not.toMatch(/disabled/)
  })

  it('CTA is disabled when pendingActions > 0', () => {
    const html = render({ ...BASE, pendingActions: 3 })
    expect(html).toMatch(/disabled/)
    expect(html).toContain('pending action')
  })

  it('CTA is disabled when needsAck is true', () => {
    const html = render({ ...BASE, needsAck: true })
    expect(html).toMatch(/disabled/)
    expect(html).toContain('recommendations')
  })
})

describe('singular lifecycle rule label', () => {
  it('uses singular "lifecycle rule" when count is 1', () => {
    const html = render({ ...BASE, lifecycleRulesCount: 1 })
    expect(html).toContain('1 lifecycle rule applied')
    expect(html).not.toContain('1 lifecycle rules')
  })
})
