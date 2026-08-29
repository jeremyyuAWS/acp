import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

// Proves Discover actually threads progress.active_folders/recent_folders into FolderActivity —
// FolderActivity's own rendering rules are covered on their own in folderActivity.test.jsx; this
// is the DOM leg, matching this codebase's SOURCE/DOM/unit split used elsewhere.

globalThis.IS_REACT_ACT_ENVIRONMENT = true

vi.mock('./api.js', () => ({
  checkReadiness: vi.fn(() => Promise.resolve(null)),
  getScanInventory: vi.fn(() => Promise.resolve(null)),
  listScanDecisions: vi.fn(() => Promise.resolve([])),
  overrideLifecycleRecommendation: vi.fn(),
  acknowledgeScan: vi.fn(),
  unacknowledgeScan: vi.fn(),
  getQueueJob: vi.fn(() => Promise.resolve({})),
  getJobs: vi.fn(() => Promise.resolve({ jobs: [] })),
  setWorkers: vi.fn(() => Promise.resolve({ workers: 0 })),
}))

const { default: Discover } = await import('./Discover.jsx')

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => {
    root.render(createElement(Discover, { sources: [], files: [], busy: false, onScan: () => {}, ...props }))
  })
  return container
}
const settle = async (n = 4) => { for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }
afterEach(() => unmountAll())

describe('Folder discovery activity on Discover', () => {
  it('shows active and recent folders from progress when discovering', async () => {
    const c = await mount({
      scope: null, run: { id: 's1', status: 'running' }, busy: true,
      progress: {
        phase: 'discovering', elapsed: 5, files_found: 12,
        active_folders: [{ name: 'Legal', path: 'My Drive/Legal', started_at: 't0' }],
        recent_folders: [{ name: 'Finance', path: 'My Drive/Finance', state: 'completed',
                          files_found: 4, completed_at: 't1' }],
      },
    })
    await settle()
    expect(c.textContent).toMatch(/Folder discovery activity/i)
    expect(c.textContent).toMatch(/My Drive\/Legal/)
    expect(c.textContent).toMatch(/My Drive\/Finance/)
  })

  it('renders nothing extra when progress carries no folder-activity fields', async () => {
    const c = await mount({
      scope: { kind: 'drive', inventory: { discovered: 5 } },
      run: { id: 's2', status: 'running' }, busy: true,
      progress: { phase: 'discovering', elapsed: 5, files_found: 5 },
    })
    await settle()
    expect(c.textContent).not.toMatch(/Folder discovery activity/i)
  })

  it('does not show folder activity while merely queued, before any listing has started', async () => {
    const c = await mount({
      scope: null, run: { id: 's3', status: 'running' }, busy: true,
      progress: { phase: 'queued' },
    })
    await settle()
    expect(c.textContent).not.toMatch(/Folder discovery activity/i)
  })
})
