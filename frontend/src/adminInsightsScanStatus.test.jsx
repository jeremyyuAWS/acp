/** All-status analytics must distinguish unavailable partial results from measured zeros. */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

const rows = [
  { id: 's-cancelled', status: 'cancelled', files: null, certifiable: null, avg_score: null },
  { id: 's-interrupted', status: 'interrupted', files: null, certifiable: null, avg_score: null },
  { id: 's-failed', status: 'failed', files: null, certifiable: null, avg_score: null },
  { id: 's-real-zero', status: 'done', files: 5, certifiable: 0, avg_score: 40 },
  { id: 's-done', status: 'done', files: 5, certifiable: 1, avg_score: 71 },
].map(r => ({ ...r, started_at: '2026-09-10T10:00:00Z', owner_email: 'alice@example.com', source: 'local' }))
vi.mock('./api.js', () => ({
  getAdminAnalytics: vi.fn(async () => ({ attempts: 5, by_source: {}, by_status: {},
    successful_results: { docs: 10, certifiable: 1, certifiable_rate: 10 },
    register: { rows, total: 5, page: 1, pages: 1 }, reporting: {}, filter_options: {} })),
  getAdminAnalyticsScan: vi.fn(), downloadAdminAnalyticsExport: vi.fn(), downloadAdminAnalyticsMethodology: vi.fn(),
}))
const { AdminInsights } = await import('./AdminInsights.jsx')
afterEach(unmountAll)
async function mount() {
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(AdminInsights, { me: { email: 'admin@example.com' } })))
  return container
}
function cells(c, id) {
  const button = [...c.querySelectorAll('button')].find(b => b.textContent === id)
  expect(button).toBeTruthy()
  return button.closest('tr').cells
}
describe('scan register outcome evidence', () => {
  for (const [id, label] of [['s-cancelled','Cancelled'], ['s-interrupted','Interrupted'], ['s-failed','Failed']]) {
    it(`shows ${label} and unavailable counts for an attempt without assessment results`, async () => {
      const row = cells(await mount(), id)
      expect(row[5].textContent).toBe(label)
      expect(row[6].textContent).toBe('—')
      expect(row[7].textContent).toBe('—')
      expect(row[8].textContent).toBe('—')
    })
  }
  it('preserves a measured zero on a successfully assessed run', async () => {
    const row = cells(await mount(), 's-real-zero')
    expect(row[5].textContent).toBe('Successful')
    expect(row[6].textContent).toBe('5')
    expect(row[7].textContent).toBe('0 (0%)')
  })
  it('renders normal successful counts and rate', async () => {
    const row = cells(await mount(), 's-done')
    expect(row[6].textContent).toBe('5')
    expect(row[7].textContent).toBe('1 (20%)')
  })
})
