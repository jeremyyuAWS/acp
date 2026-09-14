import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import axe from 'axe-core'
import { readFileSync } from 'node:fs'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const api = vi.hoisted(() => ({ getAdminAnalytics: vi.fn(), getAdminAnalyticsScan: vi.fn(), downloadAdminAnalyticsExport: vi.fn(), downloadAdminAnalyticsMethodology: vi.fn() }))
vi.mock('./api.js', () => api)
const { AdminInsights } = await import('./AdminInsights.jsx')

const done = { id: 'run-zero', owner_email: 'alice@example.com', source: 'local', status: 'done', started_at: '2026-09-10T10:00:00Z', completed_at: '2026-09-10T11:00:00Z', files: 5, certifiable: 0, uncertain: 0, avg_score: 40 }
const failed = { id: 'run-failed', owner_email: 'bob@example.com', source: 'drive', status: 'failed', started_at: '2026-09-11T10:00:00Z', completed_at: null, files: null, certifiable: null, avg_score: null, error: 'Connection denied' }
const running = { id: 'run-active', owner_email: 'bob@example.com', source: 'drive', status: 'running', started_at: '2026-09-12T10:00:00Z', completed_at: null, files: null, certifiable: null, avg_score: null }
function fixture() {
  return { attempts: 3, scans: 3, successful_runs: 1, unsuccessful_runs: 1, active_users: 2, docs: 5, certifiable: 0, uncertain: 0, error_docs: 0, avg_score: 40, certifiable_rate: 0, review_pending: 2,
    by_status: { done: 1, failed: 1, running: 1 }, by_source: { local: { attempts: 1, docs: 5, certifiable: 0 }, drive: { attempts: 2, docs: 0, certifiable: 0 } },
    by_user: [{ owner_email: 'alice@example.com', attempts: 1, successful_runs: 1, unsuccessful_runs: 0, last_activity: done.started_at }, { owner_email: 'bob@example.com', attempts: 2, successful_runs: 0, unsuccessful_runs: 1, last_activity: running.started_at }],
    activity: [{ date: '2026-09-10', statuses: { done: 1 }, attempts: 1 }, { date: '2026-09-11', statuses: { failed: 1 }, attempts: 1 }],
    successful_results: { scans: 1, docs: 5, certifiable: 0, uncertain: 0, error_docs: 0, avg_score: 40, certifiable_rate: 0 },
    result_trend: [{ ...done, certifiable_rate: 0 }, { ...done, id: 'missing', completed_at: '2026-09-11T12:00:00Z', certifiable_rate: null, files: null }],
    results_register: { rows: [done], total: 1, time_basis: 'completed_at' },
    trend: { summary: {}, points: [{ scan_id: 'run-zero', at: done.completed_at, certifiable_pct: 0, files: 5 }, { scan_id: 'missing', at: '2026-09-11T12:00:00Z', certifiable_pct: null, files: 0 }] },
    reporting: { generated_at: '2026-09-14T12:00:00Z', data_through: running.started_at, scope: 'All authorized users', timezone: 'UTC', time_basis: 'Attempts by start time; assessments by completion time', start: '2026-08-15T00:00:00Z', end: '2026-09-14T00:00:00Z', limitations: ['Department history unavailable'], review_scope: 'Current authorized queue snapshot; not period-filtered' },
    filter_options: { owners: ['alice@example.com', 'bob@example.com'], sources: ['local', 'drive'], statuses: ['done', 'failed', 'running'] },
    register: { rows: [done, failed, running], total: 26, page: 1, page_size: 25, pages: 2 }, recent_scans: [done, failed, running],
    comparison: { start: '2026-07-16T00:00:00Z', end: '2026-08-15T00:00:00Z', attempts: 0, successful_runs: 0, certifiable_rate: null, attempts_change: 3, rate_change_pp: null } }
}
const flush = async () => { for (let i = 0; i < 5; i++) await act(async () => { await Promise.resolve() }) }
async function mount() { const { root, container } = createTestRoot(); await act(async () => root.render(createElement(AdminInsights, { me: { email: 'admin@example.com', is_admin: true } }))); await flush(); return container }
const control = (c, label) => c.querySelector(`[aria-label="${label}"]`) || [...c.querySelectorAll('label')].find(x => x.textContent.includes(label))?.querySelector('input, select')
const button = (c, label) => [...c.querySelectorAll('button')].find(x => x.textContent.trim() === label)
async function click(element) { expect(element).toBeTruthy(); await act(async () => element.click()); await flush() }
async function change(element, value) { expect(element).toBeTruthy(); const setter = Object.getOwnPropertyDescriptor(element.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype, 'value').set; await act(async () => { setter.call(element, value); element.dispatchEvent(new Event('change', { bubbles: true })); element.dispatchEvent(new Event('input', { bubbles: true })) }); await flush() }
beforeEach(() => { vi.clearAllMocks(); api.getAdminAnalytics.mockResolvedValue(fixture()); api.getAdminAnalyticsScan.mockResolvedValue({ scan: failed, reporting: fixture().reporting }); api.downloadAdminAnalyticsExport.mockResolvedValue(undefined); api.downloadAdminAnalyticsMethodology.mockResolvedValue(undefined); window.history.replaceState({}, '', '/') })
afterEach(unmountAll)

