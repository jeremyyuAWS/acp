/**
 * The Recent scans table (AdminInsights.jsx) renders Docs/Certifiable/Score straight off
 * scan_runs — but "0" there is ambiguous: a scan cancelled or interrupted before assessment
 * ran leaves those fields at 0 exactly the way a scan that WAS assessed and found nothing
 * certifiable does. Reported live 2026-08-29 ("are these because they weren't assessed or
 * remediated?") looking at three same-looking rows in that state.
 *
 * The backend rides `status` along on each recent_scans row (api/routes/analytics.py). Rather
 * than a separate badge column, the Docs/Certifiable cells themselves swap the bare "0" for the
 * status word when the scan never reached assessment — asked for directly ("instead of a 0 can
 * we put cancelled or error instead so we distinguish from true 0") — so the two cases never
 * render as the identical digit.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

const ROW_DONE = {
  id: 's-done', completed_at: '2026-08-27T10:00:00Z', source: 'local',
  files: 5, certifiable: 1, uncertain: 0, avg_score: 71, status: 'done',
  owner_email: 'jeremy_acp@fgxlxj.onmicrosoft.com',
}
const ROW_DONE_REAL_ZERO = {
  id: 's-real-zero', completed_at: '2026-08-26T10:00:00Z', source: 'local',
  files: 5, certifiable: 0, uncertain: 0, avg_score: 40, status: 'done',
  owner_email: 'jeremy_acp@fgxlxj.onmicrosoft.com',
}
const ROW_CANCELLED = {
  id: 's-cancelled', completed_at: '2026-08-29T04:00:00Z', source: 'drive',
  files: 0, certifiable: 0, uncertain: 0, avg_score: null, status: 'cancelled',
  owner_email: 'jeremyyu.movate@gmail.com',
}
const ROW_INTERRUPTED = {
  id: 's-interrupted', completed_at: '2026-08-28T04:00:00Z', source: 'drive',
  files: 0, certifiable: 0, uncertain: 0, avg_score: null, status: 'interrupted',
  owner_email: 'devamovate@gmail.com',
}
const ROW_FAILED = {
  id: 's-failed', completed_at: '2026-08-28T05:00:00Z', source: 'drive',
  files: 0, certifiable: 0, uncertain: 0, avg_score: null, status: 'failed',
  owner_email: 'devamovate@gmail.com',
}

const getAdminAnalytics = vi.fn(async () => ({
  scans: 5, docs: 10, certifiable: 1, uncertain: 0, error_docs: 0, scan_exceptions: 1,
  review_pending: 0, certifiable_rate: 20, avg_score: 71, by_source: {},
  trend: { summary: {}, points: [] },
  recent_scans: [ROW_CANCELLED, ROW_INTERRUPTED, ROW_FAILED, ROW_DONE_REAL_ZERO, ROW_DONE],
}))

vi.mock('./api.js', () => ({ getAdminAnalytics }))

const { AdminInsights } = await import('./AdminInsights.jsx')

afterEach(unmountAll)

const flush = async () => { for (let i = 0; i < 4; i++) await act(async () => { await Promise.resolve() }) }

async function mount() {
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(AdminInsights, { me: { email: 'admin@example.com' } })) })
  await flush()
  return container
}

function rowFor(container, id) {
  const rows = [...container.querySelectorAll('.panel table tbody tr')]
  const idx = [ROW_CANCELLED, ROW_INTERRUPTED, ROW_FAILED, ROW_DONE_REAL_ZERO, ROW_DONE]
    .findIndex((r) => r.id === id)
  // Recent scans is the only table with more than 4 columns — Coverage by source has 4.
  const scansTable = [...container.querySelectorAll('table')].find((t) => t.rows[0]?.cells.length === 6)
  return scansTable.rows[idx + 1]
}

describe('the recent-scans table', () => {
  it('shows "Cancelled" in Docs/Certifiable instead of a bare 0', async () => {
    const c = await mount()
    const row = rowFor(c, 's-cancelled')
    const [, , docs, certifiable] = row.cells
    expect(docs.textContent).toBe('Cancelled')
    expect(certifiable.textContent).toBe('Cancelled')
  })

  it('shows "Interrupted" in Docs/Certifiable instead of a bare 0', async () => {
    const c = await mount()
    const row = rowFor(c, 's-interrupted')
    const [, , docs, certifiable] = row.cells
    expect(docs.textContent).toBe('Interrupted')
    expect(certifiable.textContent).toBe('Interrupted')
  })

  it('shows "Failed" in Docs/Certifiable instead of a bare 0', async () => {
    const c = await mount()
    const row = rowFor(c, 's-failed')
    const [, , docs, certifiable] = row.cells
    expect(docs.textContent).toBe('Failed')
    expect(certifiable.textContent).toBe('Failed')
  })

  it('leaves a real, fully-assessed zero as an actual 0 — status is done', async () => {
    const c = await mount()
    const row = rowFor(c, 's-real-zero')
    const [, , docs, certifiable] = row.cells
    expect(docs.textContent).toBe('5')
    expect(certifiable.textContent).toBe('0 (0%)')
  })

  it('renders ordinary numbers for a normally completed scan', async () => {
    const c = await mount()
    const row = rowFor(c, 's-done')
    const [, , docs, certifiable] = row.cells
    expect(docs.textContent).toBe('5')
    expect(certifiable.textContent).toBe('1 (20%)')
  })
})
