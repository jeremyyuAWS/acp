/**
 * How much of the Live Operations page is open on arrival.
 *
 * Asked for 2026-09-06 with a screenshot: keep every detail, but stop making the reader scroll
 * past three full panels to reach the map. These assert the fold, not the content — that the
 * detail panels start closed, that nothing was deleted to achieve it, and that the tiles and the
 * map are never behind a click.
 *
 * Its own mock, because the three panels only render their real bodies when their endpoints
 * answer; an unconfigured deployment renders a short "not configured" notice instead, and a test
 * against that would be asserting on the wrong branch.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import ErrorBoundary from './ErrorBoundary.jsx'

vi.mock('./api.js', () => ({
  getAdminActivity: vi.fn(async () => ({
    generated_at: '2026-09-06T14:00:00Z', runs: [], summary: {
      active_runs: 0, recent_runs: 0, running: 0, queued: 0, waiting_users: 0,
      available_slots: 7, worker_slots: 7, utilization_pct: 0, worker_tier_alive: true,
      by_stage: {}, worker_roles: {},
    },
  })),
  getWorkerCapacity: vi.fn(async () => ({
    configured: true, current_replicas: 10, min_replicas: 10, max_replicas: 10,
    cpu_cores_per_replica: 2, memory_per_replica: '4Gi', ephemeral_storage_per_replica: '8Gi',
    metrics_available: true, cpu_percent: 0, memory_percent: 1, metrics_window_minutes: 15,
    revision_health: 'Healthy', revision_provisioning_state: 'Provisioned',
    worker_app_name: 'acp-assess', measured_at: '2026-09-06T13:59:40Z', metrics: {},
  })),
  getLiveOpsCosts: vi.fn(async () => ({
    configured: false, measured_at: '2026-09-06T13:59:45Z',
    estimated_hourly_usd: null, estimated_daily_usd: null, rate_source: null, services: [],
    billing: { freshness_label: 'Azure billing feed not configured' },
  })),
  getAiCosts: vi.fn(async () => ({ today: { calls: 14102, cost_usd: 0, by_surface: [] } })),
  getAiProvidersHealth: vi.fn(async () => ({ providers: {} })),
  openAdminActivityStream: vi.fn(() => ({ close: vi.fn() })),
}))

const { default: AdminLiveTraffic } = await import('./AdminLiveTraffic.jsx')

// unmountAll is ASYNC. Called without await it tears down on the next tick, which lands on the
// NEXT test's root and leaves it rendering into a detached container — an empty page with no
// error. Awaited here and at the remount below.
afterEach(async () => {
  await unmountAll()
  try { window.localStorage.clear() } catch { /* private window or blocked site data */ }
})

const DETAIL_SECTIONS = ['Azure worker infrastructure', 'Azure cost transparency', 'Live AI operations']

async function page() {
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(ErrorBoundary, null, createElement(AdminLiveTraffic))) })
  await act(async () => { await Promise.resolve() })
  await act(async () => { await Promise.resolve() })
  return container
}

const section = (container, label) => container.querySelector(`details[aria-label="${label}"]`)

describe('Live Operations page density', () => {
  it('starts every detail panel collapsed', async () => {
    const container = await page()
    for (const label of DETAIL_SECTIONS) {
      expect(section(container, label), label).toBeTruthy()
      expect(section(container, label).open, label).toBe(false)
    }
  })

  it('collapses without deleting: the figures are still rendered', async () => {
    // The distinction that matters. A collapsed <details> keeps its content in the DOM, so the
    // numbers are one click away and still reachable by in-page search — not removed from the
    // page to buy vertical space.
    const container = await page()
    expect(section(container, 'Azure worker infrastructure').textContent).toContain('RUNNING REPLICAS')
    expect(section(container, 'Azure cost transparency').textContent).toContain('AZURE BILLING ACTUALS')
    expect(section(container, 'Live AI operations').textContent).toContain('14102 calls')
  })

  it('names each panel in its summary, so a closed one still says what it holds', async () => {
    const container = await page()
    expect(section(container, 'Azure worker infrastructure').querySelector('summary').textContent)
      .toContain('Azure worker infrastructure')
    expect(section(container, 'Azure cost transparency').querySelector('summary').textContent)
      .toContain('Cost transparency')
    expect(section(container, 'Live AI operations').querySelector('summary').textContent)
      .toContain('AI operations')
  })

  it('opens one without opening the rest', async () => {
    const container = await page()
    const azure = section(container, 'Azure worker infrastructure')
    await act(async () => { azure.open = true; azure.dispatchEvent(new Event('toggle')) })
    expect(azure.open).toBe(true)
    expect(section(container, 'Live AI operations').open).toBe(false)
  })

  it('remembers the choice for the next visit', async () => {
    const container = await page()
    const azure = section(container, 'Azure worker infrastructure')
    await act(async () => { azure.open = true; azure.dispatchEvent(new Event('toggle')) })
    await unmountAll()

    const again = await page()
    expect(section(again, 'Azure worker infrastructure').open).toBe(true)
    // Only the one that was opened — a remembered choice is per section, not a global "expand".
    expect(section(again, 'Live AI operations').open).toBe(false)
  })

  it('leaves the summary tiles and the map open', async () => {
    // These answer "is anything wrong right now", which is what the screen is opened for, so
    // they are never behind a click.
    const container = await page()
    expect(container.textContent).toContain('WORKER CAPACITY')
    expect(container.textContent).toContain('SHARED QUEUE')
    expect(container.querySelector('[role="tablist"]')).toBeTruthy()
    for (const label of DETAIL_SECTIONS) {
      expect(section(container, label).textContent).not.toContain('WORKER CAPACITY')
    }
  })
})