describe('transparent cross-user Scan Analytics', () => {
  it('keeps the former lifecycle funnel deliberately unmounted because its stages overlap', async () => {
    const source = readFileSync(`${import.meta.dirname}/AdminInsights.jsx`, 'utf8')
    expect(source).toContain('function RetainedLifecycleFunnel')
    expect(source).not.toContain('<RetainedLifecycleFunnel')
    expect((await mount()).textContent).not.toContain('Estate lifecycle')
  })
  it('filters summary contributors and moves keyboard focus to the loaded register', async () => {
    const c = await mount()
    const unsuccessful = [...c.querySelectorAll('button')].find(b => b.querySelector('.ops-kpi__label')?.textContent === 'Unsuccessful runs')
    await click(unsuccessful)
    expect(api.getAdminAnalytics.mock.lastCall[2].status).toBe('__unsuccessful__')
    expect(document.activeElement.querySelector('h2')?.textContent).toBe('Scan register')
  })
  it('discloses undated activity and excluded result counters beside the metrics', async () => {
    const data = fixture()
    data.reporting.partial_data = true
    data.reporting.missing_started_at = 2
    data.successful_results = { docs: 5, certifiable: 0, certifiable_rate: 0, missing_results: 1 }
    api.getAdminAnalytics.mockResolvedValueOnce(data)
    const c = await mount()
    expect(c.textContent).toContain('2 retained runs have no valid start timestamp')
    expect(c.textContent).toContain('1 successful completions have unavailable or inconsistent result counters')
  })
  it('provides named controls, chart tables, and accessible DOM semantics', async () => {
    const c = await mount()
    expect(c.querySelectorAll('table').length).toBeGreaterThanOrEqual(4)
    const result = await axe.run(c, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } })
    expect(result.violations.map(v => ({ id: v.id, nodes: v.nodes.map(n => n.html) }))).toEqual([])
  })
  it('renders all attempted outcomes and both initiating users without claiming unique files or inferred open findings', async () => {
    const c = await mount()
    for (const id of ['run-zero', 'run-failed', 'run-active']) expect(button(c, id)).toBeTruthy()
    expect(c.textContent).toContain('alice@example.com'); expect(c.textContent).toContain('bob@example.com')
    expect(c.textContent).toContain('Assessment observations'); expect(c.textContent).not.toContain('Unique files'); expect(c.textContent).not.toContain('Open risk')
    expect(c.textContent).toContain('Department history unavailable')
    const zeroRow = button(c, 'run-zero').closest('tr'); const failedRow = button(c, 'run-failed').closest('tr')
    expect(zeroRow.textContent).toContain('0%'); expect(failedRow.textContent).not.toContain('0%')
  })

  it('requests the same owner/status/source scope and resets pagination when filters change', async () => {
    const c = await mount(); await click(button(c, 'Next page'))
    expect(api.getAdminAnalytics.mock.lastCall[2].page).toBe(2)
    await change(control(c, 'User'), 'bob@example.com')
    expect(api.getAdminAnalytics.mock.lastCall[2]).toMatchObject({ owner: 'bob@example.com', page: 1 })
    await change(control(c, 'Status'), 'failed')
    expect(api.getAdminAnalytics.mock.lastCall[2]).toMatchObject({ owner: 'bob@example.com', status: 'failed', page: 1 })
    await change(control(c, 'Source'), 'drive')
    expect(api.getAdminAnalytics.mock.lastCall[1]).toBe('drive')
  })

  it('applies a custom interval deliberately and carries it into exports of all matching rows', async () => {
    const c = await mount(); await change(control(c, 'Reporting period') || control(c, 'Analytics reporting period'), 'custom')
    await change(control(c, 'Start date'), '2026-09-01'); await change(control(c, 'End date'), '2026-09-12'); await click(button(c, 'Apply dates'))
    const [period, source, options] = api.getAdminAnalytics.mock.lastCall
    expect(period).toBe('custom'); expect(options.start).toContain('2026-09-01'); expect(options.end).toBeTruthy()
    const exportButton = [...c.querySelectorAll('button')].find(x => /Export.*CSV/i.test(x.textContent))
    await click(exportButton)
    expect(api.downloadAdminAnalyticsExport).toHaveBeenCalledWith(period, source, expect.objectContaining({ start: options.start, end: options.end }))
  })

  it('restores an inclusive custom date label without extending the saved exclusive interval on Apply', async () => {
    window.history.replaceState({}, '', '/?analytics_period=custom&analytics_start=2026-09-01T00%3A00%3A00Z&analytics_end=2026-09-13T00%3A00%3A00Z')
    const c = await mount()
    expect(control(c, 'End date').value).toBe('2026-09-12')
    await click(button(c, 'Apply dates'))
    expect(Date.parse(api.getAdminAnalytics.mock.lastCall[2].end)).toBe(Date.parse('2026-09-13T00:00:00Z'))
  })

  it('resets the page when switching the register from attempts to completion results', async () => {
    const c = await mount(); await click(button(c, 'Next page'))
    const next = fixture(); next.register.page = 2
    api.getAdminAnalytics.mockResolvedValueOnce(next)
    await click(button(c, 'Refresh')); await click(button(c, 'Assessment completions'))
    expect(api.getAdminAnalytics.mock.lastCall[2].page).toBe(1)
    expect(button(c, 'run-zero')).toBeTruthy()
  })

  it('opens a failed attempt with recorded diagnostics and leaves register filters available', async () => {
    const c = await mount(); await change(control(c, 'Status'), 'failed'); await click(button(c, 'run-failed'))
    expect(api.getAdminAnalyticsScan).toHaveBeenCalledWith('run-failed', expect.any(Object))
    expect(c.textContent).toContain('Connection denied'); expect(control(c, 'Status').value).toBe('failed')
  })

  it('shows dated stage events and per-document finding evidence without treating missing eligibility as a pass', async () => {
    api.getAdminAnalyticsScan.mockResolvedValueOnce({ scan: done, reporting: fixture().reporting,
      events: [{ id: 'event-1', timestamp: '2026-09-10T10:30:00Z', stage: 'assessment', message: 'Assessment finished' }],
      observations: [{ id: 'doc-1', name: 'inaccessible.pdf', engine: 'PDF', status: 'assessed', score: 40, certifiable: false, issues: [{ wcag: '1.1.1', message: 'Image has no alternative text' }] }, { id: 'doc-2', name: 'unknown.pdf', score: null, certifiable: null }] })
    const c = await mount(); await click(button(c, 'run-zero'))
    const detail = c.querySelector('[aria-label="Scan detail"]')
    expect(detail.textContent).toContain('Assessment finished'); expect(detail.textContent).toContain('1.1.1: Image has no alternative text')
    const observations = [...detail.querySelectorAll('.sa-observations > details')]
    expect(observations).toHaveLength(2); expect(observations[0].textContent).toContain('Not certifiable'); expect(observations[1].textContent).toContain('Eligibility: Unavailable')
    expect(observations[1].textContent).toContain('does not establish conformance')
    await click(button(c, 'Close detail')); expect(c.querySelector('[aria-label="Scan detail"]')).toBeNull(); expect(button(c, 'run-zero')).toBeTruthy()
  })

  it('keeps a missing rate as an unavailable table value and a gap on a fixed percentage axis', async () => {
    const c = await mount()
    const table = [...c.querySelectorAll('table')].find(t => t.caption?.textContent === 'Assessment results over time')
    expect(table.rows[1].cells[2].textContent).toBe('0%'); expect(table.rows[2].cells[2].textContent).toBe('Unavailable')
    const chart = c.querySelector('svg[aria-label*="fixed 0 to 100 percent"]')
    expect(chart).toBeTruthy(); expect(chart.querySelectorAll('circle')).toHaveLength(1)
  })

  it('labels retained data as stale after refresh failure and never presents an empty success state', async () => {
    const c = await mount(); api.getAdminAnalytics.mockRejectedValueOnce(new Error('Analytics service unavailable')); await click(button(c, 'Refresh'))
    expect(c.textContent).toContain('Analytics service unavailable'); expect(c.textContent.toLowerCase()).toMatch(/stale|previous|retained/)
    expect(button(c, 'run-failed')).toBeTruthy(); expect(c.textContent).not.toContain('No matching scans')
  })

  it('ignores a late response from a superseded filter request', async () => {
    const c = await mount()
    let resolveOld
    api.getAdminAnalytics.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    await change(control(c, 'User'), 'bob@example.com')
    const selected = fixture(); selected.register = { rows: [failed], total: 1, page: 1, page_size: 25, pages: 1 }
    api.getAdminAnalytics.mockResolvedValueOnce(selected)
    await change(control(c, 'Status'), 'failed')
    expect(button(c, 'run-failed')).toBeTruthy(); expect(button(c, 'run-zero')).toBeFalsy()
    await act(async () => resolveOld(fixture())); await flush()
    expect(button(c, 'run-zero')).toBeFalsy(); expect(control(c, 'Status').value).toBe('failed')
  })
})
