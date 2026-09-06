import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ActivityPulse from './ActivityPulse.jsx'
import RemediationRunCard from './RemediationRunCard.jsx'

const here = dirname(fileURLToPath(import.meta.url))

// The sixty-second activity pulse, and its second home on the persistent card.
//
// It was one function inside RemediationOpsPanel.jsx and is now a shared component, so the
// property worth pinning first is that there is exactly ONE of it: two copies of a liveness
// indicator drift, and a card and a panel disagreeing about how busy the same run is reads as a
// data problem rather than a duplication problem.

const AT = '2026-09-06T12:00:00.000Z'
const secondsBefore = (n) => new Date(Date.parse(AT) - n * 1000).toISOString()

const SNAP = {
  run_id: 'scan-1', scan_id: 'scan-1', revision: 1757068800000, generated_at: AT,
  state: 'running', message: 'Remediation in progress', terminal: false,
  source: { provider: 'drive', provider_label: 'Google Drive', breadcrumb: 'Google Drive' },
  total_documents: 20,
  documents: { completed: 8, processing: 3, waiting: 5, review: 2, failed: 1, skipped: 1 },
  fixes: { applied: 26, verified: 21, verification_failures: 5, documents_verified: 8 },
  delivery: { stored: 8, delivered: 7, pending: 1, eligible: 8, latest_at: null },
  review: { documents: 2, items: 3 }, phases: [],
  thresholds: { stall_after_s: 900, heartbeat_s: 15, delayed_after_s: 60 },
  integrity: { ok: true, violations: [], affected: [] },
}

const busy = [
  { key: 'a', occurredAt: secondsBefore(3) },
  { key: 'b', occurredAt: secondsBefore(8) },
  { key: 'c', occurredAt: secondsBefore(9) },
  { key: 'd', occurredAt: secondsBefore(41) },
]

const pulse = (props) => renderToStaticMarkup(createElement(ActivityPulse, props))
const card = (props) => renderToStaticMarkup(
  createElement(RemediationRunCard, { snapshot: SNAP, connected: true, ...props }))


describe('the pulse reports recorded events and nothing else', () => {
  it('draws one bar per five-second bucket over the last minute', () => {
    const html = pulse({ events: busy, generatedAt: AT })
    expect(html.match(/<i /g) || []).toHaveLength(12)
    expect(html).toContain('Last 60 seconds')
  })

  it('states the count for a screen reader and hides the bars from it', () => {
    // The bars are decoration for a number the label already carries; twelve unlabelled items
    // would be twelve stops announcing nothing.
    const html = pulse({ events: busy, generatedAt: AT })
    expect(html).toContain('aria-label="Last 60 seconds: 4 recorded events"')
    expect(html).toContain('aria-hidden="true"')
  })

  it('renders NOTHING when the minute recorded nothing', () => {
    // A flat strip would claim the last minute was quiet. An absent one makes no claim, which is
    // the honest answer for a run that just started, resumed from a cursor, or had events pruned.
    expect(pulse({ events: [], generatedAt: AT })).toBe('')
    expect(pulse({ events: [{ key: 'old', occurredAt: secondsBefore(600) }], generatedAt: AT }))
      .toBe('')
  })

  it('renders nothing rather than guessing when the snapshot has no generation time', () => {
    expect(pulse({ events: busy, generatedAt: null })).toBe('')
    expect(pulse({ events: busy, generatedAt: 'not-a-date' })).toBe('')
  })

  it('ignores events with no usable timestamp instead of bucketing them at zero', () => {
    const html = pulse({ events: [...busy, { key: 'x' }, { key: 'y', occurredAt: 'nope' }],
                         generatedAt: AT })
    expect(html).toContain('4 recorded events')
  })
})


