/**
 * Scan history table (Overview.jsx) — REMOVED on 2026-09-02 by the PRD "ACP Discover and Overview
 * Simplification", along with the rest of Overview's tables and charts. Nothing on any screen
 * renders it now; scan selection lives in the header's scan picker.
 *
 * This file is kept and rewritten to pin the removal rather than deleted, because the table came
 * back once already: the "files" column was added live on 2026-08-28 after a user could not tell
 * how many files a past scan had discovered without opening it. If the table returns, it has to
 * return with that column and without the row-as-button defect below — and this test is the
 * record of both, which a deleted file would not be.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
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

const overviewSrc = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'Overview.jsx'), 'utf8')

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

describe('the scan history table is intentionally NOT on Overview', () => {
  it('renders no scan history heading, and so no table under one', async () => {
    const c = await render()
    expect(historyTable(c)).toBeFalsy()
    const headings = [...c.querySelectorAll('h2')].map((h) => h.textContent)
    expect(headings.length, 'Overview rendered no headings at all — the check below proves nothing')
      .toBeGreaterThan(0)
    expect(headings.filter((t) => /scan history/i.test(t))).toEqual([])
  })

  it('renders no scan-history row controls anywhere on the screen', async () => {
    const c = await render()
    expect(c.querySelector('button.scan-history-select')).toBeNull()
    // The defect the last version of this test guarded: a row that is itself a button, wrapping
    // another button. Neither may reappear.
    expect(c.querySelector('tr[role="button"]')).toBeNull()
  })

  it('takes a scanList without rendering it, and without throwing', async () => {
    // Overview still ACCEPTS `scanList`/`onPickScan` — App passes them — so the props must stay
    // harmless. A scan whose `files` is missing is the case that used to print a bare 0.
    const noFiles = { id: 'scan-2', certifiable: 0, scope: null, completed_at: '2026-08-08T00:00:00Z' }
    const c = await render({ run: noFiles, scanList: [noFiles, OLDER] })
    expect(c.textContent).not.toContain('1,248')
    expect(c.textContent).not.toContain('900')
  })

  it('still names the source file, so restoring the table has a starting point', () => {
    // Overview.jsx keeps the props; what it no longer keeps is the markup.
    expect(overviewSrc).not.toMatch(/scan-history-select/)
    expect(overviewSrc).toMatch(/scanList = \[\]/)
  })
})
