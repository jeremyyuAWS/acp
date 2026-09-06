import { afterEach, describe, expect, it, vi } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import ErrorBoundary from './ErrorBoundary.jsx'

// One workflow whose discover has finished while its remediate is still running, and one that is
// finished outright. Reported 2026-09-06: selecting "Recently completed" showed the 93%-complete
// remediate card, because the filter matched a run and then admitted its whole workflow.
vi.mock('./api.js', () => ({
  getAdminActivity: vi.fn(async () => ({
    generated_at: '2026-09-06T14:00:00Z',
    runs: [
      { scan_id: 'live-one', stage: 'discover', owner: 'ops@example.com', source: 'drive',
        status: 'recent', completed: 188, total: 188, updated_at: '2026-09-06T13:50:00Z' },
      { scan_id: 'live-one', stage: 'remediate', owner: 'ops@example.com', source: 'drive',
        status: 'active', running: 14, completed: 174, total: 188,
        updated_at: '2026-09-06T13:59:00Z' },
      { scan_id: 'done-two', stage: 'discover', owner: 'ops@example.com', source: 'drive',
        status: 'recent', completed: 12, total: 12, updated_at: '2026-09-06T12:00:00Z' },
    ],
    summary: {
      active_runs: 1, active_workflows: 2, recent_runs: 2, running: 14, queued: 0,
      waiting_users: 0, available_slots: 7, worker_slots: 7, utilization_pct: 0,
      worker_tier_alive: true, by_stage: {}, worker_roles: {},
    },
  })),
  getWorkerCapacity: vi.fn(async () => ({ configured: false })),
  getLiveOpsCosts: vi.fn(async () => ({ configured: false, services: [],
    billing: { freshness_label: 'Azure billing feed not configured' } })),
  openAdminActivityStream: vi.fn(() => ({ close: vi.fn() })),
}))

const { default: AdminLiveTraffic } = await import('./AdminLiveTraffic.jsx')

afterEach(unmountAll)

async function openJobsTab() {
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(ErrorBoundary, null, createElement(AdminLiveTraffic))) })
  await act(async () => { await Promise.resolve() })
  const tab = [...container.querySelectorAll('[role="tab"]')]
    .find((node) => node.textContent.startsWith('Running jobs'))
  await act(async () => { tab.click() })
  return container
}

const chip = (container, label) => [...container.querySelectorAll('[aria-label="Filter workflows by state"] button')]
  .find((node) => node.getAttribute('aria-label').startsWith(`${label},`))

describe('Live Operations job cards', () => {
  // Reported 2026-09-06: the finished discover card was headed ACTIVE JOB while its own status
  // line read Complete, because the header was the tile-kind constant, not the run's state.
  it('heads each card with what that job is actually doing', async () => {
    const container = await openJobsTab()
    const headers = [...container.querySelectorAll('.react-flow__node')]
      .map((node) => node.textContent)
      .filter((text) => text.includes('JOB'))

    expect(headers).toHaveLength(3)
    expect(headers.filter((text) => text.startsWith('COMPLETED JOB'))).toHaveLength(2)
    expect(headers.filter((text) => text.startsWith('ACTIVE JOB'))).toHaveLength(1)
    // The one headed ACTIVE is the remediate that is genuinely running.
    expect(headers.find((text) => text.startsWith('ACTIVE JOB'))).toContain('174/188')
    expect(headers.find((text) => text.startsWith('COMPLETED JOB'))).toContain('Complete')
  })
})

describe('Live Operations job state filters', () => {
  it('hides a workflow that is still running from the completed chip', async () => {
    const container = await openJobsTab()
    expect(container.textContent).toContain('remediate in progress')

    await act(async () => { chip(container, 'Recently completed').click() })
    expect(container.textContent).not.toContain('remediate in progress')
    expect(container.textContent).toContain('Recently completed')
    expect(container.textContent).toContain('done-two')
    expect(container.textContent).not.toContain('live-one')
  })

  it('shows the running workflow under the active chip', async () => {
    const container = await openJobsTab()
    await act(async () => { chip(container, 'Active').click() })
    expect(container.textContent).toContain('live-one')
    expect(container.textContent).not.toContain('done-two')
  })

  it('counts each chip so an empty result is visible before it is clicked', async () => {
    const container = await openJobsTab()
    expect(chip(container, 'Active').getAttribute('aria-label')).toBe('Active, 1 workflows')
    expect(chip(container, 'Recently completed').getAttribute('aria-label'))
      .toBe('Recently completed, 1 workflows')
    expect(chip(container, 'Stalled').getAttribute('aria-label')).toBe('Stalled, 0 workflows')
  })

  it('offers a way back when a chip empties the map', async () => {
    const container = await openJobsTab()
    await act(async () => { chip(container, 'Stalled').click() })
    const empty = [...container.querySelectorAll('[role="status"]')]
      .find((node) => node.textContent.includes('No workflows match this view'))
    expect(empty).toBeTruthy()

    const back = [...empty.querySelectorAll('button')].find((node) => node.textContent === 'Show all')
    await act(async () => { back.click() })
    expect(container.textContent).toContain('remediate in progress')
    expect(container.textContent).toContain('done-two')
  })
})