describe('the persistent card carries the same pulse', () => {
  it('shows it beside the freshness words', () => {
    const html = card({ events: busy })
    expect(html).toContain('Last 60 seconds')
    expect(html).toContain('aria-label="Last 60 seconds: 4 recorded events"')
  })

  it('uses the compact variant so it does not draw the panel\'s divider inside the card', () => {
    expect(card({ events: busy })).toContain('remops-pulse-compact')
    // ...and the panel's own strip does NOT take that modifier.
    expect(pulse({ events: busy, generatedAt: AT })).not.toContain('remops-pulse-compact')
  })

  it('is absent on a card whose run recorded nothing, rather than an empty widget on every tab', () => {
    // The card is persistent across tabs. A permanently blank strip would be visual debt on
    // every screen in the product.
    const html = card({ events: [] })
    expect(html).not.toContain('Last 60 seconds')
    expect(html).toContain('documents processed')      // the rest of the card is unaffected
  })

  it('renders without events at all, because two of its mount sites are older than this prop', () => {
    expect(() => card({})).not.toThrow()
    expect(card({})).not.toContain('Last 60 seconds')
  })
})


describe('one implementation, not two', () => {
  it('the panel imports the shared component instead of defining its own', () => {
    const panel = readFileSync(join(here, 'RemediationOpsPanel.jsx'), 'utf8')
    expect(panel).toContain("import ActivityPulse from './ActivityPulse.jsx'")
    // The give-away for a re-introduced copy: the markup, not the name.
    expect(panel).not.toContain('remops-pulse-bars')
    expect(panel).not.toMatch(/function ActivityPulse\s*\(/)
  })

  it('the card imports it too, so both surfaces read one set of buckets', () => {
    const cardSource = readFileSync(join(here, 'RemediationRunCard.jsx'), 'utf8')
    expect(cardSource).toContain("import ActivityPulse from './ActivityPulse.jsx'")
    expect(cardSource).not.toContain('remops-pulse-bars')
  })

  it('the component carries its own stylesheet', () => {
    // It used to live in the panel, which imports this CSS. Left that way, the card would render
    // an unstyled strip the moment anything made the panel lazy — silently, and only on the tabs
    // where the panel is not mounted.
    const source = readFileSync(join(here, 'ActivityPulse.jsx'), 'utf8')
    expect(source).toContain("import './remediation-live-detail.css'")
  })

  it('the compact modifier is defined in that stylesheet', () => {
    const css = readFileSync(join(here, 'remediation-live-detail.css'), 'utf8')
    expect(css).toContain('.remops-pulse-compact')
  })
})


describe('every mount site passes the events through', () => {
  // The pulse is silent when it gets none, so a forgotten prop does not throw or look broken —
  // it just never appears, on exactly the surface nobody is looking at. Each wiring is asserted
  // at its call site for that reason.
  it('App.jsx feeds the card that shows on every other tab', () => {
    const app = readFileSync(join(here, 'App.jsx'), 'utf8')
    expect(app).toMatch(/<RemediationRunCard[^>]*events=\{remRun\.events\}/s)
  })

  it('Remediate.jsx feeds the workspace tabs', () => {
    // SCOPED TO THE TABS' OWN PROPS, deliberately. `<RemediationOpsPanel events={...}/>` is
    // nested INSIDE this element's `live=` prop with an identical expression, so a lazy
    // `<RemediationWorkspaceTabs[\s\S]*?events=` matches that inner one and passes with the
    // tabs' own prop deleted — which is what the mutation harness caught. Slice the element's
    // attribute region and assert within it.
    const remediate = readFileSync(join(here, 'Remediate.jsx'), 'utf8')
    const open = remediate.indexOf('<RemediationWorkspaceTabs')
    expect(open).toBeGreaterThan(-1)
    const attrs = remediate.slice(open, remediate.indexOf('review={reviewWorkspace}', open))
    expect(attrs).toContain('events={runStream?.events || []}')
  })

  it('the workspace tabs feed their copy of the card', () => {
    const tabs = readFileSync(join(here, 'RemediationWorkspaceTabs.jsx'), 'utf8')
    expect(tabs).toMatch(/<RemediationRunCard[\s\S]*?events=\{events\}/)
  })
})
