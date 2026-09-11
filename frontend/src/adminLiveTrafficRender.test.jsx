import { afterEach, describe, expect, it, vi } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import ErrorBoundary from './ErrorBoundary.jsx'

vi.mock('./api.js', () => ({
  // CapacityModeStrip, mounted by AdminLiveTraffic, reads this. Declared here
  // rather than left undefined so these tests exercise the real path.
  getCapacitySchedule: vi.fn(async () => ({ applied: false })),
  getAdminActivity: vi.fn(async () => ({
    generated_at: '2026-09-04T20:00:00Z', runs: [], summary: {
      active_runs: 0, recent_runs: 0, running: 0, queued: 0, waiting_users: 0,
      available_slots: 7, worker_slots: 7, utilization_pct: 0, worker_tier_alive: true,
      workflow_correlation: { attributed_stage_runs: 3, unlinked_active_jobs: 0, complete: true },
      by_stage: {}, worker_roles: {
        discovery: { alive: true, pool_size: 3, age_s: 4, version: 'v25' },
        assess: { alive: true, pool_size: 2, age_s: 2, version: 'v25' },
        remediate: { alive: true, pool_size: 2, age_s: 2, version: 'v25' },
      },
    },
  })),
  getWorkerCapacity: vi.fn(async () => ({ configured: false })),
  getLiveOpsCosts: vi.fn(async () => ({
    configured: false,
    measured_at: '2026-09-04T20:00:00Z',
    estimated_hourly_usd: null,
    estimated_daily_usd: null,
    rate_source: null,
    services: [],
    billing: { freshness_label: 'Azure billing feed not configured' },
  })),
  openAdminActivityStream: vi.fn(() => ({ close: vi.fn() })),
}))

const { default: AdminLiveTraffic } = await import('./AdminLiveTraffic.jsx')

afterEach(unmountAll)

describe('Live Operations runtime rendering', () => {
  it('renders the persistent idle graph from the production Microsoft-user data shape', async () => {
    const { root, container } = createTestRoot()
    await act(async () => { root.render(createElement(ErrorBoundary, null, createElement(AdminLiveTraffic))) })
    await act(async () => { await Promise.resolve() })
    expect(container.textContent).not.toContain('Something went wrong')
    const metrics = [...container.querySelectorAll('.ops-kpi__value')]
    for (const suffix of ['active', 'jobs', '%', 'resolved']) {
      const metric = metrics.find(el => el.textContent.endsWith(suffix))
      expect(metric).toBeTruthy()
      expect(metric.querySelector('.machine-value')).not.toBeNull()
    }
    expect(container.querySelector('[aria-label="Workflow data linkage"] .ops-kpi__value .machine-value')).toBeNull()
    expect(container.textContent).toContain('Google Drive')
    expect(container.textContent).toContain('SharePoint')
    expect(container.textContent).toContain('ACP intake')
    expect(container.textContent).toContain('WORKFLOW WIRING')
    expect(container.textContent).toContain('3 stage runs linked')
    expect(container.textContent).toContain('Every active job is represented in the workflow view.')
    expect(container.textContent).toContain('Idle · select any tile to inspect the ready processing path')
  })
})
