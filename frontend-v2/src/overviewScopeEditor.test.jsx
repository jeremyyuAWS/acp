/**
 * The scan scope stays reachable from the FIRST TAB after a scan exists.
 *
 * App renders `view === 'overview'` as `run ? (assessed ? <Overview/> : gate) : placeholder`, and
 * `placeholder` is EmptyState — which is the only thing that rendered ScanSetup. So the criteria
 * and file-type controls were reachable exactly once per workspace: before its first scan. Every
 * session after that opened on the dashboard with no route back to the decision shaping every
 * number on it, and the only remaining editors were two panels inside Settings.
 *
 * This asserts the state that regressed — a run that HAS been assessed — because the empty case
 * was never broken and testing it would pass either way.
 *
 * DOM-level, not browser-level: this repo's preview server runs vite rooted at the SHARED
 * checkout whatever worktree you are in (CLAUDE.md).
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

// Spread the real module and override only the calls this render makes. Enumerating api.js's
// exports by hand fails the day one is added — and fails as "No <name> export is defined on the
// mock", which reads like a missing function rather than a stale test double.
vi.mock('./api.js', async (importActual) => ({
  ...(await importActual()),
  getSettings: async () => ({ scan_scope: '' }),
  updateSettings: async () => ({}),
  getScanDiff: async () => null,
}))

const { default: Overview } = await import('./Overview.jsx')

const RUN = { id: 'scan-1', certifiable: 1, scope: null, at: '2026-08-08T00:00:00Z' }
const FILES = [{ name: 'a.docx', score: 90, issues: [], department: 'Legal', format: 'docx' }]

async function render(props = {}) {
  const { root, container } = createTestRoot()
  await act(async () => {
    root.render(createElement(Overview, {
      run: RUN, files: FILES, trend: [], trendDates: [], onGo: () => {},
      scanList: [RUN], onPickScan: () => {}, me: { email: 'a@b.com' }, ...props,
    }))
  })
  return container
}

const scopePanel = (c) => [...c.querySelectorAll('details')]
  .find((d) => /Scan scope/i.test(d.querySelector('summary')?.textContent || ''))


describe('the scan scope is editable from the first tab', () => {
  it('offers it on an assessed run, not only before the first scan', async () => {
    const c = await render({ onScan: vi.fn() })
    expect(scopePanel(c), 'no scan-scope editor on the Overview tab').toBeTruthy()
  })

  it('renders the criterion controls inside it', async () => {
    const c = await render({ onScan: vi.fn() })
    const panel = scopePanel(c)
    expect(panel).toBeTruthy()
    // The criterion axis, by its controls rather than its prose: the checks step leads with a
    // profile radiogroup (Recommended / Automated only / Custom). The format axis moved to Assess
    // (AssessScope.jsx), so this editor no longer carries file-type chips. Asserting on the heading
    // text would pass against a heading with an empty editor under it.
    expect(panel.querySelectorAll('[role="radio"]').length,
      'no criterion-profile controls').toBeGreaterThan(0)
  })

  it('stays collapsed, so it does not displace the metrics', async () => {
    // The screen's primary job is still to report. <details> without `open` is the same
    // secondary-action treatment Discover gives Upload.
    const c = await render({ onScan: vi.fn() })
    expect(scopePanel(c).hasAttribute('open')).toBe(false)
  })

  it('is left out entirely when there is no way to rescan', async () => {
    // No onScan means no scan can be started, and a scope editor whose save cannot be acted on
    // is a control that lies about what it does.
    const c = await render({ onScan: undefined })
    expect(scopePanel(c)).toBeFalsy()
  })
})
