import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import ActivityPulse from './ActivityPulse.jsx'
import CanonicalStageCard from './CanonicalStageCard.jsx'
import RemediationRunCard from './RemediationRunCard.jsx'
import WorkflowStageStack from './WorkflowStageStack.jsx'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const here = dirname(fileURLToPath(import.meta.url))

const canonical = (overrides = {}) => ({
  workflow_id: 'workflow-1', workflow_revision: 4, stage: 'assess',
  execution_id: 'assess-4', revision: 9, state: 'processing',
  last_durable_update_at: '2026-09-07T12:00:00Z',
  counts: { work_items: { unit: 'work items', total: 12, queued: 2, processing: 1,
    completed: 8, failed: 1, skipped: 0, cancelled: 0 } },
  reconciliation: { unit: 'work items', total: 12, accounted: 12, exact: true },
  domain_reconciliation: {
    unit: 'eligible documents', total: 12, accounted: 12, exact: true,
    equation: 'eligible = waiting + processing + assessed + failed + cancelled + skipped',
    buckets: { waiting: 2, processing: 1, assessed: 8, failed: 1, cancelled: 0, skipped: 0 },
  },
  integrity: { ok: true, affected: [], violations: [] },
  control: { cancel_requested: false },
  ...overrides,
})

const terminalRemediation = {
  run_id: 'remediate-4', scan_id: 'scan-4', revision: 22, state: 'complete', terminal: true,
  message: 'Remediation complete', generated_at: '2026-09-07T12:01:00Z', total_documents: 3,
  documents: { completed: 2, processing: 0, waiting: 0, review: 1, failed: 0, skipped: 0 },
  fixes: { applied: 7, verified: 6, documents_verified: 2 },
  delivery: { delivered: 2, pending: 0, awaiting_release: 1 },
  source: { breadcrumb: 'SharePoint · Policies' },
  finding_reconciliation: { assessed: 9, accounted: 9, awaiting_review: 1, exact: true },
  integrity: { ok: true, affected: [], violations: [] },
}

const events = [
  { id: 'e1', occurredAt: '2026-09-07T12:00:42Z' },
  { id: 'e2', occurredAt: '2026-09-07T12:00:47Z' },
  { id: 'e3', occurredAt: '2026-09-07T12:00:58Z' },
]

const mounted = []
function mount(element) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  mounted.push({ container, root })
  act(() => { root.render(element) })
  return container
}

afterEach(() => {
  while (mounted.length) {
    const { container, root } = mounted.pop()
    act(() => { root.unmount() })
    container.remove()
  }
  sessionStorage.clear()
})

