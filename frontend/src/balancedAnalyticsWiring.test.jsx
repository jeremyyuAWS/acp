import { createElement, act } from 'react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { createTestRoot, unmountAll } from './testRoots.js'

const api = vi.hoisted(() => ({ getAdminAnalytics: vi.fn(), getAdminAnalyticsScan: vi.fn(), getScanInventory: vi.fn(), downloadAdminAnalyticsExport: vi.fn(), downloadAdminAnalyticsMethodology: vi.fn() }))
vi.mock('./api.js', () => api)
const { AdminInsights } = await import('./AdminInsights.jsx')
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const analytics = { attempts: 22, activity: [{ date: '2026-09-14', attempts: 22, statuses: { done: 20, failed: 2 } }], reporting: {}, filter_options: {}, register: { rows: [], total: 0 } }
const run = { id: 'chosen', files: 1, scope: { inventory: { discovered: 1, assessment_eligible: 1, by_format: { docx: 1 } } } }
const files = [{ file: 'selected.docx', type: 'DOCX', score: 60, status: 'analysed', issues: [{ wcag: '1.3.1', severity: 'SERIOUS' }] }]
const flush = async () => { for (let i = 0; i < 5; i++) await act(async () => { await Promise.resolve() }) }
beforeEach(() => { vi.clearAllMocks(); window.history.replaceState({}, '', '/'); api.getAdminAnalytics.mockResolvedValue(analytics); api.getScanInventory.mockResolvedValue({ rows: [], total: 0 }) })
afterEach(unmountAll)

describe('balanced Scan Analytics integration', () => {
  it('mounts the four focused panels and sends a calendar day to the real analytics filters', async () => {
    const { root, container: c } = createTestRoot()
    await act(async () => root.render(createElement(AdminInsights, { run, files, cap: { docx: { '1.3.1': 'auto' } } })))
    await flush()
    expect(c.querySelectorAll('.balanced-grid h2')).toHaveLength(4)
    expect(c.querySelector('.balanced-context').textContent).toContain('chosen')
    await act(async () => c.querySelector('[aria-label="2026-09-14: 22 attempts. Show matching scans"]').click())
    await flush()
    expect(api.getAdminAnalytics.mock.lastCall[2]).toMatchObject({ period: 'custom', start: '2026-09-14T00:00:00Z', end: '2026-09-15T00:00:00.000Z', page: 1 })
    expect(c.querySelector('.balanced-context').textContent).toContain('chosen')
    expect(document.activeElement.querySelector('h2').textContent).toBe('Scan register')
    expect(c.querySelector('.balanced-legacy').open).toBe(false)
  })
  it('does not attach a late inventory response from the previous selected scan', async () => {
    let resolveOld
    api.getScanInventory.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    const { root, container: c } = createTestRoot()
    await act(async () => root.render(createElement(AdminInsights, { run, files }))); await flush()
    await act(async () => root.render(createElement(AdminInsights, { run: { id: 'new', files: 0 }, files: [] }))); await flush()
    await act(async () => resolveOld({ rows: [{ file: 'stale.png', format: 'image', status: 'metadata_only' }], total: 1 })); await flush()
    expect(c.querySelector('.balanced-context').textContent).toContain('new')
    expect(c.querySelector('.balanced-coverage').textContent).not.toContain('Images')
    expect(c.querySelector('.balanced-coverage').textContent).toContain('File-type inventory is not recorded')
  })
  it('keeps selected-scan data wired through the actual app entry point', () => {
    const source = readFileSync(`${import.meta.dirname}/App.jsx`, 'utf8')
    expect(source).toContain("defaultCollapsed={['overview', 'analytics'].includes(view)}")
    expect(source).toMatch(/<AdminInsights[^>]*run=\{run\}[^>]*files=\{files\}[^>]*cap=\{cap\}[^>]*assessment=\{assessment\}/)
    const overview = readFileSync(`${import.meta.dirname}/Overview.jsx`, 'utf8')
    expect(overview).toContain('<BalancedSummary run={run} files={files}')
    expect(overview).not.toContain('<summary>Workflow and assessment details</summary>')
  })
})
