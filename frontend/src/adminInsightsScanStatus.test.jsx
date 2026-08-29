/**
 * The Recent scans table (AdminInsights.jsx) renders Docs/Certifiable/Score straight off
 * scan_runs — but "0" there is ambiguous: a scan cancelled or interrupted before assessment
 * ran leaves those fields at 0 exactly the way a scan that WAS assessed and found nothing
 * certifiable does. Reported live 2026-08-29 ("are these because they weren't assessed or
 * remediated?") looking at three same-looking rows in that state.
 *
 * The backend now rides `status` along on each recent_scans row (api/routes/analytics.py),
 * and this component turns a non-'done' status into a visible badge so the two cases never
 * look the same in the table.
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

const getAdminAnalytics = vi.fn(async () => ({
  scans: 3, docs: 5, certifiable: 1, uncertain: 0, error_docs: 0, scan_exceptions: 1,
  review_pending: 0, certifiable_rate: 20, avg_score: 71, by_source: {},
  trend: { summary: {}, points: [] },
  recent_scans: [ROW_CANCELLED, ROW_INTERRUPTED, ROW_DONE],
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

describe('the recent-scans table', () => {
  it('badges a cancelled scan instead of leaving it looking like a real zero', async () => {
    const c = await mount()
    const row = [...c.querySelectorAll('tbody tr')].find((r) => r.textContent.includes('jeremyyu.movate'))
    expect(row.textContent).toMatch(/Cancelled/)
  })

  it('badges an interrupted scan the same way', async () => {
    const c = await mount()
    const row = [...c.querySelectorAll('tbody tr')].find((r) => r.textContent.includes('devamovate'))
    expect(row.textContent).toMatch(/Interrupted/)
  })

  it('shows no status badge for a normally completed scan', async () => {
    const c = await mount()
    const row = [...c.querySelectorAll('tbody tr')].find((r) => r.textContent.includes('fgxlxj'))
    expect(row.textContent).not.toMatch(/Cancelled|Interrupted|Failed/)
  })
})