describe('unified canonical workflow experience', () => {
  it('uses the stage-specific Discover card for completed historical disclosure', () => {
    const live = renderToStaticMarkup(createElement(CanonicalStageCard, { snapshot: canonical() }))
    expect(live).toContain('data-testid="canonical-stage-card"')
    expect(live).toContain('12 of 12 eligible documents')

    const history = mount(createElement(WorkflowStageStack, {
      lineage: { workflow_id: 'workflow-1', workflow_revision: 4, stages: [
        canonical({ stage: 'discover', state: 'succeeded', execution_id: 'discover-4' }),
      ] },
      view: 'assess',
    }))
    const toggle = history.querySelector('.workflow-stage-stack__summary')
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    act(() => { toggle.click() })
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    expect(history.querySelector('.discover-run-progress')).not.toBeNull()
    expect(history.textContent).toContain('Discovery complete')
    expect(history.textContent).not.toContain('Workflow so far')
    expect(history.textContent).not.toContain('Workflow revision')
    expect(history.textContent).not.toContain('Operational work-item progress')
    expect(history.textContent).not.toContain('discover-4')
  })

  it('uses the familiar completed Assess card and keeps historical revisions read-only', () => {
    const history = mount(createElement(WorkflowStageStack, {
      lineage: { workflow_id: 'workflow-1', workflow_revision: 4, stages: [
        canonical({ stage: 'assess', state: 'succeeded', execution_id: 'assess-4',
          domain_reconciliation: {
            unit: 'eligible documents', total: 12, accounted: 12, exact: true,
            buckets: { waiting: 0, processing: 0, assessed: 12, failed: 0, cancelled: 0, skipped: 0 },
          } }),
      ] },
      view: 'remediate',
    }))
    const toggle = history.querySelector('.workflow-stage-stack__summary')
    expect(toggle.textContent).toContain('Assess · Complete')
    expect(toggle.textContent).toContain('12 assessed of 12 eligible documents')
    expect(toggle.querySelectorAll('.live-heartbeat-bars i')).toHaveLength(12)
    act(() => { toggle.click() })
    expect(history.querySelector('.workflow-stage-stack__body')).not.toBeNull()
    expect(history.querySelector('.assess-run-progress')).not.toBeNull()
    expect(history.textContent).toContain('Assessment complete')
    expect(history.textContent).not.toContain('Sealed output')
    expect(history.textContent).not.toContain('Integrity check:')
    expect(history.textContent).not.toContain('assess-4')
    for (const action of ['Start', 'Retry', 'Stop', 'Cancel', 'Apply']) {
      expect([...history.querySelectorAll('button')].some((button) =>
        button.textContent.trim().startsWith(action))).toBe(false)
    }
  })

  it('leaves current Discover and Assess presentation with their live stage cards', () => {
    const app = readFileSync(join(here, 'App.jsx'), 'utf8')
    expect(app).toContain("!['discover', 'assess', 'remediate'].includes(canonicalStage.stage)")
    expect(app).toContain('<DiscoverRunProgress')
    expect(app).toContain('<LiveAssessmentLive')
    expect(app.indexOf('<WorkflowStageStack')).toBeLessThan(app.indexOf('id="workflow-panel"'))
  })

  it('retains a terminal run summary and its final durable activity', () => {
    const html = renderToStaticMarkup(createElement(RemediationRunCard, {
      snapshot: terminalRemediation, receivedAt: Date.parse(terminalRemediation.generated_at),
      connected: false, events,
    }))
    expect(html).toContain('data-testid="rem-run-card"')
    expect(html).toMatch(/>3<\/span>[\s\S]*? of 3 documents through automatic processing/)
    expect(html).toContain('Fixes applied')
    expect(html).toContain('>7<')
    expect(html).toContain('aria-label="Last 60 seconds: 3 recorded events"')
  })

  it('does not move focus when a newer SSE snapshot updates the card', () => {
    const focusTarget = document.createElement('button')
    focusTarget.textContent = 'Keep focus here'
    document.body.appendChild(focusTarget)
    const container = mount(createElement(CanonicalStageCard, { snapshot: canonical() }))
    focusTarget.focus()

    act(() => { mounted.at(-1).root.render(createElement(CanonicalStageCard, {
      snapshot: canonical({ revision: 10, domain_reconciliation: {
        ...canonical().domain_reconciliation, accounted: 13, total: 13,
        buckets: { waiting: 1, processing: 1, assessed: 10, failed: 1, cancelled: 0, skipped: 0 },
      } }),
    })) })

    expect(document.activeElement).toBe(focusTarget)
    expect(container.textContent).toContain('13 of 13 eligible documents')
    focusTarget.remove()
  })
})

describe('accessible counts, motion, and responsive layout', () => {
  it('names exact count units in text alternatives', () => {
    const pulse = renderToStaticMarkup(createElement(ActivityPulse, {
      events, generatedAt: terminalRemediation.generated_at,
    }))
    expect(pulse).toContain('aria-label="Last 60 seconds: 3 recorded events"')

    const run = renderToStaticMarkup(createElement(RemediationRunCard, {
      snapshot: terminalRemediation, receivedAt: Date.parse(terminalRemediation.generated_at),
      events: [],
    }))
    expect(run).toContain('aria-label="3 documents: 2 completed, 1 blocked"')
    expect(run).toContain('Findings: 9 / 9 accounted')
    expect(run).toContain('1 awaiting human review')
  })

  it('removes every card animation and transition for reduced motion', () => {
    const css = readFileSync(join(here, 'canonical-stage-card.css'), 'utf8')
    const reduced = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)'))
    expect(reduced).toMatch(/canonical-stage-card__chevron[^}]*transition:\s*none/)
    expect(reduced).toMatch(/canonical-stage-card__progress > span[^}]*transition:\s*none/)
    expect(reduced).toMatch(/canonical-stage-card__delta[^}]*animation:\s*none/)
  })

  it('allows narrow cards to reflow without creating horizontal overflow', () => {
    const css = readFileSync(join(here, 'canonical-stage-card.css'), 'utf8')
    expect(css).toMatch(/\.canonical-stage-card\s*\{[^}]*overflow:\s*hidden/s)
    const narrow = css.slice(css.indexOf('@media (max-width: 720px)'))
    expect(narrow).toMatch(/grid-template-columns:\s*auto auto 1fr auto/)
    expect(narrow).toMatch(/canonical-stage-card__count\s*\{[^}]*grid-column:\s*1 \/ 4/s)
    expect(narrow).toMatch(/canonical-stage-card__hint\s*\{[^}]*display:\s*none/s)
  })
})
