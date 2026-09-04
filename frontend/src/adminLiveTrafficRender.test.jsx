import { afterEach, describe, expect, it, vi } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import ErrorBoundary from './ErrorBoundary.jsx'

vi.mock('./api.js', () => ({
  getAdminActivity: vi.fn(async () => ({
    generated_at: '2026-09-04T20:00:00Z', runs: [], summary: {
      active_runs: 0, recent_runs: 0, running: 0, queued: 0, waiting_users: 0,
      available_slots: 7, worker_slots: 7, utilization_pct: 0, worker_tier_alive: true,
      by_stage: {}, worker_roles: {
        discovery: { alive: true, pool_size: 3, age_s: 4, version: 'v25' },
        assess: { alive: true, pool_size: 2, age_s: 2, version: 'v25' },
        remediate: { alive: true, pool_size: 2, age_s: 2, version: 'v25' },
      },
    },
  })),
  getWorkerCapacity: vi.fn(async () => ({ configured: false })),
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
    expect(container.textContent).toContain('Google Drive')
    expect(container.textContent).toContain('SharePoint')
    expect(container.textContent).toContain('ACP intake')
    expect(container.textContent).toContain('Idle · select any tile to inspect the ready processing path')
  })
})
