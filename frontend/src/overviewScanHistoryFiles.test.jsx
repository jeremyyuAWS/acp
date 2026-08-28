/**
 * Scan history table (Overview.jsx) — "files" column.
 *
 * The certifiable column already rendered `certifiable / files` as a fraction, so the discovered
 * count was on screen but easy to miss (a small muted denominator, not its own labelled column).
 * Requested live 2026-08-28 after a user looked at the row and could not tell how many files a
 * past scan had discovered without opening it.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

vi.mock('./api.js', async (importActual) => ({
  ...(await importActual()),
  getSettings: async () => ({ scan_scope: '' }),
  updateSettings: async () => ({}),
  getScanDiff: async () => null,
}))

const { default: Overview } = await import('./Overview.jsx')

const RUN = { id: 'scan-1', certifiable: 1, files: 1248, scope: null, completed_at: '2026-08-08T00:00:00Z' }
const OLDER = { id: 'scan-0', certifiable: 0, files: 900, avg_score: 70, scope: null, completed_at: '2026-08-01T00:00:00Z' }
const FILES = [{ name: 'a.docx', score: 90, issues: [], department: 'Legal', format: 'docx' }]

async function render(props = {}) {
  const { root, container } = createTestRoot()
  await act(async () => {
    root.render(createElement(Overview, {
      run: RUN, files: FILES, trend: [], trendDates: [], onGo: () => {},
      scanList: [RUN, OLDER], onPickScan: () => {}, me: { email: 'a@b.com' }, ...props,
    }))
  })
  return container
}

const historyTable = (c) => [...c.querySelectorAll('h2')].find((h) => h.textContent.includes('Scan history'))?.closest('section')?.querySelector('table')

describe('scan history table — files column', () => {
  it('shows a "files" column header', async () => {
    const c = await render()
    const table = historyTable(c)
    expect(table, 'scan history table missing').toBeTruthy()
    const headers = [...table.querySelectorAll('thead th')].map((th) => th.textContent)
    expect(headers).toContain('files')
  })

  it('shows the discovered file count for each row, independent of the certifiable fraction', async () => {
    const c = await render()
    const table = historyTable(c)
    const rowTexts = [...table.querySelectorAll('tbody tr')].map((tr) => tr.textContent)
    expect(rowTexts[0]).toContain('1,248')
    expect(rowTexts[1]).toContain('900')
  })

  it('falls back to 0 when files is missing, same as the certifiable column already did', async () => {
    const noFiles = { id: 'scan-2', certifiable: 0, scope: null, completed_at: '2026-08-08T00:00:00Z' }
    const c = await render({ run: noFiles, scanList: [noFiles] })
    const table = historyTable(c)
    const row = table.querySelector('tbody tr')
    expect(row.textContent).toContain('0')
  })
})
